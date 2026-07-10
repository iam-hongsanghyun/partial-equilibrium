from __future__ import annotations

from .models import MarketParticipant, TechnologyOption


def _default_technology(participant: MarketParticipant) -> TechnologyOption:
    return TechnologyOption(
        name="Base Technology",
        initial_emissions=participant.initial_emissions,
        free_allocation_ratio=participant.free_allocation_ratio,
        penalty_price=participant.penalty_price,
        marginal_abatement_cost=participant.marginal_abatement_cost,
        max_abatement_share=participant.max_abatement_share,
        max_activity_share=1.0,
        fixed_cost=0.0,
    )


def _available_technologies(participant: MarketParticipant) -> list[TechnologyOption]:
    return participant.technology_options or [_default_technology(participant)]
