"""Round-trip test for ``blocks/decompile.py`` (blocks-graph-plan.md §4, Order 7).

For every *runnable* ``examples/*.json`` scenario-config document:

    normalize(compile_graph(graph_from_config(cfg))) == normalize(cfg)

"Runnable" excludes the two request-payload wrappers that are a different
document shape entirely (``{"config": {...}, "sweeps"/"observed_prices": ...}``
consumed by ``ets.analysis.batch``/``ets.analysis.calibration`` — not
``ets.config_io``): ``k_ets_batch_eua_sweep.json`` and
``k_ets_calibration_request.json``.

Every remaining example round-trips exactly (no xfails needed): unknown
pass-through keys config_io tolerates but no block owns (documented-inert
``international_offset_*``, stray ``_comment`` fields) round-trip through the
generic ``_extra``/``_scenario_extra``/``_year_extra`` opaque-passthrough
mechanism in ``compile.py``/``decompile.py`` rather than being dropped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ets.blocks import compile_graph, graph_from_config
from ets.config_io import normalize_config

EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples"

# These two carry a request-payload document shape, not a scenario config —
# config_io.normalize_config cannot even parse them (no top-level "scenarios").
NOT_SCENARIO_DOCS = {"k_ets_batch_eua_sweep", "k_ets_calibration_request"}

RUNNABLE_EXAMPLES = sorted(
    p.stem for p in EXAMPLES_DIR.glob("*.json") if p.stem not in NOT_SCENARIO_DOCS
)


def test_runnable_examples_is_nonempty() -> None:
    assert len(RUNNABLE_EXAMPLES) >= 25


@pytest.mark.parametrize("stem", RUNNABLE_EXAMPLES)
def test_decompile_compile_round_trip(stem: str) -> None:
    raw = json.loads((EXAMPLES_DIR / f"{stem}.json").read_text())
    expected = normalize_config(raw)
    graph = graph_from_config(raw)
    actual = compile_graph(graph)
    assert actual == expected


def test_graph_from_config_meta_is_present_and_empty() -> None:
    raw = json.loads((EXAMPLES_DIR / "climate_solutions_basic_linear.json").read_text())
    graph = graph_from_config(raw)
    assert graph.meta == {}


def test_graph_from_config_assigns_stable_node_ids() -> None:
    raw = json.loads((EXAMPLES_DIR / "climate_solutions_basic_linear.json").read_text())
    graph = graph_from_config(raw)
    ids = [n.id for n in graph.nodes]
    assert len(ids) == len(set(ids)), "node ids must be unique"


def test_multi_scenario_example_yields_one_market_node_per_scenario() -> None:
    raw = json.loads((EXAMPLES_DIR / "k_msr_compare_suite.json").read_text())
    graph = graph_from_config(raw)
    market_nodes = [n for n in graph.nodes if n.block == "carbon_market"]
    assert len(market_nodes) == len(raw["scenarios"])


def test_decompile_compile_round_trip_endogenous_investment() -> None:
    """Hand-built config (EI-6, docs/invest-feedback-plan.md D4) — not an
    examples/*.json fixture (that pool is owned by a concurrent work order):
    the master flag, a safety-rail override, a credibility override, and one
    flagged technology option must all survive
    normalize -> decompile -> compile -> normalize unchanged. The
    ``endogenous_investment`` node is synthesised (investment_feedback_enabled
    is truthy) and the flagged option round-trips as an opaque
    ``investment_trigger`` sub-dict on the participant's ``technology_options``
    (the same scope-reduction ``sector``/``technology_option`` nodes get)."""
    raw = {
        "scenarios": [
            {
                "name": "Investment Feedback",
                "model_approach": "competitive",
                "investment_feedback_enabled": True,
                "investment_max_iterations": 3,
                "invest_credibility": 0.5,
                "years": [
                    {
                        "year": "2026",
                        "total_cap": 100.0,
                        "auction_mode": "explicit",
                        "auction_offered": 50.0,
                        "participants": [
                            {
                                "name": "Steel",
                                "initial_emissions": 100.0,
                                "penalty_price": 1000.0,
                                "max_abatement": 20.0,
                                "cost_slope": 2.0,
                                "technology_options": [
                                    {
                                        "name": "H2-DRI",
                                        "initial_emissions": 40.0,
                                        "max_abatement": 40.0,
                                        "cost_slope": 2.0,
                                        "max_activity_share": 0.5,
                                        "investment_trigger": {
                                            "break_even_price": 80.0,
                                            "payout_yield": 0.03,
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    expected = normalize_config(raw)
    graph = graph_from_config(raw)
    investment_nodes = [n for n in graph.nodes if n.block == "endogenous_investment"]
    assert len(investment_nodes) == 1
    assert investment_nodes[0].params == {
        "investment_max_iterations": 3,
        "invest_credibility": 0.5,
    }
    actual = compile_graph(graph)
    assert actual == expected
