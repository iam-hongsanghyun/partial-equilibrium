"""``ets.blocks.manifest.derive_manifest`` — the model-manifest API (WO-M1).

Covers:
  (a) ``derive_manifest`` succeeds for every *runnable* ``examples/*.json``
      (same exclusion as ``test_blocks_decompile.py``: the two
      request-payload wrappers aren't scenario-config documents at all) and
      every result's ``"features"`` includes ``"core"``.
  (b) Snapshot assertions for a handful of examples, verified against the
      actual derived manifest rather than assumed (see the
      ``k_msr_P1_draft_decree`` case: despite the "K-MSR" name, it declares
      no MSR/CCR/banking block at all).
  (c) Vocabulary test: every ``BlockSpec.feature`` is drawn from a frozen
      literal vocabulary (core + the feature names + the workflow ids from
      the catalogue-mapping table) — re-point this at ``ets.features.*``
      once that tree lands (feature-modules-plan.md, later restructure
      orders; it does not exist yet).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ets.blocks import BLOCK_CATALOGUE, derive_manifest

EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples"

# Same exclusion as tests/test_blocks_decompile.py: these two carry a
# request-payload document shape (`{"config": {...}, "sweeps"/"observed_prices": ...}`),
# not a scenario config — config_io.normalize_config (and therefore
# derive_manifest) cannot parse them at all (no top-level "scenarios").
NOT_SCENARIO_DOCS = {"k_ets_batch_eua_sweep", "k_ets_calibration_request"}

RUNNABLE_EXAMPLES = sorted(
    p.stem for p in EXAMPLES_DIR.glob("*.json") if p.stem not in NOT_SCENARIO_DOCS
)


def _load(stem: str) -> dict:
    return json.loads((EXAMPLES_DIR / f"{stem}.json").read_text())


def test_runnable_examples_is_nonempty() -> None:
    assert len(RUNNABLE_EXAMPLES) >= 25


# ── (a) derive_manifest succeeds for every runnable example ─────────────


@pytest.mark.parametrize("stem", RUNNABLE_EXAMPLES)
def test_derive_manifest_succeeds_and_contains_core(stem: str) -> None:
    manifest = derive_manifest(_load(stem))
    assert "core" in manifest["features"]
    assert isinstance(manifest["blocks"], list) and manifest["blocks"]
    assert isinstance(manifest["approach"], list) and manifest["approach"]
    assert isinstance(manifest["categories"], dict)
    assert isinstance(manifest["scenarios"], dict) and manifest["scenarios"]
    for scenario_manifest in manifest["scenarios"].values():
        assert "core" in scenario_manifest["features"]
        assert scenario_manifest["approach"]


def test_manifest_shape_has_exactly_the_five_top_level_keys() -> None:
    manifest = derive_manifest(_load("climate_solutions_basic_linear"))
    assert set(manifest.keys()) == {"features", "blocks", "approach", "categories", "scenarios"}


def test_manifest_blocks_are_sorted_and_unique() -> None:
    manifest = derive_manifest(_load("climate_solutions_cbam_exposure"))
    assert manifest["blocks"] == sorted(set(manifest["blocks"]))


def test_manifest_categories_partition_blocks() -> None:
    manifest = derive_manifest(_load("k_msr_P1_decree_banking"))
    flattened = sorted(b for blocks in manifest["categories"].values() for b in blocks)
    assert flattened == manifest["blocks"]
    for block_id in manifest["blocks"]:
        category = BLOCK_CATALOGUE.get(block_id).category
        assert block_id in manifest["categories"][category]


# ── (b) snapshot assertions ───────────────────────────────────────────


def test_basic_linear_features() -> None:
    """Ground-truthed against the actual example, not assumed: the scenario
    overrides ``price_upper_bound`` to 250.0 (default 100.0 —
    ``catalogue.py``'s ``price_ceiling`` block), so ``price_controls`` is
    genuinely active alongside ``core``/``competitive``."""
    manifest = derive_manifest(_load("climate_solutions_basic_linear"))
    assert set(manifest["features"]) == {"core", "competitive", "price_controls"}
    assert manifest["approach"] == ["competitive"]


def test_msr_stability_includes_msr() -> None:
    manifest = derive_manifest(_load("climate_solutions_msr_stability"))
    assert {"msr"} <= set(manifest["features"])
    # Per-scenario breakdown: only the "With MSR" scenario actually uses it.
    assert "msr" not in manifest["scenarios"]["Without MSR"]["features"]
    assert "msr" in manifest["scenarios"]["With MSR"]["features"]


def test_cbam_exposure_includes_cbam() -> None:
    manifest = derive_manifest(_load("climate_solutions_cbam_exposure"))
    assert {"cbam"} <= set(manifest["features"])


def test_k_msr_p1_draft_decree_is_plain_competitive() -> None:
    """Despite its "K-MSR" name, this scenario sets no msr_enabled/ccr_enabled
    and uses model_approach='competitive' — no MSR, CCR, or banking block
    anywhere in the config (verified against the raw JSON, not assumed from
    the filename). It does tag every participant with a sector_group (Steel,
    Petrochem, Power, Cement, Refinery, Other), so the ``sectors`` direct
    detector (``ets.blocks.manifest._direct_detectors``) genuinely fires even
    though the scenario defines no ``sectors[]`` cap-pool table."""
    manifest = derive_manifest(_load("k_msr_P1_draft_decree"))
    assert set(manifest["features"]) == {"core", "competitive", "price_controls", "sectors"}
    assert manifest["approach"] == ["competitive"]
    assert "msr" not in manifest["features"]
    assert "banking" not in manifest["features"]
    assert "ccr" not in manifest["features"]


def test_k_msr_p1_decree_banking_includes_banking_and_msr() -> None:
    manifest = derive_manifest(_load("k_msr_P1_decree_banking"))
    assert {"banking", "msr"} <= set(manifest["features"])
    assert manifest["approach"] == ["banking"]


def test_k_msr_event_timing_2x2_includes_policy_events() -> None:
    manifest = derive_manifest(_load("k_msr_event_timing_2x2"))
    assert {"policy_events"} <= set(manifest["features"])
    # Only the two "announced 2031" scenarios actually carry a policy_events
    # entry — the "announced 2026" pair applies its change to the base
    # config directly (see the example's own "experiment" description).
    assert "policy_events" not in manifest["scenarios"]["banking / announced 2026"]["features"]
    assert "policy_events" in manifest["scenarios"]["banking / announced 2031"]["features"]
    assert "policy_events" not in manifest["scenarios"]["static / announced 2026"]["features"]
    assert "policy_events" in manifest["scenarios"]["static / announced 2031"]["features"]


# ── (b′) snapshots for the gap-filling examples (examples work order) ──
# Each asserts the EXACT intended feature set, ground-truthed against the
# derived manifest at authoring time.


def test_msr_ccr_combined_has_both_supply_operators() -> None:
    """First golden-scale example with MSR and CCR active on ONE competitive
    scenario — valid since the F1 fix (blocks-composition-rules.md §0, R10
    downgraded); unit anchor in tests/test_msr_ccr_composition.py."""
    manifest = derive_manifest(_load("k_ets_msr_ccr_combined"))
    assert set(manifest["features"]) == {"core", "competitive", "msr", "ccr", "price_controls"}
    assert manifest["approach"] == ["competitive"]


def test_lambda_msr_composes_transmission_with_msr() -> None:
    """λ overlay + bank-threshold MSR: the pf block is forward_transmission
    (feature 'transmission', NOT 'competitive' — same as k_msr_lambda_regimes)
    and the MSR node rides inside the competitive component. Every
    participant also carries a sector_group tag (Power/Steel/Cement), so
    ``sectors`` is genuinely active per the direct detector even with no
    ``sectors[]`` cap-pool table defined. Golden-scale complement to the unit
    anchor in tests/test_cap_rule_injection.py."""
    manifest = derive_manifest(_load("k_ets_lambda_msr"))
    assert set(manifest["features"]) == {
        "core", "transmission", "msr", "price_controls", "sectors",
    }
    assert manifest["approach"] == ["competitive"]
    # Per-scenario: only the MSR variant carries the msr feature.
    assert "msr" in manifest["scenarios"]["lambda 0.55 + bank-threshold MSR"]["features"]
    assert "msr" not in manifest["scenarios"]["lambda 0.55, no MSR"]["features"]


def test_elastic_policy_combines_elastic_baseline_with_msr_and_floor() -> None:
    manifest = derive_manifest(_load("climate_solutions_elastic_policy"))
    assert set(manifest["features"]) == {
        "core", "competitive", "elastic_baseline", "msr", "price_controls",
    }
    assert manifest["approach"] == ["competitive"]
    assert "msr" not in manifest["scenarios"]["Elastic baseline, no policy"]["features"]
    assert "msr" in manifest["scenarios"]["Elastic baseline + auction floor + MSR"]["features"]


def test_hoarding_basic_is_the_sole_hoarding_example() -> None:
    """First example with a nonzero hoarding_inflow anywhere in examples/
    (k_msr_paper_reproduction never sets one, verified against the raw JSON)."""
    manifest = derive_manifest(_load("k_ets_hoarding_basic"))
    assert set(manifest["features"]) == {"core", "banking", "hoarding", "price_controls"}
    assert manifest["approach"] == ["banking"]
    assert "hoarding" not in manifest["scenarios"]["Textbook banking (no hoarding)"]["features"]
    assert "hoarding" in manifest["scenarios"]["Structural hoarding 2026-27"]["features"]


def test_showcase_full_stack_features() -> None:
    """banking + decree MSR + reserve floor + CBAM + sector pools. The config
    carries a 'sectors' table, and the manifest DOES report a 'sectors'
    feature: even though decompile.py never synthesises a sector *node*
    (documented scope reduction — sectors round-trip as opaque market
    params), ``ets.blocks.manifest._direct_detectors`` scans the normalized
    config directly for a non-empty ``sectors[]`` table (or a per-participant
    ``sector_group``) and reports the feature regardless of graph coverage.
    Same direct-detector mechanism surfaces 'oba' on k_ets_oba_benchmark (see
    ``test_oba_benchmark_includes_oba`` below)."""
    raw = _load("showcase_full_stack")
    assert raw["scenarios"][0]["sectors"], "config must carry the sector pool table"
    manifest = derive_manifest(raw)
    assert set(manifest["features"]) == {
        "core", "banking", "msr", "cbam", "price_controls", "sectors",
    }
    assert {"sectors"} <= set(manifest["features"])
    assert manifest["approach"] == ["banking"]


def test_oba_benchmark_includes_oba() -> None:
    """K-ETS steel benchmark: POSCO_Pohang/Hyundai_Steel set production_output,
    benchmark_emission_intensity, AND initial_emissions (all > 0 across every
    year) — the exact activation condition ``config_io/builder.py``'s
    build_market_from_year OBA-override block checks before it overrides
    free_allocation_ratio with ``benchmark_emission_intensity *
    production_output``. The ``oba`` direct detector mirrors that predicate
    on the normalized config, so it fires regardless of decompile.py's
    documented sector/oba node-synthesis gap."""
    manifest = derive_manifest(_load("k_ets_oba_benchmark"))
    assert {"oba"} <= set(manifest["features"])


def test_subsector_decomposition_includes_sectors() -> None:
    """K-ETS sub-sector decomposition: the scenario defines a non-empty
    ``sectors[]`` cap-pool table (Steel:Integrated, Steel:EAF,
    Petrochemical:NCC, Petrochemical:BTX), the exact condition
    ``config_io/builder.py``'s build_market_from_year gates its sector-pool
    derivation on (``if sectors:``). No participant sets production_output/
    benchmark_emission_intensity, so 'oba' stays out."""
    manifest = derive_manifest(_load("k_ets_subsector_decomposition"))
    assert {"sectors"} <= set(manifest["features"])
    assert "oba" not in manifest["features"]


# ── (c) vocabulary test ──────────────────────────────────────────────

# Frozen literal vocabulary for BlockSpec.feature, per the catalogue-mapping
# table in WO-M1: "core" + the 12 feature names + the 5 analysis/workflow
# ids. NOTE: src/ets/features/* does not exist yet (arrives in a later
# feature-modules-plan.md restructure order) — this list must be re-pointed
# at that tree (e.g. `{p.name for p in Path("src/ets/features").iterdir()}`)
# once it lands, rather than staying a hand-maintained literal forever.
FEATURE_VOCABULARY = frozenset(
    {
        "core",
        # price-formation approaches
        "competitive",
        "banking",
        "hotelling",
        "nash_cournot",
        "transmission",
        # policy mechanisms
        "msr",
        "ccr",
        "price_controls",
        "oba",
        "cbam",
        "hoarding",
        "elastic_baseline",
        "sectors",
        # analysis/workflow ids
        "batch_analysis",
        "calibration",
        "narrative",
        "investment_trigger",
        "feedback_coupling",
    }
)


def test_every_block_feature_is_in_the_frozen_vocabulary() -> None:
    for block in BLOCK_CATALOGUE:
        assert block.feature in FEATURE_VOCABULARY, (
            f"{block.id}.feature = {block.feature!r} is outside the frozen vocabulary"
        )


# A derived manifest's "features" also includes any direct-detector output
# (ets.blocks.manifest._direct_detectors) that has no BlockSpec of its own —
# today just "policy_events" (splicing is engine composition, not a
# drawable block; see manifest.py's module docstring). That is a distinct,
# intentionally larger vocabulary from BlockSpec.feature's.
MANIFEST_FEATURE_VOCABULARY = FEATURE_VOCABULARY | {"policy_events"}


def test_every_derived_manifest_feature_is_in_the_frozen_vocabulary() -> None:
    for stem in RUNNABLE_EXAMPLES:
        manifest = derive_manifest(_load(stem))
        for feature in manifest["features"]:
            assert feature in MANIFEST_FEATURE_VOCABULARY, f"{stem}: unexpected feature {feature!r}"
