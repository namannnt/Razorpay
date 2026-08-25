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
│   └── synthetic_data.py    # Fake data generator
├── requirements.txt         # Python dependencies
├── .env.example            # Environment variables template
├── README.md               # This file
└── test_setup.py           # Test script
```

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy the example environment file and fill in your Razorpay test credentials:

```bash
cp .env.example .env
```

Edit `.env` with your Razorpay test mode keys from the [Razorpay Dashboard](https://dashboard.razorpay.com/app/keys).

### 3. Generate Synthetic Data

Generate test data with 70 fake subscriptions:

```bash
python -m app.synthetic_data
```

Or use the API endpoint after starting the server:

```bash
POST http://localhost:8000/generate-data
```

### 4. Run the Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Test the Setup

Run the test script to verify everything works:

```bash
pytest test_setup.py -v
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

## Database Models

- **Subscription**: Customer subscription records with status tracking
- **FailureEvent**: Payment failure events with failure codes
- **RecoveryAction**: Recovery attempts and their outcomes
- **AuditLog**: System audit trail

## Next Steps

This skeleton is ready for LangGraph agent integration. The business logic is separated into `services.py` which can be called by LangGraph nodes for:

- Analyzing failure patterns
- Deciding recovery strategies
- Executing Razorpay payment link operations
- Tracking recovery outcomes

## License

MIT
