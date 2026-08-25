"""
ChurnGuard LangGraph Agents Module

This module contains the LangGraph-based workflow for automated payment recovery.
The workflow analyzes payment failures and decides on appropriate recovery actions.

Architecture:
    FastAPI -> Service Layer -> LangGraph Workflow -> Provider Abstraction -> Persistence

Modules:
    - state: TypedDict definitions for workflow state
    - nodes: Individual workflow nodes (analyze, decide, execute)
    - graph: LangGraph state machine definition
    - provider: Payment provider abstraction (Mock/Razorpay)

Future Enhancement:
    The deterministic nodes (analyze_failure, decide_recovery_action) can be
    replaced or augmented with LLM-based versions without changing the API contract.
"""

from app.agents.state import RecoveryWorkflowState, FailureAnalysisResult, RecoveryDecisionResult
from app.agents.graph import run_recovery_workflow, RecoveryWorkflowRunner, create_recovery_graph
from app.agents.provider import (
    PaymentRecoveryProvider,
    MockPaymentProvider,
    RazorpayProvider,
    get_provider,
)

__all__ = [
    # State types
    "RecoveryWorkflowState",
    "FailureAnalysisResult",
    "RecoveryDecisionResult",
    
    # Graph/Runner
    "run_recovery_workflow",
    "RecoveryWorkflowRunner",
    "create_recovery_graph",
    
    # Providers
    "PaymentRecoveryProvider",
    "MockPaymentProvider",
    "RazorpayProvider",
    "get_provider",
]
