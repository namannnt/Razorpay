"""
LangGraph workflow nodes for ChurnGuard payment recovery.

Each node is a pure function that takes the workflow state and returns updated state.
Nodes are designed to be testable independently and can later be replaced with LLM-based versions.
"""
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from app.agents.state import RecoveryWorkflowState, FailureAnalysisResult, RecoveryDecisionResult
from app.database import FailureCode, ActionType


def load_subscription_data(state: RecoveryWorkflowState, db: Session) -> RecoveryWorkflowState:
    """
    Load subscription and failure event data from the database.
    
    This node populates the workflow state with data needed for analysis.
    Uses the service layer to fetch data.
    """
    from app.services import get_failure_event_by_id, get_subscription_by_id
    
    failure_event_id = state.get("failure_event_id")
    if not failure_event_id:
        state["error_message"] = "No failure_event_id provided in state"
        return state
    
    # Fetch failure event
    failure_event = get_failure_event_by_id(db, failure_event_id)
    if not failure_event:
        state["error_message"] = f"Failure event {failure_event_id} not found"
        return state
    
    # Fetch subscription
    subscription = get_subscription_by_id(db, failure_event.subscription_id)
    if not subscription:
        state["error_message"] = f"Subscription {failure_event.subscription_id} not found"
        return state
    
    # Populate state with loaded data
    state["subscription_id"] = subscription.id
    state["customer_name"] = subscription.customer_name
    state["customer_email"] = subscription.customer_email
    state["plan_name"] = subscription.plan_name
    state["amount"] = subscription.amount
    state["currency"] = subscription.currency
    state["subscription_status"] = subscription.status.value
    
    state["failure_code"] = failure_event.failure_code.value
    state["retry_count"] = failure_event.retry_count
    state["failure_occurred_at"] = failure_event.occurred_at
    
    return state


def analyze_failure(state: RecoveryWorkflowState, db: Session = None) -> RecoveryWorkflowState:
    """
    Analyze the failure event to determine category and recovery implications.
    
    This is a deterministic rule-based analyzer that can later be replaced
    or augmented with an LLM-based analyzer.
    
    Handles:
    - card_expired: Retry not useful, payment link preferred
    - insufficient_funds: Retry may work, but avoid aggressive retries
    - bank_downtime: Retry after delay recommended
    - authentication_failed: Customer action needed (payment link)
    - unknown: Escalate for manual review
    """
    failure_code = state.get("failure_code")
    retry_count = state.get("retry_count", 0)
    
    if not failure_code:
        state["error_message"] = "No failure_code in state"
        state["failure_category"] = "unknown"
        state["failure_analysis"] = "Cannot analyze: missing failure code"
        state["recovery_implications"] = ["Manual review required"]
        state["recommended_action_type"] = "escalate"
        return state
    
    # Deterministic analysis based on failure code
    analysis_rules: Dict[str, FailureAnalysisResult] = {
        FailureCode.card_expired.value: FailureAnalysisResult(
            failure_category="card_expired",
            analysis="Customer's payment card has expired. Automatic retry will likely fail.",
            implications=[
                "Retry without customer action will fail",
                "Customer needs to update card details",
                "Payment link with card update flow is optimal"
            ],
            is_retry_viable=False,
            recommended_strategy="payment_link"
        ),
        FailureCode.insufficient_funds.value: FailureAnalysisResult(
            failure_category="insufficient_funds",
            analysis="Customer account has insufficient funds. May succeed on retry.",
            implications=[
                "Retry may succeed if funds become available",
                "Avoid aggressive repeated retries (customer experience)",
                "Consider timing (payday cycles)",
                "Send notification to customer about failed payment"
            ],
            is_retry_viable=True,
            recommended_strategy="retry_with_delay"
        ),
        FailureCode.bank_downtime.value: FailureAnalysisResult(
            failure_category="bank_downtime",
            analysis="Bank or payment gateway experienced temporary downtime.",
            implications=[
                "Issue is likely transient",
                "Retry after delay (15-30 minutes or 24 hours)",
                "No customer action typically needed"
            ],
            is_retry_viable=True,
            recommended_strategy="retry_after_delay"
        ),
        FailureCode.authentication_failed.value: FailureAnalysisResult(
            failure_category="authentication_failed",
            analysis="Payment authentication failed (3DS/OTP verification).",
            implications=[
                "Customer needs to re-authenticate",
                "Payment link with fresh auth flow recommended",
                "May indicate fraud attempt if repeated"
            ],
            is_retry_viable=False,
            recommended_strategy="payment_link"
        )
    }
    
    # Get analysis for this failure code, or default to unknown
    result = analysis_rules.get(failure_code)
    
    if result is None:
        # Unknown failure code
        result = FailureAnalysisResult(
            failure_category="unknown",
            analysis=f"Unhandled failure code: {failure_code}. Requires manual investigation.",
            implications=[
                "Failure pattern not recognized",
                "Manual review required",
                "May need to contact customer or payment provider"
            ],
            is_retry_viable=False,
            recommended_strategy="manual_review"
        )
    
    # Update state with analysis results
    state["failure_category"] = result["failure_category"]
    state["failure_analysis"] = result["analysis"]
    state["recovery_implications"] = result["implications"]
    
    # Store intermediate recommendation (final decision made by next node)
    state["_interim_strategy"] = result["recommended_strategy"]
    state["_is_retry_viable"] = result["is_retry_viable"]
    
    return state


def decide_recovery_action(state: RecoveryWorkflowState, db: Session = None) -> RecoveryWorkflowState:
    """
    Decide on the recovery action based on failure analysis and retry history.
    
    This node applies business rules to select the appropriate action type:
    - retry_now: Immediate retry attempt
    - send_update_link: Send payment link for customer action
    - retry_after_24h: Schedule retry for later
    - escalate: Manual review required
    
    Decision factors:
    - Failure category (from analyzer)
    - Retry count (avoid infinite loops)
    - Amount (high-value may warrant different handling)
    """
    failure_category = state.get("failure_category")
    retry_count = state.get("retry_count", 0)
    amount = state.get("amount", 0)
    interim_strategy = state.get("_interim_strategy", "manual_review")
    is_retry_viable = state.get("_is_retry_viable", False)
    
    MAX_RETRIES = 3  # Maximum automatic retries before escalation
    
    # Decision matrix
    action_type = ActionType.escalate  # Default fallback
    reason_text = ""
    confidence = 0.5
    requires_payment_link = False
    
    if failure_category == "card_expired":
        # Card expired: always use payment link, never retry
        action_type = ActionType.send_update_link
        reason_text = "Card expired - customer must update payment method via payment link"
        confidence = 0.95
        requires_payment_link = True
        
    elif failure_category == "insufficient_funds":
        # Insufficient funds: retry if under max attempts
        if retry_count < MAX_RETRIES:
            if retry_count == 0:
                action_type = ActionType.retry_now
                reason_text = f"First failure due to insufficient funds - immediate retry may succeed"
                confidence = 0.6
            else:
                action_type = ActionType.retry_after_24h
                reason_text = f"Retry #{retry_count} for insufficient funds - scheduling delayed retry"
                confidence = 0.5
        else:
            action_type = ActionType.escalate
            reason_text = f"Max retries ({MAX_RETRIES}) exceeded for insufficient funds - manual review needed"
            confidence = 0.8
            
    elif failure_category == "bank_downtime":
        # Bank downtime: retry after delay
        if retry_count < MAX_RETRIES:
            action_type = ActionType.retry_after_24h
            reason_text = "Bank downtime detected - scheduled retry after 24 hours"
            confidence = 0.7
        else:
            action_type = ActionType.escalate
            reason_text = f"Persistent bank downtime after {retry_count} retries - manual investigation"
            confidence = 0.75
            
    elif failure_category == "authentication_failed":
        # Auth failed: payment link for fresh auth
        action_type = ActionType.send_update_link
        reason_text = "Authentication failed - customer needs to re-authenticate via secure payment link"
        confidence = 0.85
        requires_payment_link = True
        
    elif failure_category == "unknown":
        # Unknown: escalate
        action_type = ActionType.escalate
        reason_text = f"Unknown failure code '{state.get('failure_code')}' - requires manual investigation"
        confidence = 0.9
    
    # High-value transactions may warrant extra caution
    if amount and amount >= 100000:  # ₹1000+
        if action_type == ActionType.retry_now:
            # For high amounts, prefer delayed retry over immediate
            action_type = ActionType.retry_after_24h
            reason_text += " (adjusted for high-value transaction)"
            confidence = min(confidence + 0.1, 1.0)
    
    # Update state with decision
    state["recommended_action_type"] = action_type.value
    state["action_reason"] = reason_text
    state["confidence_score"] = confidence
    state["_requires_payment_link"] = requires_payment_link
    
    return state


def execute_recovery_action(state: RecoveryWorkflowState, db: Session) -> RecoveryWorkflowState:
    """
    Execute the decided recovery action.
    
    This node:
    1. Creates a RecoveryAction record via the service layer
    2. If action requires payment link, uses the provider abstraction
    3. Updates state with execution results
    
    Does NOT make real payments - uses MockProvider by default.
    """
    from app.services import create_recovery_action, create_audit_log
    from app.agents.provider import get_provider
    from app.database import EntityType, RecoveryStatus
    
    action_type_str = state.get("recommended_action_type")
    if not action_type_str:
        state["error_message"] = "No action_type decided - cannot execute"
        return state
    
    # Convert string to ActionType enum
    try:
        action_type = ActionType(action_type_str)
    except ValueError:
        state["error_message"] = f"Invalid action_type: {action_type_str}"
        return state
    
    failure_event_id = state.get("failure_event_id")
    reason_text = state.get("action_reason", "")
    
    # Create the recovery action record
    recovery_action = create_recovery_action(
        db=db,
        failure_event_id=failure_event_id,
        action_type=action_type,
        reason_text=reason_text
    )
    
    if not recovery_action:
        state["error_message"] = "Failed to create recovery action record"
        return state
    
    state["recovery_action_id"] = recovery_action.id
    
    # Initialize provider (mock by default)
    provider = get_provider(use_mock=True)
    razorpay_link_id = None
    
    # Execute based on action type
    if action_type == ActionType.send_update_link:
        # Create payment link
        link_result = provider.create_payment_link(
            amount=state.get("amount", 0),
            currency=state.get("currency", "INR"),
            customer_email=state.get("customer_email", ""),
            subscription_id=state.get("subscription_id", 0),
            description=reason_text
        )
        razorpay_link_id = link_result.get("payment_link_id")
        state["execution_result"] = link_result
        state["action_status"] = RecoveryStatus.pending.value
        
    elif action_type == ActionType.retry_now:
        # Attempt retry
        retry_result = provider.retry_payment(
            subscription_id=state.get("subscription_id", 0),
            failure_event_id=failure_event_id,
            amount=state.get("amount", 0),
            currency=state.get("currency", "INR")
        )
        state["execution_result"] = retry_result
        # In mock mode, stays pending; real provider would update based on actual result
        state["action_status"] = RecoveryStatus.pending.value
        
    elif action_type == ActionType.retry_after_24h:
        # Scheduled retry - just mark as pending
        state["execution_result"] = {"scheduled": True, "delay_hours": 24}
        state["action_status"] = RecoveryStatus.pending.value
        
    elif action_type == ActionType.escalate:
        # Manual review - mark as stopped until human acts
        state["execution_result"] = {"escalated": True, "requires_human": True}
        state["action_status"] = RecoveryStatus.stopped_by_rule.value
    
    # Store payment link ID if created
    state["razorpay_payment_link_id"] = razorpay_link_id
    state["is_simulated"] = True  # Always simulated in current implementation
    
    # Log audit entry for action execution
    audit_log = create_audit_log(
        db=db,
        entity_type=EntityType.recovery_action,
        entity_id=recovery_action.id,
        event_description=f"Recovery action executed: {action_type.value} (simulated={state['is_simulated']})"
    )
    
    if audit_log:
        if state.get("audit_log_ids") is None:
            state["audit_log_ids"] = []
        state["audit_log_ids"].append(audit_log.id)
    
    return state


def log_workflow_completion(state: RecoveryWorkflowState, db: Session) -> RecoveryWorkflowState:
    """
    Final node: Log workflow completion and cleanup.
    
    Records final audit entries and marks workflow as complete.
    """
    from app.services import create_audit_log, update_recovery_action_status
    from app.database import EntityType, RecoveryStatus
    
    state["workflow_completed_at"] = datetime.utcnow()
    
    # Log workflow completion
    error_msg = state.get("error_message")
    if error_msg:
        event_desc = f"Workflow completed with error: {error_msg}"
        # Update recovery action status to failed if there was an error
        if state.get("recovery_action_id"):
            update_recovery_action_status(
                db=db,
                recovery_action_id=state["recovery_action_id"],
                status=RecoveryStatus.failed,
                reason_text=error_msg
            )
    else:
        event_desc = f"Workflow completed successfully. Action: {state.get('recommended_action_type')}"
        # Update recovery action status if still pending
        if state.get("recovery_action_id") and state.get("action_status") == RecoveryStatus.pending.value:
            # Keep as pending since we're simulating
            pass
    
    # Create final audit log
    audit_log = create_audit_log(
        db=db,
        entity_type=EntityType.failure_event,
        entity_id=state.get("failure_event_id", 0),
        event_description=event_desc
    )
    
    if audit_log:
        if state.get("audit_log_ids") is None:
            state["audit_log_ids"] = []
        state["audit_log_ids"].append(audit_log.id)
    
    return state
