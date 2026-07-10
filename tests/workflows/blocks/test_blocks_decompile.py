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
