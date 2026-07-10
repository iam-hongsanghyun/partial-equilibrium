from __future__ import annotations

# Import the base class first, then attach the solver/results methods as delegates.
from .model import CarbonMarket
from . import clearing as _eq
from . import reporting as _res


# Attach equilibrium methods onto CarbonMarket
def _total_net_demand(self, carbon_price, bank_balances=None, expected_future_price=0.0):
    return _eq.total_net_demand(self, carbon_price, bank_balances, expected_future_price)


def _solve_equilibrium(self, lower_bound=0.0, upper_bound=None, bank_balances=None,
                       expected_future_price=0.0, carry_forward_in=0.0):
    return _eq.solve_equilibrium(self, lower_bound, upper_bound, bank_balances,
                                  expected_future_price, carry_forward_in)


def _solve_for_supply(self, target_supply, lower_bound, upper_bound,
                      bank_balances, expected_future_price):
    return _eq._solve_for_supply(self, target_supply, lower_bound, upper_bound,
                                  bank_balances, expected_future_price)


def _participant_outcome(self, participant, carbon_price, bank_balances=None,
                         expected_future_price=0.0):
    return _eq._participant_outcome(self, participant, carbon_price,
                                     bank_balances, expected_future_price)


# Attach results methods onto CarbonMarket
def _participant_results(self, equilibrium_price, bank_balances=None,
                         expected_future_price=0.0):
    return _res.participant_results(self, equilibrium_price, bank_balances,
                                     expected_future_price)


def _scenario_summary(self, equilibrium_price, bank_balances=None,
                      expected_future_price=0.0, auction_outcome=None,
                      participant_df=None):
    return _res.scenario_summary(self, equilibrium_price, bank_balances,
                                  expected_future_price, auction_outcome,
                                  participant_df)


CarbonMarket.total_net_demand = _total_net_demand
CarbonMarket.solve_equilibrium = _solve_equilibrium
CarbonMarket._solve_for_supply = _solve_for_supply
CarbonMarket._participant_outcome = _participant_outcome
CarbonMarket.participant_results = _participant_results
CarbonMarket.scenario_summary = _scenario_summary


__all__ = ["CarbonMarket"]
