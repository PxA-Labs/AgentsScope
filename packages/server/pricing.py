import json
import os
from pathlib import Path

# Keep an embedded fallback so the server remains self-contained in its Docker
# image, where the repository-level pricing file is not copied into the image.
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
        raise TypeError("Pricing configuration must be a JSON object")

    normalised: dict[str, dict[str, float]] = {}
    for model_name, rates in pricing.items():
        if not isinstance(model_name, str) or not isinstance(rates, dict):
            raise TypeError("Pricing entries must map model names to rate objects")
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
    # The repository-level file is the canonical source while developing from
    # the monorepo. The embedded fallback is used by the standalone image.
    candidate_paths.append(Path(__file__).resolve().parents[2] / "pricing.json")

    for path in candidate_paths:
        try:
            return _normalise_pricing(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue

    return _normalise_pricing(json.loads(_DEFAULT_PRICING_JSON))


# Base pricing table in USD per 1M tokens. Exact model entries are checked
# before prefix-matching pinned or provider-prefixed model identifiers.
PRICING_TABLE = _load_pricing_table()


def get_model_pricing(model_name: str) -> dict[str, float] | None:
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


def calculate_cost(
    model_name: str, prompt_tokens: int | None, completion_tokens: int | None
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
