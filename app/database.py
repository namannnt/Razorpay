from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import enum
import os

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./churnguard.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Enums
class SubscriptionStatus(str, enum.Enum):
    active = "active"
    failed = "failed"
    recovered = "recovered"
    cancelled = "cancelled"


class FailureCode(str, enum.Enum):
    card_expired = "card_expired"
    insufficient_funds = "insufficient_funds"
    bank_downtime = "bank_downtime"
    authentication_failed = "authentication_failed"


class ActionType(str, enum.Enum):
    retry_now = "retry_now"
    send_update_link = "send_update_link"
    retry_after_24h = "retry_after_24h"
    escalate = "escalate"


class RecoveryStatus(str, enum.Enum):
    pending = "pending"
    success = "success"
    failed = "failed"
    stopped_by_rule = "stopped_by_rule"


class EntityType(str, enum.Enum):
    subscription = "subscription"
    failure_event = "failure_event"
    recovery_action = "recovery_action"


# Models
class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, nullable=False)
    customer_email = Column(String, nullable=False)
    plan_name = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)  # in paise
    currency = Column(String, default="INR")
    status = Column(SQLEnum(SubscriptionStatus), default=SubscriptionStatus.active)
    created_at = Column(DateTime, default=datetime.utcnow)

    failure_events = relationship("FailureEvent", back_populates="subscription", cascade="all, delete-orphan")


class FailureEvent(Base):
    __tablename__ = "failure_events"

    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False)
    failure_code = Column(SQLEnum(FailureCode), nullable=False)
    retry_count = Column(Integer, default=0)
    occurred_at = Column(DateTime, default=datetime.utcnow)

    subscription = relationship("Subscription", back_populates="failure_events")
    recovery_actions = relationship("RecoveryAction", back_populates="failure_event", cascade="all, delete-orphan")


class RecoveryAction(Base):
    __tablename__ = "recovery_actions"

    id = Column(Integer, primary_key=True, index=True)
    failure_event_id = Column(Integer, ForeignKey("failure_events.id"), nullable=False)
    action_type = Column(SQLEnum(ActionType), nullable=False)
    status = Column(SQLEnum(RecoveryStatus), default=RecoveryStatus.pending)
    reason_text = Column(String, nullable=True)
    razorpay_payment_link_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    failure_event = relationship("FailureEvent", back_populates="recovery_actions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    entity_type = Column(SQLEnum(EntityType), nullable=False)
    entity_id = Column(Integer, nullable=False)
    event_description = Column(String, nullable=False)


# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
