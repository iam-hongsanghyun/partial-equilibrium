"""Rule -> plain-language suggestion table, for the ``check`` tool's ``next_steps``.

Source of truth: ``docs/blocks-composition-rules.md`` §4 (the validator rule
list, R1-R33) plus ``docs/platform-spec-d0-d1.md`` §3/§7 (R34-R36, the D1-4
market-link rules), and the synthetic ``"R-unconnected"`` warning
``pe.blocks.validate`` also emits. Every entry here is deliberately
generic advice about *what the fix is*, phrased as a question the AI can put
to the user — the specific numbers/node ids of any one violation are already
in the issue's own ``message`` (:class:`~pe.blocks.validate.ValidationIssue`);
this table only supplies the "so what do I do about it" half, so ``check()``
never has to fabricate remediation advice on the fly.

R10 is deliberately absent: F1 (``docs/blocks-composition-rules.md`` §0) was
fixed, so MSR + CCR together is now a VALID combination and
``validate_graph`` never emits an R10 issue (see ``pe.blocks.validate``'s
module docstring) — there is nothing to suggest.
"""

from __future__ import annotations

from ..blocks import ValidationIssue

# Rule id -> plain-language suggestion, ending in a yes/no question wherever
# there's a concrete fix the AI can offer to apply on the user's say-so
# (server instructions: "surface next_steps as questions not actions").
# Purely informational rules (R29) end with a statement instead.
RULE_SUGGESTIONS: dict[str, str] = {
    "R1": (
        "Attach exactly one price-formation block to this market — "
        "competitive_clearing, rubin_schennach_banking, hotelling, "
        "nash_cournot, or forward_transmission. Want me to add "
        "competitive_clearing, the default?"
    ),
    "R2": (
        "This market needs at least one participant with initial_emissions "
        "> 0 and at least one year in its years grid. Want me to add a "
        "starter participant and year?"
    ),
    "R3": (
        "This edge doesn't resolve to a real config field or engine state "
        "read (a dangling reference or a port-kind mismatch). Want me to "
        "remove it?"
    ),
    "R4": (
        "Two policy blocks can't be wired directly to each other — their "
        "execution order inside the solver is fixed. Want me to remove this "
        "edge and connect both blocks to the market's 'policies' port "
        "instead?"
    ),
    "R5": (
        "kmsr_decree only takes effect under the Rubin/Schennach banking "
        "price-formation block. Want me to switch this market to "
        "rubin_schennach_banking, or remove kmsr_decree?"
    ),
    "R6": (
        "MSR under competitive/Nash needs a bank signal: at least one year "
        "with banking_allowed=true, and a non-myopic expectations rule "
        "(next_year_baseline, perfect_foresight, or manual). Want me to set "
        "both?"
    ),
    "R7": (
        "msr_initial_reserve_mt only funds releases under a decree mode "
        "(kmsr_decree) — msr_bank_threshold ignores it. Want me to clear "
        "it, or switch this policy to kmsr_decree?"
    ),
    "R8": (
        "MSR and Hotelling can't be combined — Hotelling ignores MSR, CCR, "
        "and the price floor/ceiling entirely under a fixed carbon budget. "
        "Want me to remove the MSR block, or switch price formation off "
        "Hotelling?"
    ),
    "R9": (
        "CCR only runs under competitive (or the forward_transmission "
        "overlay) price formation. Want me to switch this market to "
        "competitive_clearing, or remove the CCR block?"
    ),
    "R11": (
        "This CCR block has both reference values (ccr_reference_emissions, "
        "ccr_reference_abatement_cost) at 0, so it never fires. Want me to "
        "set one of them to a positive value?"
    ),
    "R12": (
        "This CCR block's phi signs are opposite the paper's stabilising "
        "optimum (phi_e should be <= 0, phi_z should be >= 0). Want me to "
        "flip them?"
    ),
    "R13": (
        "forward_transmission needs forward_transmission_lambda set to a "
        "number in [0, 1] (the blend weight between the static and "
        "Hotelling components). Want me to set it, e.g. 0.5?"
    ),
    "R14": (
        "Hotelling needs a positive cumulative carbon_budget across the "
        "market's years (it silently falls back to summed total_cap "
        "otherwise). Want me to set carbon_budget?"
    ),
    "R15": (
        "nash_cournot's strategic participants must all be participants "
        "already wired into this market. Want me to fix the strategic "
        "participant list?"
    ),
    "R16": (
        "msr_start_year has no effect on the Nash-Cournot path (it only "
        "gates the competitive path). Want me to clear it, or switch price "
        "formation to competitive if a delayed MSR start matters here?"
    ),
    "R17": (
        "Banking approach plus year-level banking_allowed=true risks a "
        "second, uncoordinated participant-level bank on top of the "
        "solver's aggregate bank. Want me to turn banking_allowed off for "
        "those years?"
    ),
    "R18": (
        "Rubin/Schennach banking forbids borrowing_allowed=true — the "
        "equilibrium assumes no borrowing. Want me to turn it off?"
    ),
    "R19": (
        "A hoarding schedule only applies under the Rubin/Schennach banking "
        "block. Want me to switch price formation to "
        "rubin_schennach_banking, or remove the hoarding block?"
    ),
    "R20": (
        "This hoarding schedule sits under banking_strict_no_arbitrage="
        "true, which usually collapses it back to the static case. Want me "
        "to set banking_strict_no_arbitrage=false?"
    ),
    "R21": (
        "Under banking, the price ceiling is advisory-only inside each "
        "year's window, not strictly enforced. Confirm that's intended, or "
        "switch price formation to competitive for a hard ceiling."
    ),
    "R22": (
        "unsold_treatment='carry_forward' isn't implemented outside "
        "competitive/Nash price formation. Want me to switch it to "
        "'reserve' or 'cancel'?"
    ),
    "R23": (
        "Rubin/Schennach banking requires discount_rate + risk_premium >= "
        "0. Want me to raise one of them?"
    ),
    "R24": (
        "auction_reserve_price exceeds price_upper_bound in at least one "
        "year, which is infeasible. Want me to lower the reserve price or "
        "raise the ceiling?"
    ),
    "R25": (
        "No price_ceiling block is attached and every participant's "
        "penalty_price is 0 in a year with a positive auction — the "
        "solver's price bracket is unbounded. Want me to add a "
        "price_ceiling block, or set a penalty_price on the participants?"
    ),
    "R26": (
        "Allowance supply (free allocation + auction + reserved + "
        "cancelled) exceeds total_cap in at least one year, or a sector's "
        "allocation shares sum above 1. Want me to rebalance the year's "
        "supply, or the sector shares?"
    ),
    "R27": (
        "unsold_treatment='cancel' with no price_floor block attached — "
        "the paper's cancellation rule is floor-driven. Confirm that's "
        "intended, or want me to add a price_floor block?"
    ),
    "R28": (
        "This expectations block is attached, but the current "
        "price-formation block (banking/hotelling/forward_transmission) "
        "doesn't consume expectation_rule. Want me to remove it, or switch "
        "price formation to competitive/nash_cournot?"
    ),
    "R29": (
        "perfect_foresight expectations exclude MSR/CCR from their fixed "
        "point — anticipated-policy pricing needs the banking block "
        "instead. Informational only; no action needed unless that matters "
        "here."
    ),
    "R30": (
        "This policy's announced year isn't one of the market's years. "
        "Want me to change it to a valid year?"
    ),
    "R31": (
        "This CBAM block has every reference price at 0, so no liability is "
        "ever computed. Want me to set eua_price (or a per-jurisdiction/"
        "ensemble price)?"
    ),
    "R32": (
        "This participant has only one of production_output / "
        "benchmark_emission_intensity set — the OBA override needs both "
        "(plus initial_emissions > 0) to fire. Want me to set the missing "
        "one?"
    ),
    "R33": (
        "endogenous_investment only takes effect under competitive_clearing "
        "or rubin_schennach_banking price formation (v1 approach coverage). "
        "Want me to switch this market's price formation, or remove the "
        "endogenous_investment block?"
    ),
    "R34": (
        "The market_link graph has a cycle, a self-link, or a market_link "
        "block that isn't wired with exactly one inbound 'from' edge and one "
        "outbound 'link' edge — D1 only solves one-way DAGs (a cycle is the "
        "joint fixed point, deferred to D2). Want me to remove or rewire the "
        "offending link?"
    ),
    "R35": (
        "This market_link's channel must be mac_cost or invest_break_even "
        "(demand-side only), or it duplicates another link with the same "
        "source, target, and channel. Want me to fix the channel, or remove "
        "the duplicate?"
    ),
    "R36": (
        "Every market touching a link must declare price_unit, and every "
        "market_link must declare phi_unit — a missing unit is an economic "
        "constant hiding in a silent default. Want me to set the missing "
        "unit(s)?"
    ),
    "R-unconnected": (
        "This node isn't wired to anything yet. Want me to connect it (see "
        "describe_block for its ports), or remove it?"
    ),
}


def next_steps_for(
    issues: list[ValidationIssue], *, levels: tuple[str, ...] = ("error",)
) -> list[dict[str, str | None]]:
    """Build ``check()``'s ``next_steps``: one actionable entry per matched issue.

    Args:
        issues: Every issue from ``pe.blocks.validate_graph``.
        levels: Which issue levels to generate a next-step for. Defaults to
            ERROR only — a graph with only warnings already runs, so it
            doesn't need coaxing before ``run_model``. Pass
            ``("error", "warning")`` to also surface warning-level guidance.

    Returns:
        One dict per matched issue, in ``issues`` order:
        ``{"rule", "node", "message", "suggestion"}``.
    """
    steps: list[dict[str, str | None]] = []
    for issue in issues:
        if issue.level not in levels:
            continue
        suggestion = RULE_SUGGESTIONS.get(issue.rule)
        if suggestion is None:
            continue
        steps.append(
            {
                "rule": issue.rule,
                "node": issue.node,
                "message": issue.message,
                "suggestion": suggestion,
            }
        )
    return steps
