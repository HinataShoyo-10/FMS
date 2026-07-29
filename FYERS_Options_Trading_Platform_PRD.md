# Product Requirements Document
## Automated Options Trading Platform (FYERS API v3, Indian Markets)

**Status:** Draft v1 — grounded solely in verified findings from the FYERS API v3 Technical Analysis. No implementation assumptions beyond what is explicitly marked.

---

## 1. Project Objective

Build a modular, production-grade automated trading platform for Indian equity derivatives (options-focused) that uses FYERS API v3 as its sole broker integration at launch. The platform must support live trading, paper trading, and backtesting on a shared strategy codebase, with its own system of record for orders, positions, and market data — since FYERS itself provides no persistence, failover, or monitoring beyond the current trading day's REST snapshots.

The platform is broker-agnostic by design (FYERS is the first adapter, not the only planned one), but v1 scope is FYERS-only.

---

## 2. Scope

**In scope (v1):**
- Authentication/session management against FYERS API v3 (auth-code login + daily refresh-token flow).
- Live trading and paper trading using a shared strategy interface.
- Historical-data backtesting using FYERS `history()` data, paginated to respect documented limits.
- Option chain ingestion and storage (snapshots) for NSE/BSE/MCX-listed underlyings enabled on the account.
- Order placement, modification, cancellation, basket orders (≤10), and 2–3 leg multileg orders.
- Real-time market data and order/trade/position updates via FYERS' three WebSocket channels.
- Client-side rate limiting, retry logic, and REST-based reconciliation against WebSocket state.
- Client-side computation of Greeks/IV, PCR, Max Pain, OI-buildup classification (none are broker-supplied).
- Risk controls (loss limits, position sizing, kill switch) enforced locally, independent of any FYERS-side automation.
- Structured logging, notifications (order/PnL/error alerts), and a dashboard for monitoring.

**Out of scope (v1):**
- Any broker other than FYERS (architecture must not preclude adding one later).
- Fully unattended operation beyond 15 days without human re-authentication — no documented FYERS mechanism supports this.
- Reliance on FYERS "Smart Orders" / "Smart Exit Triggers" as the primary risk/exit mechanism — these are thin-documented and unverified for latency/reliability; may be evaluated as a supplementary layer only after empirical validation.
- Multi-account or multi-broker portfolio aggregation.
- Options strategy auto-discovery/AI-generated strategies — v1 assumes human-authored strategies against a defined `BaseStrategy` interface.
- Corporate-actions-aware equity backtesting beyond what FYERS' historical data already reflects.

---

## 3. Functional Requirements

**Authentication & Session**
- FR1: System shall implement the OAuth-style authorization-code login flow (client_id, secret_key, redirect_uri, state) to obtain an initial access_token + refresh_token.
- FR2: System shall implement the daily refresh flow (`POST /api/v3/validate-refresh-token` with appIdHash, refresh_token, PIN) to renew the access token without a full login, and shall alert a human when the 15-day refresh-token window is approaching expiry.
- FR3: System shall store all tokens and the PIN encrypted at rest, never in plaintext files or source control.

**Market Data**
- FR4: System shall fetch historical OHLCV via `history()`, automatically paginating requests to respect the 100-day (intraday), 366-day (daily), and 30-trading-day (seconds) limits, and persist fetched candles so gaps — not the full range — are re-fetched on subsequent runs.
- FR5: System shall maintain a live Data Socket subscription (SymbolUpdate/DepthUpdate, litemode where only LTP is needed) for all actively tracked symbols, and shall design a subscription-priority/rotation mechanism in case the tracked universe exceeds the confirmed 200-symbol ceiling.
- FR6: System shall use REST `quotes()`/`depth()` only for gap recovery or symbols outside the active WebSocket subscription set — not as a polling substitute for the socket.
- FR7: System shall download and cache the daily FYERS symbol-master CSVs and resolve all option/future symbol strings from this cache rather than constructing them manually.

**Option Chain & Analytics**
- FR8: System shall poll `optionchain()` on a fixed interval (rate-limiter-respecting) for each tracked underlying and persist each snapshot for time-series analytics.
- FR9: System shall compute, client-side, since none are broker-supplied: IV, Greeks (delta/gamma/theta/vega), PCR, Max Pain, ATM/ITM/OTM classification, OI-buildup classification, and expected move.

**Order Management**
- FR10: System shall support order placement (`place_order`), basket orders (≤10 legs), and native multileg orders (2–3 legs) for spread/straddle strategies.
- FR11: System shall support order modification and cancellation, single and batch.
- FR12: System shall generate and track its own client-side idempotency tag per order to prevent double submission on network retry, since FYERS provides none.
- FR13: System shall consume the Order Socket (`OnOrders`, `OnTrades`, `OnPositions`, `OnGeneral`) as the primary real-time order-state channel, and shall run a periodic reconciliation loop against `orderbook()`/`tradebook()`/`positions()` as the authoritative source of truth.
- FR14: System shall correlate its own internal order/trade IDs against FYERS' `id_fyers` field where present.

**Risk Management**
- FR15: System shall enforce daily max loss/profit, max trade count, position sizing, and exposure limits locally, independent of and in addition to any FYERS-side triggers.
- FR16: System shall provide a kill switch capable of halting new order placement and (optionally) squaring off open positions via `exit_positions()`.
- FR17: System shall halt new order placement if the Data Socket is stale beyond a configurable threshold.

**Strategy Engine**
- FR18: System shall expose a `BaseStrategy` interface (on_tick, on_candle, on_order, on_trade, on_start, on_stop) usable identically across live, paper, and backtest modes.
- FR19: System shall support multiple strategies running concurrently against the shared event bus.

**Backtesting**
- FR20: System shall backtest against persisted historical OHLC data, with commission/slippage/latency modeling, and account for option expiry/lot sizes resolved from the symbol master.

**Notifications & Dashboard**
- FR21: System shall send order, PnL, and error alerts via at least one external channel (Telegram/Email/Slack).
- FR22: System shall expose a dashboard (PnL, positions, orders, option chain, risk metrics, strategy status, logs) reflecting the platform's own persisted state, not live FYERS calls on every view.

---

## 4. Non-Functional Requirements

**Performance**
- NFR1: All REST calls must pass through a single shared token-bucket rate limiter enforcing headroom below FYERS' documented 10/sec, 200/min, 100,000/day limits (e.g., cap at 8/sec, 180/min).
- NFR2: WebSocket consumers must run in dedicated threads/processes with non-blocking hand-off to the internal event bus, since the SDK's `keep_running()` blocks its own thread.

**Reliability**
- NFR3: Each of the three WebSocket connections (Data, Order, TBT) must have an independent reconnect/backoff supervisor, since auto-reconnect parity across all three is unconfirmed from the SDK documentation.
- NFR4: REST-based reconciliation of orders/positions must run on a fixed interval regardless of WebSocket health, since the socket stream is documented as fast but not guaranteed.
- NFR5: The system must degrade safely (halt new orders, alert) on prolonged auth failure or data staleness rather than trading on stale/unknown state.

**Security**
- NFR6: Credentials (secret_key, tokens, PIN) must be stored in environment variables or a secrets manager, encrypted at rest if persisted, never logged in plaintext.
- NFR7: Separate FYERS API apps must be used for non-production and production environments (least privilege).

**Scalability**
- NFR8: The symbol-subscription layer must support prioritization/rotation to operate correctly whether the real Data Socket ceiling turns out to be 200 or 5,000 symbols (currently unconfirmed — see §10).
- NFR9: Historical and option-chain storage must be designed for continuous, unbounded accumulation (own long-horizon store), since FYERS itself caps single-request history windows.

---

## 5. User Roles

Documented FYERS auth model implies a single trading identity per app/account (one login = one FYERS trading account). Within the platform itself (not documented by FYERS, but required for the stated project goals):
- **Trader/Operator** — configures strategies, monitors dashboard, authorizes re-login, operates kill switch.
- **Administrator** — manages configuration, credentials, and environment (paper vs. live) at a system level.
- No FYERS-documented concept of sub-users, delegated permissions, or multi-user access exists within a single API app; any additional roles are a platform-level construct, not a FYERS capability.

---

## 6. Supported Instruments (per FYERS capabilities)

- NSE/BSE equities (cash segment).
- NSE/BSE/MCX Futures & Options (index and stock options are the primary focus for this platform).
- Currency derivatives and commodities, to the extent enabled on the underlying trading account.
- Access to each asset class is gated by the FYERS trading account's own segment permissions — the API grants no access beyond what the account already has (e.g., F&O must be separately enabled).
- Index option chains (e.g., NIFTY, BANKNIFTY-style underlyings) are retrievable via `optionchain()`; option/future symbol strings must be resolved from the daily symbol-master CSV rather than hand-built, since the weekly-vs-monthly token format is not cleanly documented and has changed historically across products (e.g., SENSEX vs. NIFTY).

---

## 7. Trading Workflow: Login to Order Execution

1. **App setup (one-time):** Register app at FYERS dashboard → obtain client_id + secret_key.
2. **Daily/periodic login:** Operator (or scheduler) triggers auth-code URL → user logs in with credentials + TOTP 2FA → FYERS redirects with auth_code → system exchanges it for access_token + refresh_token.
3. **Daily refresh (no full login):** System calls the refresh endpoint with appIdHash + refresh_token + PIN to mint a new access_token before market open, until the refresh_token itself expires at 15 days.
4. **Session ready:** Auth/Session module hands a valid `client_id:access_token` string to all other modules.
5. **Market data ingestion:** Symbol master cached for the day; Data Socket subscribed for tracked symbols; option chain polled on interval and snapshotted.
6. **Strategy evaluation:** Strategy Engine consumes ticks/candles/option-chain snapshots via the event bus and emits trade signals.
7. **Risk check:** Risk module validates signal against daily loss/exposure/position-size limits before allowing order submission.
8. **Order placement:** Execution module tags the order with an idempotency key and calls `place_order`/`place_basket_orders`/`place_multileg_order`. FYERS validates synchronously (margin, symbol, market hours); a rejection returns an error code immediately.
9. **Order lifecycle tracking:** Order Socket streams status transitions (PENDING → OPEN → PARTIALLY_FILLED/FILLED, or CANCELLED/REJECTED) and trade fills; Position updates follow.
10. **Reconciliation:** On a fixed interval, system diffs local state against `orderbook()`/`tradebook()`/`positions()` REST snapshots to catch any missed or duplicate socket events.
11. **Exit/risk actions:** Trailing SL, target, time-exit, or kill-switch logic triggers further orders or `exit_positions()` calls as needed, following the same placement/tracking/reconciliation path.
12. **End of day:** Reconciled state persisted; dashboard/notifications reflect final PnL; next day's login/refresh cycle begins.

---

## 8. Required Integrations

- **FYERS API v3** — REST (auth, account, orders, market data, option chain) and three WebSockets (Data, Order, TBT). Sole broker integration at launch; abstracted behind a Broker Interface for future extensibility.
- **Database (PostgreSQL, per project brief)** — system of record for orders, trades, positions, strategy parameters, backtest results, option-chain snapshots, and market data — required because FYERS itself provides no long-horizon persistence.
- **Notification channels** — Telegram/Email/Slack for order, PnL, and error alerts (FYERS provides no notification mechanism itself).
- **Symbol master files** — daily CSV downloads from `public.fyers.in/sym_details/` (NSE_CM, NSE_FO, and BSE/MCX equivalents) as the authoritative symbol-resolution source.
- **Secrets manager / encrypted store** — for client_id, secret_key, tokens, and PIN.

---

## 9. Risks, Constraints, and Documented API Limitations

| Item | Nature | Mitigation |
|---|---|---|
| Access token expires daily; refresh token expires in 15 days with no documented renewal-without-login path | Documented constraint | Proactive refresh scheduler; human-in-the-loop re-auth alerting; no promise of unattended >15-day operation |
| Refresh requires the account PIN | Documented constraint | Treat PIN with secret-key-level protection; restrict which process can access it |
| Historical data capped per request (100/366/30 days by resolution) | Documented limit | Mandatory pagination + own long-horizon store |
| Rate limits: 10/sec, 200/min, 100,000/day, with reports of stricter real-world enforcement and an undocumented escalating penalty for repeated per-minute breaches | Documented + community-reported | Centralized rate limiter with safety margin, never operate at the ceiling |
| Data Socket subscription ceiling inconsistently documented (200 vs. 5,000) | Documentation inconsistency | Empirical testing required; design for the lower bound until confirmed |
| No native IV/Greeks in option chain response | Confirmed absence in all reviewed sources | Own Analytics-module computation |
| No order idempotency protection in the SDK | Confirmed absence | Client-generated order tags + reconciliation |
| `appIdHash` not actually validated server-side; refresh token reuse not confirmed to be blocked | Community-reported bug/gap | Do not rely on these as security boundaries; implement correct behavior regardless |
| Smart Orders/Smart Exit Triggers are thin-documented | Documentation gap | Treat as experimental/supplementary, not core risk infrastructure, until validated |
| Exact order-status and order-type/side/productType enum tables not available from any source reviewed | Documentation gap | Must be sourced from the live docs UI or logged empirically before Order Management is finalized |

---

## 10. Open Questions Requiring Validation Before Implementation

1. Full numeric enum tables for order `type`, `side`, `productType`, and the complete order-status code set.
2. True Data Socket subscription ceiling (200 vs. 5,000 symbols).
3. Exact accepted format/semantics of `optionchain()`'s `timestamp` parameter for selecting a non-nearest expiry.
4. Definitive confirmation that no IV/Greeks fields exist natively in the option chain response.
5. Real-world behavior/completeness of `is_async=True` on `FyersModel`.
6. Auto-reconnect support parity across the Order Socket and TBT Socket (only explicitly documented for the Data Socket).
7. The precise escalating-penalty mechanism for repeated per-minute rate-limit breaches.
8. Full, current column schema of the symbol-master CSVs (several undocumented trailing numeric columns reported).
9. Latency/reliability of Smart Orders and Smart Exit Triggers relative to a client-side risk engine.

**Recommended approach:** resolve items 1–4 and 6–9 via a small diagnostic script against a paper/low-capital live account before finalizing the Order Management, WebSocket, and Analytics module designs.

---

## 11. Assumptions (minimal, clearly marked)

- **A1:** "PostgreSQL" and the general module list (dashboard via FastAPI, notifications via Telegram/Email/Slack) are carried over from the original project brief, not from FYERS documentation — FYERS is agnostic to database/dashboard/notification technology choice.
- **A2:** The platform's user-role model (Trader/Operator, Administrator) is a platform-level construct, since FYERS' documentation only defines a single trading identity per app/account.
- **A3:** "Production-grade" is assumed to require the reconciliation, rate-limiting, and idempotency safeguards described above, since FYERS explicitly does not provide these itself.

---

## 12. Milestones

1. **M1 — Diagnostic & Validation:** Run the diagnostic script against a paper/low-capital account to close the open questions in §10.
2. **M2 — Core Configuration & Auth/Session:** YAML-driven config; token lifecycle (issue, refresh, expiry alerting); secrets handling.
3. **M3 — Broker Interface & FYERS Adapter:** REST wrapper with rate limiting, retries, idempotency tagging; symbol-master caching and resolution.
4. **M4 — WebSocket Layer:** Three independent socket managers (Data, Order, TBT) feeding a shared internal event bus with reconnect supervision.
5. **M5 — Data & Option Chain Engine:** OHLC storage, option-chain snapshotting, Greeks/IV/PCR/Max Pain/OI-buildup computation.
6. **M6 — Order Management & Risk Engine:** Order placement/modification/cancellation, reconciliation loop, risk limits, kill switch.
7. **M7 — Strategy Engine & Paper Trading:** `BaseStrategy` interface, multi-strategy support, live paper-trading validation against real market data.
8. **M8 — Backtesting Engine:** Event-driven backtester using persisted historical data, with commission/slippage/expiry modeling.
9. **M9 — Dashboard & Notifications:** FastAPI dashboard, alerting channels, structured logging finalized.
10. **M10 — Live Trading Readiness Review:** End-to-end validation in live account with minimal capital before scaling exposure.

---

*This PRD reflects only what is documented or empirically reported about FYERS API v3 as of the technical analysis. Items in §10 must be resolved before downstream module designs (particularly Order Management and WebSocket subscription strategy) are finalized.*
