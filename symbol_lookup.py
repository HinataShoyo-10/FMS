"""
Looks up exact, valid Fyers option symbols from their published symbol
master CSV, instead of hand-constructing strings.

Why: Fyers' option symbol format has changed multiple times and weekly vs
monthly expiries use different, inconsistent conventions (confirmed by
numerous reports in their own developer community of "invalid symbol"
errors from hand-built weekly symbols). The symbol master file is the
source of truth for what's actually tradable right now.

Master file URLs (equity F&O segment):
    https://public.fyers.in/sym_details/NSE_FO.csv
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime

import pandas as pd
import requests

MASTER_URL = "https://public.fyers.in/sym_details/NSE_FO.csv"
CACHE_PATH = os.path.join(os.path.dirname(__file__), "data", "nse_fo_master.csv")
CACHE_MAX_AGE_SECONDS = 6 * 3600  # refresh a few times a day; master updates daily

# Column layout per Fyers community docs - verify against current file if
# this ever throws a column-count error, since the header has changed before.
COLUMNS = [
    "fytoken", "symbol_details", "exchange_instrument_type", "lot_size",
    "tick_size", "isin", "trading_session", "last_update", "expiry_date",
    "symbol_ticker",
]


def _download_master() -> pd.DataFrame:
    resp = requests.get(MASTER_URL, timeout=15)
    resp.raise_for_status()
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "wb") as f:
        f.write(resp.content)
    return pd.read_csv(CACHE_PATH, header=None, names=COLUMNS, low_memory=False)


def load_master(force_refresh: bool = False) -> pd.DataFrame:
    if not force_refresh and os.path.exists(CACHE_PATH):
        age = time.time() - os.path.getmtime(CACHE_PATH)
        if age < CACHE_MAX_AGE_SECONDS:
            return pd.read_csv(CACHE_PATH, header=None, names=COLUMNS, low_memory=False)
    return _download_master()


def get_option_symbol(
    underlying: str,  # e.g. "NIFTY", "BANKNIFTY"
    strike: float,
    option_type: str,  # "CE" or "PE"
    expiry_date: datetime,
    master: pd.DataFrame | None = None,
) -> str | None:
    """
    Returns the exact Fyers symbol ticker (e.g. "NSE:NIFTY25JAN23000CE") for
    the given contract if it's currently listed in the master, else None.
    """
    if master is None:
        master = load_master()

    # IMPORTANT: plain substring matching on `underlying` is wrong here -
    # "NIFTY" is a substring of "BANKNIFTY", "NIFTYNXT50", and
    # "MIDCPNIFTY" too, so a naive .str.contains("NIFTY") would silently
    # pull in the wrong underlying's contracts. Fyers option symbols are
    # "NSE:{UNDERLYING}{expiry-code}{strike}{CE/PE}" - the expiry code
    # starts with a digit, so anchoring on "underlying immediately
    # followed by a digit" isolates the exact underlying correctly.
    pattern = f"^NSE:{re.escape(underlying)}\\d"
    candidates = master[
        master["symbol_ticker"].str.match(pattern, na=False)
        & master["symbol_ticker"].str.endswith(option_type)
    ]

    target_expiry = expiry_date.date()
    candidates = candidates[
        pd.to_datetime(candidates["expiry_date"], errors="coerce").dt.date == target_expiry
    ]

    # Match the strike embedded in symbol_ticker. IMPORTANT: this must be an
    # anchored match, NOT a plain substring - the same class of bug the
    # underlying lookup above had. Fyers symbols end with "{strike}{CE|PE}",
    # so a naive .str.contains("3000") would also match "23000", "13000",
    # "30000", etc. and silently pick the wrong strike (a quiet money bug -
    # nothing throws, it just trades the wrong contract). Anchor the strike to
    # the end of the ticker immediately before the CE/PE suffix, and require
    # no digit directly precedes it (so "3000CE" does not match "...23000CE").
    strike_str = str(int(strike))
    pattern = rf"(?<!\d){re.escape(strike_str)}{re.escape(option_type)}$"
    matches = candidates[candidates["symbol_ticker"].str.contains(pattern, regex=True, na=False)]

    if matches.empty:
        return None
    return matches.iloc[0]["symbol_ticker"]


def list_available_expiries(underlying: str, master: pd.DataFrame | None = None) -> list[datetime]:
    """All expiry dates currently listed for this underlying's options."""
    if master is None:
        master = load_master()

    pattern = f"^NSE:{re.escape(underlying)}\\d"
    rows = master[master["symbol_ticker"].str.match(pattern, na=False)]
    expiries = pd.to_datetime(rows["expiry_date"], errors="coerce").dropna().unique()
    return sorted(pd.to_datetime(expiries).to_pydatetime().tolist())


if __name__ == "__main__":
    m = load_master()
    print(f"Loaded {len(m)} F&O contracts")
    expiries = list_available_expiries("NIFTY", m)
    print(f"Next few NIFTY expiries: {expiries[:5]}")
