"""
ChurnGuard - AI Agent for Subscription Payment Recovery

FastAPI backend entrypoint with basic CRUD endpoints and LangGraph recovery workflow.
Business logic is kept in service layer for LangGraph agent integration.
"""
from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db, Base, engine
from app.schemas import (
    Subscription as SubscriptionSchema,
    FailureEvent as FailureEventSchema,
    AuditLog as AuditLogSchema,
)
from app import services

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="ChurnGuard",
    description="AI agent that recovers failed subscription payments using Razorpay APIs",
    version="0.1.0"
)


# Subscription Endpoints
@app.get("/subscriptions", response_model=List[SubscriptionSchema])
def list_subscriptions(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all subscriptions with pagination."""
    return services.get_all_subscriptions(db, skip=skip, limit=limit)


@app.get("/subscriptions/{subscription_id}", response_model=SubscriptionSchema)
def get_subscription(subscription_id: int, db: Session = Depends(get_db)):
    """Get detailed information about a specific subscription including failure events and recovery actions."""
    subscription = services.get_subscription_by_id(db, subscription_id)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subscription {subscription_id} not found"
        )
    return subscription


# Failure Events Endpoints
@app.get("/failures", response_model=List[FailureEventSchema])
def list_failures(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all payment failure events with pagination."""
    return services.get_all_failure_events(db, skip=skip, limit=limit)


# Data Generation Endpoint
@app.post("/generate-data")
def generate_synthetic_data(db: Session = Depends(get_db)):
    """Generate synthetic test data (70 subscriptions with failures)."""
    try:
        # Import here to avoid circular imports
        from app.synthetic_data import generate_synthetic_data as gen_data
        result = gen_data(70)
        return {
            "message": "Synthetic data generated successfully",
            "data": result
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# Audit Log Endpoints
@app.get("/audit-log", response_model=List[AuditLogSchema])
def list_audit_logs(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all audit log entries with pagination."""
    return services.get_all_audit_logs(db, skip=skip, limit=limit)


# Recovery Workflow Endpoint
@app.post("/recovery/run/{failure_event_id}")
def run_recovery_workflow(failure_event_id: int, db: Session = Depends(get_db)):
    """
    Run the AI-powered recovery workflow for a specific failure event.
    
    This endpoint:
    1. Validates that the failure event exists
    2. Loads the associated subscription
    3. Runs the LangGraph workflow (analyze -> decide -> execute)
    4. Persists the RecoveryAction record
    5. Writes AuditLog entries
    6. Returns structured results
    
    IMPORTANT: All operations are simulated (mock provider). No real payments are processed.
    """
    from app.agents import run_recovery_workflow as run_workflow
    from app.services import get_failure_event_by_id
    
    # Validate failure event exists
    failure_event = get_failure_event_by_id(db, failure_event_id)
    if not failure_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failure event {failure_event_id} not found"
        )
    
    # Check if subscription exists
    subscription = services.get_subscription_by_id(db, failure_event.subscription_id)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subscription {failure_event.subscription_id} not found"
        )
    
    # Run the recovery workflow
    try:
        result = run_workflow(failure_event_id)
        
        # Handle errors from workflow
        if not result.get("success") and result.get("error"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error")
            )
        
        return {
            "success": True,
            "workflow_result": result,
            "message": f"Recovery action '{result.get('action_taken')}' initiated (simulated)"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow execution failed: {str(e)}"
        )


# Health check endpoint
@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
