"""Catalogue-drift guard (blocks-graph-plan.md §4, Order 5).

Every ``ParamSpec.config_key`` must appear in the normalised config_io
document its ``scope`` claims:

* ``scope == "scenario"``  -> ``normalize_scenario(blank_scenario())``
* ``scope == "year"``      -> ``normalize_year(blank_year_config())``
* ``scope == "participant"`` -> ``normalize_participant(blank_participant())``
  **or** ``normalize_technology_option(blank_technology_option(), ...)`` —
  ``technology_option`` blocks share the participant scope but a structurally
  distinct blank template (``fixed_cost``, ``max_activity_share``); checking
  against the union keeps both families of block honest without inventing a
  fifth scope.
* ``scope == "edge"`` is exempt by design: it marks block-local metadata that
  never lands in a scenario config (analysis-block request payloads).

This is the drift guard: rename or remove a config_io field and this test
fails immediately instead of the catalogue silently pointing at a dead key.
"""

from __future__ import annotations

import pytest

from pe.blocks import BLOCK_CATALOGUE
from pe.config_io import (
    blank_participant,
    blank_scenario,
    blank_technology_option,
    blank_year_config,
    normalize_participant,
    normalize_scenario,
    normalize_technology_option,
    normalize_year,
)

# D1 vocabulary keys (docs/platform-spec-d0-d1.md §5/§6: "default absent" —
# an absent key means today's carbon labels, never an injected default
# value, so `normalize_scenario(blank_scenario())` alone never carries them.
# Union in a scenario that actually SETS price_unit so the drift guard stays
# meaningful for it too (catalogue.py's carbon_market.price_unit ParamSpec).
SCENARIO_KEYS = set(normalize_scenario(blank_scenario())) | set(
    normalize_scenario({**blank_scenario(), "price_unit": "USD/tCO2e"})
)
YEAR_KEYS = set(normalize_year(blank_year_config()))
PARTICIPANT_KEYS = set(normalize_participant(blank_participant())) | set(
    normalize_technology_option(blank_technology_option(), "probe")
)


def _all_params():
    for block in BLOCK_CATALOGUE:
        for param in block.params:
            yield block, param


@pytest.mark.parametrize(
    "block_id,param_name",
    [(b.id, p.name) for b, p in _all_params()],
)
def test_param_config_key_exists_in_normalised_document(block_id: str, param_name: str) -> None:
    block = BLOCK_CATALOGUE.get(block_id)
    param = block.param(param_name)
    assert param is not None
    if param.scope == "scenario":
        assert param.config_key in SCENARIO_KEYS, (
            f"{block_id}.{param_name}: config_key '{param.config_key}' not in "
            "normalize_scenario(blank_scenario())"
        )
    elif param.scope == "year":
        assert param.config_key in YEAR_KEYS, (
            f"{block_id}.{param_name}: config_key '{param.config_key}' not in "
            "normalize_year(blank_year_config())"
        )
    elif param.scope == "participant":
        assert param.config_key in PARTICIPANT_KEYS, (
            f"{block_id}.{param_name}: config_key '{param.config_key}' not in "
            "normalize_participant/normalize_technology_option blank output"
        )
    else:
        assert param.scope == "edge", f"unexpected scope {param.scope!r}"


def test_catalogue_covers_every_block_in_plan() -> None:
    expected_ids = {
        "carbon_market",
        "market_link",
        "competitive_clearing",
        "rubin_schennach_banking",
        "hotelling",
        "nash_cournot",
        "forward_transmission",
        "msr_bank_threshold",
        "kmsr_decree",
        "endogenous_investment",
        "ccr",
        "price_floor",
        "price_ceiling",
        "auction_reserve",
        "cancellation",
        "cap_path",
        "free_allocation_phaseout",
        "oba",
        "cbam",
        "hoarding",
        "expectations",
        "price_elastic_baseline",
        "participant",
        "technology_option",
        "sector",
        "batch_sweep",
        "calibration",
        "narrative",
        "investment_trigger",
        "external_feedback",
    }
    assert set(BLOCK_CATALOGUE.ids()) == expected_ids
    assert "compare_all" not in BLOCK_CATALOGUE


def test_no_duplicate_block_ids() -> None:
    ids = BLOCK_CATALOGUE.ids()
    assert len(ids) == len(set(ids))


def test_every_block_has_at_least_one_port_or_is_analysis() -> None:
    for block in BLOCK_CATALOGUE:
        assert block.ports, f"{block.id} declares no ports"
