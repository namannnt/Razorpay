"""
LangGraph workflow graph for ChurnGuard payment recovery.

Defines the state machine with nodes and conditional edges:

    [Start] -> load_data -> analyze_failure -> decide_recovery_action
                                              |
                    +-------------------------+-------------------------+
                    |                         |                         |
                    v                         v                         v
            [retry_now/           [send_update_link]          [retry_after_24h/
             retry_after_24h]                                  escalate]
                    |                         |                         |
                    +-------------------------+-------------------------+
                                              |
                                              v
                                      execute_recovery_action
                                              |
                                              v
                                        log_workflow_completion
                                              |
                                              v
                                           [END]
"""
from typing import Literal
from datetime import datetime
from sqlalchemy.orm import Session

from langgraph.graph import StateGraph, END
from app.agents.state import RecoveryWorkflowState
from app.agents.nodes import (
    load_subscription_data,
    analyze_failure,
    decide_recovery_action,
    check_policy_guards,
    execute_recovery_action,
    log_workflow_completion,
)


def create_recovery_graph() -> StateGraph:
    """
    Create and configure the LangGraph workflow for payment recovery.
    
    Returns an uncompiled StateGraph that can be compiled with checkpointer.
    """
    # Define the graph with our state type
    workflow = StateGraph(RecoveryWorkflowState)
    
    # Add all nodes
    workflow.add_node("load_data", lambda state: _wrap_node(load_subscription_data, state))
    workflow.add_node("analyze_failure", lambda state: _wrap_node(analyze_failure, state))
    workflow.add_node("decide_recovery_action", lambda state: _wrap_node(decide_recovery_action, state))
    workflow.add_node("check_policy_guards", lambda state: _wrap_node(check_policy_guards, state))
    workflow.add_node("execute_recovery_action", lambda state: _wrap_node(execute_recovery_action, state))
    workflow.add_node("log_completion", lambda state: _wrap_node(log_workflow_completion, state))
    
    # Set entry point
    workflow.set_entry_point("load_data")
    
    # Define sequential edges
    workflow.add_edge("load_data", "analyze_failure")
    workflow.add_edge("analyze_failure", "decide_recovery_action")
    workflow.add_edge("decide_recovery_action", "check_policy_guards")
    
    # Conditional routing after policy check
    workflow.add_conditional_edges(
        "check_policy_guards",
        _route_after_policy_check,
        {
            "execute": "execute_recovery_action",
            "skip_to_audit": "log_completion"
        }
    )
    
    workflow.add_edge("execute_recovery_action", "log_completion")
    
    # End after logging
    workflow.add_edge("log_completion", END)
    
    return workflow


def _route_after_policy_check(state: RecoveryWorkflowState) -> str:
    """
    Conditional routing function after policy check node.
    
    If policy_approved is True, route to execute_recovery_action.
    If policy_approved is False (stopped by rule), route directly to log_completion.
    """
    policy_approved = state.get("policy_approved", True)
    
    if policy_approved:
        return "execute"
    else:
        return "skip_to_audit"


def _wrap_node(node_func, state):
    """
    Wrapper to inject DB session into node functions.
    
    Nodes can optionally accept a db parameter. This wrapper handles both cases.
    """
    from app.database import SessionLocal
    
    # Check if node function accepts db parameter
    import inspect
    sig = inspect.signature(node_func)
    params = list(sig.parameters.keys())
    
    if len(params) >= 2 and params[1] == 'db':
        # Node accepts db parameter
        db = SessionLocal()
        try:
            result = node_func(state, db)
            return result
        finally:
            db.close()
    else:
        # Node only takes state
        return node_func(state)


class RecoveryWorkflowRunner:
    """
    High-level runner for the recovery workflow.
    
    Provides a simple interface to execute the workflow for a given failure event.
    Handles DB sessions, error handling, and result formatting.
    """
    
    def __init__(self, use_compiled: bool = True):
        self.graph_builder = create_recovery_graph()
        self._compiled_graph = None
        if use_compiled:
            self._compiled_graph = self.graph_builder.compile()
    
    def run(self, failure_event_id: int) -> dict:
        """
        Execute the recovery workflow for a given failure event.
        
        Args:
            failure_event_id: ID of the failure event to process
            
        Returns:
            dict containing workflow results including:
            - success: bool
            - action_taken: str
            - reason: str
            - is_simulated: bool
            - error: Optional[str]
            - audit_log_ids: List[int]
        """
        from app.database import SessionLocal
        
        db = SessionLocal()
        try:
            # Initialize state
            initial_state = RecoveryWorkflowState(
                subscription_id=None,
                failure_event_id=failure_event_id,
                recovery_action_id=None,
                customer_name=None,
                customer_email=None,
                plan_name=None,
                amount=None,
                currency=None,
                subscription_status=None,
                failure_code=None,
                retry_count=None,
                failure_occurred_at=None,
                failure_analysis=None,
                failure_category=None,
                recovery_implications=None,
                recommended_action_type=None,
                action_reason=None,
                confidence_score=None,
                razorpay_payment_link_id=None,
                action_status=None,
                execution_result=None,
                error_message=None,
                is_simulated=True,
                workflow_started_at=datetime.utcnow(),
                workflow_completed_at=None,
                audit_log_ids=[],
            )
            
            # Run workflow
            if self._compiled_graph:
                final_state = self._compiled_graph.invoke(initial_state)
            else:
                # Use uncompiled graph with manual node execution
                final_state = self._run_manual(initial_state, db)
            
            # Format response
            return self._format_response(final_state)
            
        except Exception as e:
            return {
                "success": False,
                "action_taken": None,
                "reason": None,
                "is_simulated": True,
                "error": str(e),
                "audit_log_ids": [],
            }
        finally:
            db.close()
    
    def _run_manual(self, state: RecoveryWorkflowState, db: Session) -> RecoveryWorkflowState:
        """Run workflow manually without compiled graph (for testing/debugging)."""
        state = load_subscription_data(state, db)
        if state.get("error_message"):
            return log_workflow_completion(state, db)
        
        state = analyze_failure(state, db)
        state = decide_recovery_action(state, db)
        state = execute_recovery_action(state, db)
        state = log_workflow_completion(state, db)
        
        return state
    
    def _format_response(self, state: RecoveryWorkflowState) -> dict:
        """Format workflow state into API response."""
        error = state.get("error_message")
        
        return {
            "success": error is None,
            "failure_event_id": state.get("failure_event_id"),
            "subscription_id": state.get("subscription_id"),
            "recovery_action_id": state.get("recovery_action_id"),
            "action_taken": state.get("recommended_action_type"),
            "reason": state.get("action_reason"),
            "confidence": state.get("confidence_score"),
            "failure_category": state.get("failure_category"),
            "failure_analysis": state.get("failure_analysis"),
            "razorpay_payment_link_id": state.get("razorpay_payment_link_id"),
            "action_status": state.get("action_status"),
            "is_simulated": state.get("is_simulated", True),
            "error": error,
            "audit_log_ids": state.get("audit_log_ids", []),
            "workflow_started_at": state.get("workflow_started_at"),
            "workflow_completed_at": state.get("workflow_completed_at"),
        }


# Convenience function for API layer
def run_recovery_workflow(failure_event_id: int) -> dict:
    """
    Run the recovery workflow for a failure event.
    
    This is the main entry point called from the API endpoint.
    
    Args:
        failure_event_id: ID of the failure event to process
        
    Returns:
        dict with workflow results
    """
    runner = RecoveryWorkflowRunner(use_compiled=False)  # Manual mode for simplicity
    return runner.run(failure_event_id)
