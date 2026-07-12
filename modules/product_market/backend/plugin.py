r"""product_market plugin door — product-body field/structural validation (T2).

Two-door feature (``docs/feature-modules-plan.md`` PLAN v2 §"Two-door
features"): this module is the ONLY thing ``config_io`` may import from
``pe.features.product_market`` (the door rule; enforced by
``tests/test_module_isolation.py``'s ``_is_plugin_door``). It imports stdlib
only — no ``pe.core``, no runtime.

D3-3 scope (``docs/multi-commodity-plan.md`` §6 D3-3, §5; ``docs/multi-commodity
-spec.md`` §1/§6/§7 V-D3-3): :func:`normalize_product_body` validates and
normalises a ``model_approach: "product"`` market body — a goods market that
clears on a behavioural demand curve against optimising producer supply, not a
compliance-obligation flow. It carries:

* ``product_demand`` — the behavioural demand curve (linear ``{intercept, slope}``
  or ``isoelastic`` ``{kappa, eta}``; spec §1 [JC1]);
* ``import_supply`` — carbon-free elastic imports ``M = M_0 + m·P_s`` with an
  optional price-active CBAM shift (spec §1, §4e/§4f);
* ``carbon_price`` — the EXOGENOUS carbon price at which the standalone product
  market is solvable (D3-4 replaces this with the coupled ``P_carbon``; keeping
  it here is what makes the market solvable STANDALONE in D3-3, plan §6);
* ``kind: "producer"`` participants — the two-margin
  :class:`~pe.core.participant.producer.MultiCommodityProducer` structural
  parameters (``output_cost`` γ/δ, ``intensity`` σ, ``abatement`` β/a_max,
  ``oba_benchmark`` φ, ``F_lump``, ``capacity``).

Nothing here builds a market, a producer object, or a curve — that is the
runtime door (``solver.py``, engine-only) and the builder. This is field
validation of the config door: every violation raises a loud, label-prefixed
``ValueError`` (never a silent clamp), mirroring ``market_links.plugin``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "DEFAULTS",
    "normalize_product_body",
]

# ── Inert defaults (module DEFAULTS dict; no hardcoded economic constants at
# call sites, house rules). Every default is a NEUTRAL / off value: a product
# body that sets nothing beyond the required structural fields normalises to an
# inert configuration (no carbon price, no imports, CBAM off, no OBA/lump-sum).
DEFAULTS: dict[str, Any] = {
    "carbon_price": 0.0,  # currency/tCO2 — exogenous P_c; 0 = no carbon cost
    "demand_form": "linear",  # linear closed-form anchor vs isoelastic
    "demand_intercept": 0.0,  # A_d [t-steel/period] (linear)
    "demand_slope": 0.0,  # b_d [t-steel/period per currency/t] (linear)
    "demand_kappa": 0.0,  # kappa [t-steel·(currency/t)^eta] (isoelastic)
    "demand_eta": 1.0,  # eta [dimensionless], own-price elasticity (isoelastic)
    "import_m_0": 0.0,  # M_0 [t-steel/period] — autonomous imports
    "import_m": 0.0,  # m [t-steel/period per currency/t] — import price slope
    "cbam_enabled": False,  # price-active CBAM shift off by default
    "cbam_coverage": 0.0,  # c [dimensionless] in [0, 1]
    "cbam_sigma_foreign": 0.0,  # sigma_foreign [tCO2/t-steel]
    "producer_phi_oba": 0.0,  # phi_OBA [tCO2/t-steel] — OBA benchmark
    "producer_f_lump": 0.0,  # F_lump [tCO2/yr] — lump-sum free allocation
}

_ALLOWED_DEMAND_FORMS = ("linear", "isoelastic")
_PRODUCER_KIND = "producer"


def _as_mapping(value: Any, *, label: str, what: str) -> Mapping[str, Any]:
    """Return ``value`` as a mapping or raise a labelled ``ValueError``."""
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}: {what} must be an object, got {type(value).__name__}.")
    return value


def _fnum(raw: Mapping[str, Any], key: str, default: float, *, label: str) -> float:
    """Coerce ``raw[key]`` to float (falling back to ``default``), or raise."""
    if key not in raw or raw[key] is None:
        return float(default)
    try:
        return float(raw[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: {key} must be a number, got {raw[key]!r}.") from exc


def _fnum_alias(
    raw: Mapping[str, Any], keys: tuple[str, ...], default: float, *, label: str
) -> float:
    """Coerce the first present of ``keys`` (aliases) to float, else ``default``.

    Idempotency helper: normalisation runs twice in this codebase
    (``build_markets_from_config`` re-normalises an already-normalised body, as
    the carbon path does), so every sub-normaliser must round-trip its OWN
    output. Reading both the raw config spelling and the normalised spelling of
    each field is what makes ``normalize_product_body`` a fixed point.
    """
    for key in keys:
        if key in raw and raw[key] is not None:
            return _fnum(raw, key, default, label=label)
    return float(default)


def _normalize_product_demand(raw: Any, *, label: str) -> dict[str, Any]:
    """Normalise the ``product_demand`` curve spec (spec §1 [JC1]).

    Linear ``{form: "linear", intercept: A_d, slope: b_d}`` is the closed-form
    anchor; ``{form: "isoelastic", kappa, eta}`` is the numeric option. Both
    slopes/elasticities are validated for the monotone (downward) demand the
    T0 primitive's unique-root guarantee rests on. Idempotent: the normalised
    ``a_d``/``b_d`` spellings are accepted alongside the raw ``intercept``/
    ``slope``.
    """
    demand = _as_mapping(raw, label=label, what="product_demand")
    form = str(demand.get("form", DEFAULTS["demand_form"])).strip()
    if form not in _ALLOWED_DEMAND_FORMS:
        raise ValueError(
            f"{label}: product_demand.form must be one of {list(_ALLOWED_DEMAND_FORMS)}, "
            f"got {form!r}."
        )
    if form == "linear":
        a_d = _fnum_alias(demand, ("a_d", "intercept"), DEFAULTS["demand_intercept"], label=label)
        b_d = _fnum_alias(demand, ("b_d", "slope"), DEFAULTS["demand_slope"], label=label)
        if b_d < 0.0:
            raise ValueError(
                f"{label}: product_demand.slope (b_d) must be >= 0 — demand must be "
                f"downward-sloping in P_s, got {b_d}."
            )
        return {"form": "linear", "a_d": a_d, "b_d": b_d}
    kappa = _fnum(demand, "kappa", DEFAULTS["demand_kappa"], label=label)
    eta = _fnum(demand, "eta", DEFAULTS["demand_eta"], label=label)
    if kappa < 0.0:
        raise ValueError(f"{label}: product_demand.kappa must be >= 0, got {kappa}.")
    if eta <= 0.0:
        raise ValueError(f"{label}: product_demand.eta must be > 0, got {eta}.")
    return {"form": "isoelastic", "kappa": kappa, "eta": eta}


def _normalize_import_supply(raw: Any, *, label: str) -> dict[str, Any]:
    """Normalise the ``import_supply`` block ``M = M_0 + m·P_s`` (+ optional CBAM).

    ``world_price`` is accepted as an alias for the autonomous-import level
    ``M_0`` (``m_0``); ``slope`` as an alias for the import price-slope ``m``.
    The optional ``cbam`` sub-dict configures the price-active CBAM shift
    (spec §4e); it is left OFF by default (``cbam.enabled: false``). Idempotent:
    the normalised flat ``cbam_enabled``/``coverage``/``sigma_foreign`` spellings
    are accepted alongside the raw nested ``cbam`` sub-dict.
    """
    imports = _as_mapping(raw, label=label, what="import_supply")
    m_0 = _fnum_alias(imports, ("m_0", "world_price"), DEFAULTS["import_m_0"], label=label)
    m = _fnum_alias(imports, ("m", "slope"), DEFAULTS["import_m"], label=label)
    if m < 0.0:
        raise ValueError(
            f"{label}: import_supply slope (m) must be >= 0 — import supply must be "
            f"upward-sloping in P_s, got {m}."
        )

    raw_cbam = imports.get("cbam")
    if raw_cbam is None and "cbam_enabled" in imports:
        # Already-normalised (flat) shape — re-wrap so the one validation path
        # below runs on both first and second normalisation passes.
        raw_cbam = {
            "enabled": imports.get("cbam_enabled"),
            "coverage": imports.get("coverage"),
            "sigma_foreign": imports.get("sigma_foreign"),
        }
    if raw_cbam is None:
        cbam_enabled = bool(DEFAULTS["cbam_enabled"])
        coverage = float(DEFAULTS["cbam_coverage"])
        sigma_foreign = float(DEFAULTS["cbam_sigma_foreign"])
    else:
        cbam = _as_mapping(raw_cbam, label=label, what="import_supply.cbam")
        cbam_enabled = bool(cbam.get("enabled", DEFAULTS["cbam_enabled"]))
        coverage = _fnum(cbam, "coverage", DEFAULTS["cbam_coverage"], label=label)
        sigma_foreign = _fnum(cbam, "sigma_foreign", DEFAULTS["cbam_sigma_foreign"], label=label)
        if not 0.0 <= coverage <= 1.0:
            raise ValueError(
                f"{label}: import_supply.cbam.coverage (c) must be in [0, 1], got {coverage}."
            )
        if sigma_foreign < 0.0:
            raise ValueError(
                f"{label}: import_supply.cbam.sigma_foreign must be >= 0, got {sigma_foreign}."
            )
    return {
        "m_0": m_0,
        "m": m,
        "cbam_enabled": cbam_enabled,
        "coverage": coverage,
        "sigma_foreign": sigma_foreign,
    }


def _normalize_producer(raw: Any, *, index: int, label: str) -> dict[str, Any]:
    """Normalise one ``kind: "producer"`` participant's structural parameters.

    Mirrors :class:`~pe.core.participant.producer.ProducerParams`'s field set
    and bounds (γ/δ output cost, σ intensity, β/a_max abatement, φ OBA, F_lump,
    capacity) so a malformed producer is rejected at config time — δ > 0 and
    β > 0 are REQUIRED (spec §2 [JC3], V-D3-1: δ ≤ 0 gives indeterminate output;
    β ≤ 0 makes the intensity FOC ill-posed). ``capacity`` is parsed and carried
    for downstream levers but not clamped in the D3-3 shell. Idempotent: both the
    raw nested spelling (``output_cost``/``abatement``/``intensity``/
    ``oba_benchmark``/``F_lump``) and the normalised flat spelling
    (``gamma``/``delta``/``sigma``/``beta``/``a_max``/``phi_oba``/``f_lump``) are
    accepted, so the second normalisation pass round-trips.
    """
    prod_label = f"{label} participants[{index}]"
    participant = _as_mapping(raw, label=prod_label, what="participant")

    kind = str(participant.get("kind", _PRODUCER_KIND)).strip()
    if kind != _PRODUCER_KIND:
        raise ValueError(
            f"{prod_label}: a product market accepts only kind {_PRODUCER_KIND!r} "
            f"participants, got {kind!r}."
        )
    name = str(participant.get("name", "")).strip()
    if not name:
        raise ValueError(f"{prod_label}: producer must have a non-empty name.")

    output_cost = _as_mapping(
        participant.get("output_cost", {}), label=prod_label, what="output_cost"
    )
    gamma = _fnum_alias({**participant, **output_cost}, ("gamma",), 0.0, label=prod_label)
    delta = _fnum_alias({**participant, **output_cost}, ("delta",), 0.0, label=prod_label)

    sigma = _fnum_alias(participant, ("sigma", "intensity"), 0.0, label=prod_label)

    abatement = _as_mapping(participant.get("abatement", {}), label=prod_label, what="abatement")
    beta = _fnum_alias({**participant, **abatement}, ("beta",), 0.0, label=prod_label)
    a_max = _fnum_alias({**participant, **abatement}, ("a_max",), 0.0, label=prod_label)

    phi_oba = _fnum_alias(
        participant, ("phi_oba", "oba_benchmark"), DEFAULTS["producer_phi_oba"], label=prod_label
    )
    f_lump = _fnum_alias(
        participant, ("f_lump", "F_lump"), DEFAULTS["producer_f_lump"], label=prod_label
    )

    capacity_raw = participant.get("capacity")
    capacity = (
        None
        if capacity_raw is None
        else _fnum({"capacity": capacity_raw}, "capacity", 0.0, label=prod_label)
    )

    # Bounds mirror ProducerParams.__post_init__ so the failure is loud at
    # config time (naming the producer) rather than deep in the solver.
    if not delta > 0.0:
        raise ValueError(
            f"{prod_label} ({name!r}): output_cost.delta must be > 0 — δ ≤ 0 gives a "
            f"horizontal marginal cost and indeterminate output (spec §2 [JC3]), got {delta}."
        )
    if not beta > 0.0:
        raise ValueError(
            f"{prod_label} ({name!r}): abatement.beta must be > 0 — the intensity FOC "
            f"a = P_c/β is otherwise ill-posed, got {beta}."
        )
    for field_name, value in (
        ("output_cost.gamma", gamma),
        ("intensity", sigma),
        ("abatement.a_max", a_max),
        ("oba_benchmark", phi_oba),
        ("F_lump", f_lump),
    ):
        if value < 0.0:
            raise ValueError(f"{prod_label} ({name!r}): {field_name} must be >= 0, got {value}.")
    if capacity is not None and capacity < 0.0:
        raise ValueError(f"{prod_label} ({name!r}): capacity must be >= 0, got {capacity}.")

    return {
        "name": name,
        "gamma": gamma,
        "delta": delta,
        "sigma": sigma,
        "beta": beta,
        "a_max": a_max,
        "phi_oba": phi_oba,
        "f_lump": f_lump,
        "capacity": capacity,
    }


def _normalize_years(raw_years: Any, *, label: str) -> list[dict[str, Any]]:
    """Normalise the product body's ``years`` list (producers per year).

    Each year carries a non-empty ``year`` label and a non-empty list of
    ``kind: "producer"`` participants; the builder constructs one product market
    per year (mirroring the carbon builder's per-year construction). Idempotent:
    the normalised ``producers`` list is accepted alongside the raw
    ``participants`` list, so the second normalisation pass round-trips.
    """
    if not isinstance(raw_years, list) or not raw_years:
        raise ValueError(f"{label} must contain a non-empty 'years' list.")
    years: list[dict[str, Any]] = []
    for year_index, raw_year in enumerate(raw_years):
        year = _as_mapping(raw_year, label=f"{label} years[{year_index}]", what="year")
        year_label = str(year.get("year", "")).strip()
        if not year_label:
            raise ValueError(f"{label} years[{year_index}]: must have a non-empty year label.")
        raw_participants = year.get("participants")
        if raw_participants is None:
            raw_participants = year.get("producers")
        if not isinstance(raw_participants, list) or not raw_participants:
            raise ValueError(
                f"{label} year '{year_label}': must have a non-empty 'participants' list "
                "of kind 'producer'."
            )
        producers = [
            _normalize_producer(item, index=i, label=f"{label} year '{year_label}'")
            for i, item in enumerate(raw_participants)
        ]
        names = [p["name"] for p in producers]
        if len(set(names)) != len(names):
            raise ValueError(f"{label} year '{year_label}': duplicate producer name(s) {names}.")
        years.append({"year": year_label, "producers": producers})
    return years


def normalize_product_body(raw_body: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    """Validate + normalise a ``model_approach: "product"`` market body (D3-3).

    The config door for a product market. Called by ``config_io`` (from
    ``builder._normalize_market_body``) when a body declares
    ``model_approach: "product"``; returns a normalised body the builder stamps
    onto an (inert-cap) :class:`~pe.core.market.CarbonMarket` for the engine's
    ``"product"`` dispatch branch to solve STANDALONE at the exogenous
    ``carbon_price`` (plan §6 D3-3, spec §6/§7 V-D3-3).

    Args:
        raw_body: The raw product market body (a whole raw scenario dict for the
            flat single-market caller, or one ``markets[i]`` entry for the
            multi-market caller). Must declare ``model_approach: "product"``.
        label: Error-message prefix, e.g. ``"Scenario 'steel'"`` or
            ``"Market 'steel'"``.

    Returns:
        The normalised product body dict:

        * ``"model_approach": "product"``;
        * ``"carbon_price"``: exogenous P_c [currency/tCO2];
        * ``"product_demand"``: ``{form, a_d, b_d}`` (linear) or
          ``{form, kappa, eta}`` (isoelastic);
        * ``"import_supply"``: ``{m_0, m, cbam_enabled, coverage, sigma_foreign}``;
        * ``"years"``: ``[{year, producers: [{name, gamma, delta, sigma, beta,
          a_max, phi_oba, f_lump, capacity}, ...]}, ...]``.

    Raises:
        ValueError: ``model_approach`` is not ``"product"``; a missing/malformed
            ``product_demand``/``import_supply``/``years``; a producer with
            ``delta <= 0`` / ``beta <= 0`` / a negative parameter; a duplicate
            producer name; a non-``producer`` participant kind; or a negative
            ``carbon_price``.
    """
    body = _as_mapping(raw_body, label=label, what="product market body")
    model_approach = str(body.get("model_approach", "")).strip()
    if model_approach != "product":
        raise ValueError(
            f"{label}: normalize_product_body requires model_approach 'product', "
            f"got {model_approach!r}."
        )

    carbon_price = _fnum(body, "carbon_price", DEFAULTS["carbon_price"], label=label)
    if carbon_price < 0.0:
        raise ValueError(f"{label}: carbon_price must be >= 0, got {carbon_price}.")

    if "product_demand" not in body or body["product_demand"] is None:
        raise ValueError(f"{label}: a product market requires a 'product_demand' block.")
    product_demand = _normalize_product_demand(body["product_demand"], label=label)

    raw_imports = body.get("import_supply")
    import_supply = (
        _normalize_import_supply(raw_imports, label=label)
        if raw_imports is not None
        else {
            "m_0": float(DEFAULTS["import_m_0"]),
            "m": float(DEFAULTS["import_m"]),
            "cbam_enabled": bool(DEFAULTS["cbam_enabled"]),
            "coverage": float(DEFAULTS["cbam_coverage"]),
            "sigma_foreign": float(DEFAULTS["cbam_sigma_foreign"]),
        }
    )

    years = _normalize_years(body.get("years"), label=label)

    normalized: dict[str, Any] = {
        "model_approach": "product",
        "carbon_price": carbon_price,
        "product_demand": product_demand,
        "import_supply": import_supply,
        "years": years,
    }
    # D1 flow-vocabulary pass-through (docs/platform-spec-d0-d1.md §2e/§6): a
    # product market that participates in a steel↔carbon link must declare
    # ``price_unit`` (validate_links enforces it on every linked market). Carried
    # only when present and non-empty, mirroring the carbon body's
    # ``_OPTIONAL_MARKET_BODY_KEYS`` default-absent rule (byte-identical when
    # unset). ``flow_label``/``flow_unit`` ride along for display parity.
    for optional_key in ("flow_label", "flow_unit", "price_unit"):
        if optional_key in body and body[optional_key] is not None:
            value = str(body[optional_key]).strip()
            if not value:
                raise ValueError(f"{label}: {optional_key}, if present, must be non-empty.")
            normalized[optional_key] = value
    return normalized
