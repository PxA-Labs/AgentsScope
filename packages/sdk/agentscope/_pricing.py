import json
import os
from pathlib import Path
from typing import Optional

# Keep an embedded fallback so the SDK remains usable when installed outside the
# monorepo or when the canonical repository file is unavailable.
_DEFAULT_PRICING_JSON = """
{
  "gpt-4o": {"input": 2.5, "output": 10.0},
  "gpt-4o-mini": {"input": 0.15, "output": 0.6},
  "gpt-4-turbo": {"input": 10.0, "output": 30.0},
  "gpt-4": {"input": 30.0, "output": 60.0},
  "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
  "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
  "claude-3-haiku": {"input": 0.25, "output": 1.25},
  "claude-3-opus": {"input": 15.0, "output": 75.0},
  "gemini-1.5-pro": {"input": 1.25, "output": 5.0},
  "gemini-1.5-flash": {"input": 0.075, "output": 0.3}
}
"""


def _normalise_pricing(pricing: object) -> dict[str, dict[str, float]]:
    if not isinstance(pricing, dict):
        raise ValueError("Pricing configuration must be a JSON object")

    normalised: dict[str, dict[str, float]] = {}
    for model_name, rates in pricing.items():
        if not isinstance(model_name, str) or not isinstance(rates, dict):
            raise ValueError("Pricing entries must map model names to rate objects")
        if "input" not in rates or "output" not in rates:
            raise ValueError(f"Pricing entry for {model_name!r} is incomplete")
        normalised[model_name.lower()] = {
            "input": float(rates["input"]),
            "output": float(rates["output"]),
        }
    return normalised


def _load_pricing_table() -> dict[str, dict[str, float]]:
    configured_path = os.getenv("AGENTSCOPE_PRICING_FILE")
    candidate_paths = []
    if configured_path:
        candidate_paths.append(Path(configured_path))
    # Prefer package data for normal wheel installations. The repository-level
    # file remains the editable-monorepo source, and the embedded fallback keeps
    # damaged or minimal installations operational.
    candidate_paths.append(Path(__file__).resolve().parent / "pricing.json")
    candidate_paths.append(Path(__file__).resolve().parents[2] / ".." / "pricing.json")

    for path in candidate_paths:
        try:
            return _normalise_pricing(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue

    return _normalise_pricing(json.loads(_DEFAULT_PRICING_JSON))


# Base pricing table in USD per 1M tokens. Exact model entries are checked
# before prefix-matching pinned or provider-prefixed model identifiers.
PRICING_TABLE = _load_pricing_table()


def get_model_pricing(model_name: str) -> Optional[dict[str, float]]:
    """Lookup pricing for a model, including provider- and version-pinned names."""
    if not model_name:
        return None

    model_name_lower = model_name.lower()
    if "/" in model_name_lower:
        model_name_lower = model_name_lower.split("/")[-1]

    if model_name_lower in PRICING_TABLE:
        return PRICING_TABLE[model_name_lower]

    for key in sorted(PRICING_TABLE.keys(), key=len, reverse=True):
        if model_name_lower.startswith(f"{key}-"):
            return PRICING_TABLE[key]

    return None


def update_pricing_table(custom_pricing: dict[str, dict[str, float]]) -> None:
    """Update or override model pricing rates programmatically."""
    for model_name, rates in custom_pricing.items():
        if "input" in rates and "output" in rates:
            PRICING_TABLE[model_name.lower()] = {
                "input": float(rates["input"]),
                "output": float(rates["output"]),
            }


def _load_env_overrides() -> None:
    """Load JSON overrides from ``AGENTSCOPE_CUSTOM_PRICING`` if configured."""
    env_pricing = os.getenv("AGENTSCOPE_CUSTOM_PRICING")
    if env_pricing:
        try:
            custom_pricing = json.loads(env_pricing)
            if isinstance(custom_pricing, dict):
                update_pricing_table(custom_pricing)
        except (TypeError, ValueError, json.JSONDecodeError):
            # Invalid environment configuration must not break SDK imports.
            pass


# Automatically load environment overrides on import.
_load_env_overrides()


def calculate_cost(
    model_name: str, prompt_tokens: Optional[int], completion_tokens: Optional[int]
) -> float:
    """Calculate the estimated USD cost of an LLM call."""
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
