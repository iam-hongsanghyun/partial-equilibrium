r"""Anchor tests for the two v1 link channels (D1-2).

The MASTER ANCHOR PATTERN (spec ``docs/platform-spec-d0-d1.md`` §4): a
link-compiled config must equal a hand-edited config, bit-identically, for
every channel. These tests pin, per channel:

* (a) ``MacCostChannel`` shifts the target's MAC level to exactly
  ``base + phi*P_A(t)`` (hand-computed, threshold and piecewise); ``phi=0``
  leaves the markets deepcopy-equal to the input;
* (b) ``InvestBreakEvenChannel`` compiles ``break_even`` to exactly
  ``{t: base + phi*P_A(t)}`` — the A4 anchor (``phi=30``, a hand ``P_A``);
* (c) the input markets are NEVER mutated (deep pre/post compare);
* (d) copy-on-write identity for an empty / no-match target;

plus the ``LinkChannel`` isinstance-conformance of both channels and the
reviewed ``engine.wiring.link_channels`` registry, the defensive
``cost_slope`` exclusion, the wildcard participant selector, and the E8
missing-source-year error.

All arithmetic is closed-form and asserted to ``atol=1e-12`` (exact for the
representable values chosen).
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from pe.core.costs import linear_abatement_factory, piecewise_abatement_factory
from pe.core.market.model import CarbonMarket
from pe.core.participant.models import MarketParticipant, TechnologyOption
from pe.core.protocols import AdoptionSpec, LinkChannel, LinkSpec
from pe.engine.wiring import link_channels
from pe.features.market_links.channels import InvestBreakEvenChannel, MacCostChannel

FLAGGED = "H2-DRI"
OTHER = "Efficiency"
YEARS = ("2030", "2031", "2032")
# Source (upstream A) delivered price path P_A(t) — hand values.
P_A = {"2030": 10.0, "2031": 20.0, "2032": 30.0}


# ── Builders ─────────────────────────────────────────────────────────────────


def _threshold_option(name: str, level: float) -> TechnologyOption:
    """A threshold-type option: ``marginal_abatement_cost`` IS the MAC level."""
    return TechnologyOption(
        name=name,
        initial_emissions=60.0,
        free_allocation_ratio=0.0,
        penalty_price=0.0,
        marginal_abatement_cost=level,
        max_activity_share=0.5,
    )


def _piecewise_option(name: str, block_costs: tuple[float, ...]) -> TechnologyOption:
    """A piecewise option built via the kernel factory (carries ``mac_blocks``)."""
    return TechnologyOption(
        name=name,
        initial_emissions=60.0,
        free_allocation_ratio=0.0,
        penalty_price=0.0,
        marginal_abatement_cost=piecewise_abatement_factory(
            [{"amount": 5.0, "marginal_cost": c} for c in block_costs]
        ),
        max_activity_share=0.5,
    )


def _linear_option(name: str) -> TechnologyOption:
    """A linear option (``cost_slope`` — the dimensionally excluded case)."""
    return TechnologyOption(
        name=name,
        initial_emissions=60.0,
        free_allocation_ratio=0.0,
        penalty_price=0.0,
        marginal_abatement_cost=linear_abatement_factory(max_abatement=30.0, cost_slope=5.0),
        max_activity_share=0.5,
    )


def _participant(
    name: str,
    options: list[TechnologyOption],
    specs: tuple[AdoptionSpec, ...] = (),
) -> MarketParticipant:
    return MarketParticipant(
        name=name,
        initial_emissions=100.0,
        marginal_abatement_cost=10.0,
        free_allocation_ratio=0.0,
        penalty_price=100.0,
        technology_options=options,
        adoption_specs=specs,
    )


def _markets(participant_factory: Any, years: tuple[str, ...] = YEARS) -> list[CarbonMarket]:
    """Fresh participant instances per year (the config builder's convention)."""
    return [
        CarbonMarket(
            participants=participant_factory(),
            total_cap=100.0,
            auction_offered=50.0,
            scenario_name="link-test",
            year=year,
        )
        for year in years
    ]


def _mac_level(option: TechnologyOption) -> Any:
    """A comparable snapshot of an option's MAC representation."""
    mac = option.marginal_abatement_cost
    if callable(mac):
        if hasattr(mac, "cost_slope"):
            return ("linear", mac.cost_slope)
        return ("piecewise", tuple(b["marginal_cost"] for b in mac.mac_blocks))
    return float(mac)


def _mac_snapshot(markets: list[CarbonMarket]) -> list[list[tuple[str, list[tuple[str, Any]]]]]:
    return [
        [
            (p.name, [(o.name, _mac_level(o)) for o in p.technology_options or []])
            for p in m.participants
        ]
        for m in markets
    ]


def _break_even_snapshot(markets: list[CarbonMarket]) -> list[list[tuple[str, tuple[Any, ...]]]]:
    return [
        [
            (p.name, tuple((s.technology_name, s.break_even) for s in p.adoption_specs))
            for p in m.participants
        ]
        for m in markets
    ]


def _steel_option(market: CarbonMarket, option_name: str) -> TechnologyOption:
    steel = next(p for p in market.participants if p.name == "Steel")
    return next(o for o in steel.technology_options or [] if o.name == option_name)


def _steel_spec(market: CarbonMarket, technology_name: str) -> AdoptionSpec:
    steel = next(p for p in market.participants if p.name == "Steel")
    return next(s for s in steel.adoption_specs if s.technology_name == technology_name)


# ── Link factories ───────────────────────────────────────────────────────────


def _mac_link(phi: float, participants: tuple[str, ...] = ("Steel",)) -> LinkSpec:
    return LinkSpec(
        from_market="power",
        to_market="steel",
        channel="mac_cost",
        phi=phi,
        phi_unit="tCO2/tCO2",
        target_participants=participants,
        target_technologies=(FLAGGED,),
    )


def _invest_link(
    phi: float,
    participants: tuple[str, ...] = ("Steel",),
    technologies: tuple[str, ...] = (FLAGGED,),
) -> LinkSpec:
    return LinkSpec(
        from_market="hydrogen",
        to_market="steel",
        channel="invest_break_even",
        phi=phi,
        phi_unit="kgH2/tCO2",
        target_participants=participants,
        target_technologies=technologies,
    )


def _steel_and_cement_threshold() -> list[MarketParticipant]:
    return [
        _participant("Steel", [_threshold_option(FLAGGED, 100.0), _threshold_option(OTHER, 50.0)]),
        _participant("Cement", [_threshold_option(OTHER, 50.0)]),
    ]


def _steel_with_spec(break_even: Any) -> Any:
    def factory() -> list[MarketParticipant]:
        spec = AdoptionSpec(
            participant_name="Steel",
            technology_name=FLAGGED,
            break_even=break_even,
            payout_yield=0.03,
        )
        return [
            _participant(
                "Steel",
                [_threshold_option(FLAGGED, 100.0), _threshold_option(OTHER, 50.0)],
                specs=(spec,),
            ),
            _participant("Cement", [_threshold_option(OTHER, 50.0)]),
        ]

    return factory


# ══════════════════════════════════════════════════════════════════════════════
# (a) MacCostChannel — additive shift on the MAC level, base + phi*P_A(t)
# ══════════════════════════════════════════════════════════════════════════════


def test_mac_cost_threshold_shift_is_exact() -> None:
    """Threshold MAC: level -> exactly base + phi*P_A(t) per year (hand-computed)."""
    markets = _markets(_steel_and_cement_threshold)
    result = MacCostChannel().apply(_mac_link(phi=2.0), P_A, markets)
    # base = 100.0, phi = 2.0  ->  {2030: 120, 2031: 140, 2032: 160}
    expected = {"2030": 120.0, "2031": 140.0, "2032": 160.0}
    for market in result:
        flagged = _steel_option(market, FLAGGED)
        assert flagged.marginal_abatement_cost == pytest.approx(expected[market.year], abs=1e-12)
        # Untargeted option and untargeted participant are untouched.
        assert _steel_option(market, OTHER).marginal_abatement_cost == 50.0
        cement = next(p for p in market.participants if p.name == "Cement")
        assert cement.technology_options[0].marginal_abatement_cost == 50.0


def test_mac_cost_piecewise_shifts_every_block() -> None:
    """Piecewise MAC: every block's marginal_cost -> base_block + phi*P_A(t)."""

    def factory() -> list[MarketParticipant]:
        return [_participant("Steel", [_piecewise_option(FLAGGED, (10.0, 30.0))])]

    markets = _markets(factory)
    result = MacCostChannel().apply(_mac_link(phi=2.0), P_A, markets)
    # shift(t) = 2 * P_A(t); blocks (10, 30) -> (10+shift, 30+shift).
    for market in result:
        shift = 2.0 * P_A[market.year]
        mac = _steel_option(market, FLAGGED).marginal_abatement_cost
        got = tuple(b["marginal_cost"] for b in mac.mac_blocks)
        assert got == pytest.approx((10.0 + shift, 30.0 + shift), abs=1e-12)


def test_mac_cost_phi_zero_is_deepcopy_equal() -> None:
    """phi=0 leaves the MAC levels byte-identical to the input (deepcopy-equal)."""
    markets = _markets(_steel_and_cement_threshold)
    before = _mac_snapshot(markets)
    result = MacCostChannel().apply(_mac_link(phi=0.0), P_A, markets)
    assert _mac_snapshot(result) == before
    # The input is untouched (purity), and a matching target IS copied
    # (copy-on-write, not identity) — phi=0 shifts by +0, values unchanged.
    assert _mac_snapshot(markets) == before
    assert result is not markets


def test_mac_cost_wildcard_targets_every_participant() -> None:
    """target_participants ('*',) shifts the flagged option on EVERY participant."""

    def factory() -> list[MarketParticipant]:
        return [
            _participant("Steel", [_threshold_option(FLAGGED, 100.0)]),
            _participant("Cement", [_threshold_option(FLAGGED, 80.0)]),
        ]

    markets = _markets(factory)
    result = MacCostChannel().apply(_mac_link(phi=2.0, participants=("*",)), P_A, markets)
    market = result[0]  # 2030, P_A = 10, shift = 20
    steel = next(p for p in market.participants if p.name == "Steel")
    cement = next(p for p in market.participants if p.name == "Cement")
    assert steel.technology_options[0].marginal_abatement_cost == pytest.approx(120.0, abs=1e-12)
    assert cement.technology_options[0].marginal_abatement_cost == pytest.approx(100.0, abs=1e-12)


def test_mac_cost_rejects_linear_cost_slope_defensively() -> None:
    """A linear (cost_slope) option is dimensionally excluded — assert backstop."""

    def factory() -> list[MarketParticipant]:
        return [_participant("Steel", [_linear_option(FLAGGED)])]

    markets = _markets(factory)
    with pytest.raises(AssertionError, match="cost_slope"):
        MacCostChannel().apply(_mac_link(phi=2.0), P_A, markets)


# ══════════════════════════════════════════════════════════════════════════════
# (b) InvestBreakEvenChannel — compile break_even to {t: base + phi*P_A(t)}
# ══════════════════════════════════════════════════════════════════════════════


def test_invest_break_even_scalar_compiles_to_hand_mapping() -> None:
    """A4 anchor: scalar base 200, phi=30, hand P_A -> exact per-year mapping."""
    p_a = {"2030": 1.0, "2031": 1.5, "2032": 2.0}
    markets = _markets(_steel_with_spec(200.0))
    result = InvestBreakEvenChannel().apply(_invest_link(phi=30.0), p_a, markets)
    # 200 + 30 * {1.0, 1.5, 2.0} = {230, 245, 260}
    expected = {"2030": 230.0, "2031": 245.0, "2032": 260.0}
    for market in result:
        spec = _steel_spec(market, FLAGGED)
        assert spec.break_even == expected  # SAME compiled mapping in every year
        for year, value in expected.items():
            assert spec.break_even[year] == pytest.approx(value, abs=1e-12)


def test_invest_break_even_map_base_adds_per_year() -> None:
    """An existing {year: value} base has phi*P_A(t) added per year."""
    p_a = {"2030": 1.0, "2031": 1.5, "2032": 2.0}
    base = {"2030": 100.0, "2031": 120.0, "2032": 140.0}
    markets = _markets(_steel_with_spec(base))
    result = InvestBreakEvenChannel().apply(_invest_link(phi=30.0), p_a, markets)
    # {100+30, 120+45, 140+60} = {130, 165, 200}
    expected = {"2030": 130.0, "2031": 165.0, "2032": 200.0}
    assert _steel_spec(result[0], FLAGGED).break_even == expected


def test_invest_break_even_empty_technologies_targets_all_specs() -> None:
    """Empty target_technologies (optional for this channel) compiles every spec."""
    p_a = {"2030": 1.0, "2031": 1.5, "2032": 2.0}
    markets = _markets(_steel_with_spec(200.0))
    link = _invest_link(phi=30.0, technologies=())
    result = InvestBreakEvenChannel().apply(link, p_a, markets)
    assert _steel_spec(result[0], FLAGGED).break_even == {
        "2030": 230.0,
        "2031": 245.0,
        "2032": 260.0,
    }


# ══════════════════════════════════════════════════════════════════════════════
# (c) Input markets are NEVER mutated (deep pre/post compare) — both channels
# ══════════════════════════════════════════════════════════════════════════════


def test_mac_cost_never_mutates_input() -> None:
    markets = _markets(_steel_and_cement_threshold)
    before = _mac_snapshot(markets)
    input_participants = [list(m.participants) for m in markets]
    MacCostChannel().apply(_mac_link(phi=2.0), P_A, markets)
    assert _mac_snapshot(markets) == before
    for market, participants in zip(markets, input_participants, strict=True):
        assert market.participants == participants  # same objects, same order


def test_invest_break_even_never_mutates_input() -> None:
    markets = _markets(_steel_with_spec(200.0))
    before = _break_even_snapshot(markets)
    InvestBreakEvenChannel().apply(_invest_link(phi=30.0), P_A, markets)
    assert _break_even_snapshot(markets) == before
    # The original scalar base survives untouched.
    assert _steel_spec(markets[0], FLAGGED).break_even == 200.0


def test_mac_cost_shares_untouched_objects_by_identity() -> None:
    """Only the changed participant/market are copied; the rest pass by identity."""
    markets = _markets(_steel_and_cement_threshold)
    result = MacCostChannel().apply(_mac_link(phi=2.0), P_A, markets)
    market_in, market_out = markets[0], result[0]
    assert market_out is not market_in  # Steel changed -> market copied
    cement_in = next(p for p in market_in.participants if p.name == "Cement")
    cement_out = next(p for p in market_out.participants if p.name == "Cement")
    assert cement_out is cement_in  # untargeted participant shared
    steel_in = next(p for p in market_in.participants if p.name == "Steel")
    steel_out = next(p for p in market_out.participants if p.name == "Steel")
    assert steel_out is not steel_in  # targeted participant copied
    other_in = next(o for o in steel_in.technology_options or [] if o.name == OTHER)
    other_out = next(o for o in steel_out.technology_options or [] if o.name == OTHER)
    assert other_out is other_in  # untargeted option shared


# ══════════════════════════════════════════════════════════════════════════════
# (d) Copy-on-write identity for an empty / no-match target — both channels
# ══════════════════════════════════════════════════════════════════════════════


def test_mac_cost_empty_target_is_identity() -> None:
    empty: list[CarbonMarket] = []
    assert MacCostChannel().apply(_mac_link(phi=2.0), {}, empty) is empty


def test_invest_break_even_empty_target_is_identity() -> None:
    empty: list[CarbonMarket] = []
    assert InvestBreakEvenChannel().apply(_invest_link(phi=30.0), {}, empty) is empty


def test_mac_cost_no_matching_participant_is_identity() -> None:
    markets = _markets(_steel_and_cement_threshold)
    link = _mac_link(phi=2.0, participants=("Nonexistent",))
    assert MacCostChannel().apply(link, P_A, markets) is markets


def test_invest_break_even_no_matching_spec_is_identity() -> None:
    # Cement carries no adoption spec; a link targeting only Cement matches nothing.
    markets = _markets(_steel_with_spec(200.0))
    link = _invest_link(phi=30.0, participants=("Cement",))
    assert InvestBreakEvenChannel().apply(link, P_A, markets) is markets


# ══════════════════════════════════════════════════════════════════════════════
# LinkChannel conformance + the reviewed registry + E8 boundary
# ══════════════════════════════════════════════════════════════════════════════


def test_both_channels_are_link_channels() -> None:
    assert isinstance(MacCostChannel(), LinkChannel)
    assert isinstance(InvestBreakEvenChannel(), LinkChannel)


def test_link_channels_registry_is_the_reviewed_literal() -> None:
    registry = link_channels()
    # The D1 pair plus the D3-4 steel↔carbon shared-agent coupling channels
    # (docs/multi-commodity-spec.md §7): both stamp the sibling PRICE onto the
    # shared producer (price-driven — the joint engine stays byte-identical).
    assert set(registry) == {
        "mac_cost",
        "invest_break_even",
        "carbon_input_price",
        "output_ref_price",
    }
    assert registry["mac_cost"] is MacCostChannel
    assert registry["invest_break_even"] is InvestBreakEvenChannel
    # Each value is a zero-argument factory producing a conformant channel.
    for factory in registry.values():
        assert isinstance(factory(), LinkChannel)


def test_missing_source_year_raises_e8() -> None:
    """A target year absent from the source path is an E8 strict-subset error."""
    markets = _markets(_steel_and_cement_threshold)
    partial = {"2030": 10.0, "2031": 20.0}  # 2032 missing
    with pytest.raises(ValueError, match="E8 strict-subset"):
        MacCostChannel().apply(_mac_link(phi=2.0), partial, markets)


def test_input_list_object_deep_untouched_across_deepcopy_roundtrip() -> None:
    """Belt-and-braces purity: a deepcopy of the input equals the input post-apply."""
    markets = _markets(_steel_with_spec(200.0))
    pristine = copy.deepcopy(markets)
    InvestBreakEvenChannel().apply(_invest_link(phi=30.0), P_A, markets)
    assert _break_even_snapshot(markets) == _break_even_snapshot(pristine)
