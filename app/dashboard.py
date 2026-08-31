"""
ChurnGuard Dashboard — Streamlit UI for Subscription Recovery Monitoring

Run separately from the FastAPI backend via:
    streamlit run app/dashboard.py

This dashboard calls the FastAPI backend at http://localhost:8000 over HTTP
using the requests library. It does NOT import backend code directly.
"""
import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import os

# Setup Page Configuration
st.set_page_config(
    page_title="ChurnGuard | AI Revenue Recovery",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Sidebar and Configuration
st.sidebar.image("https://img.icons8.com/external-flatart-icons-flat-flatarticons/256/external-shield-protection-and-security-flatart-icons-flat-flatarticons.png", width=80)
st.sidebar.title("ChurnGuard Admin")
st.sidebar.caption("Agentic Revenue Recovery System for Razorpay Subscriptions")
st.sidebar.divider()

# Constants & Backend URL Configuration
BACKEND_URL = st.sidebar.text_input("Backend Service URL", "http://localhost:8000")

# Inject Custom CSS for Premium Fintech Look
st.markdown("""
<style>
    .stApp {
        background-color: #FAFCFF;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
        font-weight: 700 !important;
        color: #121C2B;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.9rem !important;
        font-weight: 600 !important;
        color: #64748B;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    div[data-testid="stMetric"] {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        padding: 20px 24px;
        border-radius: 12px;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.02), 0 2px 4px rgba(0, 0, 0, 0.01);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 15px rgba(24, 90, 219, 0.05);
    }
    h1, h2, h3, h4 {
        color: #121C2B !important;
        font-family: 'Inter', sans-serif !important;
    }
    .badge {
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: 600;
        display: inline-block;
    }
    .badge-success { background-color: #DEF7EC; color: #03543F; }
    .badge-pending { background-color: #E1EFFE; color: #1E429F; }
    .badge-stopped { background-color: #FDE8E8; color: #9B1C1C; }
    .badge-escalated { background-color: #FEF08A; color: #713F12; }
</style>
""", unsafe_allow_html=True)


def format_inr(paise_amount: int) -> str:
    """Convert paise to INR with comma formatting."""
    rupees = paise_amount / 100.0
    return f"₹{rupees:,.2f}"


@st.cache_data(ttl=2)
def get_failures():
    try:
        response = requests.get(f"{BACKEND_URL}/failures?limit=500", timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return []


@st.cache_data(ttl=2)
def get_audit_log(limit=50):
    try:
        response = requests.get(f"{BACKEND_URL}/audit-log?limit={limit}", timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return []


@st.cache_data(ttl=2)
def get_metrics_summary():
    try:
        response = requests.get(f"{BACKEND_URL}/metrics/summary", timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None


@st.cache_data(ttl=2)
def get_strategy_breakdown():
    try:
        response = requests.get(f"{BACKEND_URL}/metrics/strategy-breakdown", timeout=10)
        if response.status_code == 200:
            return response.json().get("strategies", [])
    except Exception:
        pass
    return []


@st.cache_data(ttl=2)
def get_recovery_actions():
    try:
        response = requests.get(f"{BACKEND_URL}/subscriptions?limit=500", timeout=10)
        if response.status_code != 200:
            return []
        subscriptions = response.json()
        recovery_actions = []
        for sub in subscriptions:
            for failure in sub.get("failure_events", []):
                for action in failure.get("recovery_actions", []):
                    recovery_actions.append({
                        "subscription_id": sub["id"],
                        "customer_name": sub["customer_name"],
                        "customer_email": sub["customer_email"],
                        "plan_name": sub["plan_name"],
                        "amount": sub["amount"],
                        "failure_id": failure["id"],
                        "failure_code": failure["failure_code"],
                        "action_id": action["id"],
                        "action_type": action["action_type"],
                        "action_status": action["status"],
                        "reason_text": action.get("reason_text", ""),
                        "payment_link_url": action.get("payment_link_url", ""),
                        "created_at": action["created_at"],
                        "resolved_at": action.get("resolved_at")
                    })
        return recovery_actions
    except Exception:
        pass
    return []


# Sidebar Data Inputs & Configuration
st.sidebar.subheader("Data Generation Config")
subscription_count = st.sidebar.number_input(
    "Subscriptions to generate",
    min_value=1,
    max_value=200,
    value=25,
    step=1,
    help="For demo recording, use 25 to stay under Razorpay's 30 payment link test limit"
)

# Sidebar: Compliance Bypass Status
st.sidebar.divider()
st.sidebar.subheader("Compliance Bypass (Testing)")
_disable_quiet_hours = os.getenv("DISABLE_QUIET_HOURS", "false").lower() == "true"
if _disable_quiet_hours:
    st.sidebar.markdown("""
    <span style='background:#DEF7EC;color:#03543F;padding:4px 10px;border-radius:6px;font-size:0.82rem;font-weight:700;'>
    🔓 EVALUATION MODE ON
    </span>
    """, unsafe_allow_html=True)
    st.sidebar.caption("Quiet hours are currently bypassed in backend. Real payment links will generate at any hour!")
else:
    st.sidebar.markdown("""
    <span style='background:#FDE8E8;color:#9B1C1C;padding:4px 10px;border-radius:6px;font-size:0.82rem;font-weight:700;'>
    🛡️ STRICT COMPLIANCE ON
    </span>
    """, unsafe_allow_html=True)
    st.sidebar.caption("Quiet hours active (10 PM–7 AM IST). Auto payment links will block during late hours.")


# Header Section
col_header, col_status = st.columns([4, 1])
with col_header:
    st.title("🛡️ ChurnGuard AI Revenue Recovery")
    st.caption("Automated Agentic Intervention Engine running on LangGraph stateful machines")

# Connection & Status Check
metrics_data = get_metrics_summary()
if metrics_data is None:
    with col_status:
        st.markdown("<span class='badge badge-stopped'>⚠️ BACKEND OFFLINE</span>", unsafe_allow_html=True)
    st.error(f"Cannot connect to the FastAPI server at `{BACKEND_URL}`. Make sure your server is running (`uvicorn app.main:app --reload --port 8000`) and the address is configured correctly in the sidebar.")
    st.stop()
else:
    with col_status:
        st.markdown("<span class='badge badge-success'>🟢 SYSTEM ONLINE</span>", unsafe_allow_html=True)

# Quiet Hours Banner — shown whenever the IST hour is inside the 9PM–8AM block
from datetime import timezone
_utc_now = datetime.now(timezone.utc)
_ist_total_minutes = _utc_now.hour * 60 + _utc_now.minute + 330
_ist_hour = (_ist_total_minutes // 60) % 24
if _ist_hour >= 22 or _ist_hour < 7:
    if _disable_quiet_hours:
        st.info(
            f"🔓 **Evaluation Mode Active ({_ist_hour:02d}:xx IST)** — "
            "It's currently within Quiet Hours (10 PM–7 AM IST), but `DISABLE_QUIET_HOURS=true` is set in `.env`. "
            "The quiet-hours policy guardrail is **bypassed** so you can experience the full automated payment link flow right now.",
            icon="🔓"
        )
    else:
        st.warning(
            f"🌙 **Quiet Hours Active ({_ist_hour:02d}:xx IST)** — "
            "ChurnGuard will not send payment links or customer notifications right now. "
            "We don't want to disturb customers between **10 PM and 7 AM IST**. "
            "Any `send_update_link` actions triggered during this window are automatically "
            "held by the policy guardrail and will be retried at 7 AM. "
            "This is by design — come back after 7 AM to see payment links being created!",
            icon="🌙"
        )

# Fetch current dashboard state
failures = get_failures()
recovery_actions = get_recovery_actions()
strategy_data = get_strategy_breakdown()

# KPI Data Mapping
total_failed = metrics_data.get("total_failed", 0)
total_recovered = metrics_data.get("total_recovered", 0)
total_at_risk_paise = metrics_data.get("total_at_risk_amount", 0)
total_recovered_paise = metrics_data.get("total_recovered_amount", 0)
recovery_rate = metrics_data.get("recovery_rate_pct", 0.0)
escalated_to_human = metrics_data.get("escalated_to_human", 0)

# KPI Metric Cards
kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
with kpi_col1:
    st.metric(
        label="🔴 Revenue At Risk",
        value=format_inr(total_at_risk_paise),
        delta=f"{total_failed} Subscriptions Failed",
        delta_color="off"
    )
with kpi_col2:
    st.metric(
        label="🟢 Revenue Recovered",
        value=format_inr(total_recovered_paise),
        delta=f"{total_recovered} Recovered Successfully",
        delta_color="normal"
    )
with kpi_col3:
    st.metric(
        label="📊 Recovery Success Rate",
        value=f"{recovery_rate:.1f}%",
        delta="Targeting 10% Industry Avg" if recovery_rate == 0 else f"+{recovery_rate:.1f}% Recovery"
    )
with kpi_col4:
    st.metric(
        label="👤 Escalated to Human",
        value=f"{escalated_to_human}",
        delta="Needs Manual Audit",
        delta_color="inverse"
    )

st.write("---")

# Session State
if "last_batch_run" not in st.session_state:
    st.session_state.last_batch_run = None
if "last_run_timestamp" not in st.session_state:
    st.session_state.last_run_timestamp = None

# Main Tabs
tab_ops, tab_failures, tab_actions, tab_sim, tab_audit = st.tabs([
    "⚡ Operations Room",
    "🚨 Active Failures",
    "🔗 Recovery Ledger",
    "🧪 Demo Simulator",
    "📜 Live Audit Trail"
])

# TAB 1: OPERATIONS ROOM
with tab_ops:
    st.subheader("System Control Panel")
    st.write("Interact with the core engine nodes, trigger synthetic failure scenarios, and review stopping rule guardrails.")

    col_run1, col_run2, col_rules = st.columns([1, 1, 1.2])

    with col_run1:
        st.write("#### 1. Ingest Synthetic Failure Data")
        st.write(f"Generate `{subscription_count}` synthetic failed subscriptions (T+1 renewal failed) to populate ChurnGuard's task list.")
        if st.button("📊 Generate Synthetic Data", use_container_width=True, type="secondary"):
            with st.spinner(f"Injecting {subscription_count} test failures..."):
                try:
                    res = requests.post(f"{BACKEND_URL}/generate-data?count={subscription_count}", timeout=30)
                    if res.status_code == 200:
                        result = res.json().get("data", {})
                        st.success(
                            f"✅ Generated: {result.get('subscriptions', 0)} subscriptions, "
                            f"{result.get('failure_events', 0)} failures, "
                            f"{result.get('recovery_actions', 0)} recovery actions"
                        )
                        st.cache_data.clear()
                        st.rerun()
                except Exception as e:
                    st.error(f"Failed to generate data: {e}")

    with col_run2:
        st.write("#### 2. Run Batch Recovery")
        st.write("Orchestrate the 5-node LangGraph agent state machine sequentially for each failed subscription event.")
        if st.button("▶️ Run Batch Recovery", use_container_width=True, type="primary"):
            with st.spinner("Processing stateful workflow... (Executing Razorpay test-mode API calls)"):
                try:
                    res = requests.post(f"{BACKEND_URL}/recovery/run-batch", timeout=300)
                    if res.status_code == 200:
                        result = res.json()
                        st.session_state.last_batch_run = result
                        st.session_state.last_run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        st.toast(f"🎉 Processed {result.get('total_processed', 0)} actions cleanly!", icon="🔥")
                        stopped = result.get('stopped_by_policy', 0)
                        links = result.get('payment_links_created', 0)
                        if stopped > 0:
                            st.toast(f"🛡️ {stopped} actions halted by Policy Guardrails.", icon="🛡️")
                        if links > 0:
                            st.toast(f"🔗 Generated {links} Razorpay payment URLs!", icon="🔗")
                        st.cache_data.clear()
                        st.rerun()
                except Exception as e:
                    st.error(f"Batch recovery failed: {e}")

        if st.session_state.last_run_timestamp:
            st.caption(f"Last Execution: {st.session_state.last_run_timestamp}")
        else:
            st.caption("Last Execution: Never Run")

    with col_rules:
        st.write("#### 🛡️ Compliance Policy Guardrails")
        st.write("Active safety constraints mapped on conditional LangGraph routing edges:")
        with st.container(border=True):
            st.markdown("🚫 **Quiet Hours Guard:** Delayed action between `10 PM – 7 AM IST` for notification compliance.")
            st.markdown("💰 **High-Value Approval Guard:** Halts automated links and demands human authorization for values `> ₹5,000`.")
            st.markdown("🔁 **Max Retries Guard:** Disables endless retry loops and escalates immediately after `3 failures`.")
            st.markdown("📉 **Repeated Failure Pattern:** Escalates to review if subscription reports `2+ failure events`.")

    if st.session_state.last_batch_run:
        st.write("---")
        st.write("### 📈 Latest Batch Run Diagnostics")
        res_data = st.session_state.last_batch_run
        diag_col1, diag_col2, diag_col3, diag_col4 = st.columns(4)
        with diag_col1:
            st.metric("Total Processed", res_data.get('total_processed', 0))
        with diag_col2:
            st.metric("Links Created", res_data.get('payment_links_created', 0))
        with diag_col3:
            st.metric("Blocked by Policy", res_data.get('stopped_by_policy', 0))
        with diag_col4:
            st.metric("Batch Errors", res_data.get('errors', 0))
        st.write("**Action Type Breakdown:**")
        st.json(res_data.get('actions_by_type', {}))

# TAB 2: ACTIVE FAILURES
with tab_failures:
    st.subheader("Failed Renewal Subscriptions Awaiting Recovery")
    st.write("Raw failure events ingested from Razorpay subscription billing failures.")

    col_chart, col_empty = st.columns([2, 1])

    if failures:
        failure_counts = {}
        for f in failures:
            code = f.get("failure_code", "unknown")
            failure_counts[code] = failure_counts.get(code, 0) + 1
        if failure_counts:
            df_failures = pd.DataFrame(
                list(failure_counts.items()), columns=["Failure Code", "Count"]
            ).set_index("Failure Code")
            with col_chart:
                st.bar_chart(df_failures, color="#E11D48")

        st.dataframe(
            pd.DataFrame(failures),
            column_config={
                "id": "Failure Event ID",
                "subscription_id": "Subscription ID",
                "failure_code": "Razorpay Error Code",
                "retry_count": st.column_config.NumberColumn("Retries", format="%d"),
                "occurred_at": st.column_config.DatetimeColumn("Occurred Time")
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No failure events currently queued. Click 'Generate Synthetic Data' in the Operations Room to start!")

# TAB 3: RECOVERY LEDGER
with tab_actions:
    st.subheader("LangGraph-Executed Interventions Ledger")
    st.write("A master log of all actions taken, corresponding links generated, and stopping rules triggered.")

    if recovery_actions:
        st.write("#### 📈 Recovery Strategy Efficacy Breakdown")
        if strategy_data:
            rows = []
            for s in strategy_data:
                label = s["action_type"].replace("_", " ").title()
                rows.append({
                    "Strategy": label,
                    "Cases": s["count"],
                    "Amount Attempted": format_inr(s["total_amount"]),
                    "Recovered Count": s["recovered_count"],
                    "Amount Recovered": format_inr(s["recovered_amount"]),
                    "Recovery Rate": f"{s['recovery_rate_pct']:.1f}%",
                })
            st.dataframe(pd.DataFrame(rows).set_index("Strategy"), use_container_width=True)

        st.write("#### 📋 History of Recovery Actions")
        df_actions = pd.DataFrame(recovery_actions)
        display_df = df_actions[[
            "customer_name", "failure_code", "action_type", "action_status",
            "reason_text", "payment_link_url", "created_at"
        ]].copy()
        display_df.columns = [
            "Customer", "Failure Reason", "Action Taken", "Status", "Policy Info", "Payment Link", "Timestamp"
        ]

        def get_styled_status(status):
            if status == "success":
                return "🟢 Resolved"
            elif status == "pending":
                return "🔵 Pending"
            elif status == "stopped_by_rule":
                return "🚫 Policy Stopped"
            elif status == "escalate":
                return "👤 Escalated"
            return status

        display_df["Status"] = display_df["Status"].apply(get_styled_status)

        st.dataframe(
            display_df,
            column_config={
                "Payment Link": st.column_config.LinkColumn("Payment Checkout", display_text="Click to Pay 🔗")
            },
            use_container_width=True,
            hide_index=True,
            height=300
        )

        st.write("---")
        st.subheader("🚫 Policy Guardrails Audit — Blocked Operations")
        st.write("Recovery attempts caught by the safety engine, keeping automated action bounded and secure.")
        stopped_actions = [ra for ra in recovery_actions if ra["action_status"] == "stopped_by_rule"]
        if stopped_actions:
            stopped_df = pd.DataFrame(stopped_actions)[[
                "customer_name", "failure_code", "action_type", "reason_text", "created_at"
            ]]
            stopped_df.columns = ["Customer", "Failure Reason", "Action Type", "Stopping Rule Violation", "Timestamp"]
            st.dataframe(stopped_df, use_container_width=True, hide_index=True)
        else:
            st.info("No actions stopped by policy checks yet.")
    else:
        st.info("No recovery actions found. Ingest and run batch recovery under Operations Room first.")

# TAB 4: DEMO SIMULATOR
with tab_sim:
    st.subheader("🧪 Live Payment Simulation Sandbox")
    st.write("Simulate a customer click-and-pay sequence on a generated checkout link to trigger the Razorpay webhook verification flow.")

    pending_actions = [ra for ra in recovery_actions if ra["action_status"] == "pending" and ra.get("payment_link_url")]

    if pending_actions:
        st.write("### Pending Payment Links Ready for Simulation")
        for i, action in enumerate(pending_actions[:10]):
            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.write(f"👤 **{action['customer_name']}** — {format_inr(action['amount'])}")
                    st.write(f"❌ *Failure Reason:* `{action['failure_code']}`")
                with col2:
                    if action.get("payment_link_url"):
                        st.link_button("🔗 View Checkout URL", action["payment_link_url"], use_container_width=True)
                with col3:
                    if st.button("Simulate Payment ✅", key=f"sim_{action['action_id']}", use_container_width=True, type="primary"):
                        try:
                            response = requests.post(
                                f"{BACKEND_URL}/demo/simulate-payment/{action['action_id']}",
                                timeout=15
                            )
                            if response.status_code == 200:
                                st.toast(f"✅ Payment Simulated for {action['customer_name']}", icon="✅")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error("Simulation endpoint reported an error.")
                        except Exception as e:
                            st.error(f"Simulation failed: {e}")
    else:
        st.info("No active payment links awaiting confirmation. Run Batch Recovery first to generate pending update links!")

# TAB 5: LIVE AUDIT TRAIL
with tab_audit:
    st.subheader("Compliance Ledger & Decisional Telemetry")
    st.write("Every state change, API call, and rule evaluation executed by ChurnGuard is recorded in this immutable audit file.")

    audit_entries = get_audit_log(limit=50)
    if audit_entries:
        for entry in audit_entries:
            timestamp = entry.get("timestamp", "")[:19]
            entity = entry.get("entity_type", "SYSTEM")
            desc = entry.get("event_description", "")

            icon = "🛡️"
            if "payment_link" in desc or "Razorpay" in desc:
                icon = "🔗"
            elif "escalat" in desc or "manual" in desc:
                icon = "👤"
            elif "Recovered" in desc or "successful" in desc or "Simulation" in desc:
                icon = "✅"
            elif "stopped" in desc or "hours" in desc or "High-Value" in desc:
                icon = "🚫"

            st.markdown(f"`{timestamp}` **{icon} [{entity.upper()}]** {desc}")
    else:
        st.info("No audit logs captured. Trigger workflows to populate telemetry logs.")

# Footer
st.markdown("---")
st.caption("ChurnGuard Dashboard v1.2 | Developed with LangGraph and Streamlit | Target: Razorpay AI Buildathon")
