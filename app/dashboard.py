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

# Configuration
BACKEND_URL = "http://localhost:8000"

st.set_page_config(
    page_title="ChurnGuard Dashboard",
    page_icon="🛡️",
    layout="wide"
)

# Custom CSS for status colors (minimal, using Streamlit defaults where possible)
st.markdown("""
<style>
.status-success { color: green; }
status-pending { color: orange; }
status-failed { color: red; }
status-stopped { color: gray; }
</style>
""", unsafe_allow_html=True)


def format_inr(paise_amount: int) -> str:
    """Convert paise to INR with comma formatting."""
    rupees = paise_amount / 100
    return f"₹{rupees:,.2f}"


def get_failures():
    """Fetch all failure events from the backend."""
    try:
        response = requests.get(f"{BACKEND_URL}/failures?limit=500", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        st.error(f"Failed to fetch failures: {e}")
        return []


def get_audit_log(limit=30):
    """Fetch audit log entries from the backend."""
    try:
        response = requests.get(f"{BACKEND_URL}/audit-log?limit={limit}", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        st.error(f"Failed to fetch audit log: {e}")
        return []


def get_metrics_summary():
    """Fetch aggregated metrics from the backend."""
    try:
        response = requests.get(f"{BACKEND_URL}/metrics/summary", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        st.error(f"Failed to fetch metrics: {e}")
        return None


def get_recovery_actions():
    """Fetch recovery actions by getting subscriptions and their nested data."""
    try:
        # Get all subscriptions which include failure_events and recovery_actions
        response = requests.get(f"{BACKEND_URL}/subscriptions?limit=500", timeout=10)
        response.raise_for_status()
        subscriptions = response.json()
        
        # Extract recovery actions with subscription info
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
    except requests.RequestException as e:
        st.error(f"Failed to fetch recovery actions: {e}")
        return []


# Header
st.title("🛡️ ChurnGuard — Agentic Subscription Recovery")
st.markdown("AI-powered recovery agent that analyzes payment failures and takes intelligent recovery actions.")

# Initialize session state for batch run results
if "last_batch_run" not in st.session_state:
    st.session_state.last_batch_run = None
if "last_run_timestamp" not in st.session_state:
    st.session_state.last_run_timestamp = None

# Control Panel
st.header("Control Panel")
col1, col2, col3 = st.columns([1, 1, 2])

with col1:
    # Add number input for subscription count
    subscription_count = st.number_input(
        "Subscriptions to generate",
        min_value=1,
        max_value=200,
        value=25,  # Default to 25 for demo safety
        step=1,
        help="For demo recording, use 25 to stay under Razorpay's 30 payment link test limit"
    )
    
    if st.button("📊 Generate Synthetic Data", use_container_width=True):
        try:
            with st.spinner(f"Generating {subscription_count} subscriptions..."):
                response = requests.post(f"{BACKEND_URL}/generate-data?count={subscription_count}", timeout=30)
                response.raise_for_status()
                result = response.json()
                data = result.get("data", {})
                st.success(
                    f"✅ Generated: {data.get('subscriptions', 0)} subscriptions, "
                    f"{data.get('failure_events', 0)} failures, "
                    f"{data.get('recovery_actions', 0)} recovery actions"
                )
        except requests.RequestException as e:
            st.error(f"Failed to generate data: {e}")

with col2:
    if st.button("▶️ Run Batch Recovery", use_container_width=True):
        with st.spinner("Running batch recovery workflow… (may take 2–4 min with real Razorpay calls)"):
            try:
                response = requests.post(f"{BACKEND_URL}/recovery/run-batch", timeout=300)
                response.raise_for_status()
                result = response.json()
                st.session_state.last_batch_run = result
                st.session_state.last_run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Display results
                st.info(f"""
                **Batch Run Complete**
                - Total processed: {result.get('total_processed', 0)}
                - Actions by type: {result.get('actions_by_type', {})}
                - Stopped by policy: {result.get('stopped_by_policy', 0)}
                - Errors: {result.get('errors', 0)}
                - Payment links created: {result.get('payment_links_created', 0)}
                """)
            except requests.RequestException as e:
                st.error(f"Batch recovery failed: {e}")

with col3:
    if st.session_state.last_run_timestamp:
        st.caption(f"Last run: {st.session_state.last_run_timestamp}")
    else:
        st.caption("Last run: Never")

# Fetch fresh data for metrics
metrics = get_metrics_summary()
failures = get_failures()
recovery_actions = get_recovery_actions()

# Headline Metrics Row
st.header("Key Metrics")
if metrics:
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric(
            label="Total Failed Subscriptions",
            value=metrics.get("total_failed", 0)
        )
    
    with col2:
        st.metric(
            label="Recovery Rate",
            value=f"{metrics.get('recovery_rate_pct', 0):.1f}%"
        )
    
    with col3:
        st.metric(
            label="₹ At Risk",
            value=format_inr(metrics.get("total_at_risk_amount", 0))
        )
    
    with col4:
        st.metric(
            label="₹ Recovered",
            value=format_inr(metrics.get("total_recovered_amount", 0))
        )
    
    with col5:
        st.metric(
            label="Escalated to Human",
            value=metrics.get("escalated_to_human", 0)
        )
else:
    st.warning("Could not load metrics. Ensure the FastAPI backend is running.")

# Failure Breakdown Chart
st.header("Failure Breakdown")
if failures:
    # Count failures by failure_code
    failure_counts = {}
    for f in failures:
        code = f.get("failure_code", "unknown")
        failure_counts[code] = failure_counts.get(code, 0) + 1
    
    if failure_counts:
        df_failures = pd.DataFrame(list(failure_counts.items()), columns=["Failure Code", "Count"])
        df_failures = df_failures.set_index("Failure Code")
        st.bar_chart(df_failures)
    else:
        st.info("No failure data available.")
else:
    st.info("No failure data available.")

# Recovery Strategy Breakdown Panel
def get_strategy_breakdown():
    """Fetch per-action-type recovery statistics from the backend."""
    try:
        response = requests.get(f"{BACKEND_URL}/metrics/strategy-breakdown", timeout=10)
        response.raise_for_status()
        return response.json().get("strategies", [])
    except requests.RequestException as e:
        st.error(f"Failed to fetch strategy breakdown: {e}")
        return []

st.header("Recovery Strategy Breakdown")
strategy_data = get_strategy_breakdown()
if strategy_data:
    rows = []
    for s in strategy_data:
        label = s["action_type"].replace("_", " ").title()
        total_inr = format_inr(s["total_amount"])
        recovered_inr = format_inr(s["recovered_amount"])
        rows.append({
            "Strategy": label,
            "Cases": s["count"],
            "Amount Attempted": total_inr,
            "Recovered": s["recovered_count"],
            "Amount Recovered": recovered_inr,
            "Recovery Rate": f"{s['recovery_rate_pct']:.1f}%",
        })
    st.dataframe(
        pd.DataFrame(rows).set_index("Strategy"),
        use_container_width=True,
    )
    st.caption(
        "Counts include both pre-existing synthetic actions and actions created by the latest batch run. "
        "Recovery Rate = successful actions ÷ total actions per strategy."
    )
else:
    st.info("No strategy data available. Generate data and run batch recovery first.")

# Recovery Action Outcomes Table
st.header("Recovery Action Outcomes")
if recovery_actions:
    df_actions = pd.DataFrame(recovery_actions)
    
    # Select and rename columns for display
    display_df = df_actions[[
        "customer_name",
        "failure_code",
        "action_type",
        "action_status",
        "reason_text",
        "payment_link_url",
        "created_at"
    ]].copy()
    
    display_df.columns = [
        "Customer",
        "Failure Reason",
        "Action Taken",
        "Status",
        "Policy Rule",
        "Payment Link",
        "Timestamp"
    ]
    
    # Make payment links clickable
    def make_clickable(url):
        if isinstance(url, str) and url.startswith("http"):
            return f'<a href="{url}" target="_blank">Click to Pay</a>'
        return ""
    
    # Apply color coding to status column
    def color_status(status):
        if status == "success":
            return "color: green;"
        elif status == "pending":
            return "color: orange;"
        elif status == "failed":
            return "color: red;"
        elif status == "stopped_by_rule":
            return "color: gray;"
        return ""
    
    # Style the dataframe
    styled_df = display_df.style.map(
        color_status, 
        subset=["Status"]
    ).format(
        {"Payment Link": make_clickable}
    )
    
    st.dataframe(styled_df, use_container_width=True, height=400)
else:
    st.info("No recovery actions recorded yet.")

# Demo Payment Simulation Section
st.header("🧪 Demo Payment Simulation")
st.markdown("**DEMO ONLY** — Simulate successful payments to show recovery flow without waiting for real test payments.")

# Get pending payment links
pending_actions = [ra for ra in recovery_actions if ra["action_status"] == "pending" and ra.get("payment_link_url")]

if pending_actions:
    st.subheader("Pending Payment Links Ready for Simulation")
    
    for i, action in enumerate(pending_actions[:10]):  # Show first 10
        col1, col2, col3 = st.columns([3, 2, 1])
        with col1:
            st.write(f"**{action['customer_name']}** — {format_inr(action['amount'])} ({action['failure_code']})")
        with col2:
            if action.get("payment_link_url"):
                st.link_button("View Payment Link", action["payment_link_url"])
        with col3:
            if st.button("Simulate Payment ✅", key=f"sim_{action['action_id']}"):
                try:
                    response = requests.post(
                        f"{BACKEND_URL}/demo/simulate-payment/{action['action_id']}",
                        timeout=10
                    )
                    response.raise_for_status()
                    st.success(f"✅ [DEMO] Payment simulated for {action['customer_name']}")
                    st.rerun()
                except requests.RequestException as e:
                    st.error(f"Simulation failed: {e}")
        st.divider()
else:
    st.info("No pending payment links available for simulation. Run batch recovery or generate synthetic data first.")

# Policy Stops Panel
st.header("🚫 Policy Guardrails — Actions Stopped by Rules")
stopped_actions = [ra for ra in recovery_actions if ra["action_status"] == "stopped_by_rule"]

if stopped_actions:
    stopped_df = pd.DataFrame(stopped_actions)[[
        "customer_name",
        "failure_code",
        "action_type",
        "reason_text",
        "created_at"
    ]]
    stopped_df.columns = ["Customer", "Failure Reason", "Action Type", "Policy Rule Triggered", "Timestamp"]
    st.dataframe(stopped_df, use_container_width=True, height=200)
    st.caption("These actions were blocked by policy guardrails, demonstrating ChurnGuard's safety mechanisms.")
else:
    st.info("No actions stopped by policy rules yet.")

# Live Audit Trail (Expandable)
st.header("📜 Live Audit Trail")
with st.expander("View Recent Audit Log Entries", expanded=False):
    audit_entries = get_audit_log(limit=30)
    if audit_entries:
        for entry in audit_entries:
            timestamp = entry.get("timestamp", "")[:19]  # Trim microseconds
            entity_type = entry.get("entity_type", "")
            entity_id = entry.get("entity_id", "")
            description = entry.get("event_description", "")
            st.text(f"[{timestamp}] {entity_type.upper()} #{entity_id}: {description}")
    else:
        st.info("No audit log entries found.")

# Footer
st.markdown("---")
st.caption("ChurnGuard Dashboard v1.0 | Backend: http://localhost:8000")
