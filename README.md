# Fyers Options Bot

Automated options trading system for Indian markets (Nifty/BankNifty) via
the Fyers API. Built in layers: data/auth foundation → backtester → paper
trading → (next) live order manager → (next) dashboard. Requires a static
IP for Fyers API activation — see **Deployment** below.

---

## Project structure

```
fyers-options-bot/
├── README.md                  # this file
├── engineering_notes.md       # build log: decisions, bugs found/fixed, open items
├── requirements.txt           # pip dependencies
├── .gitignore                 # excludes secrets, tokens, cache
│
├── config.py                  # loads credentials from env vars
├── auth.py                    # daily OAuth login, caches access token
├── fyers_client.py            # REST wrapper: profile, historical candles, option chain
│
├── black_scholes.py           # synthetic option pricer (backtesting only)
├── backtest_engine.py         # generic backtest engine + Strategy interface
├── run_backtest.py            # pulls real historical candles, runs a single backtest
├── multi_backtest_lib.py      # shared logic for running several strategies concurrently
├── run_multi_backtest.py      # runs ALL strategies in parallel, prints comparison table
├── test_engine_offline.py     # sanity test with synthetic data, no Fyers needed
├── test_multi_backtest_offline.py  # same, but for the parallel multi-strategy runner
│
├── symbol_lookup.py           # resolves exact live option symbols via Fyers' symbol master
├── market_calendar.py         # weekend / market-close time helpers (no Fyers dependency)
├── paper_trading.py           # live WebSocket data + simulated fills, no real orders
├── run_paper_trading.py       # driver loop: entry/exit rules + daily loss kill-switch, exits at market close
│
├── strategies/
│   ├── __init__.py
│   ├── short_straddle.py      # sell ATM call+put
│   ├── short_strangle.py      # sell OTM call+put (wider profit zone, less premium)
│   ├── iron_condor.py         # short strangle + long wings (defined max loss)
│   └── vertical_spreads.py    # BullCallSpread + BearPutSpread (directional, defined risk)
│
├── data/                      # gitignored — access_token.txt, trade logs, symbol master cache
└── logs/                      # gitignored — Fyers SDK logs
```

Not yet built (next phases): `order_manager.py` (the only module ever
allowed to call the real order-placement endpoint, sitting behind hard
risk limits) and a web dashboard.

---

## Deployment: getting a static IP (required for Fyers API activation)

Fyers requires a static `primaryIpAddress` (and optionally a
`secondaryIpAddress`) to activate your API app — see the activation form
under App Info. You have two options: a static IP from your home/office
ISP (fine for early development), or a small always-on cloud VM (better
for this project, since the bot needs to be reachable during market hours
reliably — a laptop that sleeps or loses home broadband mid-session is a
real failure mode once you're paper/live trading). Steps for both major
cloud providers below.

### Option A — AWS (Elastic IP + EC2)

1. **Launch an EC2 instance**
   - AWS Console → EC2 → Launch Instance
   - Choose Ubuntu 22.04/24.04 LTS, `t2.micro` or `t3.micro` (free-tier
     eligible, plenty for this bot)
   - Region: pick one geographically close to India (`ap-south-1` — Mumbai)
     for lower latency to Fyers' servers
   - Create/select a key pair (`.pem` file) — needed for SSH access
   - Under Network Settings, allow SSH (port 22) from your IP

2. **Allocate an Elastic IP** (this is what makes the IP static — a
   regular EC2 public IP changes if you stop/start the instance)
   - EC2 Console → Network & Security → Elastic IPs → Allocate Elastic IP address
   - Select the allocated IP → Actions → Associate Elastic IP address →
     choose your instance
   - This IP is now yours permanently (while associated) — this is the
     value to put in Fyers' `primaryIpAddress` field

3. **Connect and set up the environment**
   ```bash
   ssh -i your-key.pem ubuntu@<your-elastic-ip>
   sudo apt update && sudo apt install -y python3-pip python3-venv git
   git clone https://github.com/<your-username>/Algo_bot.git
   cd Algo_bot
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Note on cost**: Elastic IPs are free *while attached to a running
   instance*, but AWS charges an hourly fee for an allocated Elastic IP
   that's sitting unattached (e.g. instance stopped) — don't leave the
   instance stopped for long periods with the IP still allocated.

### Option B — DigitalOcean (Reserved IP + Droplet)

1. **Create a Droplet**
   - DigitalOcean Console → Create → Droplets
   - Image: Ubuntu 22.04/24.04 LTS
   - Plan: Basic, cheapest shared-CPU tier is enough
   - Region: pick Bangalore (`BLR1`) — DigitalOcean's India datacenter,
     lowest latency to Fyers
   - Authentication: SSH key (upload your public key) or password
   - Create the Droplet

2. **Assign a Reserved IP** (DigitalOcean's static IP feature)
   - Droplet's page → Networking tab → Reserved IPs → Assign Reserved IP
     → select this Droplet
   - Or: Console → Networking → Reserved IPs → Create Reserved IP → assign
     to your Droplet
   - This IP stays yours even if you destroy/recreate the Droplet (as long
     as you keep the reserved IP itself) — use this as `primaryIpAddress`

3. **Connect and set up the environment**
   ```bash
   ssh root@<your-reserved-ip>
   apt update && apt install -y python3-pip python3-venv git
   git clone https://github.com/<your-username>/Algo_bot.git
   cd Algo_bot
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Note on cost**: DigitalOcean charges a small hourly fee for a
   Reserved IP *only when it's not attached to a Droplet* — free while
   attached, so keep it assigned.

### After you have the IP (either provider)

- Put the IP in Fyers' app activation form (`primaryIpAddress`). If you
  want a fallback (e.g. a second region, or your ISP's static IP as
  backup), put it in `secondaryIpAddress`.
- Continue with **One-time setup** below, run from the VM rather than
  your laptop, using the credentials you set up there.
- To keep the bot running after you disconnect SSH, use `systemd` (or
  `tmux`/`screen` for something quicker):
  ```bash
  # /etc/systemd/system/paper-trading.service
  [Unit]
  Description=Fyers Options Paper Trading Bot
  After=network.target

  [Service]
  Type=simple
  User=ubuntu
  WorkingDirectory=/home/ubuntu/Algo_bot
  Environment="FYERS_CLIENT_ID=your-app-id"
  Environment="FYERS_SECRET_KEY=your-secret-key"
  Environment="FYERS_REDIRECT_URI=https://127.0.0.1"
  ExecStart=/home/ubuntu/Algo_bot/venv/bin/python run_paper_trading.py
  Restart=on-failure

  [Install]
  WantedBy=multi-user.target
  ```
  ```bash
  sudo systemctl daemon-reload
  sudo systemctl enable paper-trading
  sudo systemctl start paper-trading
  sudo systemctl status paper-trading    # check it's running
  journalctl -u paper-trading -f         # follow live logs
  ```
  Note: `auth.py`'s login step is interactive (you paste a URL back) — you
  still need to run that manually each morning via SSH before the service
  will have a valid token; it isn't part of the automated service.

---

## One-time setup

**0. Get a static IP first** — see the Deployment section above. You need
this IP to activate your Fyers app in step 1.

**1. Create a Fyers API app**
- Go to https://myapi.fyers.in/dashboard → Create App
- Note the **App ID** (client_id) and **Secret Key**
- Set a redirect URI — anything works, e.g. `https://127.0.0.1` (you don't
  need a real server; you'll just copy the URL from your browser's address
  bar after login redirects you)

**2. Get the code and install dependencies**
```bash
cd fyers-options-bot
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**3. Set credentials as environment variables** (never commit these —
`.gitignore` already excludes `.env`)
```bash
export FYERS_CLIENT_ID="your-app-id"
export FYERS_SECRET_KEY="your-secret-key"
export FYERS_REDIRECT_URI="https://127.0.0.1"
```
Tip: put these three lines in a local `.env` file and `source .env` each
session, so you don't retype them.

---

## Daily routine (run in this order, every trading day)

**Step 1 — Log in.** Fyers access tokens expire once a day (not on a
rolling timer), so this has to run each morning before anything else.
```bash
python auth.py
```
It prints a login URL → open it, log in, approve the app → copy the full
URL you get redirected to → paste it back into the terminal when prompted.
The token is cached to `data/access_token.txt` for the rest of your
scripts to reuse.

> **Running this on a headless cloud VM (AWS/DigitalOcean):** there's no
> browser on the server, so the flow is: run `python auth.py` over your
> SSH session, it prints a URL — **copy that URL and open it in your own
> laptop's browser**, log in and approve there, then copy the full
> redirected URL from your laptop's address bar and **paste it back into
> the SSH terminal** when prompted. The login itself happens on your
> laptop; only the token exchange and caching happens on the VM.

**Step 2 — Smoke test the connection.**
```bash
python fyers_client.py
```
Should print your account profile. If this fails, nothing downstream will
work — fix this first.

---

## Backtesting

No live connection needed for the offline sanity check; needs Step 1+2
above for the real-data version.

```bash
# Quick check that the engine/strategy logic itself works (synthetic data)
python test_engine_offline.py

# Real backtest against actual historical Nifty candles - single strategy
python run_backtest.py
```
Edit `strategies/short_straddle.py` (or add a new file in `strategies/`
implementing `StrategyBase`) to change the logic being tested. Adjust the
lookback window and strategy parameters directly in `run_backtest.py`.

### Backtesting all strategies at once (parallel)

```bash
# Offline sanity check - synthetic data, no Fyers connection needed
python test_multi_backtest_offline.py

# Real run - all strategies against the same actual historical data
python run_multi_backtest.py
```
`run_multi_backtest.py` fetches historical candles **once**, then runs
every strategy listed in `multi_backtest_lib.py`'s `STRATEGIES` dict
concurrently (each in its own thread, sharing the same candle data) and
prints a side-by-side comparison table: trade count, total P&L, win rate,
avg win/loss, and max drawdown per strategy.

To add a new strategy to the comparison: implement it in `strategies/`
(subclassing `StrategyBase`, same pattern as the existing ones), then add
one line to the `STRATEGIES` dict in `multi_backtest_lib.py`.

Currently included:
| Strategy | Type | Risk |
|---|---|---|
| `ShortStraddle` | Sell ATM call+put | Undefined - bounded only by stop-loss |
| `ShortStrangle` | Sell OTM call+put | Undefined - wider profit zone, less premium |
| `IronCondor` | Short strangle + long wings | Defined at entry |
| `BullCallSpread` | Buy/sell calls, bullish | Defined at entry |
| `BearPutSpread` | Buy/sell puts, bearish | Defined at entry |

The two vertical spreads use a placeholder SMA-crossover entry trigger -
see the docstring in `vertical_spreads.py`. Replace it with real
directional logic before trusting those two in paper/live trading.

---

## Paper trading

Requires Step 1+2 above, and must be run **during market hours** (no
ticks will fire outside NSE trading hours, so it'll just idle).

```bash
# One-time / periodic: verify the symbol master downloads and parses correctly
python symbol_lookup.py

# Start the live paper-trading loop
python run_paper_trading.py
```
This connects to real market data and simulates fills at real live
prices — it never places a real order. Stop anytime with `Ctrl+C`; there's
nothing to "cancel" since nothing real was ever sent to the broker.

**The script exits automatically shortly after market close (15:30) each
day** — this is intentional, not a bug. Fyers tokens expire daily and
`auth.py`'s login is interactive, so there's no way for the process to
silently refresh itself past midnight; rather than leave it running on a
dead token indefinitely, it closes any open position, prints the day's
P&L, and exits cleanly. Re-run `auth.py` and restart it (or the
`systemd` service) each trading morning. It also exits immediately if
started on a weekend.

Trade history is appended to `data/paper_trades.csv` — check this after a
session to review entries, exits, and P&L.

Before your first live paper session, review and adjust in
`run_paper_trading.py`:
- `LOT_SIZE` — verify against the current exchange-specified lot size
- `ENTRY_HOUR` / `ENTRY_MINUTE` — when the strategy looks to enter
- `STOP_LOSS_MULTIPLE`, `MAX_HOLD_MINUTES`, `DAILY_LOSS_CAP` — risk limits

---

## Quick reference — full command list top to bottom

```bash
# Deployment (once) - see Deployment section for full provider steps
# 1. Launch VM (AWS EC2 / DigitalOcean Droplet) in a Mumbai/Bangalore region
# 2. Attach a static IP (AWS Elastic IP / DO Reserved IP)
# 3. SSH in, clone the repo, set up the venv there

# Setup (once)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export FYERS_CLIENT_ID="..." FYERS_SECRET_KEY="..." FYERS_REDIRECT_URI="https://127.0.0.1"

# Every trading day
python auth.py
python fyers_client.py          # smoke test

# Backtesting (any time)
python test_engine_offline.py
python run_backtest.py
python test_multi_backtest_offline.py
python run_multi_backtest.py         # all strategies, parallel, comparison table

# Paper trading (market hours only - exits automatically at 15:30)
python symbol_lookup.py         # verify symbol master parses correctly
python run_paper_trading.py
```

---

## Notes / known limitations

- **Recent fixes worth knowing about:**
  - `symbol_lookup.py` had a substring-matching bug where searching for
    "NIFTY" could also match "BANKNIFTY", "NIFTYNXT50", or "MIDCPNIFTY"
    contracts (since "NIFTY" is literally a substring of those names) —
    now uses an anchored regex that isolates the exact underlying.
  - `run_paper_trading.py` used to have `entered_today`/`daily_pnl` state
    that never reset, meaning a long-running process would trade once and
    then sit idle forever. Fixed by having the script deliberately exit
    at market close each day (see the Paper Trading section) rather than
    try to survive across days — which also sidesteps the fact that
    Fyers tokens expire daily and the login step is interactive, so a
    resident process can't refresh its own token unattended anyway.
  - `open_position()` failures (e.g. no live tick for an illiquid strike
    within the timeout) used to crash the whole session; now caught and
    logged, skipping that day's entry instead.
- **Indian market specifics baked into this code (verify before trusting):**
  - Nifty weekly *and* monthly expiry moved from **Thursday to Tuesday**,
    effective 1 September 2025 (SEBI-directed change to spread expiry
    volume across the week). All expiry-calendar code here defaults to
    Tuesday (`expiry_weekday=1`) — if you're backtesting pre-Sept-2025
    data, pass `expiry_weekday=3` instead.
  - **Bank Nifty no longer has weekly options at all** — NSE kept only
    Nifty as a weekly index product; Bank Nifty, FinNifty, and MidcpNifty
    are monthly-only now. Don't point the weekly-expiry strategies at Bank
    Nifty — symbol lookups will fail to find valid weekly contracts.
  - Lot sizes shown here (`lot_size = 65` for Nifty) reflect the cycle
    effective January 2026. **NSE revises these periodically** — always
    check the current value (NSE site, your broker, or the option chain
    itself) before running with real or paper capital, since a stale lot
    size silently misprices every P&L number this code produces.
- **Token expiry**: Fyers access tokens invalidate once daily — re-run
  `auth.py` each morning, or later automate it with Selenium if you want a
  hands-off pipeline (adds fragility, optional).
- **Backtesting uses synthetic option pricing** (Black-Scholes off real
  underlying price history), not real historical option premiums — Fyers
  doesn't reliably provide the latter for expired weekly contracts. Good
  for validating entry/exit *logic*, not for precise expected-return
  numbers.
- **`symbol_lookup.py`'s CSV column layout is unverified against a live
  download** in this environment (no network access here) — run it
  standalone first and confirm the printed expiries look sane before
  trusting it in the paper/live loop.
- Not yet built: the order manager (only module ever allowed to place real
  orders, behind hard risk limits) and the web dashboard.
