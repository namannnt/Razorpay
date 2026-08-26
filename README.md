# ChurnGuard

AI agent that recovers failed subscription payments using Razorpay's test-mode APIs.

## Project Structure

```
/workspace
├── app/
│   ├── main.py              # FastAPI application entrypoint
│   ├── database.py          # Database configuration and models
│   ├── schemas.py           # Pydantic schemas for validation
│   ├── services.py          # Business logic layer (for LangGraph integration)
│   ├── dashboard.py         # Streamlit dashboard (runs separately)
│   └── synthetic_data.py    # Fake data generator
├── requirements-backend.txt     # Backend dependencies (FastAPI, uvicorn, etc.)
├── requirements-dashboard.txt   # Dashboard dependencies (Streamlit only)
├── .env.example            # Environment variables template
├── README.md               # This file
└── test_setup.py           # Test script
```

## Setup Instructions

The backend (FastAPI) and dashboard (Streamlit) run as separate processes and should be installed in separate virtual environments to avoid dependency conflicts.

### Backend Setup

1. Create and activate a virtual environment for the backend:

```bash
python -m venv venv-backend
source venv-backend/bin/activate  # On Windows: venv-backend\Scripts\activate
```

2. Install backend dependencies:

```bash
pip install -r requirements-backend.txt
```

3. Configure Environment Variables:

Copy the example environment file and fill in your Razorpay test credentials:

```bash
cp .env.example .env
```

Edit `.env` with your Razorpay test mode keys from the [Razorpay Dashboard](https://dashboard.razorpay.com/app/keys).

4. Generate Synthetic Data:

Generate test data with 70 fake subscriptions:

```bash
python -m app.synthetic_data
```

Or use the API endpoint after starting the server:

```bash
POST http://localhost:8000/generate-data
```

5. Run the Backend Server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Dashboard Setup

1. In a **separate terminal**, create and activate a virtual environment for the dashboard:

```bash
python -m venv venv-dashboard
source venv-dashboard/bin/activate  # On Windows: venv-dashboard\Scripts\activate
```

2. Install dashboard dependencies:

```bash
pip install -r requirements-dashboard.txt
```

3. Run the Streamlit Dashboard:

Make sure the backend server is running first, then:

```bash
streamlit run app/dashboard.py
```

The dashboard will open in your browser at `http://localhost:8501` and connect to the backend at `http://localhost:8000`.

### Testing

Run the test scripts to verify everything works:

```bash
# In the backend virtualenv
pytest test_setup.py -v
pytest test_agents.py -v
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/subscriptions` | List all subscriptions |
| GET | `/subscriptions/{id}` | Get subscription details with failure events and recovery actions |
| GET | `/failures` | List all failure events |
| POST | `/generate-data` | Generate synthetic test data |
| GET | `/audit-log` | List audit log entries |
| POST | `/recovery/run-batch` | Run batch recovery for all pending subscriptions |
| GET | `/metrics/summary` | Get summary metrics (failed, recovered, amounts, recovery rate) |
| POST | `/demo/simulate-payment/{id}` | DEMO ONLY: Simulate payment success for a recovery action |

## Database Models

- **Subscription**: Customer subscription records with status tracking
- **FailureEvent**: Payment failure events with failure codes
- **RecoveryAction**: Recovery attempts and their outcomes
- **AuditLog**: System audit trail

## Dashboard Features

The Streamlit dashboard provides:

- **Control Panel**: Generate synthetic data and run batch recovery
- **Metrics Cards**: Total failed subscriptions, recovery rate, ₹ at risk, ₹ recovered, escalated to human
- **Failure Breakdown Chart**: Bar chart of failure code distribution
- **Recovery Action Outcomes Table**: Color-coded status table with payment links
- **Demo Payment Simulation**: Simulate customer payments for demo purposes
- **Policy Stops Panel**: Shows actions stopped by policy rules (guardrails demonstration)
- **Live Audit Trail**: Expandable section with recent audit log entries

## Next Steps

This skeleton is ready for LangGraph agent integration. The business logic is separated into `services.py` which can be called by LangGraph nodes for:

- Analyzing failure patterns
- Deciding recovery strategies
- Executing Razorpay payment link operations
- Tracking recovery outcomes

## License

MIT
