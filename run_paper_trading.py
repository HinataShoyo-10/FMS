"""
Runs a live paper-trading session: connects to real market data, decides
entries/exits using simple rules, simulates fills - places NO real orders.

Usage:
    python run_paper_trading.py

Stop anytime with Ctrl+C - open positions (if any) are just abandoned in
memory, nothing needs to be "cancelled" since nothing real was ever placed.

IMPORTANT - deliberately exits daily, does not run across midnight:
Fyers access tokens expire once per calendar day, and auth.py's login is
interactive (you paste a URL back manually). A long-running process that
stays up past midnight would keep running on a dead token - the
WebSocket's auto-reconnect would loop forever without ever succeeding,
and since the process never actually crashes, a systemd Restart=on-failure
policy won't catch it either. So: this script deliberately exits shortly
after market close each day. If you're running it via systemd, that's
expected behavior, not a bug - you (or a scheduled task) need to re-run
`auth.py` and restart the service each morning. See the README's
Deployment section for the exact commands.
"""

import threading
import time
from datetime import datetime

import symbol_lookup
from market_calendar import (
    holiday_calendar_covers,
    is_past_market_close,
    is_trading_holiday,
    is_weekend,
)
from paper_trading import PaperTradingSession

UNDERLYING_SYMBOL = "NSE:NIFTY50-INDEX"
UNDERLYING_NAME = "NIFTY"
# NOTE: don't swap this to Bank Nifty expecting weekly options - NSE
# discontinued Bank Nifty weeklies (SEBI-directed, effective Sept 2025).
# Bank Nifty is monthly-only now; a weekly-expiry strategy pointed at it
# will fail to find valid symbols via symbol_lookup.
LOT_SIZE = 65  # Nifty 50, effective Jan 2026 cycle - VERIFY before use, NSE revises periodically
STRIKE_ROUND_TO = 50

STOP_LOSS_MULTIPLE = 1.5      # exit if loss exceeds 1.5x credit received
MAX_HOLD_MINUTES = 240        # exit after this long regardless
DAILY_LOSS_CAP = -15000       # kill-switch: stop opening new positions past this
ENTRY_HOUR, ENTRY_MINUTE = 9, 30    # simple time-of-day entry trigger, adjust as needed

CHECK_INTERVAL_SECONDS = 5


def pick_expiry_and_strikes(session: PaperTradingSession):
    spot = session.prices.get(UNDERLYING_SYMBOL)
    if spot is None:
        return None

    expiries = symbol_lookup.list_available_expiries(UNDERLYING_NAME)
    next_expiry = next((e for e in expiries if e > datetime.now()), None)
    if next_expiry is None:
        return None

    atm_strike = round(spot / STRIKE_ROUND_TO) * STRIKE_ROUND_TO
    ce_symbol = symbol_lookup.get_option_symbol(UNDERLYING_NAME, atm_strike, "CE", next_expiry)
    pe_symbol = symbol_lookup.get_option_symbol(UNDERLYING_NAME, atm_strike, "PE", next_expiry)

    if not ce_symbol or not pe_symbol:
        print(f"Couldn't resolve symbols for strike {atm_strike}, expiry {next_expiry}")
        return None

    return ce_symbol, pe_symbol


def main():
    now = datetime.now()
    if is_weekend(now):
        print(f"{now.date()} is a weekend - NSE is closed, nothing to do. Exiting.")
        return
    if is_trading_holiday(now):
        print(f"{now.date()} is an NSE trading holiday - market closed, nothing to do. Exiting.")
        return
    # If we have no holiday data for this year, the check above can't be
    # trusted - warn the operator to refresh market_calendar.py rather than
    # silently assuming the market is open (it'll still run; on a real
    # holiday Fyers just returns no ticks and the loop idles to 15:30).
    if not holiday_calendar_covers(now):
        print(f"WARNING: no NSE holiday calendar data for {now.year} - "
              f"refresh market_calendar.py. Proceeding assuming a normal session.")

    session = PaperTradingSession(UNDERLYING_SYMBOL, UNDERLYING_NAME, LOT_SIZE)

    ws_thread = threading.Thread(target=session.start, daemon=True)
    ws_thread.start()

    print("Waiting for data connection...")
    time.sleep(3)

    daily_pnl = 0.0
    entered_today = False
    entry_credit = 0.0

    print("Paper trading loop running for today's session. Ctrl+C to stop early.")
    try:
        while True:
            now = datetime.now()

            if is_past_market_close(now):
                if session.position is not None:
                    pnl = session.mark_to_market()
                    session.close_position("market_close")
                    if pnl is not None:
                        daily_pnl += pnl
                print(f"\nMarket closed. Session daily P&L (paper): {daily_pnl:.0f}")
                print("Exiting for the day - re-run auth.py and restart tomorrow morning.")
                return

            if session.position is None:
                past_kill_switch = daily_pnl <= DAILY_LOSS_CAP
                at_entry_time = now.hour == ENTRY_HOUR and now.minute == ENTRY_MINUTE
                if not entered_today and at_entry_time and not past_kill_switch:
                    strikes = pick_expiry_and_strikes(session)
                    if strikes:
                        ce_symbol, pe_symbol = strikes
                        legs_spec = [
                            (ce_symbol, "SELL", 1),
                            (pe_symbol, "SELL", 1),
                        ]
                        try:
                            position = session.open_position(legs_spec)
                            entry_credit = sum(
                                l.entry_price * l.lots * l.lot_size for l in position.legs
                            )
                            entered_today = True
                        except RuntimeError as e:
                            # e.g. no live tick within timeout for an illiquid
                            # strike - log and skip today rather than crash
                            # the whole session over one bad entry attempt
                            print(f"Entry failed, skipping for today: {e}")
                            entered_today = True
                elif past_kill_switch:
                    pass  # daily loss cap hit - no new entries, just idle
            else:
                pnl = session.mark_to_market()
                if pnl is not None:
                    held_minutes = (now - session.position.entry_time).total_seconds() / 60
                    if pnl < -STOP_LOSS_MULTIPLE * entry_credit:
                        session.close_position("stop_loss")
                        daily_pnl += pnl
                    elif held_minutes >= MAX_HOLD_MINUTES:
                        session.close_position("max_hold_time")
                        daily_pnl += pnl

            time.sleep(CHECK_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print(f"\nStopped early. Session daily P&L (paper): {daily_pnl:.0f}")


if __name__ == "__main__":
    main()

