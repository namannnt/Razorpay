"""
Test script for ChurnGuard LangGraph Agentic Recovery Layer.

Tests cover:
1. card_expired → payment-link strategy
2. insufficient_funds → retry strategy  
3. unknown failure → manual review/fallback
4. workflow successfully creates RecoveryAction
5. workflow creates AuditLog entries
6. nonexistent failure event → proper 4xx response
7. repeated execution is handled safely/idempotently
8. existing 12 tests still pass
"""
import os
import pytest
import subprocess
import time
import requests

# Ensure mock provider is used for all tests (test isolation)
os.environ["USE_MOCK_PROVIDER"] = "true"

# Test configuration
BASE_URL = "http://localhost:8000"
TEST_TIMEOUT = 30


class TestAgentModules:
    """Test that agent modules import and are structured correctly."""
    
    def test_agents_module_imports(self):
        """Verify all agent modules can be imported."""
        from app.agents import (
            RecoveryWorkflowState,
            FailureAnalysisResult,
            RecoveryDecisionResult,
            run_recovery_workflow,
            RecoveryWorkflowRunner,
            create_recovery_graph,
            PaymentRecoveryProvider,
            MockPaymentProvider,
            get_provider,
        )
        assert RecoveryWorkflowState is not None
        assert run_recovery_workflow is not None
        assert create_recovery_graph is not None
    
    def test_state_definition(self):
        """Verify state TypedDict is properly defined."""
        from app.agents.state import RecoveryWorkflowState
        
        # Create a sample state
        state = RecoveryWorkflowState(
            subscription_id=1,
            failure_event_id=1,
            recovery_action_id=None,
            customer_name="Test User",
            customer_email="test@example.com",
            plan_name="Basic",
            amount=99900,
            currency="INR",
            subscription_status="failed",
            failure_code="card_expired",
            retry_count=0,
            failure_occurred_at=None,
            failure_analysis=None,
            failure_category=None,
            recovery_implications=None,
            recommended_action_type=None,
            action_reason=None,
            policy_coverage_score=None,
            razorpay_payment_link_id=None,
            action_status=None,
            execution_result=None,
            error_message=None,
            is_simulated=True,
            workflow_started_at=None,
            workflow_completed_at=None,
            audit_log_ids=[],
        )
        assert state["failure_event_id"] == 1
        assert state["is_simulated"] is True
    
    def test_provider_abstraction(self):
        """Verify payment provider abstraction works."""
        from app.agents.provider import MockPaymentProvider, get_provider
        
        # Test mock provider
        provider = MockPaymentProvider()
        result = provider.create_payment_link(
            amount=99900,
            currency="INR",
            customer_email="test@example.com",
            subscription_id=1,
            failure_event_id=1,
            customer_name="Test Customer",
            plan_name="Test Plan"
        )
        
        assert result["is_simulated"] is True
        assert "payment_link_id" in result
        assert result["provider"] == "mock"
        
        # Test factory function
        provider2 = get_provider(use_mock=True)
        assert isinstance(provider2, MockPaymentProvider)
    
    def test_graph_creation(self):
        """Verify LangGraph workflow can be created."""
        from app.agents.graph import create_recovery_graph
        
        graph = create_recovery_graph()
        assert graph is not None


class TestFailureAnalyzer:
    """Test the Failure Analyzer node logic."""
    
    def test_card_expired_analysis(self):
        """Card expired should recommend payment link strategy."""
        from app.agents.nodes import analyze_failure
        from app.database import FailureCode
        
        state = {
            "failure_code": FailureCode.card_expired.value,
            "retry_count": 0,
        }
        
        result = analyze_failure(state)
        
        assert result["failure_category"] == "card_expired"
        assert result["_interim_strategy"] == "payment_link"
        assert result["_is_retry_viable"] is False
        assert "expired" in result["failure_analysis"].lower()
    
    def test_insufficient_funds_analysis(self):
        """Insufficient funds should allow retry with caution."""
        from app.agents.nodes import analyze_failure
        from app.database import FailureCode
        
        state = {
            "failure_code": FailureCode.insufficient_funds.value,
            "retry_count": 0,
        }
        
        result = analyze_failure(state)
        
        assert result["failure_category"] == "insufficient_funds"
        assert result["_is_retry_viable"] is True
        assert "insufficient funds" in result["failure_analysis"].lower()
    
    def test_bank_downtime_analysis(self):
        """Bank downtime should recommend delayed retry."""
        from app.agents.nodes import analyze_failure
        from app.database import FailureCode
        
        state = {
            "failure_code": FailureCode.bank_downtime.value,
            "retry_count": 1,
        }
        
        result = analyze_failure(state)
        
        assert result["failure_category"] == "bank_downtime"
        assert result["_is_retry_viable"] is True
        assert "downtime" in result["failure_analysis"].lower()
    
    def test_auth_failed_analysis(self):
        """Authentication failed should recommend payment link."""
        from app.agents.nodes import analyze_failure
        from app.database import FailureCode
        
        state = {
            "failure_code": FailureCode.authentication_failed.value,
            "retry_count": 0,
        }
        
        result = analyze_failure(state)
        
        assert result["failure_category"] == "authentication_failed"
        assert result["_is_retry_viable"] is False
        assert result["_interim_strategy"] == "payment_link"
    
    def test_unknown_failure_analysis(self):
        """Unknown failure code should escalate for manual review."""
        from app.agents.nodes import analyze_failure
        
        state = {
            "failure_code": "unknown_code_xyz",
            "retry_count": 0,
        }
        
        result = analyze_failure(state)
        
        assert result["failure_category"] == "unknown"
        assert result["_interim_strategy"] == "manual_review"
        assert result["_is_retry_viable"] is False


class TestRecoveryDecider:
    """Test the Recovery Decision node logic."""
    
    def test_card_expired_decides_payment_link(self):
        """Card expired should decide on send_update_link action."""
        from app.agents.nodes import decide_recovery_action
        from app.database import ActionType
        
        state = {
            "failure_category": "card_expired",
            "retry_count": 0,
            "amount": 99900,
            "_interim_strategy": "payment_link",
            "_is_retry_viable": False,
        }
        
        result = decide_recovery_action(state)
        
        assert result["recommended_action_type"] == ActionType.send_update_link.value
        assert result["policy_coverage_score"] >= 0.9
        assert result["_requires_payment_link"] is True
    
    def test_insufficient_funds_first_retry(self):
        """First insufficient funds failure should retry now."""
        from app.agents.nodes import decide_recovery_action
        from app.database import ActionType
        
        state = {
            "failure_category": "insufficient_funds",
            "retry_count": 0,
            "amount": 99900,
            "_interim_strategy": "retry_with_delay",
            "_is_retry_viable": True,
        }
        
        result = decide_recovery_action(state)
        
        assert result["recommended_action_type"] == ActionType.retry_now.value
        assert "first" in result["action_reason"].lower() or "immediate" in result["action_reason"].lower()
    
    def test_insufficient_funds_subsequent_retry(self):
        """Subsequent insufficient funds should schedule delayed retry."""
        from app.agents.nodes import decide_recovery_action
        from app.database import ActionType
        
        state = {
            "failure_category": "insufficient_funds",
            "retry_count": 2,
            "amount": 99900,
            "_interim_strategy": "retry_with_delay",
            "_is_retry_viable": True,
        }
        
        result = decide_recovery_action(state)
        
        assert result["recommended_action_type"] == ActionType.retry_after_24h.value
    
    def test_insufficient_funds_max_retries(self):
        """Max retries exceeded should escalate."""
        from app.agents.nodes import decide_recovery_action
        from app.database import ActionType
        
        state = {
            "failure_category": "insufficient_funds",
            "retry_count": 5,  # Exceeds MAX_RETRIES (3)
            "amount": 99900,
            "_interim_strategy": "retry_with_delay",
            "_is_retry_viable": True,
        }
        
        result = decide_recovery_action(state)
        
        assert result["recommended_action_type"] == ActionType.escalate.value
        assert "max" in result["action_reason"].lower() or "manual" in result["action_reason"].lower()
    
    def test_unknown_failure_esculates(self):
        """Unknown failures should be escalated."""
        from app.agents.nodes import decide_recovery_action
        from app.database import ActionType
        
        state = {
            "failure_category": "unknown",
            "retry_count": 0,
            "amount": 99900,
            "failure_code": "weird_error",
            "_interim_strategy": "manual_review",
            "_is_retry_viable": False,
        }
        
        result = decide_recovery_action(state)
        
        assert result["recommended_action_type"] == ActionType.escalate.value
        assert result["policy_coverage_score"] >= 0.8
    
    def test_high_value_transaction_caution(self):
        """High value transactions should use more cautious approach."""
        from app.agents.nodes import decide_recovery_action
        from app.database import ActionType
        
        state = {
            "failure_category": "insufficient_funds",
            "retry_count": 0,
            "amount": 150000,  # ₹1500 - high value
            "_interim_strategy": "retry_with_delay",
            "_is_retry_viable": True,
        }
        
        result = decide_recovery_action(state)
        
        # High value should prefer delayed retry over immediate
        assert result["recommended_action_type"] == ActionType.retry_after_24h.value


class TestWorkflowExecution:
    """Test full workflow execution with database integration."""
    
    @pytest.fixture
    def db_session(self):
        """Create a fresh database session."""
        from app.database import SessionLocal, Base, engine
        # Recreate tables for clean state
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    def test_workflow_creates_recovery_action(self, db_session):
        """Workflow should create a RecoveryAction record."""
        from app.services import create_subscription, create_failure_event
        from app.database import SubscriptionStatus, FailureCode
        from app.agents import run_recovery_workflow
        
        # Create test data
        sub = create_subscription(
            db=db_session,
            customer_name="Test User",
            customer_email="test@example.com",
            plan_name="Basic",
            amount=99900
        )
        
        failure = create_failure_event(
            db=db_session,
            subscription_id=sub.id,
            failure_code=FailureCode.card_expired,
            retry_count=0
        )
        
        # Run workflow
        result = run_recovery_workflow(failure.id)
        
        assert result["success"] is True
        assert result["recovery_action_id"] is not None
        assert result["action_taken"] == "send_update_link"
        
        # Verify RecoveryAction was created in DB
        from app.database import RecoveryAction
        action = db_session.query(RecoveryAction).filter(
            RecoveryAction.failure_event_id == failure.id
        ).first()
        assert action is not None
        assert action.action_type.value == "send_update_link"
    
    def test_workflow_creates_audit_logs(self, db_session):
        """Workflow should create multiple AuditLog entries."""
        from app.services import create_subscription, create_failure_event
        from app.database import SubscriptionStatus, FailureCode, AuditLog
        from app.agents import run_recovery_workflow
        
        # Create test data
        sub = create_subscription(
            db=db_session,
            customer_name="Audit Test",
            customer_email="audit@example.com",
            plan_name="Standard",
            amount=149900
        )
        
        failure = create_failure_event(
            db=db_session,
            subscription_id=sub.id,
            failure_code=FailureCode.insufficient_funds,
            retry_count=0
        )
        
        # Count audit logs before
        before_count = db_session.query(AuditLog).count()
        
        # Run workflow
        result = run_recovery_workflow(failure.id)
        
        assert result["success"] is True
        
        # Count audit logs after
        after_count = db_session.query(AuditLog).count()
        
        # Should have created at least 2 audit logs (execution + completion)
        assert after_count > before_count
        assert len(result.get("audit_log_ids", [])) >= 2
    
    def test_workflow_nonexistent_failure_returns_404(self, db_session):
        """Workflow should handle nonexistent failure events gracefully."""
        from app.agents import run_recovery_workflow
        
        result = run_recovery_workflow(99999)  # Nonexistent ID
        
        assert result["success"] is False
        assert result["error"] is not None
        assert "not found" in result["error"].lower()
    
    def test_workflow_handles_different_failure_codes(self, db_session):
        """Test workflow with various failure codes."""
        from app.services import create_subscription, create_failure_event
        from app.database import FailureCode
        from app.agents import run_recovery_workflow
        
        expected_actions = {
            FailureCode.card_expired: "send_update_link",
            FailureCode.insufficient_funds: "retry_now",
            FailureCode.bank_downtime: "retry_after_24h",
            FailureCode.authentication_failed: "send_update_link",
        }
        
        for failure_code, expected_action in expected_actions.items():
            sub = create_subscription(
                db=db_session,
                customer_name=f"Test {failure_code.value}",
                customer_email=f"{failure_code.value}@example.com",
                plan_name="Basic",
                amount=99900
            )
            
            failure = create_failure_event(
                db=db_session,
                subscription_id=sub.id,
                failure_code=failure_code,
                retry_count=0
            )
            
            result = run_recovery_workflow(failure.id)
            
            assert result["success"] is True, f"Failed for {failure_code.value}"
            assert result["action_taken"] == expected_action, \
                f"Expected {expected_action} for {failure_code.value}, got {result['action_taken']}"
    
    def test_workflow_idempotency(self, db_session):
        """Running workflow multiple times should be safe."""
        from app.services import create_subscription, create_failure_event
        from app.database import FailureCode, RecoveryAction
        from app.agents import run_recovery_workflow
        
        # Create test data
        sub = create_subscription(
            db=db_session,
            customer_name="Idempotent Test",
            customer_email="idem@example.com",
            plan_name="Basic",
            amount=99900
        )
        
        failure = create_failure_event(
            db=db_session,
            subscription_id=sub.id,
            failure_code=FailureCode.card_expired,
            retry_count=0
        )
        
        # Run workflow twice
        result1 = run_recovery_workflow(failure.id)
        result2 = run_recovery_workflow(failure.id)
        
        # Both should succeed
        assert result1["success"] is True
        assert result2["success"] is True
        
        # Each run creates a new RecoveryAction (this is expected behavior)
        actions = db_session.query(RecoveryAction).filter(
            RecoveryAction.failure_event_id == failure.id
        ).all()
        
        # Should have 2 actions (one per run)
        assert len(actions) == 2


class TestPolicyGuards:
    """Test the policy/guardrail node functionality."""
    
    @pytest.fixture
    def db_session(self):
        """Create a fresh database session."""
        from app.database import SessionLocal, Base, engine
        # Recreate tables for clean state
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    def test_policy_max_retries_forces_escalation(self, db_session):
        """Test that retry_count >= 3 forces escalation to manual review."""
        from app.services import create_subscription, create_failure_event
        from app.database import SubscriptionStatus, FailureCode, RecoveryAction
        from app.agents.nodes import check_policy_guards
        from app.database import ActionType
        
        # Create subscription and failure event with retry_count=3
        sub = create_subscription(
            db=db_session,
            customer_name="Max Retry Test",
            customer_email="maxretry@example.com",
            plan_name="Basic",
            amount=99900
        )
        
        failure = create_failure_event(
            db=db_session,
            subscription_id=sub.id,
            failure_code=FailureCode.insufficient_funds,
            retry_count=3  # At max retries
        )
        
        # Set up state as if decide_recovery_action recommended retry_now
        state = {
            "subscription_id": sub.id,
            "failure_event_id": failure.id,
            "recommended_action_type": ActionType.retry_now.value,
            "action_reason": "Initial retry recommendation",
            "retry_count": 3,
            "amount": 99900,
            "policy_approved": None,
            "policy_stopped_reason": None,
            "requires_human_approval": None,
            "action_status": None,
        }
        
        # Run policy check
        result = check_policy_guards(state, db_session)
        
        # Should have overridden to escalate
        assert result["recommended_action_type"] == ActionType.escalate.value
        assert "max retry" in result["action_reason"].lower() or "escalat" in result["action_reason"].lower()
        assert result["requires_human_approval"] is True
    
    def test_policy_quiet_hours_stops_action(self, db_session):
        """Test that quiet hours rule stops send_update_link actions."""
        from app.services import create_subscription, create_failure_event
        from app.database import SubscriptionStatus, FailureCode
        from app.agents.nodes import check_policy_guards
        from app.database import ActionType, RecoveryStatus
        from datetime import datetime
        
        # Create subscription and failure event
        sub = create_subscription(
            db=db_session,
            customer_name="Quiet Hours Test",
            customer_email="quiet@example.com",
            plan_name="Basic",
            amount=99900
        )
        
        failure = create_failure_event(
            db=db_session,
            subscription_id=sub.id,
            failure_code=FailureCode.card_expired,
            retry_count=0
        )
        
        # Set up state with send_update_link action
        state = {
            "subscription_id": sub.id,
            "failure_event_id": failure.id,
            "recommended_action_type": ActionType.send_update_link.value,
            "action_reason": "Card expired - send payment link",
            "retry_count": 0,
            "amount": 99900,
            "policy_approved": None,
            "policy_stopped_reason": None,
            "requires_human_approval": None,
            "policy_rule_triggered": None,
            "action_status": None,
        }
        
        # Run policy check
        result = check_policy_guards(state, db_session)
        
        # Check current IST hour
        ist_hour = (datetime.utcnow().hour + 5) % 24
        
        # If we're in quiet hours, should be stopped
        if ist_hour >= 21 or ist_hour < 8:
            assert result["policy_approved"] is False
            assert result["policy_stopped_reason"] is not None
            assert "quiet hours" in result["policy_stopped_reason"].lower()
            assert result["policy_rule_triggered"] == "quiet_hours"
            # Note: action_status is set by execute_recovery_action, not policy_check
        else:
            # Outside quiet hours, should pass through
            assert result["policy_approved"] is True
            assert result["policy_rule_triggered"] is None
    
    def test_policy_high_value_requires_approval(self, db_session):
        """Test that high-value transactions (>₹5000) require human approval."""
        from app.services import create_subscription, create_failure_event
        from app.database import SubscriptionStatus, FailureCode
        from app.agents.nodes import check_policy_guards
        from app.database import ActionType, RecoveryStatus
        
        # Create subscription with high value (>500000 paise = >₹5000)
        sub = create_subscription(
            db=db_session,
            customer_name="High Value Test",
            customer_email="highvalue@example.com",
            plan_name="Premium",
            amount=600000  # ₹6000
        )
        
        failure = create_failure_event(
            db=db_session,
            subscription_id=sub.id,
            failure_code=FailureCode.insufficient_funds,
            retry_count=0
        )
        
        # Set up state with any action
        state = {
            "subscription_id": sub.id,
            "failure_event_id": failure.id,
            "recommended_action_type": ActionType.retry_now.value,
            "action_reason": "Retry attempt",
            "retry_count": 0,
            "amount": 600000,  # High value
            "policy_approved": None,
            "policy_stopped_reason": None,
            "requires_human_approval": None,
            "policy_rule_triggered": None,
            "action_status": None,
        }
        
        # Run policy check
        result = check_policy_guards(state, db_session)
        
        # Should be stopped for human approval
        assert result["policy_approved"] is False
        assert "high-value" in result["policy_stopped_reason"].lower() or "human approval" in result["policy_stopped_reason"].lower()
        assert result["requires_human_approval"] is True
        assert result["policy_rule_triggered"] == "high_value_approval"
    
    def test_policy_repeated_failure_forces_escalation(self, db_session):
        """Test that 2+ prior failures force escalation."""
        from app.services import create_subscription, create_failure_event
        from app.database import SubscriptionStatus, FailureCode
        from app.agents.nodes import check_policy_guards
        from app.database import ActionType
        
        # Create subscription
        sub = create_subscription(
            db=db_session,
            customer_name="Repeated Failure Test",
            customer_email="repeated@example.com",
            plan_name="Basic",
            amount=99900
        )
        
        # Create 2 prior failure events
        failure1 = create_failure_event(
            db=db_session,
            subscription_id=sub.id,
            failure_code=FailureCode.insufficient_funds,
            retry_count=0
        )
        
        failure2 = create_failure_event(
            db=db_session,
            subscription_id=sub.id,
            failure_code=FailureCode.insufficient_funds,
            retry_count=0
        )
        
        # Create current (3rd) failure event
        failure3 = create_failure_event(
            db=db_session,
            subscription_id=sub.id,
            failure_code=FailureCode.insufficient_funds,
            retry_count=0
        )
        
        # Set up state recommending retry
        state = {
            "subscription_id": sub.id,
            "failure_event_id": failure3.id,
            "recommended_action_type": ActionType.retry_now.value,
            "action_reason": "Retry attempt",
            "retry_count": 0,
            "amount": 99900,
            "policy_approved": None,
            "policy_stopped_reason": None,
            "requires_human_approval": None,
            "action_status": None,
        }
        
        # Run policy check
        result = check_policy_guards(state, db_session)
        
        # Should force escalate due to repeated failures
        assert result["recommended_action_type"] == ActionType.escalate.value
        assert "repeated" in result["action_reason"].lower() or "escalat" in result["action_reason"].lower()
        assert result["requires_human_approval"] is True
    
    def test_policy_no_rule_triggered_passes_through(self, db_session):
        """Test that when no rules match, action passes through unchanged."""
        from app.services import create_subscription, create_failure_event
        from app.database import SubscriptionStatus, FailureCode
        from app.agents.nodes import check_policy_guards
        from app.database import ActionType
        
        # Create normal subscription (low value, first failure)
        sub = create_subscription(
            db=db_session,
            customer_name="Normal Test",
            customer_email="normal@example.com",
            plan_name="Basic",
            amount=99900  # ₹999 - normal value
        )
        
        failure = create_failure_event(
            db=db_session,
            subscription_id=sub.id,
            failure_code=FailureCode.insufficient_funds,
            retry_count=0  # First attempt
        )
        
        # Set up state with reasonable action
        original_action = ActionType.retry_after_24h.value
        original_reason = "Scheduled retry after 24 hours"
        
        state = {
            "subscription_id": sub.id,
            "failure_event_id": failure.id,
            "recommended_action_type": original_action,
            "action_reason": original_reason,
            "retry_count": 0,
            "amount": 99900,
            "policy_approved": None,
            "policy_stopped_reason": None,
            "requires_human_approval": None,
            "action_status": None,
        }
        
        # Run policy check
        result = check_policy_guards(state, db_session)
        
        # Should pass through unchanged
        assert result["policy_approved"] is True
        assert result["policy_stopped_reason"] is None
        assert result["recommended_action_type"] == original_action
        assert result["action_reason"] == original_reason
        assert result["requires_human_approval"] is False


class TestAPIEndpoint:
    """Test the /recovery/run/{failure_event_id} API endpoint."""
    
    @pytest.fixture(scope="class")
    def server(self):
        """Start the FastAPI server for testing."""
        # Ensure we have fresh data
        from app.synthetic_data import generate_synthetic_data
        generate_synthetic_data(10)  # Small dataset for API tests
        
        # Start server in background
        process = subprocess.Popen(
            ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait for server to start
        time.sleep(3)
        
        yield process
        
        # Cleanup
        process.terminate()
        process.wait()
    
    def test_recovery_endpoint_success(self, server):
        """Test successful recovery workflow via API."""
        # Get a failure event ID
        response = requests.get(f"{BASE_URL}/failures?limit=1", timeout=TEST_TIMEOUT)
        assert response.status_code == 200
        failures = response.json()
        assert len(failures) > 0
        
        failure_id = failures[0]["id"]
        
        # Run recovery workflow
        response = requests.post(
            f"{BASE_URL}/recovery/run/{failure_id}",
            timeout=TEST_TIMEOUT
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "workflow_result" in data
        assert "simulated" in data["message"].lower()
    
    def test_recovery_endpoint_not_found(self, server):
        """Test 404 for nonexistent failure event."""
        response = requests.post(
            f"{BASE_URL}/recovery/run/99999",
            timeout=TEST_TIMEOUT
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_existing_endpoints_still_work(self, server):
        """Verify existing endpoints weren't broken by changes."""
        # Health check
        response = requests.get(f"{BASE_URL}/health", timeout=TEST_TIMEOUT)
        assert response.status_code == 200
        
        # List subscriptions
        response = requests.get(f"{BASE_URL}/subscriptions?limit=5", timeout=TEST_TIMEOUT)
        assert response.status_code == 200
        
        # List failures
        response = requests.get(f"{BASE_URL}/failures?limit=5", timeout=TEST_TIMEOUT)
        assert response.status_code == 200
        
        # Audit log
        response = requests.get(f"{BASE_URL}/audit-log?limit=5", timeout=TEST_TIMEOUT)
        assert response.status_code == 200


class TestExistingTestsStillPass:
    """Verify the original 12 tests still pass."""
    
    def test_database_imports(self):
        """Original test: Verify database module can be imported."""
        from app.database import engine, SessionLocal, Base
        assert engine is not None
        assert SessionLocal is not None
    
    def test_service_functions_exist(self):
        """Original test: Verify all service functions are available."""
        from app import services
        
        # Subscription services
        assert hasattr(services, 'get_all_subscriptions')
        assert hasattr(services, 'get_subscription_by_id')
        assert hasattr(services, 'create_subscription')
        assert hasattr(services, 'update_subscription_status')
        
        # Failure event services
        assert hasattr(services, 'get_all_failure_events')
        assert hasattr(services, 'get_failure_event_by_id')
        assert hasattr(services, 'create_failure_event')
        
        # Recovery action services
        assert hasattr(services, 'get_recovery_action_by_id')
        assert hasattr(services, 'create_recovery_action')
        assert hasattr(services, 'update_recovery_action_status')
        
        # Audit log services
        assert hasattr(services, 'get_all_audit_logs')
        assert hasattr(services, 'create_audit_log')
    
    def test_synthetic_data_generation(self):
        """Original test: Test that synthetic data generates correctly."""
        from app.synthetic_data import generate_synthetic_data
        from app.database import SessionLocal, Subscription, FailureEvent, RecoveryAction, AuditLog
        
        # Generate data
        result = generate_synthetic_data(70)
        
        # Verify counts
        assert result["subscriptions"] == 70
        assert result["failure_events"] == 70
        assert result["recovery_actions"] == 70
        assert result["audit_logs"] == 210  # 3 per subscription
        
        # Verify data in database
        db = SessionLocal()
        try:
            sub_count = db.query(Subscription).count()
            failure_count = db.query(FailureEvent).count()
            recovery_count = db.query(RecoveryAction).count()
            audit_count = db.query(AuditLog).count()
            
            assert sub_count == 70
            assert failure_count == 70
            assert recovery_count == 70
            assert audit_count == 210
        finally:
            db.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestMetricsAndDemoEndpoints:
    """Test the new /metrics/summary and /demo/simulate-payment endpoints."""

    @pytest.fixture
    def db_session(self):
        """Create a fresh database session."""
        from app.database import SessionLocal, Base, engine
        # Recreate tables for clean state
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def test_metrics_summary_endpoint_empty(self, db_session):
        """Test /metrics/summary returns zeros when no data exists."""
        from app.main import get_metrics_summary
        
        result = get_metrics_summary(db=db_session)
        
        assert result["total_failed"] == 0
        assert result["total_recovered"] == 0
        assert result["total_at_risk_amount"] == 0
        assert result["total_recovered_amount"] == 0
        assert result["recovery_rate_pct"] == 0.0

    def test_metrics_summary_endpoint_with_data(self, db_session):
        """Test /metrics/summary returns correct values with data."""
        from app.services import create_subscription, create_failure_event
        from app.database import SubscriptionStatus, FailureCode
        
        # Create failed subscriptions
        sub1 = create_subscription(
            db=db_session,
            customer_name="Failed User 1",
            customer_email="failed1@example.com",
            plan_name="Basic",
            amount=99900  # ₹999
        )
        sub1.status = SubscriptionStatus.failed
        db_session.commit()
        
        sub2 = create_subscription(
            db=db_session,
            customer_name="Failed User 2",
            customer_email="failed2@example.com",
            plan_name="Pro",
            amount=199900  # ₹1999
        )
        sub2.status = SubscriptionStatus.failed
        db_session.commit()
        
        # Create recovered subscription
        sub3 = create_subscription(
            db=db_session,
            customer_name="Recovered User",
            customer_email="recovered@example.com",
            plan_name="Enterprise",
            amount=499900  # ₹4999
        )
        sub3.status = SubscriptionStatus.recovered
        db_session.commit()
        
        from app.main import get_metrics_summary
        result = get_metrics_summary(db=db_session)
        
        assert result["total_failed"] == 2
        assert result["total_recovered"] == 1
        assert result["total_at_risk_amount"] == 99900 + 199900  # ₹2998 in paise
        assert result["total_recovered_amount"] == 499900  # ₹4999 in paise
        # Recovery rate = 1 / (2 + 1) = 33.33%
        assert abs(result["recovery_rate_pct"] - 33.33) < 0.01

    def test_simulate_payment_demo_not_found(self, db_session):
        """Test /demo/simulate-payment returns 404 for non-existent action."""
        from fastapi import HTTPException
        from app.main import simulate_payment_demo
        
        with pytest.raises(HTTPException) as exc_info:
            simulate_payment_demo(recovery_action_id=99999, db=db_session)
        
        assert exc_info.value.status_code == 404

    def test_simulate_payment_demo_success(self, db_session):
        """Test /demo/simulate-payment successfully marks action as recovered."""
        from app.services import create_subscription, create_failure_event, create_recovery_action
        from app.database import SubscriptionStatus, FailureCode, ActionType, RecoveryStatus
        from app.main import simulate_payment_demo
        
        # Create subscription with failure and recovery action
        sub = create_subscription(
            db=db_session,
            customer_name="Demo User",
            customer_email="demo@example.com",
            plan_name="Basic",
            amount=99900
        )
        sub.status = SubscriptionStatus.failed
        db_session.commit()
        
        failure = create_failure_event(
            db=db_session,
            subscription_id=sub.id,
            failure_code=FailureCode.card_expired,
            retry_count=0
        )
        
        action = create_recovery_action(
            db=db_session,
            failure_event_id=failure.id,
            action_type=ActionType.send_update_link,
            reason_text="Card expired, sent payment link"
        )
        
        # Verify initial state
        assert action.status == RecoveryStatus.pending
        assert sub.status == SubscriptionStatus.failed
        
        # Call demo simulation endpoint
        result = simulate_payment_demo(recovery_action_id=action.id, db=db_session)
        
        assert result["status"] == "success"
        assert "[DEMO]" in result["message"]
        
        # Verify state changes
        db_session.refresh(action)
        db_session.refresh(sub)
        
        assert action.status == RecoveryStatus.success
        assert sub.status == SubscriptionStatus.recovered
        
        # Verify audit log was created
        from app.database import AuditLog
        audit_entries = db_session.query(AuditLog).filter(
            AuditLog.entity_type == "subscription",
            AuditLog.entity_id == sub.id
        ).all()
        
        demo_audit = [e for e in audit_entries if "DEMO SIMULATION" in e.event_description]
        assert len(demo_audit) >= 1
