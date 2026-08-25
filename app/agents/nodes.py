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


def check_policy_guards(state: RecoveryWorkflowState, db: Session) -> RecoveryWorkflowState:
    """
    Policy/guardrail node that applies business rules before executing recovery actions.
    
    This node is inserted between decide_recovery_action and execute_recovery_action.
    It applies the following rules IN ORDER (first match wins, no further rules checked):
    
    a. "max_retries" — if retry_count >= 3: force action_type to escalate
    b. "quiet_hours" — if hour >= 21 or < 8 (IST approximation), stop send_update_link
    c. "high_value_approval" — if amount > 500000 paise (₹5000), require human approval
    d. "repeated_failure_pattern" — if subscription has 2+ prior FailureEvents, force escalate
    
    If none match: policy_approved=True, policy_rule_triggered=None, action passes through unchanged.
    """
    from app.services import get_subscription_by_id
    from app.database import ActionType, RecoveryStatus
    
    # Initialize policy fields with defaults (pass-through)
    state["policy_approved"] = True
    state["policy_stopped_reason"] = None
    state["requires_human_approval"] = False
    state["policy_rule_triggered"] = None
    
    # Get current values
    action_type_str = state.get("recommended_action_type")
    retry_count = state.get("retry_count", 0)
    amount = state.get("amount", 0)
    subscription_id = state.get("subscription_id")
    
    if not action_type_str:
        state["error_message"] = "No action_type to validate against policy"
        return state
    
    # Convert string to ActionType enum for comparison
    try:
        current_action = ActionType(action_type_str)
    except ValueError:
        state["error_message"] = f"Invalid action_type: {action_type_str}"
        return state
    
    # ========== Rule a: max_retries ==========
    # If retry_count >= 3, override any retry_now action to escalate
    if retry_count >= 3:
        if current_action == ActionType.retry_now:
            state["recommended_action_type"] = ActionType.escalate.value
            state["action_reason"] = "Max retry limit (3) reached — escalating to manual review instead of further automated retries"
            state["policy_approved"] = True  # Policy approved the override (not stopped, just redirected)
            state["policy_rule_triggered"] = "max_retries"
            state["requires_human_approval"] = True
            return state
    
    # ========== Rule b: quiet_hours ==========
    # If current IST hour is >= 21 or < 8, block send_update_link actions
    # Using UTC hour with adjustment: IST = UTC + 5:30
    # For simplicity, we approximate: if UTC hour is 16-22, it's roughly 9PM-8AM IST
    # More precisely: IST hour = (UTC hour + 5.5) % 24
    utc_hour = datetime.utcnow().hour
    ist_hour = (utc_hour + 5) % 24  # Approximate IST hour (ignoring the 30 min)
    
    if (ist_hour >= 21 or ist_hour < 8):
        if current_action == ActionType.send_update_link:
            # Block customer communication during quiet hours
            state["policy_approved"] = False
            state["policy_stopped_reason"] = f"Quiet hours rule: Customer communication (send_update_link) paused during 9PM-8AM IST — rescheduled for next morning (current IST hour approx: {ist_hour})"
            state["policy_rule_triggered"] = "quiet_hours"
            # Do NOT change recommended_action_type, just block execution
            return state
    
    # ========== Rule c: high_value_approval ==========
    # If amount > 500000 paise (₹5000), require human approval
    if amount and amount > 500000:
        state["policy_approved"] = False
        state["policy_stopped_reason"] = f"Transaction amount ₹{amount/100:.2f} exceeds auto-approval threshold of ₹5000 — requires human approval before any automated action"
        state["policy_rule_triggered"] = "high_value_approval"
        state["requires_human_approval"] = True
        return state
    
    # ========== Rule d: repeated_failure_pattern ==========
    # If subscription has 2+ prior FailureEvents, force escalate
    if subscription_id:
        subscription = get_subscription_by_id(db, subscription_id)
        if subscription:
            # Count all failure events for this subscription
            total_failures = len(subscription.failure_events)
            # If 2 or more failures exist (including current one), trigger rule
            if total_failures >= 2:
                state["recommended_action_type"] = ActionType.escalate.value
                state["action_reason"] = f"This subscription has failed {total_failures} times — escalating to manual review rather than continuing automated recovery"
                state["policy_approved"] = True  # Policy approved the override
                state["policy_rule_triggered"] = "repeated_failure_pattern"
                state["requires_human_approval"] = True
                return state
    
    # No rules matched - pass through unchanged with policy_approved=True
    state["policy_approved"] = True
    state["policy_rule_triggered"] = None
    return state


def execute_recovery_action(state: RecoveryWorkflowState, db: Session) -> RecoveryWorkflowState:
    """
    Execute the decided recovery action.
    
    This node:
    1. Creates a RecoveryAction record via the service layer
    2. If action requires payment link, uses the provider abstraction
    3. Updates state with execution results
    
    Does NOT make real payments - uses MockProvider by default.
    
    Handles policy_stopped_reason from check_policy_guards node:
    - If policy_approved is False, creates RecoveryAction with status=stopped_by_rule
    - Otherwise proceeds with normal execution
    """
    from app.services import create_recovery_action, create_audit_log
    from app.agents.provider import get_provider
    from app.database import EntityType, RecoveryStatus
    
    action_type_str = state.get("recommended_action_type")
    if not action_type_str:
        state["error_message"] = "No action_type decided - cannot execute"
        return state
    
    # Check if policy stopped this action
    policy_approved = state.get("policy_approved", True)
    policy_stopped_reason = state.get("policy_stopped_reason")
    
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
    
    # Handle policy-stopped actions (skip actual execution)
    if not policy_approved and policy_stopped_reason:
        # Update the action status to stopped_by_rule
        from app.services import update_recovery_action_status
        update_recovery_action_status(
            db=db,
            recovery_action_id=recovery_action.id,
            status=RecoveryStatus.stopped_by_rule,
            reason_text=policy_stopped_reason
        )
        state["action_status"] = RecoveryStatus.stopped_by_rule.value
        state["execution_result"] = {"stopped_by_policy": True, "reason": policy_stopped_reason}
        
        # Log audit entry for policy stop
        audit_log = create_audit_log(
            db=db,
            entity_type=EntityType.recovery_action,
            entity_id=recovery_action.id,
            event_description=f"Recovery action stopped by policy guard: {policy_stopped_reason}"
        )
        if audit_log:
            if state.get("audit_log_ids") is None:
                state["audit_log_ids"] = []
            state["audit_log_ids"].append(audit_log.id)
        
        return state
    
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
            failure_event_id=failure_event_id,
            customer_name=state.get("customer_name", ""),
            plan_name=state.get("plan_name", ""),
            description=reason_text
        )
        razorpay_link_id = link_result.get("payment_link_id")
        payment_link_url = link_result.get("short_url")
        
        # Update the recovery action with payment link details
        recovery_action.razorpay_payment_link_id = razorpay_link_id
        recovery_action.payment_link_url = payment_link_url
        db.commit()
        
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
    If a policy rule was triggered, logs which rule fired and why.
    """
    from app.services import create_audit_log, update_recovery_action_status
    from app.database import EntityType, RecoveryStatus
    
    state["workflow_completed_at"] = datetime.utcnow()
    
    # Log policy rule trigger if applicable (separate from normal workflow steps)
    policy_rule_triggered = state.get("policy_rule_triggered")
    if policy_rule_triggered:
        policy_stopped_reason = state.get("policy_stopped_reason", "")
        policy_approved = state.get("policy_approved", True)
        
        if policy_approved:
            # Policy approved an override (e.g., max_retries, repeated_failure_pattern)
            event_desc = f"Policy guard '{policy_rule_triggered}' triggered: action overridden but approved. Reason: {policy_stopped_reason or 'N/A'}"
        else:
            # Policy blocked execution (e.g., quiet_hours, high_value_approval)
            event_desc = f"Policy guard '{policy_rule_triggered}' triggered: action BLOCKED. Reason: {policy_stopped_reason}"
        
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
    
    # Create final audit log (if not already created for policy rule)
    if not policy_rule_triggered:
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
