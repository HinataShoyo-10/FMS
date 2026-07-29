"""
Sanity test: runs all strategies against synthetic data, in parallel
threads, and prints the comparison table. No Fyers connection needed.
"""

import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd

from multi_backtest_lib import STRATEGIES, print_comparison, run_one

random.seed(42)


def weekly_expiries(start: datetime, end: datetime, expiry_weekday: int = 1) -> list:
    # Tuesday (weekday 1) - NSE moved Nifty weekly expiry from Thursday
    # to Tuesday effective 1 Sept 2025.
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
        if d.weekday() < 5:
            ret = random.gauss(0.0002, 0.008)  # slight upward drift + realistic daily vol
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

    results = []
    with ThreadPoolExecutor(max_workers=len(STRATEGIES)) as pool:
        futures = {
            pool.submit(run_one, name, factory, candles, expiries): name
            for name, factory in STRATEGIES.items()
        }
        for future in as_completed(futures):
            results.append(future.result())

    print(f"Candles: {len(candles)}, Expiries: {len(expiries)}\n")
    print_comparison(results)


if __name__ == "__main__":
    main()
