class AgentScopeError(Exception):
    """Base exception for AgentScope SDK."""

    pass


class BudgetExceededError(AgentScopeError):
    """Raised when an agent execution session exceeds its USD budget limit."""

    pass
