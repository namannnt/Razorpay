# ChurnGuard Architecture

## System Overview

ChurnGuard is an agentic subscription-recovery system built with a FastAPI backend, LangGraph workflow engine, and Streamlit dashboard. The system processes failed payment events through a 5-node AI workflow that analyzes failures, decides recovery actions, enforces policy guardrails, executes recovery (including Razorpay payment link creation), and maintains a complete audit trail.

## Detailed Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL SYSTEMS                                │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐                           ┌─────────────────────────┐  │
│  │  Razorpay API   │                           │    Streamlit Dashboard  │  │
│  │  (Test Mode)    │                           │    (port 8501)          │  │
│  │                 │                           │                         │  │
│  │ - payment_link  │<──────────────────────────┤ - Control Panel         │  │
│  │   .create()     │      HTTP POST            │ - Metrics Cards         │  │
│  │                 │                           │ - Failure Chart         │  │
│  └────────┬────────┘                           │ - Actions Table         │  │
│           │                                    │ - Audit Panel           │  │
│           │ Webhook                            └─────────────────────────┘  │
│           │ payment_link.paid                                              │
│           v                                                                │
│  ┌─────────────────┐                                                       │
│  │  /webhooks/     │                                                       │
│  │  razorpay       │                                                       │
│  └────────┬────────┘                                                       │
│           │                                                                │
└───────────┼────────────────────────────────────────────────────────────────┘
            │
            v
┌──────────────────────────────────────────────────────────────────────────────┐
│                           FASTAPI BACKEND (port 8000)                        │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         API Endpoints                                   │ │
│  │                                                                        │ │
│  │  POST /recovery/run/{id}        → Run single recovery workflow         │ │
│  │  POST /recovery/run-batch       → Run batch recovery (sequential)      │ │
│  │  GET  /metrics/summary          → Aggregated recovery metrics          │ │
│  │  POST /generate-data            → Generate synthetic test data         │ │
│  │  GET  /subscriptions            → List subscriptions                   │ │
│  │  GET  /failures                 → List failure events                  │ │
│  │  GET  /audit-log                → List audit entries                   │ │
│  │  POST /demo/simulate-payment    → DEMO: Mark action as successful      │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                      │                                       │
│                                      v                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    Service Layer (services.py)                          │ │
│  │                                                                        │ │
│  │  - get_subscription_by_id()     - create_recovery_action()             │ │
│  │  - get_failure_event_by_id()    - update_recovery_action_status()      │ │
│  │  - create_audit_log()           - get_all_subscriptions()              │ │
│  │  - compute_metrics_summary()    - etc.                                 │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                      │                                       │
│                                      v                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                   LangGraph Agent Workflow                              │ │
│  │                                                                        │ │
│  │   Entry: run_recovery_workflow(failure_event_id, db)                   │ │
│  │                                                                        │ │
│  │   ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐   │ │
│  │   │ Node 1      │───>│ Node 2      │───>│ Node 3                  │   │ │
│  │   │ load_data   │    │ analyze_    │    │ decide_recovery_action  │   │ │
│  │   │             │    │ failure     │    │                         │   │ │
│  │   └─────────────┘    └─────────────┘    └───────────┬─────────────┘   │ │
│  │                                                     │                 │ │
│  │                                                     v                 │ │
│  │   ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐   │ │
│  │   │ Node 6      │<───│ Node 5      │<───│ Node 4                  │   │ │
│  │   │ log_        │    │ execute_    │    │ check_policy_guards     │   │ │
│  │   │ completion  │    │ recovery_   │    │                         │   │ │
│  │   │             │    │ action      │    │ [Conditional Edge]      │   │ │
│  │   └─────────────┘    └─────────────┘    └─────────────────────────┘   │ │
│  │                                                                        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                      │                                       │
│                                      v                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    Provider Abstraction (provider.py)                   │ │
│  │                                                                        │ │
│  │  MockProvider (default):                                               │ │
│  │  - create_payment_link() → Returns fake payment_link_id + short_url    │ │
│  │                                                                    │ │
│  │  RazorpayProvider (when use_mock=False):                               │ │
│  │  - create_payment_link() → Calls real Razorpay API                     │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     v
┌──────────────────────────────────────────────────────────────────────────────┐
│                              SQLite Database                                 │
│                           churnguard.db                                      │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ Tables:                                                                 │ │
│  │                                                                        │ │
│  │  Subscription                                                          │ │
│  │  ├─ id (PK)               ├─ customer_email                            │ │
│  │  ├─ customer_name         ├─ plan_name                                 │ │
│  │  ├─ amount (paise)        ├─ status (failed/recovered/etc)             │ │
│  │  └─ currency              └─ created_at, updated_at                    │ │
│  │                                                                        │ │
│  │  FailureEvent                                                        │ │
│  │  ├─ id (PK)               ├─ failure_code (enum)                       │ │
│  │  ├─ subscription_id (FK)  ├─ retry_count                               │ │
│  │  └─ occurred_at                                                        │ │
│  │                                                                        │ │
│  │  RecoveryAction                                                      │ │
│  │  ├─ id (PK)               ├─ action_type (enum)                        │ │
│  │  ├─ failure_event_id (FK) ├─ status (enum)                             │ │
│  │  ├─ reason_text           ├─ payment_link_url                          │ │
│  │  ├─ razorpay_payment_link_id                                           │ │
│  │  └─ created_at, resolved_at                                            │ │
│  │                                                                        │ │
│  │  AuditLog                                                            │ │
│  │  ├─ id (PK)               ├─ entity_type (enum)                        │ │
│  │  ├─ entity_id             ├─ event_description                         │ │
│  │  └─ timestamp                                                          │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## LangGraph Workflow Nodes

### Node 1: `load_subscription_data`

**Purpose**: Fetch subscription and failure event data from the database.

**Inputs**: 
- `failure_event_id` (from initial state)

**Operations**:
1. Calls `get_failure_event_by_id(db, failure_event_id)`
2. Calls `get_subscription_by_id(db, failure_event.subscription_id)`
3. Populates state with subscription details (customer_name, email, plan_name, amount, currency, status)
4. Populates state with failure details (failure_code, retry_count, occurred_at)

**Outputs** (state updates):
- `subscription_id`, `customer_name`, `customer_email`, `plan_name`, `amount`, `currency`, `subscription_status`
- `failure_code`, `retry_count`, `failure_occurred_at`
- `error_message` (if not found)

**Error Handling**: Sets `error_message` if failure event or subscription not found; workflow terminates early at log_completion node.

---

### Node 2: `analyze_failure`

**Purpose**: Classify the failure and determine recovery implications using rule-based analysis.

**Inputs**:
- `failure_code` (e.g., `card_expired`, `insufficient_funds`, `bank_downtime`, `authentication_failed`)
- `retry_count`

**Operations**:
Applies deterministic rules based on failure code:

| Failure Code | Category | Analysis | Is Retry Viable | Recommended Strategy |
|--------------|----------|----------|-----------------|---------------------|
| `card_expired` | card_expired | Card has expired; retry will fail | No | payment_link |
| `insufficient_funds` | insufficient_funds | May succeed on retry | Yes | retry_with_delay |
| `bank_downtime` | bank_downtime | Transient issue | Yes | retry_after_delay |
| `authentication_failed` | authentication_failed | Customer needs to re-auth | No | payment_link |
| Unknown | unknown | Unhandled code | No | manual_review |

**Outputs**:
- `failure_category`: Normalized category string
- `failure_analysis`: Human-readable explanation
- `recovery_implications`: List of considerations
- `_interim_strategy`: Recommended strategy for next node
- `_is_retry_viable`: Boolean flag

---

### Node 3: `decide_recovery_action`

**Purpose**: Select specific action type based on failure analysis and business rules.

**Inputs**:
- `failure_category` (from analyze_failure)
- `retry_count`
- `amount` (in paise)
- `_interim_strategy`, `_is_retry_viable`

**Decision Matrix**:

| Failure Category | Condition | Action Type | Reason |
|------------------|-----------|-------------|--------|
| `card_expired` | Always | `send_update_link` | Customer must update card |
| `insufficient_funds` | retry_count == 0 | `retry_now` | First failure, immediate retry |
| `insufficient_funds` | 0 < retry_count < 3 | `retry_after_24h` | Delayed retry |
| `insufficient_funds` | retry_count >= 3 | `escalate` | Max retries exceeded |
| `bank_downtime` | retry_count < 3 | `retry_after_24h` | Wait for bank recovery |
| `bank_downtime` | retry_count >= 3 | `escalate` | Persistent issue |
| `authentication_failed` | Always | `send_update_link` | Fresh auth needed |
| `unknown` | Always | `escalate` | Manual investigation |

**High-Value Adjustment**: If `amount >= 100000` (₹1000+), changes `retry_now` → `retry_after_24h` for caution.

**Outputs**:
- `recommended_action_type`: One of `retry_now`, `send_update_link`, `retry_after_24h`, `escalate`
- `action_reason`: Explanation text
- `confidence_score`: 0.0–1.0 confidence in decision
- `_requires_payment_link`: True if action is `send_update_link`

---

### Node 4: `check_policy_guards` ⭐

**Purpose**: Apply safety guardrails before executing recovery actions. This node directly addresses Razorpay's evaluation criterion for **stopping rules**.

**Inputs**:
- `recommended_action_type`
- `retry_count`
- `amount`
- `subscription_id`
- Current UTC time (for quiet hours check)

**Policy Rules** (checked in order, first match wins):

#### Rule A: Max Retries
- **Condition**: `retry_count >= 3` AND `action_type == retry_now`
- **Action**: Override to `escalate`
- **Rationale**: Prevent infinite retry loops; human review needed after 3 attempts
- **Output**: `policy_approved=True`, `policy_rule_triggered="max_retries"`, `requires_human_approval=True`

#### Rule B: Quiet Hours
- **Condition**: IST hour >= 21 OR < 8 AND `action_type == send_update_link`
- **Action**: Block execution (do not change action_type)
- **Rationale**: Customer experience — no payment emails at midnight
- **Output**: `policy_approved=False`, `policy_stopped_reason="..."`, `policy_rule_triggered="quiet_hours"`

#### Rule C: High-Value Approval
- **Condition**: `amount > 500000` (₹5000+)
- **Action**: Block execution
- **Rationale**: Fintech compliance — large transactions require human oversight
- **Output**: `policy_approved=False`, `policy_stopped_reason="..."`, `policy_rule_triggered="high_value_approval"`, `requires_human_approval=True`

#### Rule D: Repeated-Failure Pattern
- **Condition**: Subscription has 2+ prior `FailureEvent` records
- **Action**: Override to `escalate`
- **Rationale**: Pattern indicates systemic issue needing investigation
- **Output**: `policy_approved=True`, `policy_rule_triggered="repeated_failure_pattern"`, `requires_human_approval=True`

**Pass-Through**: If no rules match, `policy_approved=True`, `policy_rule_triggered=None`.

**Outputs**:
- `policy_approved`: Boolean — determines conditional edge routing
- `policy_stopped_reason`: String (if blocked)
- `requires_human_approval`: Boolean
- `policy_rule_triggered`: Name of triggered rule or None

**Conditional Edge**: After this node, graph routes:
- If `policy_approved=True` → `execute_recovery_action`
- If `policy_approved=False` → `log_completion` (skip execution)

---

### Node 5: `execute_recovery_action`

**Purpose**: Execute the decided recovery action and persist results.

**Inputs**:
- `recommended_action_type`
- `policy_approved`, `policy_stopped_reason`
- Subscription/failure data for payment link creation

**Operations**:

1. **Create RecoveryAction Record**:
   ```python
   recovery_action = create_recovery_action(
       db=db,
       failure_event_id=failure_event_id,
       action_type=action_type,
       reason_text=reason_text
   )
   ```

2. **If Policy Stopped** (`policy_approved=False`):
   - Update status to `stopped_by_rule`
   - Create audit log entry noting policy block
   - Skip actual execution

3. **If Policy Approved**:
   - Initialize provider: `provider = get_provider(use_mock=True)`
   - If `action_type == send_update_link`:
     - Call `provider.create_payment_link(...)` with amount, currency, customer_email, subscription_id, etc.
     - Store returned `razorpay_payment_link_id` and `short_url`
   - Update `RecoveryAction` with:
     - `status = pending`
     - `razorpay_payment_link_id`
     - `payment_link_url`

4. **Create Audit Log**: Entry noting action execution.

**Outputs**:
- `recovery_action_id`: ID of created record
- `razorpay_payment_link_id`: Razorpay's payment link ID (if applicable)
- `action_status`: `pending`, `stopped_by_rule`, or error
- `execution_result`: Dict with execution details

---

### Node 6: `log_workflow_completion`

**Purpose**: Finalize workflow state and write completion audit trail.

**Inputs**:
- All accumulated state from previous nodes
- `recovery_action_id`, `audit_log_ids`

**Operations**:
1. Set `workflow_completed_at = datetime.utcnow()`
2. Create final audit log entry: "Workflow completed for failure_event_id={id}, action={action_type}, status={action_status}"
3. Append audit log ID to `audit_log_ids` list

**Outputs**:
- `workflow_completed_at`: Timestamp
- `audit_log_ids`: List of all audit log entry IDs created during workflow

---

## State Object Flow

The `RecoveryWorkflowState` TypedDict flows through all nodes, accumulating data:

```python
class RecoveryWorkflowState(TypedDict):
    # Identifiers
    subscription_id: Optional[int]
    failure_event_id: Optional[int]
    recovery_action_id: Optional[int]
    
    # Subscription data (populated by Node 1)
    customer_name: Optional[str]
    customer_email: Optional[str]
    plan_name: Optional[str]
    amount: Optional[int]  # in paise
    currency: Optional[str]
    subscription_status: Optional[str]
    
    # Failure data (populated by Node 1)
    failure_code: Optional[str]
    retry_count: Optional[int]
    failure_occurred_at: Optional[datetime]
    
    # Analysis results (populated by Node 2)
    failure_analysis: Optional[str]
    failure_category: Optional[str]
    recovery_implications: Optional[List[str]]
    
    # Decision results (populated by Node 3)
    recommended_action_type: Optional[str]
    action_reason: Optional[str]
    confidence_score: Optional[float]
    
    # Policy check results (populated by Node 4)
    policy_approved: Optional[bool]
    policy_stopped_reason: Optional[str]
    requires_human_approval: Optional[bool]
    policy_rule_triggered: Optional[str]
    
    # Execution results (populated by Node 5)
    razorpay_payment_link_id: Optional[str]
    action_status: Optional[str]
    execution_result: Optional[Any]
    
    # Error handling
    error_message: Optional[str]
    is_simulated: bool  # Always True until real Razorpay integration
    
    # Audit tracking (populated by Nodes 5, 6)
    workflow_started_at: Optional[datetime]
    workflow_completed_at: Optional[datetime]
    audit_log_ids: Optional[List[int]]
```

---

## Razorpay Evaluation Criteria Mapping

### 1. Measured Batch Recovery Rate ✅

**Criterion**: Track recovery rate across batch runs with measurable metrics.

**Implementation**:
- **Endpoint**: `GET /metrics/summary`
- **Returns**:
  ```json
  {
    "total_failed": 25,
    "total_recovered": 0,
    "total_at_risk_amount": 25897500,
    "total_recovered_amount": 0,
    "recovery_rate_pct": 0.0,
    "escalated_to_human": 17
  }
  ```
- **Dashboard**: "Key Metrics" section displays:
  - Total Failed Subscriptions
  - Recovery Rate (%)
  - ₹ At Risk
  - ₹ Recovered
  - Escalated to Human count

**Batch Endpoint**: `POST /recovery/run-batch` returns:
```json
{
  "total_processed": 21,
  "actions_by_type": {
    "retry_after_24h": 9,
    "send_update_link": 9,
    "escalate": 2,
    "retry_now": 1
  },
  "stopped_by_policy": 11,
  "errors": 0,
  "payment_links_created": 4
}
```

---

### 2. Stopping Rules (Guardrails) ✅

**Criterion**: Implement policy-based stopping rules for safe automation.

**Implementation**: `check_policy_guards` node (Node 4) implements all 4 required rules:

| Rule | Trigger | Effect | Test |
|------|---------|--------|------|
| Max Retries | `retry_count >= 3` | Override to `escalate` | `test_policy_max_retries_forces_escalation` |
| Quiet Hours | IST 9PM–8AM + `send_update_link` | Block execution | `test_policy_quiet_hours_stops_action` |
| High-Value Approval | `amount > ₹5000` | Block execution | `test_policy_high_value_requires_approval` |
| Repeated-Failure Escalation | 2+ prior failures | Override to `escalate` | `test_policy_repeated_failure_forces_escalation` |

**Audit Trail**: Each policy trigger creates an `AuditLog` entry with description noting the rule.

**Dashboard**: "🚫 Policy Guardrails" panel shows all stopped actions with triggered rule.

---

### 3. Audit Trail ✅

**Criterion**: Maintain complete audit trail of all agent decisions and actions.

**Implementation**:
- **Table**: `AuditLog` with columns: `id`, `entity_type`, `entity_id`, `event_description`, `timestamp`
- **Entity Types**: `subscription`, `failure_event`, `recovery_action`
- **Logging Points**:
  1. `execute_recovery_action` node: Logs action creation and policy stops
  2. `log_workflow_completion` node: Logs workflow completion
  3. `/webhooks/razorpay`: Logs payment confirmation
  4. `/demo/simulate-payment`: Logs demo simulation

**Endpoint**: `GET /audit-log?limit=30` returns paginated entries.

**Dashboard**: "📜 Live Audit Trail" expandable panel shows recent entries with timestamps.

---

### 4. Compliant Escalation ✅

**Criterion**: Proper escalation path for cases requiring human intervention.

**Implementation**:
- **Action Type**: `escalate` (one of 4 action types)
- **Trigger Conditions**:
  - Max retries exceeded (3 attempts)
  - Unknown failure code
  - Repeated-failure pattern (2+ failures)
  - Policy override (max_retries rule)
- **Human Approval Flag**: `requires_human_approval` boolean set when:
  - Max retries rule triggers
  - High-value approval rule triggers
  - Repeated-failure rule triggers

**Dashboard Metric**: "Escalated to Human" count = `escalate` actions + `stopped_by_policy` count from last batch run.

**Audit Entry**: Example: `"Recovery action escalated to manual review: Max retry limit (3) reached"`

---

## Data Flow Summary

```
User Action (Dashboard/API)
    │
    v
POST /recovery/run-batch
    │
    v
For each FailureEvent:
    │
    v
run_recovery_workflow(failure_event_id, db)
    │
    ├─> load_subscription_data ──> State: {subscription, failure data}
    │
    ├─> analyze_failure ──> State: {failure_category, analysis, implications}
    │
    ├─> decide_recovery_action ──> State: {action_type, reason, confidence}
    │
    ├─> check_policy_guards ──> State: {policy_approved, rule_triggered}
    │       │
    │       ├─ If approved ──> execute_recovery_action ──> Create RecoveryAction + Payment Link
    │       │
    │       └─ If blocked ──> (skip execute)
    │
    └─> log_workflow_completion ──> AuditLog entries
    │
    v
Return: {success, action_taken, razorpay_payment_link_id, audit_log_ids}
    │
    v
Aggregate results across batch
    │
    v
Return summary: {total_processed, actions_by_type, stopped_by_policy, errors}
    │
    v
Dashboard metrics update via GET /metrics/summary
```

---

## Security & Compliance Notes

1. **Webhook Verification**: `/webhooks/razorpay` verifies `X-Razorpay-Signature` header using `RAZORPAY_WEBHOOK_SECRET`.

2. **Demo Endpoint Isolation**: `/demo/simulate-payment` is clearly marked as DEMO ONLY; production deployments should disable or remove this endpoint.

3. **Audit Immutability**: `AuditLog` entries are append-only; no update/delete operations are exposed.

4. **Environment Separation**: `.env` file keeps secrets out of code; `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` must be configured.

5. **Quiet Hours Compliance**: Customer communication (`send_update_link`) is blocked during 9PM–8AM IST to respect customer experience norms.

6. **High-Value Transaction Oversight**: Transactions > ₹5000 require human approval before any automated action.
