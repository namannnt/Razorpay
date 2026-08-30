"""
LangGraph state definitions for ChurnGuard recovery workflow.

This module defines the TypedDict state that flows through the LangGraph workflow.
The state represents workflow context, not persisted data (which remains in SQLAlchemy models).
"""
from typing import TypedDict, Optional, List, Any
from datetime import datetime


class RecoveryWorkflowState(TypedDict):
    """
    State object for the payment recovery workflow.
    
    This represents the workflow context as it moves through nodes.
    All persistent data is stored via the service layer in SQLAlchemy models.
    """
    # Identifiers
    subscription_id: Optional[int]
    failure_event_id: Optional[int]
    recovery_action_id: Optional[int]
    
    # Subscription data (cached from DB for workflow use)
    customer_name: Optional[str]
    customer_email: Optional[str]
    plan_name: Optional[str]
    amount: Optional[int]  # in paise
    currency: Optional[str]
    subscription_status: Optional[str]
    
    # Failure data
    failure_code: Optional[str]
    retry_count: Optional[int]
    failure_occurred_at: Optional[datetime]
    
    # Analysis results
    failure_analysis: Optional[str]
    failure_category: Optional[str]  # 'card_expired', 'insufficient_funds', 'bank_downtime', 'auth_failed', 'unknown'
    recovery_implications: Optional[List[str]]
    
    # Decision results
    recommended_action_type: Optional[str]  # 'retry_now', 'send_update_link', 'retry_after_24h', 'escalate'
    action_reason: Optional[str]
    policy_coverage_score: Optional[float]  # 0.0 to 1.0
    
    # Policy check results (new fields)
    policy_approved: Optional[bool]
    policy_stopped_reason: Optional[str]
    requires_human_approval: Optional[bool]
    policy_rule_triggered: Optional[str]  # name of the rule that fired, or None
    
    # Execution results
    razorpay_payment_link_id: Optional[str]
    action_status: Optional[str]  # 'pending', 'success', 'failed', 'stopped_by_rule'
    execution_result: Optional[Any]
    
    # Error handling
    error_message: Optional[str]
    is_simulated: bool  # Always True until real Razorpay integration
    
    # Audit tracking
    workflow_started_at: Optional[datetime]
    workflow_completed_at: Optional[datetime]
    audit_log_ids: Optional[List[int]]


class FailureAnalysisResult(TypedDict):
    """Structured result from the Failure Analyzer node."""
    failure_category: str
    analysis: str
    implications: List[str]
    is_retry_viable: bool
    recommended_strategy: str


class RecoveryDecisionResult(TypedDict):
    """Structured result from the Recovery Decision node."""
    action_type: str
    reason_text: str
    policy_coverage: float
    requires_payment_link: bool
    max_retries_recommended: int
