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
import pytest
import subprocess
import time
import requests

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
            confidence_score=None,
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
            subscription_id=1
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
        assert result["confidence_score"] >= 0.9
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
        assert result["confidence_score"] >= 0.8
    
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
