"""
Synthetic data generator for ChurnGuard.
Generates realistic Indian subscription data with payment failures.
"""
from faker import Faker
from datetime import datetime, timedelta
import random

from app.database import (
    SessionLocal, Base, engine,
    Subscription, FailureEvent, RecoveryAction, AuditLog,
    SubscriptionStatus, FailureCode, ActionType, RecoveryStatus, EntityType
)

# Initialize Faker with Indian locale
fake = Faker("en_IN")
Faker.seed(42)  # For reproducibility

# Plan configurations
PLANS = [
    {"name": "Basic Monthly", "amount_paise": 49900},
    {"name": "Standard Monthly", "amount_paise": 99900},
    {"name": "Premium Monthly", "amount_paise": 149900},
    {"name": "Basic Annual", "amount_paise": 499900},
    {"name": "Standard Annual", "amount_paise": 999900},
    {"name": "Premium Annual", "amount_paise": 1499900},
    {"name": "Enterprise Monthly", "amount_paise": 249900},
    {"name": "Enterprise Annual", "amount_paise": 2999900},
]

# Failure code weights - card_expired and insufficient_funds are most common
FAILURE_CODE_WEIGHTS = {
    FailureCode.card_expired: 35,
    FailureCode.insufficient_funds: 35,
    FailureCode.authentication_failed: 20,
    FailureCode.bank_downtime: 10,
}


def generate_subscription(status: SubscriptionStatus = SubscriptionStatus.failed):
    """Generate a single subscription record."""
    plan = random.choice(PLANS)
    
    # Generate realistic Indian name and email
    first_name = fake.first_name()
    last_name = fake.last_name()
    customer_name = f"{first_name} {last_name}"
    
    # Create email from name or use fake email
    if random.random() > 0.3:
        customer_email = f"{first_name.lower()}.{last_name.lower()}@{random.choice(['gmail.com', 'yahoo.co.in', 'outlook.com', 'rediffmail.com'])}"
    else:
        customer_email = fake.email()
    
    # Random creation date within last 6 months
    days_ago = random.randint(1, 180)
    created_at = datetime.utcnow() - timedelta(days=days_ago)
    
    return Subscription(
        customer_name=customer_name,
        customer_email=customer_email,
        plan_name=plan["name"],
        amount=plan["amount_paise"],
        currency="INR",
        status=status,
        created_at=created_at
    )


def generate_failure_event(subscription_id: int):
    """Generate a failure event for a subscription."""
    # Weighted random selection of failure code
    failure_codes = list(FAILURE_CODE_WEIGHTS.keys())
    weights = list(FAILURE_CODE_WEIGHTS.values())
    failure_code = random.choices(failure_codes, weights=weights)[0]
    
    # Random retry count (0-3)
    retry_count = random.randint(0, 3)
    
    # Failure occurred 1-30 days ago
    days_ago = random.randint(1, 30)
    occurred_at = datetime.utcnow() - timedelta(days=days_ago)
    
    return FailureEvent(
        subscription_id=subscription_id,
        failure_code=failure_code,
        retry_count=retry_count,
        occurred_at=occurred_at
    )


def generate_recovery_action(failure_event_id: int):
    """Generate a recovery action for a failure event."""
    action_types = list(ActionType)
    action_type = random.choice(action_types)
    
    recovery_statuses = list(RecoveryStatus)
    # Weight towards pending since these need agent attention
    status_weights = [50, 20, 20, 10]  # pending, success, failed, stopped_by_rule
    status = random.choices(recovery_statuses, weights=status_weights)[0]
    
    reason_texts = {
        ActionType.retry_now: "Automatic retry initiated",
        ActionType.send_update_link: "Payment update link sent via email",
        ActionType.retry_after_24h: "Scheduled retry after 24 hours",
        ActionType.escalate: "Escalated to manual review team",
    }
    
    razorpay_link = None
    if action_type in [ActionType.retry_now, ActionType.send_update_link]:
        razorpay_link = f"pl_{fake.random_number(digits=10)}"
    
    created_at = datetime.utcnow() - timedelta(days=random.randint(0, 10))
    resolved_at = None
    if status != RecoveryStatus.pending:
        resolved_at = created_at + timedelta(hours=random.randint(1, 48))
    
    return RecoveryAction(
        failure_event_id=failure_event_id,
        action_type=action_type,
        status=status,
        reason_text=reason_texts.get(action_type, "Action initiated"),
        razorpay_payment_link_id=razorpay_link,
        created_at=created_at,
        resolved_at=resolved_at
    )


def generate_audit_log(entity_type: EntityType, entity_id: int, event_description: str):
    """Generate an audit log entry."""
    timestamp = datetime.utcnow() - timedelta(days=random.randint(0, 30))
    return AuditLog(
        timestamp=timestamp,
        entity_type=entity_type,
        entity_id=entity_id,
        event_description=event_description
    )


def clear_database():
    """Clear all tables in the database."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("Database cleared.")


def generate_synthetic_data(num_subscriptions: int = 70):
    """Generate synthetic data for testing."""
    # Clear and recreate tables
    clear_database()
    
    db = SessionLocal()
    
    try:
        subscriptions = []
        failure_events = []
        recovery_actions = []
        audit_logs = []
        
        print(f"Generating {num_subscriptions} subscriptions...")
        
        for i in range(num_subscriptions):
            # Create subscription (all start as failed for this demo)
            subscription = generate_subscription(SubscriptionStatus.failed)
            subscriptions.append(subscription)
            
            # Flush to get the ID
            db.add(subscription)
            db.flush()
            
            # Create audit log for subscription
            audit_logs.append(AuditLog(
                timestamp=datetime.utcnow() - timedelta(days=random.randint(0, 30)),
                entity_type=EntityType.subscription,
                entity_id=subscription.id,
                event_description=f"Subscription created for {subscription.customer_email}"
            ))
            
            # Create failure event
            failure_event = generate_failure_event(subscription.id)
            failure_events.append(failure_event)
            
            db.add(failure_event)
            db.flush()
            
            # Create audit log for failure event
            audit_logs.append(AuditLog(
                timestamp=datetime.utcnow() - timedelta(days=random.randint(0, 30)),
                entity_type=EntityType.failure_event,
                entity_id=failure_event.id,
                event_description=f"Payment failure detected: {failure_event.failure_code.value}"
            ))
            
            # Create recovery action
            recovery_action = generate_recovery_action(failure_event.id)
            recovery_actions.append(recovery_action)
            
            db.add(recovery_action)
            db.flush()
            
            # Create audit log for recovery action (after flush to get ID)
            audit_logs.append(AuditLog(
                timestamp=datetime.utcnow() - timedelta(days=random.randint(0, 30)),
                entity_type=EntityType.recovery_action,
                entity_id=recovery_action.id,
                event_description=f"Recovery action initiated: {recovery_action.action_type.value}"
            ))
        
        # Bulk add audit logs
        for log in audit_logs:
            db.add(log)
        
        db.commit()
        
        print(f"✓ Created {len(subscriptions)} subscriptions")
        print(f"✓ Created {len(failure_events)} failure events")
        print(f"✓ Created {len(recovery_actions)} recovery actions")
        print(f"✓ Created {len(audit_logs)} audit log entries")
        
        # Print summary statistics
        print("\n--- Summary Statistics ---")
        
        # Failure code distribution
        failure_codes = db.query(FailureEvent.failure_code).all()
        print("\nFailure Code Distribution:")
        for code in FailureCode:
            count = sum(1 for fc in failure_codes if fc[0] == code)
            print(f"  {code.value}: {count}")
        
        # Recovery action status distribution
        statuses = db.query(RecoveryAction.status).all()
        print("\nRecovery Action Status Distribution:")
        for status in RecoveryStatus:
            count = sum(1 for s in statuses if s[0] == status)
            print(f"  {status.value}: {count}")
        
        return {
            "subscriptions": len(subscriptions),
            "failure_events": len(failure_events),
            "recovery_actions": len(recovery_actions),
            "audit_logs": len(audit_logs)
        }
        
    except Exception as e:
        db.rollback()
        print(f"Error generating data: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    generate_synthetic_data(70)
