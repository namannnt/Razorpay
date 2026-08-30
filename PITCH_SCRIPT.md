# ChurnGuard Pitch Script (5-Minute Demo Video)

**Total Duration**: 5:00  
**Presenter**: [Your Name]  
**Product**: ChurnGuard — Agentic Subscription Recovery for Razorpay  

---

## 0:00–0:30 — Problem: Failed Subscriptions Are Silent Revenue Leaks

**[Screen: Dashboard homepage, metrics section visible but empty]**

"Every month, thousands of subscription renewals fail silently. A customer's card expires. Their account has insufficient funds. The bank's payment gateway goes down temporarily. In each case, the subscription flips to 'failed' status — and without automated recovery, that revenue is simply lost."

**[Click "Generate Synthetic Data" button]**

"Manual follow-up is slow, inconsistent, and doesn't scale. For fintech companies using Razorpay, the challenge is compounded by the need for compliant, auditable workflows that respect customer experience — no midnight emails — and business rules like human approval for high-value transactions."

**[Wait for data generation to complete — ~2 seconds]**

"Today I'm showing you ChurnGuard: an AI agent that automates the entire recovery lifecycle while enforcing safety guardrails at every step."

**[Point to metrics cards now populated]**

"We just generated 25 failed subscriptions representing over ₹2,58,975 in at-risk revenue. Let me show you how ChurnGuard recovers it."

---

## 0:30–1:30 — Live Batch Recovery Demo

**[Screen: Dashboard with data loaded, cursor hovering over "Run Batch Recovery"]**

"I'll now run batch recovery on all 25 failures. Watch as each one flows through our 5-node LangGraph workflow: load data, analyze failure, decide action, check policy guards, and execute recovery."

**[Click "Run Batch Recovery" button]**

"The workflow processes each failure sequentially. You can see the batch summary appear:"

**[Point to batch results panel]**

"- 21 total processed
- 9 payment links created for card-expired and auth-failed customers  
- 9 delayed retries scheduled for insufficient funds
- 2 escalated to manual review
- 1 immediate retry attempted
- 11 stopped by policy guardrails"

**[Scroll down to Failure Breakdown chart]**

"This bar chart shows the distribution of failure codes — card expired, insufficient funds, bank downtime, authentication failed. Each triggers a different recovery strategy."

**[Scroll to Recovery Action Outcomes table]**

"And here's the actions table: each row shows the customer, failure reason, action taken, current status, and — for payment link actions — a clickable link to Razorpay's hosted payment page."

---

## 1:30–2:30 — Deep Dive: One Failure Event's Full Trace

**[Screen: Zoom into first row of actions table — pick a card_expired case]**

"Let me trace one specific failure end-to-end. This customer, Priya Sharma, has a ₹999 Pro plan subscription that failed because her card expired."

**[Open browser dev tools or API client, show POST /recovery/run/{id} request]**

"When the workflow runs, here's what happens internally:"

**[Show terminal/logs if available, or describe]**

"**Step 1 — Load Data**: We fetch Priya's subscription record and the failure event. Her card expired two days ago, retry count is zero."

"**Step 2 — Analyze Failure**: Our rule-based analyzer classifies this as `card_expired`. Key insight: automatic retry will definitely fail — the card is physically expired. Customer action is required."

"**Step 3 — Decide Action**: Based on the analysis, we select `send_update_link` — send a Razorpay payment link where Priya can update her card details. Rule-match certainty: 95%."

"**Step 4 — Check Policy Guards**: We verify no stopping rules apply. It's 2 PM IST — not quiet hours. Amount is under ₹5000 — no high-value approval needed. Only one prior failure — not a repeated pattern. Policy approves execution."

"**Step 5 — Execute**: We create a RecoveryAction record and call Razorpay's payment_link.create API. Here's the real payment link URL..."

**[Copy payment link URL from table, open in new tab]**

"...which opens Razorpay's hosted payment page. Priya clicks this link, enters her new card details, and completes the payment."

**[Show Razorpay test-mode payment page if possible, or describe]**

"**Step 6 — Audit Log**: Every decision point is logged. Let me show you the audit trail..."

**[Expand "Live Audit Trail" panel]**

"You can see timestamped entries: 'Workflow started', 'Action decided: send_update_link', 'Payment link created: plink_XXX', 'Workflow completed'. Complete compliance trail."

---

## 2:30–3:15 — Guardrails: Why They Matter in Fintech

**[Screen: Scroll to "Policy Guardrails" panel]**

"Now let's talk about the four stopping rules that make ChurnGuard safe for production fintech use."

**[Point to first stopped action in table]**

"**Rule 1: Max Retries**. This customer has already been retried 3 times for insufficient funds. Our workflow overrides any further retry attempts and escalates to human review instead. Infinite retry loops damage customer relationships and waste engineering cycles."

**[Point to second stopped action]**

"**Rule 2: Quiet Hours**. This payment link was blocked because it's 10 PM IST. We don't email customers at midnight asking for payment. The action is queued and will execute at 8 AM tomorrow."

**[Point to third stopped action]**

"**Rule 3: High-Value Approval**. This ₹8,000 enterprise transaction exceeds our ₹5,000 auto-approval threshold. No automated action is taken — a human must review and approve before any payment link is sent. This is critical for fraud prevention and compliance."

**[If visible, point to fourth stopped action]**

"**Rule 4: Repeated-Failure Escalation**. This subscription has failed twice in two months. That's a pattern indicating a systemic issue — maybe the customer is unhappy or their business is struggling. We escalate to a human for a personalized outreach rather than continuing automated retries."

"These guardrails aren't just nice-to-have — they're essential for responsible automation in financial services."

---

## 3:15–4:00 — Simulate Payment Success, Show Live Metrics Update

**[Screen: Return to top of dashboard, focus on Key Metrics cards]**

"Right now our recovery rate is 0% because none of the payment links have been clicked yet. In a real deployment, we'd wait for customers to complete payments via Razorpay webhooks."

**[Scroll to "Demo Payment Simulation" section]**

"For demo purposes, I'll simulate a successful payment. This endpoint bypasses the webhook flow and directly marks the action as successful."

**[Click "Simulate Payment ✅" button for first pending action]**

"Watch the metrics update live..."

**[Point to metrics cards as they refresh]**

"- Total Recovered went from 0 to 1
- Recovery Rate jumped from 0% to 4.0%
- ₹ Recovered increased by ₹999"

**[Click 2-3 more simulation buttons rapidly]**

"After simulating 4 payments, we're at 16.0% recovery rate and nearly ₹4,000 recovered. In a real batch run with actual customer payments, these numbers would update automatically via Razorpay webhooks."

**[Show webhook endpoint code briefly if time permits]**

"Our `/webhooks/razorpay` endpoint verifies the webhook signature, finds the matching RecoveryAction by payment_link_id, updates its status to 'success', and flips the Subscription status from 'failed' to 'recovered'. All changes are audit-logged."

---

## 4:00–4:45 — Recap: Full Batch Run Numbers

**[Screen: Back to full dashboard view]**

"Let me recap what we accomplished in this demo:"

**[Gesture to each metric card]**

"- Started with 25 failed subscriptions representing ₹2,58,975 at risk
- Ran batch recovery through our 5-node LangGraph workflow
- Created 4 Razorpay payment links for immediate customer action
- Scheduled 9 workflow retries for transient failures (scheduling logic only - no automatic re-charging)
- Attempted 1 immediate retry (workflow tracking only)
- Escalated 2 cases to human review (max retries + repeated failures)
- Stopped 11 actions due to policy guardrails (quiet hours + high-value)
- Simulated 4 payment successes, recovering ₹3,996"

**[Point to audit trail panel]**

"Every single decision — from failure classification to policy checks to payment link creation — is logged in our audit trail. This isn't just debugging convenience; it's regulatory compliance."

**[Optional: show test count]**

"And we have 55 automated tests covering every node, every policy rule, webhook verification, and batch processing edge cases. Production-ready code."

---

## 4:45–5:00 — Close: What This Demonstrates + Roadmap

**[Screen: Center on dashboard title or logo]**

"ChurnGuard demonstrates that agentic workflows aren't just experimental — they're production-ready solutions for real business problems. Failed subscription revenue doesn't have to be lost. With the right guardrails, AI agents can recover it safely, scalably, and compliantly."

**[Final line, direct to camera]**

"Next steps: extending ChurnGuard to handle checkout-abandonment recovery, adding LLM-based failure classification for nuanced decisions, and migrating to PostgreSQL with async batch processing for enterprise scale. Thank you."

**[End recording]**

---

## Presenter Notes & Tips

### Before Recording

1. **Pre-generate data** so you don't wait during recording. Have the dashboard loaded with 25 failures ready to go.

2. **Test the flow** once or twice to ensure smooth transitions between sections. Know exactly where to scroll.

3. **Have Razorpay dashboard open** in another tab showing test-mode payment links if you want to show the "real" Razorpay side.

4. **Disable notifications** on your machine to avoid popups during recording.

### During Recording

- **Speak clearly and slowly**. It's easy to rush when nervous. Pause briefly after key points.

- **Use your mouse deliberately**. Slow, smooth movements. Don't jitter around the screen.

- **If you mess up**, pause for 3 seconds, then continue. You can edit out mistakes in post.

- **Keep energy up**. Smile when appropriate. Show genuine enthusiasm for the product.

### After Recording

- **Trim dead air** at start/end and between sections.

- **Add captions** if possible — many viewers watch without sound initially.

- **Export at 1080p minimum**. Blurry text on dashboards looks unprofessional.

---

## Backup Talking Points (if you finish early)

### On LangGraph Choice

"We chose LangGraph because it gives us explicit control over the workflow graph while still allowing LLM integration later. Unlike black-box agent frameworks, we can see exactly which node made which decision — crucial for debugging and compliance."

### On Mock vs. Real Razorpay

"By default we use a MockProvider that simulates payment link creation. To switch to real Razorpay, you just set `use_mock=False` and configure your API keys in `.env`. The abstraction layer means zero code changes."

### On Test Coverage

"Our 55 tests include 5 dedicated guardrail tests — one for each stopping rule. We test not just that rules trigger correctly, but also that they *don't* trigger when they shouldn't. False positives block revenue; false negatives risk compliance violations."

### On Scalability

"Current batch processing is sequential by design — simple, debuggable, sufficient for demos. Production deployments would use asyncio.gather() or Celery workers to process hundreds of failures in parallel. The workflow itself is stateless and horizontally scalable."

---

## Common Questions & Answers

**Q: Why rule-based classification instead of LLM?**  
A: "Deterministic rules are auditable and predictable — essential for fintech. An LLM might hallucinate or change behavior between versions. That said, our architecture supports swapping in an LLM node later for hybrid approaches."

**A: "Automatic retry not yet implemented. Use payment links for customer-initiated retries."** For subscription recovery, Razorpay handles automatic retries at the subscription level (T+1, T+2, T+3 days), but these aren't accessible via manual API calls. ChurnGuard's retry actions create workflow tracking records. The real recovery mechanism is the payment link creation where customers can update their card details."

**Q: What happens if Razorpay API is down?**  
A: "The provider abstraction catches exceptions and returns an error state. The workflow logs the failure and marks the action as 'failed' rather than 'pending'. Retry logic would be implemented at the batch level, not within individual workflows."

**Q: Do the retry actions actually retry payments?**  
**Q: How do you handle timezone edge cases for quiet hours?**  
A: "We approximate IST as UTC+5 for simplicity. This could misclassify events around 8:30 AM / 9:30 PM boundaries. Production code would use `pytz` for precise timezone handling. This is listed in our Known Limitations."

**Q: Can this recover checkout abandonments too?**  
A: "Not currently — ChurnGuard focuses exclusively on post-failure renewal recovery per the challenge brief. Checkout recovery is a natural extension: same workflow, different trigger event. It's on our roadmap."

**Q: Why SQLite instead of Postgres?**  
A: "Development simplicity. Zero configuration, single file, works out of the box. Swapping to Postgres requires changing one environment variable (`DATABASE_URL`) and running migrations. We've documented this in Known Limitations."

---

**END OF SCRIPT**
