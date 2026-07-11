"""Regression test: dashboard payload captures WARNINGs from ``pe.*`` loggers.

The web UI surfaces simulation warnings via ``_build_dashboard_payload``,
which attaches a collecting handler to the package root logger for the
duration of the run. It previously listened on ``"src.ets"`` — a logger name
nothing in the package emits under (modules are imported as ``pe.<module>``,
so ``logging.getLogger(__name__)`` yields ``pe.*``) — leaving the warnings
panel silently empty.
"""

import json
import logging
from pathlib import Path

import pe.web.api as api

# TEST INFRA (not the example library): the recovered minimal competitive
# scenario under tests/fixtures/, used here as a generic clean run.
MINIMAL_SCENARIO = (
    next(p for p in Path(__file__).resolve().parents if p.name == "tests")
    / "fixtures"
    / "minimal_scenario.json"
)


def test_ets_logger_warning_reaches_payload(monkeypatch) -> None:
    """A WARNING emitted by an ``pe.*`` logger mid-run lands in payload["warnings"]."""
    config = json.loads(MINIMAL_SCENARIO.read_text(encoding="utf-8"))

    real_run_simulation = api.run_simulation

    def run_and_warn(markets):
        logging.getLogger("pe.solvers.simulation").warning("synthetic-warning-for-test")
        return real_run_simulation(markets)

    monkeypatch.setattr(api, "run_simulation", run_and_warn)
    payload = api._build_dashboard_payload(config)

    assert any("synthetic-warning-for-test" in message for message in payload["warnings"])


def test_no_spurious_warnings_on_clean_run() -> None:
    """A clean scenario produces an empty warnings list (handler is scoped to the run)."""
    config = json.loads(MINIMAL_SCENARIO.read_text(encoding="utf-8"))

    payload = api._build_dashboard_payload(config)

    assert payload["warnings"] == []
