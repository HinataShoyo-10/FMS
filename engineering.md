# Engineering Log — Codebase Alignment & Fix Pass

Companion to the existing `engineering_notes.md` (the original build log). This
file records a dedicated pass to: (1) understand the whole project, (2) align
the on-disk folder layout to the structure the docs describe, (3) fix the bugs
that surfaced while doing so, and (4) close a pending item. Written as the work
was done, in order.

Date of this pass: 2026-07-25.

---

## 0. What this project is (orientation)

A layered, single-broker (Fyers API v3) automated **options** trading bot for
Indian index derivatives (Nifty), built bottom-up:

```
auth/data foundation  ->  Black-Scholes backtester  ->  paper trading  ->  (future) order manager  ->  (future) dashboard
```

- **Foundation:** `config.py` (env-var credentials), `auth.py` (daily OAuth,
  token cache), `fyers_client.py` (thin REST wrapper).
- **Backtester:** `black_scholes.py` (synthetic option pricer — Fyers gives no
  reliable historical premiums), `backtest_engine.py` (generic engine +
  `StrategyBase`), the `strategies/` (straddle/strangle/condor/verticals),
  `run_backtest.py`, `multi_backtest_lib.py` + `run_multi_backtest.py`
  (parallel comparison), and two offline tests using synthetic candles.
- **Paper trading:** `symbol_lookup.py` (resolves real option symbols from
  Fyers' symbol-master CSV), `market_calendar.py` (dependency-free date/time
  helpers), `paper_trading.py` (live WebSocket data + simulated fills, never
  places a real order), `run_paper_trading.py` (daily driver loop).
- **Reference docs:** `FYERS_Options_Trading_Platform_PRD.md` and
  `FYERS_API_v3_Technical_Analysis.md` describe the full product vision. The
  current code is an early-phase subset; the order manager and dashboard from
  the PRD are intentionally not built yet.

Design decisions and the earlier round of fixes are documented in
`engineering_notes.md` and remain valid — this pass did not undo any of them.

---

## 1. The primary problem found: docs describe a structure the repo didn't have

`README.md` documents this layout (note the `strategies/` package plus
`data/`, `logs/`, `.gitignore`):

```
├── strategies/
│   ├── __init__.py
│   ├── short_straddle.py
│   ├── short_strangle.py
│   ├── iron_condor.py
│   └── vertical_spreads.py
├── data/      # gitignored
└── logs/      # gitignored
```

The repo on disk did **not** match:
- All four strategy files sat flat in the project root, with **no
  `strategies/` package**.
- No `data/`, no `logs/`, no `.gitignore`.
- An **undocumented empty `__init__.py`** sat in the root (turning the project
  root itself into a package — not what the docs intend).

This wasn't cosmetic. Four entry points import from the `strategies` package:

```
run_backtest.py              -> from strategies.short_straddle import ShortStraddle
multi_backtest_lib.py        -> from strategies.{iron_condor,short_straddle,short_strangle,vertical_spreads} import ...
test_engine_offline.py       -> from strategies.short_straddle import ShortStraddle
test_multi_backtest_offline.py (via multi_backtest_lib)
```

With the files flat in root and no `strategies/` package, **every one of these
raised `ModuleNotFoundError: No module named 'strategies'`** — i.e. the
backtester and both offline tests were non-runnable as shipped. Aligning the
folders to the documented structure is therefore both the requested
reorganization *and* the fix for the broken imports.

---

## 2. Structural changes (folder alignment)

| Action | Detail |
|---|---|
| Created `strategies/` package | Moved `short_straddle.py`, `short_strangle.py`, `iron_condor.py`, `vertical_spreads.py` into it. Their own imports (`from backtest_engine import ...`, `from black_scholes import ...`) are unchanged and still resolve, since those modules stay in root. |
| Added `strategies/__init__.py` | Makes it a real package (what the imports need) and re-exports the five strategy classes, so `from strategies import ShortStraddle` also works alongside the existing `from strategies.short_straddle import ShortStraddle`. |
| Removed root `__init__.py` | Was empty, undocumented, and made the project root a package for no reason. Removing it matches the documented layout. |
| Created `data/` + `data/.gitkeep` | Documented (gitignored) runtime dir for `access_token.txt`, `paper_trades.csv`, `nse_fo_master.csv`. `config.py` / `paper_trading.py` / `symbol_lookup.py` all already `os.makedirs(..., exist_ok=True)` here, so no code change needed — the dir just now exists in the repo. |
| Created `logs/` + `logs/.gitkeep` | Documented (gitignored) dir for Fyers SDK logs (`config.LOG_PATH`). |
| Added `.gitignore` | Was documented as present but absent. Excludes secrets (`.env`, `data/access_token.txt`), the generated contents of `data/`+`logs/` (while keeping the dirs via `.gitkeep`), `__pycache__`, venvs, and common tooling/OS cruft. This matters: without it, the first run would write a **real access token into a trackable file**. |

Resulting layout now matches `README.md` exactly.

---

## 3. Bugs fixed

### 3.1 — Strike substring-collision in `symbol_lookup.py` (latent money bug) 🔴

`get_option_symbol()` selected the contract for a strike with:

```python
strike_str = str(int(strike))
matches = candidates[candidates["symbol_ticker"].str.contains(strike_str, na=False)]
```

This is a plain substring test. Fyers tickers end `...{strike}{CE|PE}`, so a
lookup for strike `3000` also matches `23000`, `13000`, `30000`, … and
`matches.iloc[0]` would silently return **the wrong strike**. This is the
*exact same bug class* the team already fixed for the *underlying* name
(`engineering_notes.md` mistake #4: "NIFTY" substring-matching "BANKNIFTY") —
it was simply still present on the **strike** field. Same failure mode too:
nothing throws, it just quietly trades the wrong instrument. In paper/live this
misprices or mis-selects the position with real money.

**Fix** — anchored regex, mirroring the underlying-anchor approach already in
this file:

```python
strike_str = str(int(strike))
pattern = rf"(?<!\d){re.escape(strike_str)}{re.escape(option_type)}$"
matches = candidates[candidates["symbol_ticker"].str.contains(pattern, regex=True, na=False)]
```

- `...{option_type}$` anchors the strike to the end, immediately before the
  `CE`/`PE` suffix (so `3000` must be the actual strike, not a fragment of a
  larger number, and must carry the requested option type).
- `(?<!\d)` (no digit immediately before) stops `3000CE` from matching the
  tail of `...23000CE`.
- Folding `option_type` into the anchored pattern also removes the now-
  redundant separate `.str.endswith(option_type)` filter's reliance for
  correctness (that filter remains earlier in the function as a cheap
  pre-filter).

### 3.2 — Stale base `lot_size` in `backtest_engine.py`

`engineering_notes.md` #3 recorded updating the Nifty lot size `75 → 65`
"everywhere," but `StrategyBase.lot_size` was still the old placeholder `75`.
Every concrete strategy overrides it with `65`, so nothing in the current run
paths was mispriced — but the base default is the value any *new* strategy
subclass inherits by default, so a stale `75` there is a latent P&L-mispricing
trap for the next strategy someone adds. Updated to `65` with the same
"VERIFY before real use, NSE revises periodically" caveat the strategy files
carry.

### 3.3 — Unused import in `test_multi_backtest_offline.py`

`from backtest_engine import BacktestEngine` was imported but never used (the
engine is driven through `run_one` in `multi_backtest_lib`). Removed. (Same
category as `engineering_notes.md` #9.)

---

## 4. Pending item completed: NSE trading-holiday awareness

`engineering_notes.md` §4 and the `market_calendar.py` / `run_paper_trading.py`
comments flagged that the calendar only knew about **weekends**, not NSE
**trading holidays** (Republic Day, Diwali, etc.). On a holiday the bot would
idle to 15:30 then exit — harmless, but it can't *know* it's a holiday. This
pass implements it, staying within the module's deliberate design constraint
(dependency-free, no Fyers SDK import, so it stays trivially unit-testable —
the reason the module exists per `engineering_notes.md` #5).

Added to `market_calendar.py`:
- `_NSE_HOLIDAYS_BY_YEAR` — hardcoded holiday dates for **2025 (final)** and
  **2026 (best-effort)**, under a loud `VERIFY / REFRESH ANNUALLY` banner
  pointing at NSE's official holiday circular. Fixed-date holidays are marked
  reliable; movable-festival dates (Holi/Diwali/Id) are marked `~ (VERIFY)`.
  This matches how the rest of the repo treats exchange constants (lot size,
  expiry weekday): a sensible default the operator MUST confirm before trusting
  with capital.
- `is_trading_holiday(now)` — is this date a listed holiday.
- `holiday_calendar_covers(now)` — does the table even have data for this
  year? Lets callers distinguish "confirmed open" from "unknown / list is
  stale" instead of silently assuming open.
- `is_trading_day(now)` — `not weekend and not holiday`.
- `is_market_open(now)` — trading day **and** inside the 09:15–15:30 window
  (added `MARKET_OPEN_HOUR/MINUTE` constants; pre-open auction and Muhurat
  sessions explicitly not modeled).

Wired into `run_paper_trading.py`'s startup guard, right after the existing
weekend check:
- Exits immediately with a clear message on a known trading holiday (instead
  of idling to 15:30).
- If the holiday list has **no data for the current year**, prints a warning to
  refresh `market_calendar.py` and proceeds assuming a normal session (fail-
  safe: on a real holiday Fyers just returns no ticks and the loop idles out,
  so this can't cause bad trades — it only affects idle-vs-exit behavior).

Design note: a wrong/stale holiday date here cannot place a bad order. Worst
case it makes the bot exit on a day it wrongly thinks is closed, or idle
harmlessly on a real holiday it didn't know about. It does not feed the
order path. That's why a hardcoded, operator-verified list is acceptable here
rather than a live NSE calendar fetch (which would add a network dependency
and break the module's dependency-free, unit-testable design).

---

## 5. Verification performed

Consistent with the sandbox limits noted in `engineering_notes.md` (no live
Fyers connection / no network to the broker), verification focused on
everything runnable offline. A throwaway virtualenv with `pandas` + `requests`
was used, then removed.

- **`python -m py_compile` on every `.py`** (root + `strategies/`) — all
  compile clean.
- **`test_engine_offline.py`** — ran end-to-end: 120 synthetic candles → 22
  trades through the full engine + `ShortStraddle`. This exercises the
  previously-broken `from strategies.short_straddle import ...` path, proving
  the reorg fixed it.
- **`test_multi_backtest_offline.py`** — ran end-to-end: all five strategies
  in parallel threads, comparison table rendered. Exercises the full
  `multi_backtest_lib` → `strategies.*` import chain (four modules that were
  all failing before).
- **`symbol_lookup` strike fix** — synthetic DataFrame with colliding strikes
  (`3000` vs `23000`/`13000`/`30000`), plus a `BANKNIFTY` decoy and a wrong-
  `option_type` decoy. Confirmed a lookup for `NIFTY 3000 CE` returns exactly
  `NSE:NIFTY25JAN3000CE` and that `23000` still resolves to its own contract.
- **`market_calendar`** — asserted weekend / weekday-holiday / normal-trading-
  day classification, the 09:15–15:30 `is_market_open` window on both sides,
  holiday closure, and `holiday_calendar_covers` true/false for a known vs.
  unknown year. All pass.
- **Package + lot_size** — `from strategies import <all five>` re-exports
  resolve; `StrategyBase.lot_size == 65`.

**Not verified (unchanged from before — needs a real Fyers connection):**
`auth.py` OAuth exchange, `fyers_client.py` real REST calls,
`symbol_lookup.py`'s CSV column layout against a live `NSE_FO.csv` download,
`paper_trading.py`'s live WebSocket, and the full `run_paper_trading.py` loop
against a live session. The `strategies.*`-importing runner `run_backtest.py` /
`run_multi_backtest.py` also pull in the `fyers_apiv3` SDK, so they need the
SDK installed to run — but their strategy-import paths are the same ones the
offline tests proved.

---

## 6. Files touched this pass

**Moved:** `short_straddle.py`, `short_strangle.py`, `iron_condor.py`,
`vertical_spreads.py` → `strategies/`.

**Created:** `strategies/__init__.py`, `.gitignore`, `data/.gitkeep`,
`logs/.gitkeep`, this `engineering.md`.

**Removed:** root `__init__.py`.

**Edited:** `symbol_lookup.py` (strike anchor fix), `backtest_engine.py`
(`lot_size` 75→65), `test_multi_backtest_offline.py` (drop unused import),
`market_calendar.py` (holiday calendar + helpers), `run_paper_trading.py`
(holiday startup guard).

---

## 7. Still open / out of scope for this pass

These are genuinely un-buildable here (need a live Fyers account, network, or a
running market) or are large future phases from the PRD — flagged, not started,
consistent with `engineering_notes.md` §4:

- **Order manager** — the only module ever allowed to place real orders, behind
  hard risk limits. Large, safety-critical, PRD phase M6. Not started; must not
  be stubbed casually given what it does.
- **Web dashboard** — PRD phase M9. Not started.
- **Vertical-spread entry logic** — `BullCallSpread`/`BearPutSpread` still use
  the placeholder SMA-crossover trigger; not a real edge (unchanged — replacing
  it needs a genuine strategy decision, not a mechanical fix).
- **Live-download validation of `symbol_lookup.py`'s CSV `COLUMNS`** — still
  inferred from community docs, not confirmed against a real `NSE_FO.csv`
  (no network to Fyers here). The strike-matching fix above is independent of
  and unaffected by the column layout.
- **2026 holiday dates** — verify the `~ (VERIFY)` movable-festival entries in
  `market_calendar.py` against NSE's official 2026 circular before the 2026
  trading year; refresh the list each year.
- **Static-IP deployment / real Fyers app activation** — README documents the
  AWS/DigitalOcean + systemd path; not exercised on a real VM here.
