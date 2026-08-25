"""
ChurnGuard - AI Agent for Subscription Payment Recovery

FastAPI backend entrypoint with basic CRUD endpoints and LangGraph recovery workflow.
Business logic is kept in service layer for LangGraph agent integration.
"""
from fastapi import FastAPI, Depends, HTTPException, status, Request, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import hmac
import hashlib
import os

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


# Razorpay Webhook Endpoint
@app.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle Razorpay webhook events for payment_link.paid and payment.captured.
    
    Verifies webhook signature using RAZORPAY_WEBHOOK_SECRET.
    Updates RecoveryAction and Subscription status on successful payment.
    """
    from app.database import RecoveryAction, Subscription, RecoveryStatus, SubscriptionStatus
    from app.services import create_audit_log
    from app.database import EntityType
    
    # Get webhook secret from environment
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    if not webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="RAZORPAY_WEBHOOK_SECRET not configured"
        )
    
    # Get the raw body and signature
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Razorpay-Signature header"
        )
    
    # Verify webhook signature
    try:
        import razorpay
        utility = razorpay.Utility()
        # Verify using Razorpay's utility
        verified = utility.verify_webhook_signature(
            body.decode('utf-8'),
            signature,
            webhook_secret
        )
        if not verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid webhook signature"
            )
    except Exception as e:
        # Fallback to manual verification if SDK method fails
        expected_signature = hmac.new(
            webhook_secret.encode('utf-8'),
            body,
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_signature):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid webhook signature"
            )
    
    # Parse the payload
    import json
    try:
        payload = json.loads(body.decode('utf-8'))
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )
    
    # Extract event data
    event_name = payload.get("event", "")
    entity = payload.get("payload", {})
    
    # Handle payment_link.paid event
    if event_name == "payment_link.paid":
        payment_link_data = entity.get("payment_link", {}).get("entity", {})
        payment_link_id = payment_link_data.get("id")
        
        if not payment_link_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing payment_link.id in payload"
            )
        
        # Find the matching RecoveryAction by razorpay_payment_link_id
        recovery_action = db.query(RecoveryAction).filter(
            RecoveryAction.razorpay_payment_link_id == payment_link_id
        ).first()
        
        if not recovery_action:
            # Payment link not found in our system - might be from another source
            # Return 200 anyway to avoid Razorpay retrying
            return {"status": "ignored", "reason": "payment_link_not_found_in_system"}
        
        # Update RecoveryAction status to success
        recovery_action.status = RecoveryStatus.success
        recovery_action.resolved_at = services.datetime.utcnow()
        db.commit()
        
        # Update associated Subscription status to recovered
        failure_event = recovery_action.failure_event
        if failure_event:
            subscription = failure_event.subscription
            if subscription:
                subscription.status = SubscriptionStatus.recovered
                db.commit()
                
                # Log audit entry
                create_audit_log(
                    db=db,
                    entity_type=EntityType.subscription,
                    entity_id=subscription.id,
                    event_description=f"Subscription recovered via Razorpay payment link {payment_link_id}. Amount: ₹{payment_link_data.get('amount', 0)/100:.2f}"
                )
        
        return {"status": "success", "recovery_action_id": recovery_action.id}
    
    # Handle payment.captured event (alternative event type)
    elif event_name == "payment.captured":
        payment_data = entity.get("payment", {}).get("entity", {})
        payment_link_id = payment_data.get("payment_link_id")
        
        if not payment_link_id:
            # Not a payment link payment, ignore
            return {"status": "ignored", "reason": "not_a_payment_link_payment"}
        
        # Find the matching RecoveryAction
        recovery_action = db.query(RecoveryAction).filter(
            RecoveryAction.razorpay_payment_link_id == payment_link_id
        ).first()
        
        if not recovery_action:
            return {"status": "ignored", "reason": "payment_link_not_found_in_system"}
        
        # Update RecoveryAction status to success
        recovery_action.status = RecoveryStatus.success
        recovery_action.resolved_at = services.datetime.utcnow()
        db.commit()
        
        # Update associated Subscription
        failure_event = recovery_action.failure_event
        if failure_event and failure_event.subscription:
            subscription = failure_event.subscription
            subscription.status = SubscriptionStatus.recovered
            db.commit()
            
            # Log audit entry
            create_audit_log(
                db=db,
                entity_type=EntityType.subscription,
                entity_id=subscription.id,
                event_description=f"Subscription recovered via Razorpay payment captured. Amount: ₹{payment_data.get('amount', 0)/100:.2f}"
            )
        
        return {"status": "success", "recovery_action_id": recovery_action.id}
    
    # Other events - acknowledge but don't process
    else:
        return {"status": "ignored", "event": event_name}


# Batch Recovery Endpoint
@app.post("/recovery/run-batch")
def run_batch_recovery(
    failure_event_ids: Optional[List[int]] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Run recovery workflow for multiple failure events.
    
    If failure_event_ids is provided, processes only those events.
    Otherwise, processes all failure events with pending or no successful RecoveryAction.
    
    Returns summary statistics including actions by type, stopped by policy, errors, etc.
    Catches errors per-record so one failure doesn't stop the batch.
    """
    from app.agents import run_recovery_workflow
    from app.database import FailureEvent, RecoveryAction, RecoveryStatus
    from sqlalchemy import or_
    
    # Determine which failure events to process
    if failure_event_ids:
        # Process specified events
        events_to_process = db.query(FailureEvent).filter(
            FailureEvent.id.in_(failure_event_ids)
        ).all()
    else:
        # Process all events without successful recovery actions
        # Get all failure events
        all_events = db.query(FailureEvent).all()
        
        # Filter out events that already have a successful recovery action
        events_to_process = []
        for event in all_events:
            has_successful_action = db.query(RecoveryAction).filter(
                RecoveryAction.failure_event_id == event.id,
                RecoveryAction.status == RecoveryStatus.success
            ).first() is not None
            
            if not has_successful_action:
                events_to_process.append(event)
    
    # Initialize counters
    total_processed = 0
    actions_by_type = {}
    stopped_by_policy = 0
    errors = 0
    payment_links_created = 0
    
    # Process each event sequentially
    for failure_event in events_to_process:
        total_processed += 1
        
        try:
            # Run the recovery workflow
            result = run_recovery_workflow(failure_event.id)
            
            # Count action types
            action_taken = result.get("action_taken")
            if action_taken:
                actions_by_type[action_taken] = actions_by_type.get(action_taken, 0) + 1
                
                if action_taken == "send_update_link" and result.get("razorpay_payment_link_id"):
                    payment_links_created += 1
            
            # Check if stopped by policy
            if result.get("action_status") == "stopped_by_rule":
                stopped_by_policy += 1
            
            # Check for errors
            if result.get("error"):
                errors += 1
                
        except Exception as e:
            errors += 1
            # Continue processing other events - don't let one failure stop the batch
            continue
    
    return {
        "total_processed": total_processed,
        "actions_by_type": actions_by_type,
        "stopped_by_policy": stopped_by_policy,
        "errors": errors,
        "payment_links_created": payment_links_created
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
