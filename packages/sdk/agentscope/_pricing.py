# Hardcoded token pricing table for LLM cost estimation
# Prices are represented in USD per 1,000,000 (1M) tokens.

PRICING_TABLE = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
}


def calculate_cost(
    model_name: str, prompt_tokens: int | None, completion_tokens: int | None
) -> float:
    """Calculate the estimated USD cost of an LLM call.

    Args:
        model_name: The name of the LLM model used.
        prompt_tokens: Number of prompt (input) tokens.
        completion_tokens: Number of completion (output) tokens.

    Returns:
        The estimated cost in USD (float).
    """
    if not model_name or model_name not in PRICING_TABLE:
        return 0.0

    prices = PRICING_TABLE[model_name]
    input_tokens = prompt_tokens or 0
    output_tokens = completion_tokens or 0

    input_cost = (input_tokens / 1_000_000) * prices["input"]
    output_cost = (output_tokens / 1_000_000) * prices["output"]

    return input_cost + output_cost
