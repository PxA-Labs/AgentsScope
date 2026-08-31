import os

import pytest

from agentscope import _pricing


@pytest.fixture(autouse=True)
def isolate_pricing_state():
    original_table = {
        name: rates.copy() for name, rates in _pricing.PRICING_TABLE.items()
    }
    original_env = os.environ.get("AGENTSCOPE_CUSTOM_PRICING")
    yield
    _pricing.PRICING_TABLE.clear()
    _pricing.PRICING_TABLE.update(
        {name: rates.copy() for name, rates in original_table.items()}
    )
    if original_env is None:
        os.environ.pop("AGENTSCOPE_CUSTOM_PRICING", None)
    else:
        os.environ["AGENTSCOPE_CUSTOM_PRICING"] = original_env
