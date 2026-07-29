"""
Sanity test for the backtest engine using synthetic price data - no Fyers
connection required. Run this to confirm the engine/strategy logic works
before wiring in real historical data.
"""

import random
from datetime import datetime, timedelta

import pandas as pd

from backtest_engine import BacktestEngine
from strategies.short_straddle import ShortStraddle

random.seed(42)


def weekly_expiries(start: datetime, end: datetime, expiry_weekday: int = 1) -> list:
    """Tuesday (weekday 1) - NSE moved Nifty weekly expiry from Thursday
    to Tuesday effective 1 Sept 2025. Same logic as run_backtest.py's
    version, inlined here so this offline test doesn't need to import
    fyers_client (which requires the fyers_apiv3 package / network to install)."""
    expiries = []
    d = start
    while d <= end:
        if d.weekday() == expiry_weekday:
            expiries.append(d.replace(hour=15, minute=30, second=0, microsecond=0))
        d += timedelta(days=1)
    return expiries


def make_synthetic_candles(start: datetime, days: int, start_price: float = 22000.0) -> pd.DataFrame:
    rows = []
    price = start_price
    d = start
    while len(rows) < days:
        if d.weekday() < 5:  # skip weekends
            ret = random.gauss(0, 0.008)  # ~0.8% daily stdev, roughly realistic for Nifty
            price *= (1 + ret)
            rows.append({"timestamp": pd.Timestamp(d, tz="Asia/Kolkata"), "open": price,
                         "high": price * 1.005, "low": price * 0.995, "close": price, "volume": 0})
        d += timedelta(days=1)
    return pd.DataFrame(rows)


def main():
    start = datetime(2025, 1, 1)
    candles = make_synthetic_candles(start, days=120)
    end = candles["timestamp"].iloc[-1].to_pydatetime().replace(tzinfo=None)

    expiries = weekly_expiries(start, end + timedelta(days=14))

    strategy = ShortStraddle(stop_loss_multiple=1.5, max_hold_days=4)
    engine = BacktestEngine(strategy)
    engine.run(candles, expiries)

    print(f"Candles: {len(candles)}, Expiries in range: {len(expiries)}")
    print("\n--- Summary ---")
    for k, v in engine.summary().items():
        print(f"{k}: {v}")

    print("\n--- First 5 trades ---")
    for t in engine.trades[:5]:
        print(f"{t.entry_date.date()} -> {t.exit_date.date()} | {t.legs_summary} | "
              f"pnl={t.pnl:.0f} | {t.exit_reason}")


if __name__ == "__main__":
    main()
