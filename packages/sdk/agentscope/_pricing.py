import json
import os
from typing import Dict, Optional

# Base pricing table (in USD per 1M tokens)
# We support prefix-matching so pinned/versioned variants resolve correctly.
PRICING_TABLE: Dict[str, Dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    "claude-3-opus": {"input": 15.00, "output": 75.00},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
}


def get_model_pricing(model_name: str) -> Optional[dict[str, float]]:
    """Lookup pricing configuration for a given model name, including minor/date-pinned versions."""
    if not model_name:
        return None

    model_name_lower = model_name.lower()
    if model_name_lower in PRICING_TABLE:
        return PRICING_TABLE[model_name_lower]

    for key in sorted(PRICING_TABLE.keys(), key=len, reverse=True):
        if model_name_lower.startswith(f"{key}-"):
            return PRICING_TABLE[key]

    return None


def update_pricing_table(custom_pricing: Dict[str, Dict[str, float]]) -> None:
    """Programmatically update or override the model pricing table.

    Args:
        custom_pricing: Dictionary of model names to dicts containing 'input' and 'output' rates.
    """
    for model_name, rates in custom_pricing.items():
        if "input" in rates and "output" in rates:
            PRICING_TABLE[model_name.lower()] = {
                "input": float(rates["input"]),
                "output": float(rates["output"]),
            }


def _load_env_overrides() -> None:
    """Load custom pricing overrides from AGENTSCOPE_CUSTOM_PRICING environment variable."""
    env_pricing = os.getenv("AGENTSCOPE_CUSTOM_PRICING")
    if env_pricing:
        try:
            custom_pricing = json.loads(env_pricing)
            if isinstance(custom_pricing, dict):
                update_pricing_table(custom_pricing)
        except Exception:
            # Silently ignore parsing errors in environment configurations
            pass


# Automatically load any environment overrides on import
_load_env_overrides()


def calculate_cost(
    model_name: str, prompt_tokens: Optional[int], completion_tokens: Optional[int]
) -> float:
    """Calculate the estimated USD cost of an LLM call.

    Args:
        model_name: The name/identifier of the LLM model.
        prompt_tokens: Number of prompt (input) tokens.
        completion_tokens: Number of completion (output) tokens.

    Returns:
        The estimated cost in USD (float).
    """
    prices = get_model_pricing(model_name)
    if not prices:
        return 0.0

    if prompt_tokens is not None and prompt_tokens < 0:
        raise ValueError("prompt_tokens cannot be negative")
    if completion_tokens is not None and completion_tokens < 0:
        raise ValueError("completion_tokens cannot be negative")

    input_tokens = 0 if prompt_tokens is None else prompt_tokens
    output_tokens = 0 if completion_tokens is None else completion_tokens

    input_cost = (input_tokens / 1_000_000) * prices["input"]
    output_cost = (output_tokens / 1_000_000) * prices["output"]

    return input_cost + output_cost
