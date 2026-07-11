r"""OBA plugin door — output-based free-allocation transform (T2).

Two-door feature (``docs/feature-modules-plan.md`` PLAN v2 §"Two-door
features"): this module is the ONLY thing ``config_io`` may import from
``ets.features.oba`` (the door rule). OBA has no runtime module — it is a
pure build-time ``ParticipantTransform`` (feature verdicts v2: "oba
(build-time transform, builder.py:412-424 — plugin-only)"). Imports nothing
but stdlib: the transform is pure dict arithmetic, no ``ets.core`` types are
needed at the call boundary.

``OBABenchmarkAllocation`` is relocated VERBATIM from the pre-refactor
``config_io/builder.py`` (the "Apply Output-Based Allocation (OBA)
overrides" block, historically lines 442-454 of ``build_market_from_year``):
same guard, same expressions, same variable names.

Ordering (Arbitration outcomes, O9 literal-pin additions, BINDING): this
transform MUST run AFTER the host's trajectory patch — it reads
``initial_emissions`` off the ``raw`` dict, and that field carries the
trajectory-PATCHED value once the trajectory-patch step has run earlier in
the pipeline. Its write to ``free_allocation_ratio`` OVERWRITES whatever an
earlier step (the sectors pool allocation, ``features.sectors.plugin
.SectorPoolAllocation``) wrote for the same participant — a documented
cross-feature coupling through the raw-dict medium (precedence OBA > sector
> per-year). Both are pinned by ``config_io/builder.py``'s
``_PARTICIPANT_TRANSFORMS`` literal order, not just this docstring —
``tests/test_builder_pipeline.py`` enforces the order and the coupling.

References:
    docs/feature-modules-plan.md — PLAN v2 §"Two-door features", "Feature
    verdicts v2"; Arbitration outcomes (O9 binding literal-pin additions).
    core/protocols.py — ``ParticipantTransform`` (declared-fields discipline,
    purity contract).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["OBABenchmarkAllocation"]


class OBABenchmarkAllocation:
    r"""Output-Based Allocation (OBA): benchmark intensity x output overrides the ratio.

    Algorithm:
        LaTeX:
        $$ A_{\mathrm{free}} = \iota_{\mathrm{bench}} \cdot Q_{\mathrm{out}},
           \qquad r_{\mathrm{free}} = \min\!\left(1,\;
           \frac{A_{\mathrm{free}}}{e_0}\right) $$

        ASCII fallback:
            free_alloc_mt          = benchmark_emission_intensity * production_output
            free_allocation_ratio  = min(1.0, free_alloc_mt / initial_emissions)

        Symbols (units):
            iota_bench : ``benchmark_emission_intensity``, benchmark emission
                         intensity per unit of output          [tCO2e/unit]
            Q_out      : ``production_output``, output volume    [unit/yr]
            e0         : ``initial_emissions`` (the PATCHED value read off
                         ``raw`` — this transform must run after the
                         trajectory patch, see module docstring)  [Mt CO2e]
            A_free     : implied free allocation from the benchmark
                                                                    [Mt CO2e]
            r_free     : ``free_allocation_ratio``, dimensionless (0-1)

    Active only when ``production_output``, ``benchmark_emission_intensity``,
    and ``initial_emissions`` are all strictly positive (the original guard,
    preserved verbatim); a participant failing the guard passes through
    unchanged.

    Declared fields (``core/protocols.py`` ``ParticipantTransform``
    declared-fields discipline):
        Reads: ``production_output``, ``benchmark_emission_intensity``,
            ``initial_emissions``.
        Writes: ``free_allocation_ratio`` — OVERWRITES any value an earlier
            transform in the pipeline wrote (e.g. the sectors pool
            allocation; Arbitration outcomes, O9).
    """

    def apply(
        self, raw: dict[str, Any], year_num: float, meta: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Override ``free_allocation_ratio`` from the OBA benchmark, if configured.

        Args:
            raw: The participant's raw config dict for this year. Must
                already carry the trajectory-patched ``initial_emissions``
                (this transform must run after the trajectory patch — see
                module docstring). Not mutated.
            year_num: Unused (OBA has no trajectory of its own); accepted
                only for ``ParticipantTransform`` conformance.
            meta: Unused; accepted only for ``ParticipantTransform``
                conformance.

        Returns:
            A new dict with ``free_allocation_ratio`` overridden when
            ``production_output``, ``benchmark_emission_intensity``, and
            ``initial_emissions`` are all positive; ``raw`` itself
            (unchanged) otherwise.
        """
        po = float(raw.get("production_output") or 0.0)
        bei = float(raw.get("benchmark_emission_intensity") or 0.0)
        ie = float(raw.get("initial_emissions") or 0.0)
        if po > 0 and bei > 0 and ie > 0:
            free_alloc_mt = bei * po
            return {**raw, "free_allocation_ratio": min(1.0, free_alloc_mt / ie)}
        return raw
