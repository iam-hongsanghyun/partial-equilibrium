"""F6 mechanical invariant — CBAM/sectors doors are reporting/transform-only.

F6 (``docs/blocks-composition-rules.md``): CBAM is a post-clearing REPORTING
overlay, never a price channel; sector logic is attributes + build-time
allocation + aggregation. Armed at the ratchet flip (v1 O14 / v2 O19,
``docs/feature-modules-plan.md`` PLAN v2: the flip "also arm[s] the F6
mechanical check"): the public surface of ``features/cbam/plugin.py`` and
``features/sectors/plugin.py`` may contain ONLY

* ``ParticipantReporter`` / ``SummaryReporter`` implementations (post-clear
  diagnostics columns), or
* ``ParticipantTransform`` implementations (pure build-time raw-dict
  transforms), or
* the pinned build-time derivation function ``derive_sector_pools`` (the
  sector-pool arithmetic the builder host calls — build-time, pre-clearing).

and must NEVER implement a price-formation protocol (``CapRule``,
``PriceOverlay``, ``DemandOverlay``, ``Friction``) — adding one would turn a
reporting door into a price channel, which is exactly the drift F6 forbids.
(``SupplyRule`` shares the ``apply`` method name with
``ParticipantTransform``, so it is excluded from the structural negative
check; a supply rule in a reporting door would still fail the positive check
below unless it faked a transform signature — a review error the
declared-fields discipline catches.)

Fast by construction: imports the two plugin doors and ``core.protocols``
only; no solving.
"""

from __future__ import annotations

import inspect

import pytest

from ets.core.protocols import (
    CapRule,
    DemandOverlay,
    Friction,
    ParticipantReporter,
    ParticipantTransform,
    PriceOverlay,
    SummaryReporter,
)
from ets.features.cbam import plugin as cbam_plugin
from ets.features.sectors import plugin as sectors_plugin

# The only permitted non-class public name: the sector-pool build-time
# derivation (part of the transform pipeline; consumed by config_io's
# builder host literal). Additions require a lead-modeller-approved order.
_PINNED_PUBLIC_FUNCTIONS = {
    "ets.features.sectors.plugin": {"derive_sector_pools"},
    "ets.features.cbam.plugin": set(),
}

_ALLOWED_PROTOCOLS = (ParticipantReporter, SummaryReporter, ParticipantTransform)
_FORBIDDEN_PROTOCOLS = (CapRule, PriceOverlay, DemandOverlay, Friction)


def _public_surface(module) -> dict[str, object]:
    """Names the module deliberately exposes: ``__all__`` if present, else
    every non-underscore name DEFINED in the module (imported names are not
    part of a door's surface)."""
    if hasattr(module, "__all__"):
        return {name: getattr(module, name) for name in module.__all__}
    return {
        name: obj
        for name, obj in vars(module).items()
        if not name.startswith("_")
        and getattr(obj, "__module__", None) == module.__name__
    }


@pytest.mark.parametrize("module", [cbam_plugin, sectors_plugin], ids=lambda m: m.__name__)
def test_f6_plugin_surface_is_reporting_or_transform_only(module) -> None:
    surface = _public_surface(module)
    assert surface, f"{module.__name__}: empty public surface?"

    for name, obj in surface.items():
        if inspect.isclass(obj):
            assert issubclass(obj, _ALLOWED_PROTOCOLS), (
                f"{module.__name__}.{name}: every public class in a "
                "reporting/transform door must implement ParticipantReporter, "
                "SummaryReporter, or ParticipantTransform (F6)."
            )
            for forbidden in _FORBIDDEN_PROTOCOLS:
                assert not issubclass(obj, forbidden), (
                    f"{module.__name__}.{name}: implements "
                    f"{forbidden.__name__} — a price-formation protocol in a "
                    "reporting door is the exact drift F6 forbids."
                )
        elif inspect.isfunction(obj):
            assert name in _PINNED_PUBLIC_FUNCTIONS[module.__name__], (
                f"{module.__name__}.{name}: unpinned public function on a "
                "reporting/transform door (F6); pin it here only with a "
                "lead-modeller-approved order."
            )
        else:
            pytest.fail(
                f"{module.__name__}.{name}: unexpected public object "
                f"({type(obj).__name__}) on a reporting/transform door (F6)."
            )
