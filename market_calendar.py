"""
Pure date/time helpers for NSE market hours - no Fyers SDK dependency, so
these are easy to unit test and reusable across paper/live trading scripts.
"""

from __future__ import annotations

from datetime import date, datetime

MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15   # NSE cash/derivatives open
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30  # NSE cash/derivatives close

# ---------------------------------------------------------------------------
# NSE trading holidays (equity / F&O segment).
#
# !!! VERIFY / REFRESH ANNUALLY !!!  NSE publishes the official holiday list
# each year as a circular - this MUST be refreshed from the authoritative
# source before each calendar year (and re-checked mid-year, as the exchange
# occasionally amends it):
#     https://www.nseindia.com/resources/exchange-communication-holidays
#
# Same spirit as the lot-size / expiry-day constants elsewhere in this repo:
# a reasonable default that the operator MUST confirm before trusting with
# real or paper capital. A wrong/stale date here only makes the bot idle on a
# day it thinks is a holiday (or attempt to trade on a real holiday, where
# Fyers will simply return no ticks) - it will not place bad orders, but it
# will misreport "market open" state, so keep it current.
#
# Movable-festival dates (Holi, Diwali, Id, etc.) shift year to year and are
# the ones most likely to be wrong if this list goes stale - fixed-date
# holidays (Republic Day, Independence Day, Gandhi Jayanti, Christmas) are
# stable. Muhurat (Diwali evening) special sessions are NOT encoded here.
#
# Stored as ISO "YYYY-MM-DD" strings, grouped by year, parsed once below.
# ---------------------------------------------------------------------------
_NSE_HOLIDAYS_BY_YEAR: dict[int, list[str]] = {
    # 2025 - full year, per NSE's published 2025 holiday circular (past dates,
    # retained so pre-2026 backtests / date checks resolve correctly).
    2025: [
        "2025-02-26",  # Mahashivratri
        "2025-03-14",  # Holi
        "2025-03-31",  # Id-Ul-Fitr (Ramzan Id)
        "2025-04-10",  # Shri Mahavir Jayanti
        "2025-04-14",  # Dr. Baba Saheb Ambedkar Jayanti
        "2025-04-18",  # Good Friday
        "2025-05-01",  # Maharashtra Day
        "2025-08-15",  # Independence Day
        "2025-08-27",  # Ganesh Chaturthi
        "2025-10-02",  # Mahatma Gandhi Jayanti / Dussehra
        "2025-10-21",  # Diwali Laxmi Pujan (regular session closed; Muhurat separate)
        "2025-10-22",  # Diwali Balipratipada
        "2025-11-05",  # Prakash Gurpurb Sri Guru Nanak Dev
        "2025-12-25",  # Christmas
    ],
    # 2026 - BEST-EFFORT, MUST BE VERIFIED against NSE's official 2026 circular.
    # Fixed-date entries are reliable; movable-festival dates (marked ~) are
    # approximate and MUST be confirmed before the 2026 trading year.
    2026: [
        "2026-01-26",  # Republic Day (fixed)
        "2026-03-04",  # ~Holi (VERIFY)
        "2026-03-21",  # ~Id-Ul-Fitr (VERIFY)
        "2026-03-31",  # ~Shri Mahavir Jayanti / Ram Navami window (VERIFY)
        "2026-04-03",  # ~Good Friday (VERIFY)
        "2026-04-14",  # Dr. Baba Saheb Ambedkar Jayanti (fixed)
        "2026-05-01",  # Maharashtra Day (fixed)
        "2026-08-15",  # Independence Day (fixed; falls on a Saturday in 2026)
        "2026-10-02",  # Mahatma Gandhi Jayanti (fixed)
        "2026-11-09",  # ~Diwali / Balipratipada window (VERIFY)
        "2026-12-25",  # Christmas (fixed)
    ],
}

# Parsed set of holiday `date` objects, and the set of years the calendar
# actually covers (so callers can tell "not a holiday" from "we have no data
# for that year" - see holiday_calendar_covers()).
NSE_TRADING_HOLIDAYS: frozenset[date] = frozenset(
    date.fromisoformat(d)
    for dates in _NSE_HOLIDAYS_BY_YEAR.values()
    for d in dates
)
_CALENDAR_YEARS: frozenset[int] = frozenset(_NSE_HOLIDAYS_BY_YEAR)


def is_weekend(now: datetime) -> bool:
    return now.weekday() >= 5  # Saturday=5, Sunday=6


def is_trading_holiday(now: datetime) -> bool:
    """
    True if `now` falls on a known NSE trading holiday (weekday closures only;
    weekends are handled by is_weekend). Only as accurate as the hardcoded
    list above - see the VERIFY banner there. Returns False for any date in a
    year the calendar doesn't cover; use holiday_calendar_covers() to detect
    that case explicitly.
    """
    return now.date() in NSE_TRADING_HOLIDAYS


def holiday_calendar_covers(now: datetime) -> bool:
    """
    True if the holiday list has data for `now`'s year. When this is False, a
    False from is_trading_holiday() means "unknown", not "confirmed open" -
    the operator should refresh the calendar for that year.
    """
    return now.year in _CALENDAR_YEARS


def is_trading_day(now: datetime) -> bool:
    """A normal NSE session day: not a weekend and not a listed holiday."""
    return not is_weekend(now) and not is_trading_holiday(now)


def is_past_market_close(
    now: datetime,
    close_hour: int = MARKET_CLOSE_HOUR,
    close_minute: int = MARKET_CLOSE_MINUTE,
) -> bool:
    close = now.replace(hour=close_hour, minute=close_minute, second=0, microsecond=0)
    return now >= close


def is_market_open(now: datetime) -> bool:
    """
    True only during a live NSE session: a trading day (not weekend/holiday)
    and within the 09:15-15:30 window. Note: does not model the pre-open
    auction (09:00-09:15) or Muhurat special sessions.
    """
    if not is_trading_day(now):
        return False
    open_t = now.replace(
        hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0
    )
    return open_t <= now and not is_past_market_close(now)
