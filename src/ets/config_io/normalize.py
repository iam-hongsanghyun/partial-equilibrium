from __future__ import annotations

from typing import Any

from ..core.expectations import ALLOWED_EXPECTATION_RULES, validate_expectation_rule
from ..features.endogenous_investment.plugin import (
    normalize_investment_trigger as _normalize_investment_trigger,
)

ALLOWED_AUCTION_MODES = {"explicit", "derive_from_cap"}


def _norm_traj(raw: Any) -> dict:
    """Normalise a 4-key trajectory dict, returning {} if empty/missing."""
    if not raw or not isinstance(raw, dict):
        return {}
    out: dict = {}
    for k in ("start_year", "end_year"):
        if raw.get(k) is not None:
            out[k] = str(raw[k])
    for k in ("start_value", "end_value"):
        try:
            out[k] = float(raw[k])
        except (KeyError, TypeError, ValueError):
            pass
    if not all(k in out for k in ("start_year", "end_year", "start_value", "end_value")):
        return {}
    return out
ALLOWED_ABATEMENT_TYPES = {"linear", "threshold", "piecewise"}
ALLOWED_MODEL_APPROACHES = {"competitive", "hotelling", "banking", "nash_cournot", "all"}


def normalize_year(raw_year: dict[str, Any]) -> dict[str, Any]:
    from .templates import blank_year_config
    year_config = blank_year_config()
    year_config.update(raw_year)

    year_config["year"] = str(year_config["year"]).strip()
    if not year_config["year"]:
        raise ValueError("Each yearly configuration must have a non-empty year label.")

    year_config["total_cap"] = float(year_config["total_cap"])
    year_config["auction_mode"] = str(year_config["auction_mode"]).strip()
    if "auction_offered" not in year_config and "auctioned_allowances" in raw_year:
        year_config["auction_offered"] = raw_year["auctioned_allowances"]
    year_config["auction_offered"] = float(
        year_config.get("auction_offered", 0.0)
    )
    year_config["reserved_allowances"] = float(
        year_config.get("reserved_allowances", 0.0)
    )
    year_config["cancelled_allowances"] = float(
        year_config.get("cancelled_allowances", 0.0)
    )
    year_config["auction_reserve_price"] = float(
        year_config.get("auction_reserve_price", 0.0)
    )
    year_config["minimum_bid_coverage"] = float(
        year_config.get("minimum_bid_coverage", 0.0)
    )
    year_config["unsold_treatment"] = str(
        year_config.get("unsold_treatment", "reserve")
    ).strip()
    year_config["price_lower_bound"] = float(year_config["price_lower_bound"])
    year_config["price_upper_bound"] = float(year_config["price_upper_bound"])
    year_config["banking_allowed"] = bool(year_config.get("banking_allowed", False))
    year_config["borrowing_allowed"] = bool(
        year_config.get("borrowing_allowed", False)
    )
    year_config["borrowing_limit"] = float(year_config.get("borrowing_limit", 0.0))
    year_config["expectation_rule"] = validate_expectation_rule(
        year_config.get("expectation_rule", "next_year_baseline"),
        year_config["year"],
    )
    year_config["manual_expected_price"] = float(
        year_config.get("manual_expected_price", 0.0)
    )
    year_config["carbon_budget"] = float(year_config.get("carbon_budget") or 0.0)
    year_config["hoarding_inflow"] = float(year_config.get("hoarding_inflow") or 0.0)
    if year_config["hoarding_inflow"] < 0.0:
        raise ValueError(
            f"Year '{year_config['year']}': hoarding_inflow must be >= 0."
        )
    year_config["eua_price"] = float(year_config.get("eua_price") or 0.0)
    # Per-jurisdiction and ensemble EUA prices — keep as dicts, just ensure float values
    raw_eua_prices = year_config.get("eua_prices") or {}
    year_config["eua_prices"] = {k: float(v or 0.0) for k, v in raw_eua_prices.items()} if isinstance(raw_eua_prices, dict) else {}
    raw_ensemble = year_config.get("eua_price_ensemble") or {}
    year_config["eua_price_ensemble"] = {k: float(v or 0.0) for k, v in raw_ensemble.items()} if isinstance(raw_ensemble, dict) else {}

    if year_config["auction_mode"] not in ALLOWED_AUCTION_MODES:
        raise ValueError(
            f"Year '{year_config['year']}' has invalid auction_mode "
            f"'{year_config['auction_mode']}'."
        )
    if year_config["price_upper_bound"] <= year_config["price_lower_bound"]:
        raise ValueError(
            f"Year '{year_config['year']}' must have price_upper_bound greater than "
            "price_lower_bound."
        )
    if not 0.0 <= year_config["minimum_bid_coverage"] <= 1.0:
        raise ValueError(
            f"Year '{year_config['year']}' minimum_bid_coverage must be between 0 and 1."
        )
    if year_config["auction_reserve_price"] < 0.0:
        raise ValueError(
            f"Year '{year_config['year']}' auction_reserve_price must be non-negative."
        )
    if year_config["unsold_treatment"] not in {"reserve", "cancel", "carry_forward"}:
        raise ValueError(
            f"Year '{year_config['year']}' unsold_treatment must be one of reserve, cancel, carry_forward."
        )
    if year_config["manual_expected_price"] < 0.0:
        raise ValueError(
            f"Year '{year_config['year']}' manual_expected_price must be non-negative."
        )

    participants = year_config.get("participants", [])
    if not isinstance(participants, list):
        raise ValueError(
            f"Year '{year_config['year']}' participants must be provided as a list."
        )
    year_config["participants"] = [normalize_participant(item) for item in participants]

    # ── Validation rules (config-time, before trajectory overrides) ─────────
    yr = year_config["year"]
    # Duplicate participant names
    names = [p["name"] for p in year_config["participants"]]
    seen: set = set()
    dupes: set = set()
    for n in names:
        (dupes if n in seen else seen).add(n)
    if dupes:
        raise ValueError(
            f"Year '{yr}' has duplicate participant name(s): {sorted(dupes)}."
        )
    # Penalty price below price floor — compliance never buys, always pays penalty
    floor = year_config["price_lower_bound"]
    for p in year_config["participants"]:
        pp = float(p["penalty_price"])
        if 0 < pp < floor:
            raise ValueError(
                f"Year '{yr}', participant '{p['name']}': penalty_price ({pp:.1f}) is below "
                f"price_lower_bound ({floor:.1f}). Participants would always pay penalty instead of complying."
            )
    # Note: cap consistency (free_alloc + auction ≤ total_cap) is validated in
    # build_market_from_year() after trajectory overrides are applied.

    return year_config


def normalize_participant(raw_participant: dict[str, Any]) -> dict[str, Any]:
    from .templates import blank_participant
    participant = blank_participant()
    participant.update(raw_participant)

    participant["name"] = str(participant["name"]).strip()
    if not participant["name"]:
        raise ValueError("Each participant must have a non-empty name.")

    participant["abatement_type"] = str(participant["abatement_type"]).strip()
    if participant["abatement_type"] not in ALLOWED_ABATEMENT_TYPES:
        raise ValueError(
            f"Participant '{participant['name']}' has invalid abatement_type "
            f"'{participant['abatement_type']}'."
        )

    numeric_fields = [
        "initial_emissions",
        "free_allocation_ratio",
        "penalty_price",
        "max_abatement",
        "cost_slope",
        "threshold_cost",
        "cbam_export_share",
        "cbam_coverage_ratio",
    ]
    for field in numeric_fields:
        participant[field] = float(participant[field])
    if not 0.0 <= participant["cbam_export_share"] <= 1.0:
        raise ValueError(
            f"Participant '{participant['name']}' cbam_export_share must be between 0 and 1."
        )
    if not 0.0 <= participant["cbam_coverage_ratio"] <= 1.0:
        raise ValueError(
            f"Participant '{participant['name']}' cbam_coverage_ratio must be between 0 and 1."
        )
    # Multi-jurisdiction CBAM
    raw_jurs = participant.get("cbam_jurisdictions") or []
    participant["cbam_jurisdictions"] = [
        {
            "name": str(j.get("name", "")),
            "export_share": float(j.get("export_share", 0.0) or 0.0),
            "coverage_ratio": float(j.get("coverage_ratio", 1.0) or 1.0),
            **( {"reference_price": float(j["reference_price"])} if j.get("reference_price") is not None else {} ),
        }
        for j in raw_jurs
        if isinstance(j, dict)
    ]
    # Option A: price-elastic baseline coefficient (per participant)
    try:
        participant["output_price_elasticity"] = float(
            participant.get("output_price_elasticity") or 0.0
        )
    except (TypeError, ValueError):
        participant["output_price_elasticity"] = 0.0
    if participant["output_price_elasticity"] < 0.0:
        raise ValueError(
            f"Participant '{participant['name']}' output_price_elasticity must be non-negative."
        )
    participant["sector_group"] = str(participant.get("sector_group") or "")
    try:
        participant["sector_allocation_share"] = float(participant.get("sector_allocation_share") or 0.0)
    except (TypeError, ValueError):
        participant["sector_allocation_share"] = 0.0
    if not 0.0 <= participant["sector_allocation_share"] <= 1.0:
        raise ValueError(
            f"Participant '{participant['name']}' sector_allocation_share must be between 0 and 1."
        )
    # Scope 2 / indirect emissions
    for s2_field in ("electricity_consumption", "grid_emission_factor", "scope2_cbam_coverage"):
        try:
            participant[s2_field] = float(participant.get(s2_field) or 0.0)
        except (TypeError, ValueError):
            participant[s2_field] = 0.0
    if not 0.0 <= participant["scope2_cbam_coverage"] <= 1.0:
        raise ValueError(
            f"Participant '{participant['name']}' scope2_cbam_coverage must be between 0 and 1."
        )
    # BAU emissions trajectory — overrides initial_emissions year by year
    participant["initial_emissions_trajectory"] = _norm_traj(
        participant.get("initial_emissions_trajectory")
    )
    # Grid emission factor trajectory — overrides grid_emission_factor year by year
    participant["grid_emission_factor_trajectory"] = _norm_traj(
        participant.get("grid_emission_factor_trajectory")
    )
    # Output-based allocation (OBA) / benchmark fields
    try:
        participant["production_output"] = float(participant.get("production_output") or 0.0)
    except (TypeError, ValueError):
        participant["production_output"] = 0.0
    try:
        participant["benchmark_emission_intensity"] = float(participant.get("benchmark_emission_intensity") or 0.0)
    except (TypeError, ValueError):
        participant["benchmark_emission_intensity"] = 0.0
    technology_options = participant.get("technology_options", [])
    if not isinstance(technology_options, list):
        raise ValueError(
            f"Participant '{participant['name']}' technology_options must be a list."
        )
    participant["technology_options"] = [
        normalize_technology_option(item, participant["name"])
        for item in technology_options
    ]

    mac_blocks = participant.get("mac_blocks", [])
    if not isinstance(mac_blocks, list):
        raise ValueError(
            f"Participant '{participant['name']}' mac_blocks must be a list."
        )
    normalized_blocks: list[dict[str, float]] = []
    previous_cost = -float("inf")
    for index, block in enumerate(mac_blocks):
        if not isinstance(block, dict):
            raise ValueError(
                f"Participant '{participant['name']}' MAC block {index + 1} must be an object."
            )
        amount = float(block.get("amount", 0.0))
        marginal_cost = float(block.get("marginal_cost", 0.0))
        # amount must be non-negative; marginal_cost MAY be negative — negative-cost
        # abatement measures (e.g. net-saving efficiency options) are a standard
        # feature of real MACC curves and sort first under the ordering rule below.
        if amount < 0:
            raise ValueError(
                f"Participant '{participant['name']}' MAC block {index + 1} amount must be non-negative."
            )
        if marginal_cost < previous_cost:
            raise ValueError(
                f"Participant '{participant['name']}' mac_blocks must be ordered by non-decreasing marginal_cost."
            )
        normalized_blocks.append(
            {"amount": amount, "marginal_cost": marginal_cost}
        )
        previous_cost = marginal_cost
    participant["mac_blocks"] = normalized_blocks

    if participant["abatement_type"] == "piecewise" and not normalized_blocks:
        raise ValueError(
            f"Participant '{participant['name']}' piecewise abatement requires mac_blocks."
        )

    return participant


def normalize_technology_option(
    raw_option: dict[str, Any], participant_name: str
) -> dict[str, Any]:
    from .templates import blank_technology_option
    option = blank_technology_option()
    option.update(raw_option)
    option["name"] = str(option["name"]).strip()
    if not option["name"]:
        raise ValueError(
            f"Participant '{participant_name}' technology options must have a non-empty name."
        )

    option["abatement_type"] = str(option["abatement_type"]).strip()
    if option["abatement_type"] not in ALLOWED_ABATEMENT_TYPES:
        raise ValueError(
            f"Participant '{participant_name}' technology '{option['name']}' has invalid "
            f"abatement_type '{option['abatement_type']}'."
        )

    numeric_fields = [
        "initial_emissions",
        "free_allocation_ratio",
        "penalty_price",
        "max_abatement",
        "cost_slope",
        "threshold_cost",
        "fixed_cost",
        "max_activity_share",
    ]
    for field in numeric_fields:
        option[field] = float(option[field])

    mac_blocks = option.get("mac_blocks", [])
    if not isinstance(mac_blocks, list):
        raise ValueError(
            f"Participant '{participant_name}' technology '{option['name']}' mac_blocks must be a list."
        )
    normalized_blocks: list[dict[str, float]] = []
    previous_cost = -float("inf")
    for index, block in enumerate(mac_blocks):
        if not isinstance(block, dict):
            raise ValueError(
                f"Participant '{participant_name}' technology '{option['name']}' MAC block {index + 1} must be an object."
            )
        amount = float(block.get("amount", 0.0))
        marginal_cost = float(block.get("marginal_cost", 0.0))
        # amount must be non-negative; marginal_cost MAY be negative (negative-cost
        # abatement measures are valid and sort first under the ordering rule).
        if amount < 0:
            raise ValueError(
                f"Participant '{participant_name}' technology '{option['name']}' MAC block {index + 1} amount must be non-negative."
            )
        if marginal_cost < previous_cost:
            raise ValueError(
                f"Participant '{participant_name}' technology '{option['name']}' mac_blocks must be ordered by non-decreasing marginal_cost."
            )
        normalized_blocks.append({"amount": amount, "marginal_cost": marginal_cost})
        previous_cost = marginal_cost
    option["mac_blocks"] = normalized_blocks

    if option["abatement_type"] == "piecewise" and not normalized_blocks:
        raise ValueError(
            f"Participant '{participant_name}' technology '{option['name']}' piecewise abatement requires mac_blocks."
        )

    # Endogenous-investment trigger (docs/invest-feedback-spec.md D6): presence
    # of a non-empty ``investment_trigger`` sub-dict IS the flag. Content
    # validation is delegated to the feature's config door — the config_io ->
    # plugin door is legal (docs/feature-modules-plan.md PLAN v2 "Two-door
    # features") — so a malformed trigger (missing payout_yield, both/neither
    # break_even form, an out-of-bound credibility, ...) raises HERE, at
    # normalize time, naming this participant/technology (spec D6). The
    # ORIGINAL wire-format dict round-trips unchanged (never the AdoptionSpec
    # kwargs shape) so compile.py/decompile.py can pass it through opaquely;
    # the key is always present (default {}) so the catalogue's
    # config_key-existence drift guard (tests/workflows/blocks/
    # test_blocks_catalogue.py) can assert against it regardless of whether
    # any one option actually flags itself — the *template*
    # (``templates.blank_technology_option``) deliberately does NOT carry
    # this key (config-driven display principle: blank stays blank).
    raw_trigger = option.get("investment_trigger")
    if raw_trigger:
        _normalize_investment_trigger(raw_trigger, option["name"], participant_name)
        option["investment_trigger"] = dict(raw_trigger)
    else:
        option["investment_trigger"] = {}

    return option
