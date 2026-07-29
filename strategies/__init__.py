"""
Options strategies package.

Each module here defines one or more strategies subclassing
`backtest_engine.StrategyBase` (implementing should_enter / build_position /
should_exit). They are consumed by the backtest runners and registered for
the parallel comparison in `multi_backtest_lib.STRATEGIES`.

Re-exported here so callers can do e.g. `from strategies import ShortStraddle`
in addition to `from strategies.short_straddle import ShortStraddle`.
"""

from strategies.iron_condor import IronCondor
from strategies.short_straddle import ShortStraddle
from strategies.short_strangle import ShortStrangle
from strategies.vertical_spreads import BearPutSpread, BullCallSpread

__all__ = [
    "ShortStraddle",
    "ShortStrangle",
    "IronCondor",
    "BullCallSpread",
    "BearPutSpread",
]
