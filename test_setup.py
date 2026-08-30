"""
Test script for ChurnGuard setup verification.
Tests database connectivity, synthetic data generation, and API endpoints.
"""
import os
import pytest
import subprocess
import time
import requests
from sqlalchemy import text

# Ensure mock provider is used for all tests (test isolation)
os.environ["USE_MOCK_PROVIDER"] = "true"

# Test configuration
BASE_URL = "http://localhost:8000"
TEST_TIMEOUT = 30


class TestDatabaseConnection:
    """Test database connectivity."""
    
    def test_database_imports(self):
        """Verify database module can be imported."""
        from app.database import engine, SessionLocal, Base
        assert engine is not None
        assert SessionLocal is not None
    
    def test_database_tables_created(self):
        """Verify database tables are created on import."""
        from app.database import engine, Base
        # Check that tables exist
        inspector = __import__('sqlalchemy').inspect(engine)
        tables = inspector.get_table_names()
        assert 'subscriptions' in tables
        assert 'failure_events' in tables
        assert 'recovery_actions' in tables
        assert 'audit_logs' in tables


class TestSyntheticData:
    """Test synthetic data generation."""
    
    def test_synthetic_data_module_imports(self):
        """Verify synthetic_data module can be imported."""
        from app.synthetic_data import generate_synthetic_data, PLANS, FAILURE_CODE_WEIGHTS
        assert len(PLANS) >= 6
        assert FAILURE_CODE_WEIGHTS is not None
    
    def test_synthetic_data_generation(self):
        """Test that synthetic data generates correctly."""
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
            
            # Verify failure code distribution (card_expired and insufficient_funds should be most common)
            from app.database import FailureCode
            card_expired_count = db.query(FailureEvent).filter(
                FailureEvent.failure_code == FailureCode.card_expired
            ).count()
            insufficient_funds_count = db.query(FailureEvent).filter(
                FailureEvent.failure_code == FailureCode.insufficient_funds
            ).count()
            
            # Each should be roughly 35% of 70 = ~24-25
            assert card_expired_count > 15  # At least 20%
            assert insufficient_funds_count > 15  # At least 20%
            
        finally:
            db.close()


class TestAPIEndpoints:
    """Test FastAPI endpoints (requires running server)."""
    
    @pytest.fixture(scope="class")
    def server(self):
        """Start the FastAPI server for testing."""
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
    
    def test_health_endpoint(self, server):
        """Test health check endpoint."""
        response = requests.get(f"{BASE_URL}/health", timeout=TEST_TIMEOUT)
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
    
    def test_generate_data_endpoint(self, server):
        """Test data generation endpoint."""
        response = requests.post(f"{BASE_URL}/generate-data", timeout=TEST_TIMEOUT)
        assert response.status_code == 200
        data = response.json()
        # Message now includes count: "Synthetic data generated successfully (N subscriptions)"
        assert data["message"].startswith("Synthetic data generated successfully")
        assert data["data"]["subscriptions"] == 70
    
    def test_list_subscriptions_endpoint(self, server):
        """Test list subscriptions endpoint."""
        # Ensure data exists
        requests.post(f"{BASE_URL}/generate-data", timeout=TEST_TIMEOUT)
        
        response = requests.get(f"{BASE_URL}/subscriptions?limit=10", timeout=TEST_TIMEOUT)
        assert response.status_code == 200
        subscriptions = response.json()
        assert len(subscriptions) <= 10
    
    def test_get_subscription_detail_endpoint(self, server):
        """Test get subscription detail endpoint."""
        # Ensure data exists
        requests.post(f"{BASE_URL}/generate-data", timeout=TEST_TIMEOUT)
        
        response = requests.get(f"{BASE_URL}/subscriptions/1", timeout=TEST_TIMEOUT)
        assert response.status_code == 200
        subscription = response.json()
        assert "id" in subscription
        assert "customer_name" in subscription
        assert "failure_events" in subscription
    
    def test_list_failures_endpoint(self, server):
        """Test list failures endpoint."""
        # Ensure data exists
        requests.post(f"{BASE_URL}/generate-data", timeout=TEST_TIMEOUT)
        
        response = requests.get(f"{BASE_URL}/failures?limit=10", timeout=TEST_TIMEOUT)
        assert response.status_code == 200
        failures = response.json()
        assert len(failures) <= 10
    
    def test_audit_log_endpoint(self, server):
        """Test audit log endpoint."""
        # Ensure data exists
        requests.post(f"{BASE_URL}/generate-data", timeout=TEST_TIMEOUT)
        
        response = requests.get(f"{BASE_URL}/audit-log?limit=10", timeout=TEST_TIMEOUT)
        assert response.status_code == 200
        logs = response.json()
        assert len(logs) <= 10


class TestServices:
    """Test service layer functions."""
    
    def test_service_functions_exist(self):
        """Verify all service functions are available."""
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
        
        # Analytics services
        assert hasattr(services, 'get_failed_subscriptions_count')
        assert hasattr(services, 'get_pending_recovery_actions')
        assert hasattr(services, 'get_subscription_failure_history')
    
    def test_service_crud_operations(self):
        """Test basic CRUD operations through services."""
        from app.database import SessionLocal, SubscriptionStatus, FailureCode, ActionType, RecoveryStatus, EntityType
        from app import services
        
        db = SessionLocal()
        try:
            # Create a subscription
            sub = services.create_subscription(
                db=db,
                customer_name="Test User",
                customer_email="test@example.com",
                plan_name="Test Plan",
                amount=99900
            )
            assert sub.id is not None
            assert sub.customer_name == "Test User"
            
            # Get subscription
            retrieved = services.get_subscription_by_id(db, sub.id)
            assert retrieved is not None
            assert retrieved.customer_email == "test@example.com"
            
            # Update status
            updated = services.update_subscription_status(db, sub.id, SubscriptionStatus.failed)
            assert updated.status == SubscriptionStatus.failed
            
            # Create failure event
            failure = services.create_failure_event(
                db=db,
                subscription_id=sub.id,
                failure_code=FailureCode.card_expired
            )
            assert failure.id is not None
            
            # Create recovery action
            recovery = services.create_recovery_action(
                db=db,
                failure_event_id=failure.id,
                action_type=ActionType.retry_now,
                reason_text="Test recovery"
            )
            assert recovery.id is not None
            
            # Update recovery action
            updated_recovery = services.update_recovery_action_status(
                db=db,
                recovery_action_id=recovery.id,
                status=RecoveryStatus.success
            )
            assert updated_recovery.status == RecoveryStatus.success
            
            # Create audit log
            audit = services.create_audit_log(
                db=db,
                entity_type=EntityType.subscription,
                entity_id=sub.id,
                event_description="Test audit entry"
            )
            assert audit.id is not None
            
            # Get audit logs
            logs = services.get_all_audit_logs(db, limit=5)
            assert len(logs) > 0
            
        finally:
            db.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
