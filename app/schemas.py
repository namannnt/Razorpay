from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from enum import Enum


# Enums matching database
class SubscriptionStatusEnum(str, Enum):
    active = "active"
    failed = "failed"
    recovered = "recovered"
    cancelled = "cancelled"


class FailureCodeEnum(str, Enum):
    card_expired = "card_expired"
    insufficient_funds = "insufficient_funds"
    bank_downtime = "bank_downtime"
    authentication_failed = "authentication_failed"


class ActionTypeEnum(str, Enum):
    retry_now = "retry_now"
    send_update_link = "send_update_link"
    retry_after_24h = "retry_after_24h"
    escalate = "escalate"


class RecoveryStatusEnum(str, Enum):
    pending = "pending"
    success = "success"
    failed = "failed"
    stopped_by_rule = "stopped_by_rule"


class EntityTypeEnum(str, Enum):
    subscription = "subscription"
    failure_event = "failure_event"
    recovery_action = "recovery_action"


# Base schemas
class SubscriptionBase(BaseModel):
    customer_name: str
    customer_email: EmailStr
    plan_name: str
    amount: int  # in paise
    currency: str = "INR"
    status: SubscriptionStatusEnum = SubscriptionStatusEnum.active


class SubscriptionCreate(SubscriptionBase):
    pass


class SubscriptionUpdate(BaseModel):
    customer_name: Optional[str] = None
    customer_email: Optional[EmailStr] = None
    plan_name: Optional[str] = None
    amount: Optional[int] = None
    currency: Optional[str] = None
    status: Optional[SubscriptionStatusEnum] = None


class RecoveryActionBase(BaseModel):
    action_type: ActionTypeEnum
    status: RecoveryStatusEnum = RecoveryStatusEnum.pending
    reason_text: Optional[str] = None
    razorpay_payment_link_id: Optional[str] = None
    payment_link_url: Optional[str] = None  # Customer-facing URL; exposed so the dashboard Simulate Payment panel can filter on it


class RecoveryActionCreate(RecoveryActionBase):
    failure_event_id: int


class RecoveryAction(RecoveryActionBase):
    id: int
    failure_event_id: int
    created_at: datetime
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FailureEventBase(BaseModel):
    failure_code: FailureCodeEnum
    retry_count: int = 0


class FailureEventCreate(FailureEventBase):
    subscription_id: int


class FailureEvent(FailureEventBase):
    id: int
    subscription_id: int
    occurred_at: datetime
    recovery_actions: List[RecoveryAction] = []

    class Config:
        from_attributes = True


class Subscription(SubscriptionBase):
    id: int
    created_at: datetime
    failure_events: List[FailureEvent] = []

    class Config:
        from_attributes = True


class AuditLogBase(BaseModel):
    entity_type: EntityTypeEnum
    entity_id: int
    event_description: str


class AuditLogCreate(AuditLogBase):
    pass


class AuditLog(AuditLogBase):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True
