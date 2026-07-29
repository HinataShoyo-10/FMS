"""
Runs every strategy against the SAME historical candle set, concurrently
(threads - each backtest is lightweight, not CPU-bound, so no
multiprocessing overhead needed), and prints a side-by-side comparison.

Usage:
    python run_multi_backtest.py
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from fyers_client import FyersClient
from multi_backtest_lib import STRATEGIES, print_comparison, run_one
from run_backtest import weekly_expiries


def main():
    client = FyersClient()

    symbol = "NSE:NIFTY50-INDEX"
    range_to = datetime.today()
    range_from = range_to - timedelta(days=180)

    candles = client.get_historical_candles(
        symbol=symbol,
        resolution="D",
        range_from=range_from.strftime("%Y-%m-%d"),
        range_to=range_to.strftime("%Y-%m-%d"),
    )
    print(f"Fetched {len(candles)} daily candles for {symbol}\n")

    expiries = weekly_expiries(range_from, range_to + timedelta(days=14))

    results = []
    with ThreadPoolExecutor(max_workers=len(STRATEGIES)) as pool:
        futures = {
            pool.submit(run_one, name, factory, candles, expiries): name
            for name, factory in STRATEGIES.items()
        }
        for future in as_completed(futures):
            results.append(future.result())

    print_comparison(results)


if __name__ == "__main__":
    main()
