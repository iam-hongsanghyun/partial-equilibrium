from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .config import EXAMPLES_DIR
from .scenarios import blank_config, save_config
from .simulation import run_simulation_from_file

SAMPLE_MODES = {
    "basic": EXAMPLES_DIR / "climate_solutions_basic_linear.json",
    "transition": EXAMPLES_DIR / "climate_solutions_transition_pathway.json",
    "threshold": EXAMPLES_DIR / "climate_solutions_threshold_pathway.json",
    "mac": EXAMPLES_DIR / "climate_solutions_mac_pathway.json",
    "technology": EXAMPLES_DIR / "climate_solutions_technology_switching.json",
    "partial": EXAMPLES_DIR / "climate_solutions_partial_adoption.json",
    "banking": EXAMPLES_DIR / "climate_solutions_banking_borrowing.json",
    "auction": EXAMPLES_DIR / "climate_solutions_auction_controls.json",
    "compare": EXAMPLES_DIR / "climate_solutions_compare_suite.json",
    "full": EXAMPLES_DIR / "climate_solutions_full_featured_pathway.json",
}


def _resolve_config_path(config: str | None, mode: str | None) -> Path | None:
    if config:
        return Path(config)
    if mode:
        return SAMPLE_MODES[mode]
    return None


def _print_sample_modes() -> None:
    print("\nAvailable sample modes\n")
    for mode, path in SAMPLE_MODES.items():
        print(f"- {mode}: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ETS equilibrium simulator.")
    parser.add_argument(
        "--config",
        type=str,
        help="Path to a JSON config file defining scenarios, years, and participants.",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(SAMPLE_MODES.keys()),
        help="Run a bundled sample scenario mode without specifying --config.",
    )
    parser.add_argument(
        "--list-modes",
        action="store_true",
        help="List bundled sample modes and exit.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the local browser-based scenario editor.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for the local browser-based editor.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the local editor without opening a browser automatically.",
    )
    parser.add_argument(
        "--export-template",
        type=str,
        help="Write a blank scenario JSON template to the given path and exit.",
    )
    args = parser.parse_args()

    if args.list_modes:
        _print_sample_modes()
        return

    if args.export_template:
        save_config(blank_config(), args.export_template)
        print(f"Blank config template written to {args.export_template}")
        return

    config_path = _resolve_config_path(args.config, args.mode)

    if args.gui or config_path is None:
        from .webapp import launch_web_app

        launch_web_app(port=args.port, open_browser=not args.no_browser)
        return

    pd.set_option("display.float_format", lambda value: f"{value:,.2f}")
    summary_df, participant_df = run_simulation_from_file(config_path)

    if args.mode:
        print(f"\nRunning sample mode: {args.mode}")
        print(f"Source config: {config_path}\n")

    print("\nETS Scenario Summary\n")
    print(summary_df.to_string(index=False))

    print("\nParticipant-Level Results\n")
    print(participant_df.to_string(index=False))


if __name__ == "__main__":
    main()
