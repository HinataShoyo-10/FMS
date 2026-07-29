"""
Generic backtest engine for options strategies on index underlyings
(Nifty/BankNifty), using synthetic Black-Scholes pricing.

Design: a Strategy plugs in via three hooks (see StrategyBase). The engine
walks day-by-day through historical underlying candles, calls the
strategy's hooks, and tracks any open Position's synthetic option P&L
using bs_price + realized_volatility from black_scholes.py.

This lets you test entry/exit LOGIC and rough risk behavior. It does not
give you precise expected returns - see black_scholes.py for why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import pandas as pd

from black_scholes import bs_price, realized_volatility, years_between

OptionType = Literal["CE", "PE"]
Side = Literal["BUY", "SELL"]


@dataclass
class Leg:
    """One option leg of a position, e.g. the call side of a short straddle."""
    strike: float
    option_type: OptionType
    side: Side
    entry_premium: float
    lots: int = 1


@dataclass
class Position:
    entry_date: datetime
    expiry_date: datetime
    legs: list[Leg] = field(default_factory=list)
    is_open: bool = True
    exit_date: datetime | None = None
    exit_pnl: float = 0.0
    exit_reason: str = ""


@dataclass
class Trade:
    entry_date: datetime
    exit_date: datetime
    pnl: float
    exit_reason: str
    legs_summary: str


class StrategyBase:
    """
    Subclass this and implement the three hooks. `lot_size` should match
    the exchange lot size for the underlying you're trading (changes
    periodically - verify current value on the NSE/Fyers contract specs
    before using in paper/live trading).
    """

    lot_size: int = 65  # Nifty 50, effective Jan 2026 cycle - VERIFY before real use, NSE revises periodically

    def should_enter(self, date: datetime, spot: float, row: pd.Series) -> bool:
        """Return True if a new position should be opened on this bar."""
        raise NotImplementedError

    def build_position(
        self, date: datetime, spot: float, expiry_date: datetime, volatility: float
    ) -> Position:
        """Construct the Position (its legs + entry premiums) for entry."""
        raise NotImplementedError

    def should_exit(
        self, position: Position, date: datetime, spot: float, current_pnl: float
    ) -> tuple[bool, str]:
        """Return (True, reason) if the open position should be closed now."""
        raise NotImplementedError


class BacktestEngine:
    def __init__(self, strategy: StrategyBase, vol_lookback_days: int = 20):
        self.strategy = strategy
        self.vol_lookback_days = vol_lookback_days
        self.trades: list[Trade] = []

    def _mark_to_market(self, position: Position, date: datetime, spot: float) -> float:
        """Current P&L of an open position if marked at `spot` on `date`."""
        total = 0.0
        for leg in position.legs:
            tte = years_between(date, position.expiry_date)
            vol = position._current_vol  # stashed at entry, see run()
            quote = bs_price(spot, leg.strike, tte, vol, leg.option_type)
            current_premium = quote.price
            # SELL: profit when premium falls; BUY: profit when it rises
            if leg.side == "SELL":
                leg_pnl = (leg.entry_premium - current_premium) * leg.lots * self.strategy.lot_size
            else:
                leg_pnl = (current_premium - leg.entry_premium) * leg.lots * self.strategy.lot_size
            total += leg_pnl
        return total

    def run(self, candles: pd.DataFrame, expiry_dates: list[datetime]) -> list[Trade]:
        """
        candles: DataFrame with columns [timestamp, open, high, low, close],
                 one row per trading day (daily resolution), sorted ascending.
        expiry_dates: sorted list of weekly/monthly expiry datetimes covering
                 the candle range - used to pick "next expiry" at entry time.
        """
        closes = candles["close"].tolist()
        open_position: Position | None = None

        for i, row in candles.iterrows():
            date = row["timestamp"].to_pydatetime().replace(tzinfo=None)
            spot = float(row["close"])

            # rolling realized vol as our BS volatility input
            window = closes[max(0, i - self.vol_lookback_days): i + 1]
            if len(window) < 5:
                continue
            vol = realized_volatility(window)

            if open_position is not None:
                pnl = self._mark_to_market(open_position, date, spot)
                exit_now, reason = self.strategy.should_exit(open_position, date, spot, pnl)
                if exit_now:
                    open_position.is_open = False
                    open_position.exit_date = date
                    open_position.exit_pnl = pnl
                    open_position.exit_reason = reason
                    self.trades.append(
                        Trade(
                            entry_date=open_position.entry_date,
                            exit_date=date,
                            pnl=pnl,
                            exit_reason=reason,
                            legs_summary=", ".join(
                                f"{l.side} {l.option_type} {l.strike}" for l in open_position.legs
                            ),
                        )
                    )
                    open_position = None
                continue

            if self.strategy.should_enter(date, spot, row):
                next_expiry = next((e for e in expiry_dates if e > date), None)
                if next_expiry is None:
                    continue
                open_position = self.strategy.build_position(date, spot, next_expiry, vol)
                open_position._current_vol = vol  # stash for mark-to-market

        return self.trades

    def summary(self) -> dict:
        if not self.trades:
            return {"trades": 0}
        pnls = [t.pnl for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        equity_curve = pd.Series(pnls).cumsum()
        running_max = equity_curve.cummax()
        drawdown = (equity_curve - running_max).min()

        return {
            "trades": len(self.trades),
            "total_pnl": sum(pnls),
            "win_rate": len(wins) / len(pnls),
            "avg_win": sum(wins) / len(wins) if wins else 0,
            "avg_loss": sum(losses) / len(losses) if losses else 0,
            "max_drawdown": drawdown,
        }
