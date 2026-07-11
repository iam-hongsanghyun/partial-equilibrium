from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Union

if TYPE_CHECKING:
    from ..protocols import AdoptionSpec, DemandOverlay


CostSpec = Union[float, Callable[[float], float]]


@dataclass(frozen=True)
class TechnologyOption:
    name: str
    initial_emissions: float
    free_allocation_ratio: float
    penalty_price: float
    marginal_abatement_cost: CostSpec
    max_abatement_share: float = 1.0
    max_activity_share: float = 1.0
    fixed_cost: float = 0.0

    def __post_init__(self) -> None:
        if self.initial_emissions < 0:
            raise ValueError(f"{self.name}: initial_emissions must be non-negative.")
        if not 0.0 <= self.free_allocation_ratio <= 1.0:
            raise ValueError(
                f"{self.name}: free_allocation_ratio must be between 0 and 1."
            )
        if self.penalty_price < 0:
            raise ValueError(f"{self.name}: penalty_price must be non-negative (0 = no cap).")
        if not 0.0 <= self.max_abatement_share <= 1.0:
            raise ValueError(
                f"{self.name}: max_abatement_share must be between 0 and 1."
            )
        if not 0.0 <= self.max_activity_share <= 1.0:
            raise ValueError(
                f"{self.name}: max_activity_share must be between 0 and 1."
            )
        if self.fixed_cost < 0:
            raise ValueError(f"{self.name}: fixed_cost must be non-negative.")

    @property
    def free_allocation(self) -> float:
        return self.initial_emissions * self.free_allocation_ratio

    @property
    def max_abatement(self) -> float:
        return self.initial_emissions * self.max_abatement_share


@dataclass
class ComplianceOutcome:
    abatement: float
    residual_emissions: float
    allowance_buys: float
    allowance_sells: float
    penalty_emissions: float
    abatement_cost: float
    allowance_cost: float
    penalty_cost: float
    sales_revenue: float
    fixed_cost: float
    technology_name: str
    initial_emissions: float
    free_allocation: float
    penalty_price: float
    starting_bank_balance: float
    ending_bank_balance: float
    expected_future_price: float
    banked_allowances: float
    borrowed_allowances: float
    total_cost: float
    technology_mix: tuple[tuple[str, float], ...] = ()

    @property
    def net_allowances_traded(self) -> float:
        return self.allowance_buys - self.allowance_sells


@dataclass
class MarketParticipant:
    """
    A heterogeneous ETS participant with optional endogenous technology choice.
    """

    name: str
    initial_emissions: float
    marginal_abatement_cost: CostSpec
    free_allocation_ratio: float
    penalty_price: float
    max_abatement_share: float = 1.0
    technology_options: list[TechnologyOption] | None = None
    # CBAM exposure — single-jurisdiction shorthand (EU)
    cbam_export_share: float = 0.0    # share of activity exported to CBAM-covered markets (0–1)
    cbam_coverage_ratio: float = 1.0  # fraction of embedded emissions covered by CBAM (0–1)
    # Multi-jurisdiction CBAM — list of {name, export_share, coverage_ratio}
    # If non-empty, overrides the single-jurisdiction fields above for CBAM calculation.
    cbam_jurisdictions: list = field(default_factory=list)
    # Sector classification for grouped reporting (e.g. "Steel", "Petrochemical")
    sector_group: str = ""
    # Sector-level allocation: participant's share of their sector's free pool (0–1)
    sector_allocation_share: float = 0.0
    # Indirect / Scope 2 emissions — electricity-based
    # indirect_emissions = electricity_consumption × grid_emission_factor
    # scope2_cbam_coverage: fraction of indirect embedded emissions covered by CBAM (0 = not covered)
    electricity_consumption: float = 0.0   # MWh (or any consistent energy unit)
    grid_emission_factor: float = 0.0      # tCO2/MWh (grid average or marginal)
    scope2_cbam_coverage: float = 0.0      # 0–1; 0 = Scope 2 not in CBAM scope
    # Output-based allocation (OBA) / benchmark
    # free_allocation = benchmark_emission_intensity × production_output (overrides ratio when set)
    production_output: float = 0.0             # units/yr (e.g. Mt steel)
    benchmark_emission_intensity: float = 0.0  # tCO2/unit
    # ── Option A: price-elastic baseline (within-clearing feedback) ──────────
    # Carbon-intensive activity (and hence the BAU baseline) contracts as the
    # carbon price rises above a reference anchor.  output_price_elasticity ε ≥ 0
    # is the (linearised) price elasticity of activity; reference_carbon_price
    # P_ref > 0 is the anchor at which activity is undistorted.  ε = 0 OR
    # P_ref = 0 disables the channel (baseline stays fixed — identical to before).
    output_price_elasticity: float = 0.0       # ε, dimensionless (≥ 0)
    reference_carbon_price: float = 0.0        # P_ref, price units (0 disables)
    # Attached demand overlays (``core.protocols.DemandOverlay``) — today at
    # most one, the price-elastic baseline (``features.elastic_baseline``);
    # ``activity_multiplier`` below dispatches over this tuple. Empty means
    # no demand-side feedback (product-over-empty-tuple == 1.0, the
    # pre-refactor no-op).
    demand_overlays: tuple[DemandOverlay, ...] = ()
    # Attached investment-trigger declarations (``core.protocols.AdoptionSpec``)
    # for the endogenous-investment feedback loop — the ``demand_overlays``
    # pattern: neutral default ``()`` means the participant is invisible to the
    # investment feature (no flagged technologies, no code-path change). The
    # ONLY sanctioned writer is ``features.endogenous_investment.plugin
    # .attach_adoption_specs`` (arrives with the feature runtime, EI-4/EI-6);
    # no construction site sets this field directly.
    adoption_specs: tuple[AdoptionSpec, ...] = ()

    # Fields that jointly determine whether the price-elastic baseline
    # channel is active; mutating any of them re-validates the loud guard
    # below (``_validate_elastic_guard``) so post-construction stamping can
    # never silently leave an active channel without its overlay — see
    # ``__setattr__`` and ``features/elastic_baseline/plugin.py``
    # ``stamp_and_attach`` (the ONLY sanctioned post-construction mutator).
    _ELASTIC_GUARD_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"output_price_elasticity", "reference_carbon_price", "demand_overlays"}
    )

    def __post_init__(self) -> None:
        self._validate_state(
            self.name,
            self.initial_emissions,
            self.free_allocation_ratio,
            self.penalty_price,
            self.max_abatement_share,
        )
        if self.technology_options:
            for option in self.technology_options:
                if not isinstance(option, TechnologyOption):
                    raise ValueError(
                        f"{self.name}: technology_options must contain TechnologyOption instances."
                    )
        if self.output_price_elasticity < 0:
            raise ValueError(
                f"{self.name}: output_price_elasticity must be non-negative."
            )
        if self.reference_carbon_price < 0:
            raise ValueError(
                f"{self.name}: reference_carbon_price must be non-negative."
            )
        self._validate_elastic_guard()
        # Arms `__setattr__`'s revalidation for every assignment from here
        # on — see `_validate_elastic_guard` / `__setattr__` docstrings.
        self._elastic_guard_armed = True

    def __setattr__(self, name: str, value: Any) -> None:
        """Set an attribute, then re-validate the elastic-baseline guard.

        Any post-construction assignment to ``output_price_elasticity``,
        ``reference_carbon_price``, or ``demand_overlays`` re-runs
        ``_validate_elastic_guard`` immediately after the write (once
        ``__post_init__`` has armed the check — during ``__post_init__``
        itself the fields are set one at a time by the generated
        ``__init__`` and are not yet all consistent). This is what closes
        the bypass the Arbitration outcomes (O8, binding) require: a bare
        ``participant.reference_carbon_price = x`` on an elastic participant
        with no overlay attached raises immediately, instead of silently
        leaving the channel active-but-unwired. ``stamp_and_attach``
        (``features/elastic_baseline/plugin.py``) is the validated path —
        it always attaches the overlay before (or in the same call as) the
        price stamp, so it never trips this guard.

        Args:
            name: Attribute name being set.
            value: New value.

        Raises:
            ValueError: via ``_validate_elastic_guard`` if the write leaves
                the elastic-baseline channel active without an overlay.
        """
        super().__setattr__(name, value)
        if name in self._ELASTIC_GUARD_FIELDS and getattr(
            self, "_elastic_guard_armed", False
        ):
            self._validate_elastic_guard()

    def _validate_elastic_guard(self) -> None:
        """Raise if the elastic-baseline channel is active without its overlay.

        The loud guard the Arbitration outcomes (O8, binding) mandate:
        ``output_price_elasticity > 0`` and ``reference_carbon_price > 0``
        jointly activate the price-elastic baseline (mirroring
        ``activity_multiplier``'s activation predicate); an active channel
        MUST carry at least one ``demand_overlays`` entry, or the baseline
        would silently stay fixed even though the scenario config says it
        should contract. Checked at construction (``__post_init__``) AND at
        every subsequent mutation of the three fields it reads
        (``__setattr__``) — a guard that only fired in ``__post_init__``
        would miss ``config_io/builder.py``'s post-construction
        ``reference_carbon_price`` stamp, which is exactly the bypass this
        guard exists to close.

        Raises:
            ValueError: if ``output_price_elasticity > 0`` and
                ``reference_carbon_price > 0`` but ``demand_overlays`` is
                empty.
        """
        if (
            self.output_price_elasticity > 0.0
            and self.reference_carbon_price > 0.0
            and not self.demand_overlays
        ):
            raise ValueError(
                f"{self.name}: output_price_elasticity="
                f"{self.output_price_elasticity!r} and reference_carbon_price="
                f"{self.reference_carbon_price!r} are both active, but no demand "
                "overlay is attached — the price-elastic baseline would silently "
                "never contract. Use "
                "ets.features.elastic_baseline.plugin.stamp_and_attach(participant, "
                "reference_carbon_price) to stamp reference_carbon_price and attach "
                "the ElasticBaselineOverlay together; a direct "
                "`participant.reference_carbon_price = ...` assignment bypasses the "
                "overlay and is rejected."
            )

    @staticmethod
    def _validate_state(
        label: str,
        initial_emissions: float,
        free_allocation_ratio: float,
        penalty_price: float,
        max_abatement_share: float,
    ) -> None:
        if initial_emissions < 0:
            raise ValueError(f"{label}: initial_emissions must be non-negative.")
        if not 0.0 <= free_allocation_ratio <= 1.0:
            raise ValueError(
                f"{label}: free_allocation_ratio must be between 0 and 1."
            )
        if penalty_price < 0:
            raise ValueError(f"{label}: penalty_price must be non-negative (0 = no cap).")
        if not 0.0 <= max_abatement_share <= 1.0:
            raise ValueError(
                f"{label}: max_abatement_share must be between 0 and 1."
            )

    @property
    def free_allocation(self) -> float:
        return self.initial_emissions * self.free_allocation_ratio

    @property
    def max_abatement(self) -> float:
        return self.initial_emissions * self.max_abatement_share

    def activity_multiplier(self, carbon_price: float) -> float:
        r"""Demand-overlay dispatcher: activity scaling for the BAU baseline.

        Product over every attached ``demand_overlays`` entry (today at most
        one — the price-elastic baseline, Option A,
        ``features.elastic_baseline.plugin.ElasticBaselineOverlay``); the
        baseline emissions, abatement potential, and benchmarked free
        allocation all scale by the returned factor. An empty
        ``demand_overlays`` tuple is the pre-refactor no-op: the product over
        zero factors is 1.0, identical to the old ``eps <= 0 or P_ref <= 0``
        early return, since a participant with the elastic channel disabled
        never gets an overlay attached (``features.elastic_baseline.plugin
        .stamp_and_attach``; see ``MarketParticipant``'s loud guard, which
        makes the reverse — an active channel with no overlay — impossible
        to construct).

        Algorithm:
            LaTeX:  $$m(P) = \prod_i m_i(P)$$
                    with, for the price-elastic overlay,
                    $m_i(P) = \max\!\left(0,\; 1 - \varepsilon\,
                    \frac{P - P_\mathrm{ref}}{P_\mathrm{ref}}\right)$
            ASCII:  m(P) = prod(overlay.baseline_multiplier(P) for overlay
                    in demand_overlays); elastic overlay:
                    m_i(P) = max(0, 1 - eps * (P - P_ref) / P_ref)

        Symbols:
            P      : carbon price (price units)
            P_ref  : reference (undistorted) carbon price; reference_carbon_price
            eps    : output_price_elasticity ε (dimensionless, ≥ 0)

        At P = P_ref the (single, elastic) multiplier is 1; it falls
        linearly as P rises and is floored at 0.

        Args:
            carbon_price: Carbon price P (price units).

        Returns:
            Dimensionless multiplier m(P) >= 0; 1.0 with no overlays
            attached.
        """
        multiplier = 1.0
        for overlay in self.demand_overlays:
            multiplier *= overlay.baseline_multiplier(carbon_price)
        return multiplier

    # ── Delegate methods — implementation lives in compliance.py / technology.py ──

    def _default_technology(self) -> TechnologyOption:
        from .technology import _default_technology
        return _default_technology(self)

    def _available_technologies(self) -> list[TechnologyOption]:
        from .technology import _available_technologies
        return _available_technologies(self)

    def _abatement_cost(
        self, technology: TechnologyOption, abatement: float, activity_share: float = 1.0
    ) -> float:
        from .compliance import _abatement_cost
        return _abatement_cost(self, technology, abatement, activity_share)

    def _finalize_inventory(
        self,
        *,
        residual_emissions: float,
        free_allocation: float,
        carbon_price: float,
        penalty_price: float,
        starting_bank_balance: float,
        expected_future_price: float,
        banking_allowed: bool,
        borrowing_allowed: bool,
        borrowing_limit: float,
    ) -> dict[str, float]:
        from .compliance import _finalize_inventory
        return _finalize_inventory(
            residual_emissions=residual_emissions,
            free_allocation=free_allocation,
            carbon_price=carbon_price,
            penalty_price=penalty_price,
            starting_bank_balance=starting_bank_balance,
            expected_future_price=expected_future_price,
            banking_allowed=banking_allowed,
            borrowing_allowed=borrowing_allowed,
            borrowing_limit=borrowing_limit,
        )

    def _total_compliance_cost(
        self,
        technology: TechnologyOption,
        abatement: float,
        carbon_price: float,
        starting_bank_balance: float,
        expected_future_price: float,
        banking_allowed: bool,
        borrowing_allowed: bool,
        borrowing_limit: float,
    ) -> float:
        from .compliance import _total_compliance_cost
        return _total_compliance_cost(
            self, technology, abatement, carbon_price,
            starting_bank_balance, expected_future_price,
            banking_allowed, borrowing_allowed, borrowing_limit,
        )

    def _optimize_for_technology(
        self,
        technology: TechnologyOption,
        carbon_price: float,
        starting_bank_balance: float,
        expected_future_price: float,
        banking_allowed: bool,
        borrowing_allowed: bool,
        borrowing_limit: float,
    ) -> ComplianceOutcome:
        from .compliance import _optimize_for_technology
        return _optimize_for_technology(
            self, technology, carbon_price,
            starting_bank_balance, expected_future_price,
            banking_allowed, borrowing_allowed, borrowing_limit,
        )

    def _optimize_mixed_technology_portfolio(
        self,
        technologies: list[TechnologyOption],
        carbon_price: float,
        starting_bank_balance: float,
        expected_future_price: float,
        banking_allowed: bool,
        borrowing_allowed: bool,
        borrowing_limit: float,
        slsqp_max_iters: int = 400,
        slsqp_ftol: float = 1e-9,
    ) -> ComplianceOutcome:
        from .compliance import _optimize_mixed_technology_portfolio
        return _optimize_mixed_technology_portfolio(
            self, technologies, carbon_price,
            starting_bank_balance, expected_future_price,
            banking_allowed, borrowing_allowed, borrowing_limit,
            slsqp_max_iters=slsqp_max_iters,
            slsqp_ftol=slsqp_ftol,
        )

    def optimize_compliance(
        self,
        carbon_price: float,
        starting_bank_balance: float = 0.0,
        expected_future_price: float = 0.0,
        banking_allowed: bool = False,
        borrowing_allowed: bool = False,
        borrowing_limit: float = 0.0,
        slsqp_max_iters: int = 400,
        slsqp_ftol: float = 1e-9,
    ) -> ComplianceOutcome:
        from .compliance import optimize_compliance
        return optimize_compliance(
            self, carbon_price,
            starting_bank_balance=starting_bank_balance,
            expected_future_price=expected_future_price,
            banking_allowed=banking_allowed,
            borrowing_allowed=borrowing_allowed,
            borrowing_limit=borrowing_limit,
            slsqp_max_iters=slsqp_max_iters,
            slsqp_ftol=slsqp_ftol,
        )

    def abatement_amount(self, carbon_price: float, **kwargs: float) -> float:
        return self.optimize_compliance(carbon_price, **kwargs).abatement

    def residual_emissions(self, carbon_price: float, **kwargs: float) -> float:
        return self.optimize_compliance(carbon_price, **kwargs).residual_emissions

    def allowance_demand_or_supply(self, carbon_price: float, **kwargs: float) -> float:
        return self.optimize_compliance(carbon_price, **kwargs).net_allowances_traded
