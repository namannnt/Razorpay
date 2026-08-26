# ChurnGuard

**Agentic subscription-recovery system for Razorpay's AI Revenue Recovery track** — an AI-powered workflow that detects failed payments, classifies failure reasons, decides recovery actions, checks policy guardrails, executes recovery (including real Razorpay test-mode payment links), and logs everything for audit.

## Problem Statement

Failed subscription renewals are a silent revenue leak for SaaS businesses. When a customer's card expires, funds are insufficient, or authentication fails, the subscription status flips to "failed" — but without automated recovery, that revenue is simply lost. Manual follow-up is slow, inconsistent, and doesn't scale. For fintech companies using Razorpay, the challenge is compounded by the need for compliant, auditable recovery workflows that respect customer experience (no midnight emails) and business rules (high-value transactions need human approval). ChurnGuard addresses this by automating the entire recovery lifecycle while enforcing safety guardrails at every step.

## Solution Overview

ChurnGuard implements a LangGraph-based agent workflow with 5 sequential nodes:

1. **Load Data** — Fetches subscription and failure event details from the database
2. **Analyze Failure** — Classifies the failure code (`card_expired`, `insufficient_funds`, `bank_downtime`, `authentication_failed`, `unknown`) and determines if retry is viable
3. **Decide Recovery Action** — Selects an action type (`retry_now`, `send_update_link`, `retry_after_24h`, `escalate`) based on failure category, retry count, and transaction amount
4. **Check Policy Guards** — Applies 4 stopping rules before execution:
   - **Max Retries**: If `retry_count >= 3`, force escalation instead of further retries
   - **Quiet Hours**: Block `send_update_link` during 9PM–8AM IST (customer communication pause)
   - **High-Value Approval**: Require human approval for amounts > ₹5000
   - **Repeated-Failure Escalation**: If subscription has 2+ prior failures, escalate to manual review
5. **Execute Recovery Action** — Creates `RecoveryAction` record; if `send_update_link`, generates real Razorpay test-mode payment link via MockProvider; if stopped by policy, marks as `stopped_by_rule`
6. **Log Workflow Completion** — Writes audit trail entries for compliance tracking

```
┌─────────────────┐
│ Synthetic Data  │
│ (70 subs + fail)│
└────────┬────────┘
         │
         v
┌─────────────────┐     ┌──────────────────────────────────────────────────────┐
│   FastAPI       │────>│              LangGraph Agent                         │
│   Backend       │     │  ┌──────────┐    ┌──────────┐    ┌──────────────┐   │
│  (port 8000)    │     │  │  Load    │───>│ Analyze  │───>│    Decide    │   │
│                 │     │  │  Data    │    │ Failure  │    │   Action     │   │
│ /recovery/run   │     │  └──────────┘    └──────────┘    └──────┬───────┘   │
│ /recovery/      │     │                                          │           │
│   run-batch     │     │  ┌──────────┐    ┌──────────┐           v           │
│ /metrics/       │     │  │   Log    │<───│ Execute  │<──┌──────────────┐   │
│   summary       │     │  │Completion│    │ Recovery │    │ Check Policy │   │
│ /webhooks/      │     │  └────┬─────┘    └──────────┘    │   Guards     │   │
│   razorpay      │     │       │                          └──────────────┘   │
└────────┬────────┘     └───────┼──────────────────────────────────────────────┘
         │                      │
         │                      v
         │            ┌───────────────────┐
         │            │ Razorpay Test API │
         │            │ (payment_link.create)
         │            └─────────┬─────────┘
         │                      │
         v                      v
┌─────────────────┐     ┌─────────────────┐
│   SQLite        │     │   Webhook       │
│   Database      │<────│ /webhooks/      │
│ churnguard.db   │     │   razorpay      │
│                 │     └─────────────────┘
│ - Subscription  │
│ - FailureEvent  │
│ - RecoveryAction│
│ - AuditLog      │
└────────┬────────┘
         │
         v
┌─────────────────┐
│ Streamlit       │
│ Dashboard       │
│ (port 8501)     │
│                 │
│ - Batch Run     │
│ - Metrics Cards │
│ - Failure Chart │
│ - Actions Table │
│ - Audit Panel   │
└─────────────────┘
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend Framework | FastAPI |
| Agent Workflow | LangGraph |
| Frontend Dashboard | Streamlit |
| Database | SQLite (dev), configurable for PostgreSQL |
| Payment Provider | Razorpay (test mode) |
| Testing | pytest |
| Environment | Python 3.12+, separate venvs for backend/dashboard |

## Setup Instructions

### 1. Backend Setup

```bash
# Create and activate virtual environment
python -m venv venv-backend
source venv-backend/bin/activate  # Windows: venv-backend\Scripts\activate

# Install dependencies
pip install -r requirements-backend.txt

# Configure environment variables
cp .env.example .env
```

Edit `.env` with your Razorpay test credentials:
```
RAZORPAY_KEY_ID=your_test_key_id_here
RAZORPAY_KEY_SECRET=your_test_key_secret_here
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret_here
DATABASE_URL=sqlite:///./churnguard.db
ENVIRONMENT=development
```

Get test keys from [Razorpay Dashboard → Settings → API Keys](https://dashboard.razorpay.com/app/keys).

### 2. Dashboard Setup (Separate Terminal)

```bash
# Create and activate separate virtual environment
python -m venv venv-dashboard
source venv-dashboard/bin/activate  # Windows: venv-dashboard\Scripts\activate

# Install dependencies
pip install -r requirements-dashboard.txt
```

### 3. Generate Test Data

```bash
# In backend venv, start server first
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# In another terminal (backend venv still active)
curl -X POST http://localhost:8000/generate-data
```

Or use the dashboard's "Generate Synthetic Data" button.

### 4. Run Services

**Backend:**
```bash
source venv-backend/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Dashboard:**
```bash
source venv-dashboard/bin/activate
streamlit run app/dashboard.py
```

Dashboard opens at `http://localhost:8501`.

## How to Run a Demo End-to-End

1. **Generate Data**: Click "📊 Generate Synthetic Data" in dashboard control panel (creates 70 subscriptions with ~70 failure events)

2. **Run Batch Recovery**: Click "▶️ Run Batch Recovery" — watch as each failure is processed through the 5-node workflow

3. **View Results**:
   - **Key Metrics**: See recovery rate, ₹ at risk, ₹ recovered, escalated count
   - **Failure Breakdown**: Bar chart showing distribution of failure codes
   - **Recovery Action Outcomes**: Table with customer, failure reason, action taken, status, payment links

4. **Simulate Payment**: In "Demo Payment Simulation" section, click "Simulate Payment ✅" for any pending action — metrics update live showing increased recovery rate and ₹ recovered

5. **Inspect Audit Trail**: Expand "📜 Live Audit Trail" to see timestamped entries for every workflow decision and action

6. **Review Guardrails**: Check "🚫 Policy Guardrails" panel for actions stopped by max-retries, quiet-hours, or high-value rules

## Test Coverage Summary

**Total Tests: 55**

| File | Count | Coverage Area |
|------|-------|---------------|
| `test_setup.py` | 12 | Database imports, table creation, synthetic data generation, basic CRUD endpoints (health, subscriptions, failures, audit log), service layer functions |
| `test_agents.py` | 35 | LangGraph state definition, provider abstraction, graph creation, failure analysis (5 failure codes), recovery decisions (card_expired→payment_link, insufficient_funds→retry, max_retries→escalate, unknown→escalate, high-value adjustments), workflow execution (recovery action creation, audit logs, 404 handling, idempotency), **policy guardrail tests** (max_retries forces escalation, quiet_hours stops send_update_link, high_value requires approval, repeated_failure forces escalation, pass-through when no rules triggered), integration tests (recovery endpoint success/404, existing endpoints), metrics endpoint, demo payment simulation |
| `test_webhook_and_batch.py` | 8 | Razorpay webhook signature verification (valid/invalid/missing), unknown payment link handling, batch processing (multiple events, specific IDs, error continuation, summary counts) |

**Guardrail-Specific Tests** (5 tests in `test_agents.py`):
- `test_policy_max_retries_forces_escalation` — Verifies retry_count >= 3 overrides to escalate
- `test_policy_quiet_hours_stops_action` — Verifies send_update_link blocked during 9PM-8AM IST
- `test_policy_high_value_requires_approval` — Verifies amounts > ₹5000 require human approval
- `test_policy_repeated_failure_forces_escalation` — Verifies 2+ failures trigger escalation
- `test_policy_no_rule_triggered_passes_through` — Verifies normal flow when no rules match

## Known Limitations

1. **Single-Workflow Scope by Design**: Per the challenge brief, ChurnGuard focuses exclusively on post-failure subscription recovery. Checkout-abandonment recovery and dunning email campaigns are not implemented (see Future Roadmap).

2. **SQLite Database**: Uses SQLite (`churnguard.db`) for development simplicity. Production deployments should configure PostgreSQL via `DATABASE_URL` environment variable. No migrations are included — schema is created on startup via `Base.metadata.create_all()`.

3. **Sequential Batch Processing**: The `/recovery/run-batch` endpoint processes failures one-at-a-time in a loop. Large batches (1000+) will be slow. No async/parallel execution is implemented.

4. **Mock Payment Provider**: By default, `get_provider(use_mock=True)` returns a `MockProvider` that simulates Razorpay payment link creation with fake URLs. Real Razorpay integration requires setting `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` in `.env` and switching to `use_mock=False` in `execute_recovery_action` node.

5. **Demo-Only Payment Simulation**: The `/demo/simulate-payment/{id}` endpoint bypasses webhook verification and directly marks actions as successful. This is clearly marked as DEMO ONLY and should never be used in production. Real payment confirmation must flow through `/webhooks/razorpay`.

6. **Rule-Based Failure Classification**: The `analyze_failure` node uses deterministic if-else rules based on failure codes. No LLM-based classification is implemented (see Future Roadmap).

7. **Approximate IST Calculation**: Quiet hours rule uses `(utc_hour + 5) % 24` for IST approximation, ignoring the 30-minute offset. This is sufficient for demo purposes but may misclassify edge cases around 8:30 AM / 9:30 PM boundaries.

## Future Roadmap

- **Checkout-Recovery Workflow**: Extend agent to handle abandoned checkout sessions (pre-subscription) with cart-recovery payment links, separate from post-failure renewal recovery.

- **LLM-Based Failure Classification**: Replace rule-based `analyze_failure` node with an LLM call that analyzes failure context, customer history, and payment metadata to classify failures and recommend actions with confidence scores.

- **PostgreSQL + Async Batch Processing**: Migrate to PostgreSQL with Alembic migrations; implement async batch processing using `asyncio.gather()` or Celery for parallel recovery execution on large datasets.
