"""
Short strangle: sell an OTM call and OTM put (wider than a straddle,
lower premium collected, but a wider profit zone before loss starts).
Same undefined-risk caveat as the straddle - the stop-loss width is what
actually caps your risk, size it deliberately.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from backtest_engine import Leg, Position, StrategyBase
from black_scholes import bs_price, years_between


class ShortStrangle(StrategyBase):
    lot_size = 65  # Nifty 50, effective Jan 2026 cycle - VERIFY before real use, NSE revises periodically

    def __init__(
        self,
        entry_weekday: int = 0,
        otm_offset_pct: float = 0.02,  # strikes ~2% away from spot on each side
        stop_loss_multiple: float = 1.5,
        max_hold_days: int = 4,
        strike_round_to: int = 50,
    ):
        self.entry_weekday = entry_weekday
        self.otm_offset_pct = otm_offset_pct
        self.stop_loss_multiple = stop_loss_multiple
        self.max_hold_days = max_hold_days
        self.strike_round_to = strike_round_to

    def should_enter(self, date: datetime, spot: float, row: pd.Series) -> bool:
        return date.weekday() == self.entry_weekday

    def build_position(
        self, date: datetime, spot: float, expiry_date: datetime, volatility: float
    ) -> Position:
        call_strike = round((spot * (1 + self.otm_offset_pct)) / self.strike_round_to) * self.strike_round_to
        put_strike = round((spot * (1 - self.otm_offset_pct)) / self.strike_round_to) * self.strike_round_to
        tte = years_between(date, expiry_date)

        call_quote = bs_price(spot, call_strike, tte, volatility, "CE")
        put_quote = bs_price(spot, put_strike, tte, volatility, "PE")

        legs = [
            Leg(strike=call_strike, option_type="CE", side="SELL", entry_premium=call_quote.price),
            Leg(strike=put_strike, option_type="PE", side="SELL", entry_premium=put_quote.price),
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
