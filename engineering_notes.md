# Engineering Notes — Fyers Options Bot

Running log of design decisions, mistakes caught, and how they were
resolved, in the order they came up. Meant for future-you (or anyone else
picking this up) to understand *why* the code looks the way it does, not
just what it does.

Last updated: as of the paper-trading + multi-strategy + deployment build
phase.

---

## 1. Architecture decisions

**Layered build order**: auth/data foundation → backtester → paper
trading → (planned) order manager → (planned) dashboard. Each layer only
depends on the ones before it, and nothing above the order-manager layer
is ever allowed to call a real order-placement endpoint — paper trading
uses read-only WebSocket subscriptions only.

**Why Black-Scholes for backtesting instead of real option premiums**:
Fyers doesn't reliably provide historical premium data for expired weekly
option contracts, and hand-building historical option symbol strings is
fragile (see mistake #2 below). Standard retail-algo workaround: derive
synthetic premiums from real historical *underlying* price + realized
volatility via Black-Scholes. Validates entry/exit *logic*, not precise
expected returns — skew near expiry isn't captured.

**Why the symbol master CSV instead of hand-built option symbols**:
Fyers' weekly-expiry symbol format has changed and is inconsistent enough
that the developer community reports frequent "invalid symbol" errors
from hand-constructed strings. `symbol_lookup.py` downloads and caches
Fyers' published `NSE_FO.csv` master file and looks up the exact live
ticker instead of guessing at a format.

**Why threads (not processes) for parallel multi-strategy backtesting**:
Each backtest is a lightweight Python loop, not CPU-bound number
crunching — `ThreadPoolExecutor` avoids multiprocessing overhead for no
real speed benefit. Each `BacktestEngine`/`Strategy` instance is
independent with no shared mutable state, so this is safe.

**Why the paper trader exits daily instead of running across midnight**:
See mistake #5 below — this was originally a bug, now a deliberate design
constraint driven by how Fyers auth works.

---

## 2. Mistakes made and how they were resolved

### #1 — Stale Nifty expiry day (Thursday → Tuesday)
**What happened**: All expiry-calendar code (`run_backtest.py`,
`run_multi_backtest.py`, both offline tests) defaulted `expiry_weekday=3`
(Thursday). NSE actually moved Nifty weekly *and* monthly expiry to
**Tuesday**, effective 1 September 2025 (SEBI-directed, to spread expiry
volume across the week).
**Caught by**: user flagging "don't forget we're trading Indian options
market" as a prompt to re-verify assumptions.
**Fix**: default changed to `expiry_weekday=1` (Tuesday) everywhere, with
a comment noting `expiry_weekday=3` is still correct for backtesting
pre-Sept-2025 historical data.

### #2 — Bank Nifty weekly options no longer exist
**What happened**: Code and docs assumed Bank Nifty weekly options were a
live product one could trade. SEBI restricted each exchange to a single
weekly index-options expiry (effective Nov 2024 / Sept 2025 rollout) — NSE
kept only Nifty as weekly; Bank Nifty, FinNifty, and MidcpNifty are
monthly-only now.
**Fix**: explicit warning comments added in `run_paper_trading.py` and
the README so nobody points the weekly-expiry strategies at Bank Nifty
and gets silent symbol-lookup failures.

### #3 — Stale Nifty lot size (75 → 65)
**What happened**: `lot_size = 75` was hardcoded as a placeholder across
all strategy files and `run_paper_trading.py`. NSE revised the Nifty 50
lot size to 65 (Bank Nifty to 30), effective the January 2026 expiry
cycle, as part of a broader index-derivatives rebasing.
**Fix**: updated to 65 everywhere, with a "NSE revises periodically -
VERIFY before real use" comment attached to every occurrence, since a
stale lot size silently mis-prices every P&L number the code produces.

### #4 — Symbol substring-matching bug (the serious one)
**What happened**: `symbol_lookup.py` used
`symbol_ticker.str.contains("NIFTY")` to find Nifty contracts. "NIFTY" is
a substring of "BANKNIFTY", "NIFTYNXT50", and "MIDCPNIFTY" too — so a
lookup intended for Nifty could silently return a Bank Nifty (or other)
contract instead. This is the kind of bug that costs real money quietly,
since nothing would throw an error - it would just trade the wrong
instrument.
**Caught by**: proactive code review requested by the user ("look for any
further code changes as well").
**Fix**: replaced substring matching with an anchored regex,
`^NSE:{underlying}\d`, requiring the underlying name be immediately
followed by a digit (the start of the expiry-date encoding in Fyers'
symbol format). Verified with a synthetic test: querying "NIFTY" against
a mixed symbol list now correctly excludes BankNifty/NiftyNxt50/
MidcpNifty and returns only the exact match.

### #5 — Paper trading state never reset across days
**What happened**: `entered_today` and `daily_pnl` in
`run_paper_trading.py` were initialized once at script start and never
reset. A long-running process (e.g. under `systemd`, per the deployment
plan) would take one trade on day one and then sit idle forever after,
since `entered_today` stayed `True` permanently.
**Deeper issue found while fixing**: patching in a simple day-rollover
reset wasn't actually the right fix. Fyers access tokens expire once per
*calendar day*, and `auth.py`'s login step is interactive (a URL has to
be opened and pasted back manually) — so a process that stays resident
past midnight would keep running on a dead token. The WebSocket's
auto-reconnect would loop forever without ever succeeding, and because
the process never actually crashes, `systemd`'s `Restart=on-failure`
wouldn't catch it either.
**Fix**: redesigned the script to **exit deliberately at market close
(15:30 IST) every day** — closing any open position first and printing
the day's P&L — rather than try to survive across days. Also exits
immediately if started on a weekend. This sidesteps the reset bug
entirely (the process just restarts fresh) and matches the reality of
daily token expiry. Documented in the README that the operator needs to
re-run `auth.py` and restart the service each trading morning; full
unattended multi-day automation is out of scope while the login step
stays interactive.
**New module**: extracted `is_weekend()` / `is_past_market_close()` into
`market_calendar.py`, dependency-free (no Fyers SDK import), specifically
so this logic could be unit-tested directly — confirmed correct for a
known Saturday, a known weekday, and both sides of the 15:30 boundary.

### #6 — Crash on illiquid strike / momentary data gap
**What happened**: `PaperTradingSession.open_position()` raises
`RuntimeError` if no live tick arrives for a subscribed symbol within a
5-second timeout. Nothing in `run_paper_trading.py`'s main loop caught
this, so an illiquid strike or a momentary WebSocket hiccup at entry time
would crash the entire session instead of just skipping that day's trade.
**Fix**: wrapped the entry attempt in `try/except RuntimeError`, logging
the failure and marking the day as "entered" (skipped) rather than
retrying indefinitely or crashing.

### #7 — Messy leftover code in mark-to-market calc
**What happened**: `backtest_engine.py`'s `_mark_to_market()` had dead,
duplicate P&L calculation lines left over from drafting (an unused
`direction` variable and two overwritten `leg_pnl` assignments before the
real logic).
**Fix**: cleaned up to the single clear if/else form. No behavioral
change — caught during authoring, before the code was ever run.

### #8 — Timezone mismatch in offline test
**What happened**: `test_engine_offline.py`'s synthetic candles used
tz-aware timestamps (`Asia/Kolkata`), but `weekly_expiries()` produced
naive `datetime` objects. Comparing them raised
`TypeError: can't compare offset-naive and offset-aware datetimes`.
**Fix**: `BacktestEngine.run()` strips tzinfo when converting candle
timestamps (`.replace(tzinfo=None)`), so all internal date comparisons
are consistently naive.

### #9 — Unused import
**What happened**: `timedelta` was imported in `run_paper_trading.py` but
never used after refactoring.
**Fix**: removed. Trivial, but caught during the same review pass as
mistakes #4-6.

---

## 3. Verification performed

Since the sandbox this was built in has no network access, nothing that
requires a live Fyers connection could be tested end-to-end. What *was*
verified directly:

- `test_engine_offline.py` — synthetic price data through the full
  backtest engine + `ShortStraddle` strategy: entries, stop-loss exits,
  max-hold exits, and summary stats all computed correctly.
- `test_multi_backtest_offline.py` — all five strategies run concurrently
  against identical synthetic data, comparison table renders correctly.
- `symbol_lookup.py`'s regex fix — tested against a hand-built synthetic
  DataFrame containing NIFTY/BANKNIFTY/NIFTYNXT50/MIDCPNIFTY symbols;
  confirmed only the exact underlying matches.
- `market_calendar.py` — `is_weekend()` and `is_past_market_close()`
  tested directly against known dates/times (a known Saturday, a known
  Tuesday, and both sides of the 15:30 boundary).
- Every `.py` file in the repo — syntax-checked with `python -m
  py_compile` after each change.

**Not verified** (needs a real Fyers connection + real market hours):
- `auth.py`'s actual OAuth exchange
- `fyers_client.py`'s real historical-candle and option-chain calls
- `symbol_lookup.py`'s CSV column layout against a live download of
  `NSE_FO.csv` (structure was inferred from community documentation, not
  confirmed against the actual file)
- `paper_trading.py`'s live WebSocket connection and real-tick fill
  simulation
- The full `run_paper_trading.py` daily loop against a live market session

---

## 4. Open items / not yet built

- **Order manager** — the one module that would ever be allowed to place
  a real order, sitting behind hard position/loss limits. Not started.
- **Web dashboard** — for monitoring positions/P&L and a manual
  kill-switch. Not started.
- **NSE trading holiday calendar** — `market_calendar.py` only checks
  weekends, not exchange holidays (Republic Day, Diwali, etc.). On a
  holiday the bot will sit idle harmlessly until 15:30 then exit, but
  won't detect the holiday explicitly.
- **Vertical spread entry logic** — `BullCallSpread`/`BearPutSpread` use a
  placeholder SMA-crossover trigger just to make them runnable/
  backtestable. Not a real edge; needs to be replaced with genuine
  directional logic before paper/live use.
- **`symbol_lookup.py` CSV column layout** — needs to be run once against
  a live download and the `COLUMNS` list adjusted if it doesn't match, as
  this was inferred rather than confirmed against Fyers' actual file.
- **Static IP / deployment** — README has full AWS (Elastic IP) and
  DigitalOcean (Reserved IP) setup steps plus a `systemd` service
  template, but the app hasn't actually been activated on Fyers with a
  real static IP yet, and the service file hasn't been run on a real VM.
