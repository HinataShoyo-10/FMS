"""
Ties it together: pulls historical Nifty/BankNifty daily candles from
Fyers, generates a rough weekly-expiry calendar, runs a strategy through
the backtest engine, and prints a summary.

Usage:
    python run_backtest.py
"""

from datetime import datetime, timedelta

from backtest_engine import BacktestEngine
from fyers_client import FyersClient
from strategies.short_straddle import ShortStraddle


def weekly_expiries(start: datetime, end: datetime, expiry_weekday: int = 1) -> list[datetime]:
    """
    Rough weekly expiry calendar. Default is Tuesday (weekday 1) - NSE
    moved Nifty weekly AND monthly expiry from Thursday to Tuesday
    effective 1 September 2025 (SEBI-directed change to spread expiry
    volume across the week). If you're testing pre-Sept-2025 historical
    data, pass expiry_weekday=3 (Thursday) instead.

    NOTE: Bank Nifty no longer has WEEKLY options at all as of the same
    change - NSE kept only Nifty as a weekly index product; Bank Nifty,
    FinNifty, and MidcpNifty are monthly-only now. Don't point this
    calendar at Bank Nifty weeklies - that product doesn't exist anymore.

    Also verify against the actual NSE holiday-adjusted expiry calendar for
    the period you're testing - expiries shift around exchange holidays.
    Treat this as a starting approximation, not ground truth.
    """
    expiries = []
    d = start
    while d <= end:
        if d.weekday() == expiry_weekday:
            expiries.append(d.replace(hour=15, minute=30, second=0, microsecond=0))
        d += timedelta(days=1)
    return expiries


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
    print(f"Fetched {len(candles)} daily candles for {symbol}")

    expiries = weekly_expiries(range_from, range_to + timedelta(days=14))

    strategy = ShortStraddle(stop_loss_multiple=1.5, max_hold_days=4)
    engine = BacktestEngine(strategy)
    engine.run(candles, expiries)

    summary = engine.summary()
    print("\n--- Backtest summary ---")
    for k, v in summary.items():
        print(f"{k}: {v}")

    print("\n--- Trades ---")
    for t in engine.trades:
        print(
            f"{t.entry_date.date()} -> {t.exit_date.date()} | "
            f"{t.legs_summary} | pnl={t.pnl:.0f} | {t.exit_reason}"
        )


if __name__ == "__main__":
    main()
