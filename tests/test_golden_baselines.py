"""Golden-baseline replay gate for the curated example library.

Re-runs every scenario in ``examples/*.json`` through the engine TODAY and
compares the full solved output against the stored baseline in
``tests/baselines/<stem>.json`` captured by ``tests/baselines/_capture.py``.

Bar: bit-identical -- ``rtol=0, atol=0`` on every numeric cell, exact equality
on strings, structure and shape included. Any relaxation of this bar requires
joint sign-off from lead-modeller and ets-lead-economist and must be written
here with an explicit tolerance and a comment saying why.

The capture/serialization logic is imported from
``tests/baselines/_capture.py`` (single source of truth) so the comparison is
apples-to-apples, including the NaN/inf -> null normalization.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = REPO_ROOT / "tests" / "baselines"
EXAMPLES_DIR = REPO_ROOT / "examples"


def _load_capture_module():
    """Import tests/baselines/_capture.py by path (it is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "pe_baseline_capture", BASELINE_DIR / "_capture.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_capture = _load_capture_module()

# Baseline files, keyed by scenario stem. MANIFEST.json is metadata, not a
# baseline; _capture.py is the shared capture script.
BASELINE_FILES = sorted(p for p in BASELINE_DIR.glob("*.json") if p.name != "MANIFEST.json")
SCENARIO_NAMES = [p.stem for p in BASELINE_FILES]

# The curated library is deliberately small and fast (round numbers, few years,
# few participants), so no example crosses the slow threshold. The set is kept
# for structure -- a future heavier example is added here and deselected with
# ``-m "not slow"`` while the gate still runs everything by default.
SLOW_SCENARIOS: set[str] = set()

SCENARIO_PARAMS = [
    pytest.param(name, marks=pytest.mark.slow) if name in SLOW_SCENARIOS else name
    for name in SCENARIO_NAMES
]


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _walk_diff(baseline: object, actual: object, path: str, drifts: list[dict]) -> None:
    """Recursively compare two JSON-safe structures, recording every mismatch.

    Numeric cells are held to rtol=0, atol=0 (exact equality); everything
    else (strings, bools, None, structure) must match exactly.
    """
    if _is_number(baseline) and _is_number(actual):
        if not (baseline == actual):
            abs_diff = abs(actual - baseline)
            denom = abs(baseline)
            rel_diff = abs_diff / denom if denom > 0 else math.inf
            drifts.append(
                {
                    "path": path,
                    "baseline": baseline,
                    "actual": actual,
                    "abs_diff": abs_diff,
                    "rel_diff": rel_diff,
                }
            )
        return
    if isinstance(baseline, dict) and isinstance(actual, dict):
        for key in baseline.keys() | actual.keys():
            if key not in baseline:
                drifts.append(
                    {"path": f"{path}.{key}", "baseline": "<absent>", "actual": actual[key]}
                )
            elif key not in actual:
                drifts.append(
                    {"path": f"{path}.{key}", "baseline": baseline[key], "actual": "<absent>"}
                )
            else:
                _walk_diff(baseline[key], actual[key], f"{path}.{key}", drifts)
        return
    if isinstance(baseline, list) and isinstance(actual, list):
        if len(baseline) != len(actual):
            drifts.append(
                {
                    "path": f"{path}.<len>",
                    "baseline": len(baseline),
                    "actual": len(actual),
                }
            )
        for i, (b, a) in enumerate(zip(baseline, actual)):
            _walk_diff(b, a, f"{path}[{i}]", drifts)
        return
    if baseline != actual or type(baseline) is not type(actual):
        drifts.append({"path": path, "baseline": baseline, "actual": actual})


def _format_drift_report(name: str, drifts: list[dict], limit: int = 20) -> str:
    numeric = [d for d in drifts if "abs_diff" in d]
    lines = [
        f"DRIFT in scenario '{name}': {len(drifts)} mismatching cell(s) "
        f"vs baseline (bar: rtol=0, atol=0).",
    ]
    if numeric:
        worst = max(numeric, key=lambda d: d["abs_diff"])
        lines.append(
            f"  max abs diff = {worst['abs_diff']!r} "
            f"(rel = {worst['rel_diff']!r}) at {worst['path']}"
        )
        first = numeric[0]
        lines.append(
            f"  first numeric drift at {first['path']}: "
            f"baseline={first['baseline']!r} actual={first['actual']!r}"
        )
    for d in drifts[:limit]:
        lines.append(f"  {d['path']}: baseline={d['baseline']!r} actual={d['actual']!r}")
    if len(drifts) > limit:
        lines.append(f"  ... and {len(drifts) - limit} more")
    return "\n".join(lines)


def test_baseline_coverage() -> None:
    """Every example must have a baseline and every baseline an example.

    A missing pairing is a failure, not a skip: an unbaselined example is an
    unguarded code path; an orphaned baseline means an example was deleted or
    renamed without the gate noticing.
    """
    example_stems = {p.stem for p in EXAMPLES_DIR.glob("*.json")}
    baseline_stems = set(SCENARIO_NAMES)
    missing_baselines = sorted(example_stems - baseline_stems)
    orphaned_baselines = sorted(baseline_stems - example_stems)
    assert not missing_baselines, (
        f"Examples without a golden baseline (run tests/baselines/_capture.py): {missing_baselines}"
    )
    assert not orphaned_baselines, (
        f"Baselines without a matching example file: {orphaned_baselines}"
    )
    # The curated library is exactly seven examples <-> seven baselines.
    assert len(example_stems) == 7, f"expected 7 curated examples, found {sorted(example_stems)}"
    assert len(baseline_stems) == 7, f"expected 7 baselines, found {sorted(baseline_stems)}"


@pytest.mark.parametrize("scenario_name", SCENARIO_PARAMS)
def test_golden_baseline_replay(scenario_name: str) -> None:
    baseline_path = BASELINE_DIR / f"{scenario_name}.json"
    config_path = EXAMPLES_DIR / f"{scenario_name}.json"
    assert baseline_path.exists(), f"Baseline file missing: {baseline_path}"
    assert config_path.exists(), (
        f"Example file missing for baseline '{scenario_name}': {config_path}"
    )

    baseline = json.loads(baseline_path.read_text())

    entry_point, fragment = _capture._run_example(config_path)
    assert entry_point == baseline["entry_point"], (
        f"Scenario '{scenario_name}' now dispatches to {entry_point!r}, "
        f"baseline was captured via {baseline['entry_point']!r}"
    )

    # Round-trip the fresh output through JSON so float representation is
    # identical on both sides of the comparison (repr -> shortest round-trip).
    actual = json.loads(json.dumps(fragment, allow_nan=False))
    expected = {key: baseline[key] for key in fragment.keys() if key in baseline}
    missing_keys = set(fragment.keys()) - set(baseline.keys())
    assert not missing_keys, (
        f"Baseline '{scenario_name}' lacks output sections {sorted(missing_keys)}"
    )

    drifts: list[dict] = []
    _walk_diff(expected, actual, scenario_name, drifts)
    assert not drifts, _format_drift_report(scenario_name, drifts)
