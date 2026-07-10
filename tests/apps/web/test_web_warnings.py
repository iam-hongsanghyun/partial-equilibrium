"""Regression test: dashboard payload captures WARNINGs from ``ets.*`` loggers.

The web UI surfaces simulation warnings via ``_build_dashboard_payload``,
which attaches a collecting handler to the package root logger for the
duration of the run. It previously listened on ``"src.ets"`` — a logger name
nothing in the package emits under (modules are imported as ``ets.<module>``,
so ``logging.getLogger(__name__)`` yields ``ets.*``) — leaving the warnings
panel silently empty.
"""

import json
import logging
from pathlib import Path

import ets.web.api as api

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


def test_ets_logger_warning_reaches_payload(monkeypatch) -> None:
    """A WARNING emitted by an ``ets.*`` logger mid-run lands in payload["warnings"]."""
    config = json.loads(
        (EXAMPLES / "climate_solutions_basic_linear.json").read_text(encoding="utf-8")
    )

    real_run_simulation = api.run_simulation

    def run_and_warn(markets):
        logging.getLogger("ets.solvers.simulation").warning("synthetic-warning-for-test")
        return real_run_simulation(markets)

    monkeypatch.setattr(api, "run_simulation", run_and_warn)
    payload = api._build_dashboard_payload(config)

    assert any("synthetic-warning-for-test" in message for message in payload["warnings"])


def test_no_spurious_warnings_on_clean_run() -> None:
    """A clean scenario produces an empty warnings list (handler is scoped to the run)."""
    config = json.loads(
        (EXAMPLES / "climate_solutions_basic_linear.json").read_text(encoding="utf-8")
    )

    payload = api._build_dashboard_payload(config)

    assert payload["warnings"] == []
