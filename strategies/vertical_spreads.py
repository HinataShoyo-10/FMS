"""
Directional vertical spreads - defined risk both ways, needs a genuine
directional view to have an edge.

The entry trigger here (short-vs-long SMA crossover) is a placeholder to
make the strategy runnable/backtestable - it is NOT a signal you should
trust as-is. Replace `should_enter` with whatever directional logic you
actually believe in (technical, fundamental, options-flow-based, etc.)
before taking this anywhere near paper or live trading.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from backtest_engine import Leg, Position, StrategyBase
from black_scholes import bs_price, years_between


class _VerticalSpreadBase(StrategyBase):
    lot_size = 65  # Nifty 50, effective Jan 2026 cycle - VERIFY before real use, NSE revises periodically

    def __init__(
        self,
        short_sma: int = 5,
        long_sma: int = 20,
        spread_width_points: float = 200,
        max_hold_days: int = 5,
        strike_round_to: int = 50,
    ):
        self.short_sma = short_sma
        self.long_sma = long_sma
        self.spread_width_points = spread_width_points
        self.max_hold_days = max_hold_days
        self.strike_round_to = strike_round_to
        self._closes_seen: list[float] = []

    def _smas(self) -> tuple[float, float] | None:
        # Note: the engine only calls should_enter() when no position is
        # open, so _closes_seen has small gaps during held trades. Fine for
        # a rough SMA trigger; swap in real price history if you need exact
        # continuity.
        if len(self._closes_seen) < self.long_sma:
            return None
        short = sum(self._closes_seen[-self.short_sma:]) / self.short_sma
        long_ = sum(self._closes_seen[-self.long_sma:]) / self.long_sma
        return short, long_

    def should_exit(
        self, position: Position, date: datetime, spot: float, current_pnl: float
    ) -> tuple[bool, str]:
        days_held = (date - position.entry_date).days
        if days_held >= self.max_hold_days:
            return True, "max_hold_days"
        if date >= position.expiry_date:
            return True, "expiry"
        return False, ""


class BullCallSpread(_VerticalSpreadBase):
    """Buy ATM call, sell a further-OTM call. Bullish, defined risk."""

    def should_enter(self, date: datetime, spot: float, row: pd.Series) -> bool:
        self._closes_seen.append(spot)
        smas = self._smas()
        return smas is not None and smas[0] > smas[1]  # short SMA above long SMA

    def build_position(
        self, date: datetime, spot: float, expiry_date: datetime, volatility: float
    ) -> Position:
        r = self.strike_round_to
        buy_strike = round(spot / r) * r
        sell_strike = round((spot + self.spread_width_points) / r) * r
        tte = years_between(date, expiry_date)

        buy_q = bs_price(spot, buy_strike, tte, volatility, "CE")
        sell_q = bs_price(spot, sell_strike, tte, volatility, "CE")

        legs = [
            Leg(strike=buy_strike, option_type="CE", side="BUY", entry_premium=buy_q.price),
            Leg(strike=sell_strike, option_type="CE", side="SELL", entry_premium=sell_q.price),
        ]
        self._entry_debit = (buy_q.price - sell_q.price) * self.lot_size
        return Position(entry_date=date, expiry_date=expiry_date, legs=legs)


class BearPutSpread(_VerticalSpreadBase):
    """Buy ATM put, sell a further-OTM put. Bearish, defined risk."""

    def should_enter(self, date: datetime, spot: float, row: pd.Series) -> bool:
        self._closes_seen.append(spot)
        smas = self._smas()
        return smas is not None and smas[0] < smas[1]  # short SMA below long SMA

    def build_position(
        self, date: datetime, spot: float, expiry_date: datetime, volatility: float
    ) -> Position:
        r = self.strike_round_to
        buy_strike = round(spot / r) * r
        sell_strike = round((spot - self.spread_width_points) / r) * r
        tte = years_between(date, expiry_date)

        buy_q = bs_price(spot, buy_strike, tte, volatility, "PE")
        sell_q = bs_price(spot, sell_strike, tte, volatility, "PE")

        legs = [
            Leg(strike=buy_strike, option_type="PE", side="BUY", entry_premium=buy_q.price),
            Leg(strike=sell_strike, option_type="PE", side="SELL", entry_premium=sell_q.price),
        ]
        self._entry_debit = (buy_q.price - sell_q.price) * self.lot_size
        return Position(entry_date=date, expiry_date=expiry_date, legs=legs)
