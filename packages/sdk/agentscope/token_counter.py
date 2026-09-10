import math
from typing import Optional


def estimate_tokens(text: Optional[str], model_name: str = "gpt-4o") -> int:
    """Estimate token count for a text string using tiktoken if available.

    Falls back to a character heuristic (~4 chars/token) if tiktoken is
    not installed.

    Args:
        text: The prompt or completion text to tokenize.
        model_name: Name of the model for tiktoken encoding lookup.

    Returns:
        Estimated non-negative integer token count.
    """
    if not text:
        return 0

    try:
        import tiktoken

        try:
            encoding = tiktoken.encoding_for_model(model_name)
        except Exception:
            encoding = tiktoken.get_encoding("cl100k_base")

        return len(encoding.encode(text))
    except (ImportError, Exception):
        # Fallback estimation heuristic: ~4 characters per token
        return max(1, math.ceil(len(text) / 4.0))
