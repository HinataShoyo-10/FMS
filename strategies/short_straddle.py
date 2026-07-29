"""
Example strategy: sell an ATM straddle at entry, exit on a stop-loss
(premium expanding past a multiple of entry credit) or a fixed number of
days held - whichever comes first.

This is a STARTING POINT to validate the engine, not a recommendation.
Short straddles carry undefined risk on a large underlying move - the
stop-loss here is what caps that, and its width is the single most
important parameter to get right for your own risk tolerance.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from backtest_engine import Leg, Position, StrategyBase
from black_scholes import bs_price, years_between


class ShortStraddle(StrategyBase):
    lot_size = 65  # Nifty 50, effective Jan 2026 cycle - VERIFY before real use, NSE revises periodically

    def __init__(
        self,
        entry_weekday: int = 0,  # Monday
        stop_loss_multiple: float = 1.5,  # exit if loss > 1.5x credit received
        max_hold_days: int = 4,
        strike_round_to: int = 50,
    ):
        self.entry_weekday = entry_weekday
        self.stop_loss_multiple = stop_loss_multiple
        self.max_hold_days = max_hold_days
        self.strike_round_to = strike_round_to

    def should_enter(self, date: datetime, spot: float, row: pd.Series) -> bool:
        return date.weekday() == self.entry_weekday

    def build_position(
        self, date: datetime, spot: float, expiry_date: datetime, volatility: float
    ) -> Position:
        atm_strike = round(spot / self.strike_round_to) * self.strike_round_to
        tte = years_between(date, expiry_date)

        call_quote = bs_price(spot, atm_strike, tte, volatility, "CE")
        put_quote = bs_price(spot, atm_strike, tte, volatility, "PE")

        legs = [
            Leg(strike=atm_strike, option_type="CE", side="SELL", entry_premium=call_quote.price),
            Leg(strike=atm_strike, option_type="PE", side="SELL", entry_premium=put_quote.price),
        ]
        self._entry_credit = sum(l.entry_premium for l in legs) * self.lot_size
        return Position(entry_date=date, expiry_date=expiry_date, legs=legs)

    def should_exit(
        self, position: Position, date: datetime, spot: float, current_pnl: float
    ) -> tuple[bool, str]:
        days_held = (date - position.entry_date).days

        if current_pnl < -self.stop_loss_multiple * self._entry_credit:
            return True, "stop_loss"
        if days_held >= self.max_hold_days:
            return True, "max_hold_days"
        if date >= position.expiry_date:
            return True, "expiry"

        return False, ""
