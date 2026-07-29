"""
Iron condor: short strangle + long further-OTM wings to cap max loss.
Collects less premium than a naked strangle, but risk is defined at entry
(max loss = wing width - net credit), so no stop-loss is strictly required
to bound risk the way it is for the straddle/strangle - though one is
still included here for early exit on adverse moves.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from backtest_engine import Leg, Position, StrategyBase
from black_scholes import bs_price, years_between


class IronCondor(StrategyBase):
    lot_size = 65  # Nifty 50, effective Jan 2026 cycle - VERIFY before real use, NSE revises periodically

    def __init__(
        self,
        entry_weekday: int = 0,
        short_otm_offset_pct: float = 0.02,
        wing_width_points: float = 200,  # distance from short strike to long (protective) strike
        stop_loss_multiple: float = 2.0,  # relative to net credit received
        max_hold_days: int = 4,
        strike_round_to: int = 50,
    ):
        self.entry_weekday = entry_weekday
        self.short_otm_offset_pct = short_otm_offset_pct
        self.wing_width_points = wing_width_points
        self.stop_loss_multiple = stop_loss_multiple
        self.max_hold_days = max_hold_days
        self.strike_round_to = strike_round_to

    def should_enter(self, date: datetime, spot: float, row: pd.Series) -> bool:
        return date.weekday() == self.entry_weekday

    def build_position(
        self, date: datetime, spot: float, expiry_date: datetime, volatility: float
    ) -> Position:
        r = self.strike_round_to
        short_call_strike = round((spot * (1 + self.short_otm_offset_pct)) / r) * r
        short_put_strike = round((spot * (1 - self.short_otm_offset_pct)) / r) * r
        long_call_strike = round((short_call_strike + self.wing_width_points) / r) * r
        long_put_strike = round((short_put_strike - self.wing_width_points) / r) * r

        tte = years_between(date, expiry_date)

        sc = bs_price(spot, short_call_strike, tte, volatility, "CE")
        sp = bs_price(spot, short_put_strike, tte, volatility, "PE")
        lc = bs_price(spot, long_call_strike, tte, volatility, "CE")
        lp = bs_price(spot, long_put_strike, tte, volatility, "PE")

        legs = [
            Leg(strike=short_call_strike, option_type="CE", side="SELL", entry_premium=sc.price),
            Leg(strike=short_put_strike, option_type="PE", side="SELL", entry_premium=sp.price),
            Leg(strike=long_call_strike, option_type="CE", side="BUY", entry_premium=lc.price),
            Leg(strike=long_put_strike, option_type="PE", side="BUY", entry_premium=lp.price),
        ]
        # net credit = premium received from shorts minus premium paid for longs
        self._entry_credit = (
            (sc.price + sp.price - lc.price - lp.price) * self.lot_size
        )
        return Position(entry_date=date, expiry_date=expiry_date, legs=legs)

    def should_exit(
        self, position: Position, date: datetime, spot: float, current_pnl: float
    ) -> tuple[bool, str]:
        days_held = (date - position.entry_date).days
        if current_pnl < -self.stop_loss_multiple * abs(self._entry_credit):
            return True, "stop_loss"
        if days_held >= self.max_hold_days:
            return True, "max_hold_days"
        if date >= position.expiry_date:
            return True, "expiry"
        return False, ""
