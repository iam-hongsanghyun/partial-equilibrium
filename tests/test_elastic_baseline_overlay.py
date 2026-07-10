"""Tests for the elastic-baseline feature module (PLAN v2 O8, binding).

Covers the three things the binding Arbitration outcomes (O8) require:

(a) the loud guard — an active price-elastic channel (``output_price_elasticity
    > 0`` and ``reference_carbon_price > 0``) with no ``demand_overlays``
    attached MUST raise ``ValueError``, both at direct construction AND at
    every post-construction mutation (proving the pre-refactor bypass —
    ``participant.reference_carbon_price = x`` — is closed, not just
    ``__post_init__``);
(b) a plugin-attached participant reproduces the pre-refactor closed-form
    ``m(P) = max(0, 1 - eps*(P-P_ref)/P_ref)`` at several prices;
(c) ``eps == 0`` participants are unchanged and raise-free, with or without a
    post-construction ``reference_carbon_price`` stamp.

See also ``tests/test_feedback_option_a.py`` (end-to-end neutrality and
demand-destruction behaviour) and ``tests/test_module_isolation.py`` (the
``config_io -> features.elastic_baseline.plugin`` door edge).
"""

from __future__ import annotations

import numpy as np
import pytest

from ets.core.participant.models import MarketParticipant
from ets.features.elastic_baseline.plugin import ElasticBaselineOverlay, stamp_and_attach


def _raw_participant(**overrides: float) -> MarketParticipant:
    """Construct a bare ``MarketParticipant`` (no plugin involvement)."""
    kwargs: dict = {
        "name": "X",
        "initial_emissions": 100.0,
        "marginal_abatement_cost": 10.0,
        "free_allocation_ratio": 0.0,
        "penalty_price": 400.0,
    }
    kwargs.update(overrides)
    return MarketParticipant(**kwargs)


# ── (a) The loud guard ───────────────────────────────────────────────────────


def test_direct_construction_with_active_channel_and_no_overlay_raises():
    """eps>0, P_ref>0, no overlay attached -> ValueError at construction."""
    with pytest.raises(ValueError, match="demand overlay"):
        _raw_participant(output_price_elasticity=0.5, reference_carbon_price=50.0)


def test_post_construction_bypass_of_reference_carbon_price_raises():
    """eps>0, P_ref stamped directly (bypassing the plugin) -> ValueError.

    Proves the guard is not limited to ``__post_init__``: the participant
    starts valid (P_ref == 0, channel inactive), then a bare field
    assignment — exactly the pre-refactor ``config_io/builder.py`` stamping
    loop's pattern — activates the channel without an overlay and must be
    rejected immediately.
    """
    participant = _raw_participant(output_price_elasticity=0.5)
    with pytest.raises(ValueError, match="demand overlay"):
        participant.reference_carbon_price = 50.0


def test_post_construction_bypass_via_elasticity_assignment_also_raises():
    """Symmetric bypass: P_ref already active, then eps set directly."""
    participant = _raw_participant(reference_carbon_price=50.0)
    with pytest.raises(ValueError, match="demand overlay"):
        participant.output_price_elasticity = 0.5


def test_stamp_and_attach_closes_the_bypass():
    """The validated path (``stamp_and_attach``) never trips the guard."""
    participant = _raw_participant(output_price_elasticity=0.5)
    stamp_and_attach(participant, 50.0)
    assert participant.reference_carbon_price == 50.0
    assert len(participant.demand_overlays) == 1
    assert isinstance(participant.demand_overlays[0], ElasticBaselineOverlay)


def test_guard_error_names_the_plugin_attachment_function():
    """The error message points at the validated attachment path."""
    with pytest.raises(ValueError, match="stamp_and_attach"):
        _raw_participant(output_price_elasticity=0.5, reference_carbon_price=50.0)


# ── (b) Closed-form reproduction via the plugin-attached overlay ────────────


@pytest.mark.parametrize(
    ("eps", "p_ref", "price"),
    [
        (0.5, 50.0, 50.0),   # at reference: m == 1
        (0.5, 50.0, 60.0),   # +20% over reference: m == 0.90
        (0.5, 50.0, 40.0),   # -20% under reference: m == 1.10
        (2.0, 50.0, 500.0),  # floored at 0
        (0.3, 20.0, 15.0),
        (1.5, 100.0, 10.0),
    ],
)
def test_plugin_attached_participant_reproduces_closed_form(
    eps: float, p_ref: float, price: float
) -> None:
    participant = _raw_participant(output_price_elasticity=eps)
    stamp_and_attach(participant, p_ref)
    expected = max(0.0, 1.0 - eps * (price - p_ref) / p_ref)
    np.testing.assert_allclose(
        participant.activity_multiplier(price), expected, rtol=0, atol=1e-12
    )


def test_overlay_baseline_multiplier_matches_dispatcher():
    """The overlay's own ``baseline_multiplier`` agrees with the dispatcher."""
    overlay = ElasticBaselineOverlay(output_price_elasticity=0.5, reference_carbon_price=50.0)
    for price in (10.0, 50.0, 90.0, 500.0):
        expected = max(0.0, 1.0 - 0.5 * (price - 50.0) / 50.0)
        np.testing.assert_allclose(
            overlay.baseline_multiplier(price), expected, rtol=0, atol=1e-12
        )


# ── (c) eps == 0 participants: unchanged, raise-free ────────────────────────


def test_zero_elasticity_participant_never_raises_and_stays_neutral():
    participant = _raw_participant(output_price_elasticity=0.0)
    # Post-construction stamp, direct field assignment: allowed since eps<=0.
    participant.reference_carbon_price = 50.0
    assert participant.demand_overlays == ()
    assert participant.activity_multiplier(500.0) == 1.0


def test_zero_elasticity_participant_via_stamp_and_attach_gets_no_overlay():
    participant = _raw_participant(output_price_elasticity=0.0)
    stamp_and_attach(participant, 50.0)
    assert participant.reference_carbon_price == 50.0
    assert participant.demand_overlays == ()
    assert participant.activity_multiplier(500.0) == 1.0


def test_disabled_participant_default_state_has_no_overlays():
    participant = _raw_participant()
    assert participant.demand_overlays == ()
    assert participant.activity_multiplier(120.0) == 1.0
