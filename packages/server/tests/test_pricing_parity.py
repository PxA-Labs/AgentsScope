import json
from pathlib import Path

import pytest
from pricing import PRICING_TABLE, calculate_cost, get_model_pricing


@pytest.fixture(scope="module")
def canonical_pricing():
    path = Path(__file__).resolve().parents[3] / "pricing.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_server_pricing_matches_canonical_file(canonical_pricing):
    assert PRICING_TABLE == canonical_pricing


def test_exact_model_entries_take_precedence_over_prefix_matching():
    assert get_model_pricing("gpt-4o-mini") == {"input": 0.15, "output": 0.6}
    assert get_model_pricing("gpt-4-turbo") == {"input": 10.0, "output": 30.0}


def test_provider_and_version_pinned_models_use_their_exact_base_rate():
    assert get_model_pricing("openai/gpt-4o-mini-2024-07-18") == {
        "input": 0.15,
        "output": 0.6,
    }
    assert get_model_pricing("openai/gpt-4-turbo-2024-04-09") == {
        "input": 10.0,
        "output": 30.0,
    }


def test_cost_estimates_match_sdk_rates_for_affected_models():
    assert calculate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == pytest.approx(0.75)
    assert calculate_cost("gpt-4-turbo", 1_000_000, 1_000_000) == pytest.approx(40.0)
