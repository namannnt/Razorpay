"""
Service layer for ChurnGuard - contains business logic separate from API endpoints.
This module is designed to be called by the LangGraph agent layer.
"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
import random

from app.database import (
    Subscription, FailureEvent, RecoveryAction, AuditLog,
    SubscriptionStatus, FailureCode, ActionType, RecoveryStatus, EntityType
)


# Service functions for Subscriptions
def get_all_subscriptions(db: Session, skip: int = 0, limit: int = 100):
    """Retrieve all subscriptions with pagination."""
    return db.query(Subscription).offset(skip).limit(limit).all()


def get_subscription_by_id(db: Session, subscription_id: int):
    """Retrieve a single subscription by ID with its failure events and recovery actions."""
    return db.query(Subscription).filter(Subscription.id == subscription_id).first()


def create_subscription(db: Session, customer_name: str, customer_email: str, 
                        plan_name: str, amount: int, currency: str = "INR",
                        status: SubscriptionStatus = SubscriptionStatus.active):
    """Create a new subscription."""
    db_subscription = Subscription(
        customer_name=customer_name,
        customer_email=customer_email,
        plan_name=plan_name,
        amount=amount,
        currency=currency,
        status=status
    )
    db.add(db_subscription)
    db.commit()
    db.refresh(db_subscription)
    
    # Log audit
    create_audit_log(
        db=db,
        entity_type=EntityType.subscription,
        entity_id=db_subscription.id,
        event_description=f"Subscription created for {customer_email}"
    )
    
    return db_subscription


def update_subscription_status(db: Session, subscription_id: int, status: SubscriptionStatus):
    """Update the status of a subscription."""
    db_subscription = db.query(Subscription).filter(Subscription.id == subscription_id).first()
    if db_subscription:
        old_status = db_subscription.status
        db_subscription.status = status
        db.commit()
        db.refresh(db_subscription)
        
        # Log audit
        create_audit_log(
            db=db,
            entity_type=EntityType.subscription,
            entity_id=subscription_id,
            event_description=f"Subscription status changed from {old_status.value} to {status.value}"
        )
        
        return db_subscription
    return None


# Service functions for Failure Events
def get_all_failure_events(db: Session, skip: int = 0, limit: int = 100):
    """Retrieve all failure events with pagination."""
    return db.query(FailureEvent).offset(skip).limit(limit).all()


def get_failure_event_by_id(db: Session, failure_event_id: int):
    """Retrieve a single failure event by ID."""
    return db.query(FailureEvent).filter(FailureEvent.id == failure_event_id).first()


def create_failure_event(db: Session, subscription_id: int, failure_code: FailureCode, 
                         retry_count: int = 0):
    """Create a new failure event."""
    db_failure = FailureEvent(
        subscription_id=subscription_id,
        failure_code=failure_code,
        retry_count=retry_count
    )
    db.add(db_failure)
    db.commit()
    db.refresh(db_failure)
    
    # Update subscription status to failed
    update_subscription_status(db, subscription_id, SubscriptionStatus.failed)
    
    # Log audit
    create_audit_log(
        db=db,
        entity_type=EntityType.failure_event,
        entity_id=db_failure.id,
        event_description=f"Payment failure detected: {failure_code.value}"
    )
    
    return db_failure


def increment_retry_count(db: Session, failure_event_id: int):
    """Increment the retry count for a failure event."""
    db_failure = db.query(FailureEvent).filter(FailureEvent.id == failure_event_id).first()
    if db_failure:
        db_failure.retry_count += 1
        db.commit()
        db.refresh(db_failure)
    return db_failure


# Service functions for Recovery Actions
def get_recovery_action_by_id(db: Session, recovery_action_id: int):
    """Retrieve a recovery action by ID."""
    return db.query(RecoveryAction).filter(RecoveryAction.id == recovery_action_id).first()


def create_recovery_action(db: Session, failure_event_id: int, action_type: ActionType,
                           reason_text: str = None, razorpay_payment_link_id: str = None):
    """Create a new recovery action."""
    db_action = RecoveryAction(
        failure_event_id=failure_event_id,
        action_type=action_type,
        reason_text=reason_text,
        razorpay_payment_link_id=razorpay_payment_link_id
    )
    db.add(db_action)
    db.commit()
    db.refresh(db_action)
    
    # Log audit
    create_audit_log(
        db=db,
        entity_type=EntityType.recovery_action,
        entity_id=db_action.id,
        event_description=f"Recovery action initiated: {action_type.value}"
    )
    
    return db_action


def update_recovery_action_status(db: Session, recovery_action_id: int, 
                                   status: RecoveryStatus, reason_text: str = None):
    """Update the status of a recovery action."""
    db_action = db.query(RecoveryAction).filter(RecoveryAction.id == recovery_action_id).first()
    if db_action:
        db_action.status = status
        db_action.reason_text = reason_text or db_action.reason_text
        if status in [RecoveryStatus.success, RecoveryStatus.failed, RecoveryStatus.stopped_by_rule]:
            db_action.resolved_at = datetime.utcnow()
        db.commit()
        db.refresh(db_action)
        
        # Log audit
        create_audit_log(
            db=db,
            entity_type=EntityType.recovery_action,
            entity_id=recovery_action_id,
            event_description=f"Recovery action status updated to {status.value}"
        )
        
        # If recovery was successful, update subscription status
        if status == RecoveryStatus.success:
            failure_event = db.query(FailureEvent).filter(FailureEvent.id == db_action.failure_event_id).first()
            if failure_event:
                update_subscription_status(db, failure_event.subscription_id, SubscriptionStatus.recovered)
        
        return db_action
    return None


# Service functions for Audit Log
def get_all_audit_logs(db: Session, skip: int = 0, limit: int = 100):
    """Retrieve all audit log entries with pagination."""
    return db.query(AuditLog).order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit).all()


def create_audit_log(db: Session, entity_type: EntityType, entity_id: int, event_description: str):
    """Create an audit log entry."""
    db_audit = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        event_description=event_description
    )
    db.add(db_audit)
    db.commit()
    db.refresh(db_audit)
    return db_audit


# Analytics helper functions (for agent decision-making)
def get_failed_subscriptions_count(db: Session):
    """Get count of failed subscriptions."""
    return db.query(Subscription).filter(Subscription.status == SubscriptionStatus.failed).count()


def get_failure_events_by_code(db: Session, failure_code: FailureCode):
    """Get failure events filtered by failure code."""
    return db.query(FailureEvent).filter(FailureEvent.failure_code == failure_code).all()


def get_pending_recovery_actions(db: Session):
    """Get all pending recovery actions that need agent attention."""
    return db.query(RecoveryAction).filter(RecoveryAction.status == RecoveryStatus.pending).all()


def get_subscription_failure_history(db: Session, subscription_id: int):
    """Get complete failure and recovery history for a subscription."""
    subscription = get_subscription_by_id(db, subscription_id)
    if not subscription:
        return None
    
    return {
        "subscription": subscription,
        "failure_events": subscription.failure_events,
        "recovery_actions": [
            action for fe in subscription.failure_events for action in fe.recovery_actions
        ]
    }
