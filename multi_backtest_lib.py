"""
Shared logic for running multiple strategies concurrently and comparing
results. Kept separate from run_multi_backtest.py so this can be imported
and tested without pulling in the Fyers SDK dependency chain.
"""

from backtest_engine import BacktestEngine
from strategies.iron_condor import IronCondor
from strategies.short_straddle import ShortStraddle
from strategies.short_strangle import ShortStrangle
from strategies.vertical_spreads import BearPutSpread, BullCallSpread

# Add/remove entries here to control what gets backtested.
STRATEGIES = {
    "Short Straddle": lambda: ShortStraddle(stop_loss_multiple=1.5, max_hold_days=4),
    "Short Strangle": lambda: ShortStrangle(otm_offset_pct=0.02, stop_loss_multiple=1.5, max_hold_days=4),
    "Iron Condor": lambda: IronCondor(short_otm_offset_pct=0.02, wing_width_points=200, max_hold_days=4),
    "Bull Call Spread": lambda: BullCallSpread(spread_width_points=200, max_hold_days=5),
    "Bear Put Spread": lambda: BearPutSpread(spread_width_points=200, max_hold_days=5),
}


def run_one(name: str, strategy_factory, candles, expiries) -> dict:
    strategy = strategy_factory()
    engine = BacktestEngine(strategy)
    engine.run(candles, expiries)
    summary = engine.summary()
    summary["name"] = name
    return summary


def print_comparison(results: list[dict]):
    results.sort(key=lambda r: r.get("total_pnl", 0), reverse=True)

    header = (
        f"{'Strategy':<20}{'Trades':>8}{'Total P&L':>14}"
        f"{'Win Rate':>10}{'Avg Win':>12}{'Avg Loss':>12}{'Max DD':>12}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        if r.get("trades", 0) == 0:
            print(f"{r['name']:<20}{'0':>8}   (no trades taken)")
            continue
        print(
            f"{r['name']:<20}"
            f"{r['trades']:>8}"
            f"{r['total_pnl']:>14,.0f}"
            f"{r['win_rate']*100:>9.1f}%"
            f"{r['avg_win']:>12,.0f}"
            f"{r['avg_loss']:>12,.0f}"
            f"{r['max_drawdown']:>12,.0f}"
        )
