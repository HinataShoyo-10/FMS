"""
Paper trading engine.

Connects to REAL live market data via Fyers' WebSocket (data_ws), but never
calls any order-placement endpoint. All "fills" are simulated using the
actual live LTP (last traded price) at the moment a paper order is
"placed" - so unlike the backtester, this uses real premiums, not
Black-Scholes estimates. This is the layer that should catch problems the
backtester can't: real bid/ask spread behavior, illiquid strikes, data
feed hiccups, timing issues.

Nothing in this file can place a real order. The only Fyers calls made are
read-only market data subscriptions.
"""

from __future__ import annotations

import csv
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from fyers_apiv3.FyersWebsocket import data_ws

import auth
import config
import symbol_lookup

TRADE_LOG_PATH = os.path.join(os.path.dirname(__file__), "data", "paper_trades.csv")


@dataclass
class PaperLeg:
    symbol: str
    side: str  # "SELL" or "BUY"
    entry_price: float
    lots: int
    lot_size: int


@dataclass
class PaperPosition:
    entry_time: datetime
    legs: list[PaperLeg] = field(default_factory=list)
    is_open: bool = True
    exit_time: datetime | None = None
    exit_pnl: float = 0.0
    exit_reason: str = ""


class PriceCache:
    """Thread-safe latest-tick cache, updated by the WebSocket callback."""

    def __init__(self):
        self._lock = threading.Lock()
        self._prices: dict[str, float] = {}

    def update(self, symbol: str, ltp: float) -> None:
        with self._lock:
            self._prices[symbol] = ltp

    def get(self, symbol: str) -> float | None:
        with self._lock:
            return self._prices.get(symbol)


class PaperTradingSession:
    """
    A single paper-trading session for one underlying, running a strategy
    that decides when to open/close a straddle-shaped position based on
    live prices. Wire up your own strategy logic via the callback hooks
    below, or use PaperShortStraddle as a starting example.
    """

    def __init__(self, underlying_symbol: str, underlying_name: str, lot_size: int):
        self.underlying_symbol = underlying_symbol  # e.g. "NSE:NIFTY50-INDEX"
        self.underlying_name = underlying_name  # e.g. "NIFTY", for symbol lookup
        self.lot_size = lot_size

        self.prices = PriceCache()
        self.position: PaperPosition | None = None
        self.subscribed_symbols: set[str] = set()

        token = auth.load_cached_token()
        if not token:
            raise RuntimeError("No cached access token found. Run `python auth.py` first.")
        self.ws_token = f"{config.FYERS_CLIENT_ID}:{token}"

        self._ws: data_ws.FyersDataSocket | None = None
        self._ensure_trade_log()

    def _ensure_trade_log(self):
        os.makedirs(os.path.dirname(TRADE_LOG_PATH), exist_ok=True)
        if not os.path.exists(TRADE_LOG_PATH):
            with open(TRADE_LOG_PATH, "w", newline="") as f:
                csv.writer(f).writerow(
                    ["entry_time", "exit_time", "legs", "pnl", "exit_reason"]
                )

    def _log_trade(self, position: PaperPosition):
        legs_desc = "; ".join(
            f"{l.side} {l.symbol} @ {l.entry_price}" for l in position.legs
        )
        with open(TRADE_LOG_PATH, "a", newline="") as f:
            csv.writer(f).writerow(
                [position.entry_time, position.exit_time, legs_desc,
                 position.exit_pnl, position.exit_reason]
            )

    # ---- WebSocket plumbing --------------------------------------------

    def _on_message(self, message: dict):
        symbol = message.get("symbol")
        ltp = message.get("ltp")
        if symbol and ltp is not None:
            self.prices.update(symbol, float(ltp))

    def _on_error(self, message):
        print("WebSocket error:", message)

    def _on_close(self, message):
        print("WebSocket closed:", message)

    def _on_connect(self):
        self._subscribe([self.underlying_symbol])
        print(f"Connected, subscribed to {self.underlying_symbol}")

    def _subscribe(self, symbols: list[str]):
        new_symbols = [s for s in symbols if s not in self.subscribed_symbols]
        if new_symbols:
            self._ws.subscribe(symbols=new_symbols, data_type="SymbolUpdate")
            self.subscribed_symbols.update(new_symbols)

    def start(self):
        self._ws = data_ws.FyersDataSocket(
            access_token=self.ws_token,
            log_path=config.LOG_PATH,
            litemode=False,
            write_to_file=False,
            reconnect=True,
            on_connect=self._on_connect,
            on_close=self._on_close,
            on_error=self._on_error,
            on_message=self._on_message,
        )
        self._ws.connect()  # blocking - runs the socket loop

    # ---- Paper order simulation ----------------------------------------

    def open_position(self, legs_spec: list[tuple[str, str, int]]) -> PaperPosition:
        """
        legs_spec: list of (symbol, side, lots) tuples. Subscribes to each
        symbol, waits briefly for a live tick, then "fills" at that price.
        Never touches the real order API.
        """
        symbols = [s for s, _, _ in legs_spec]
        self._subscribe(symbols)

        # give the socket a moment to deliver first ticks for new symbols
        deadline = time.time() + 5
        while time.time() < deadline:
            if all(self.prices.get(s) is not None for s in symbols):
                break
            time.sleep(0.2)

        legs = []
        for symbol, side, lots in legs_spec:
            price = self.prices.get(symbol)
            if price is None:
                raise RuntimeError(f"No live price received for {symbol} - can't paper-fill")
            legs.append(PaperLeg(symbol=symbol, side=side, entry_price=price,
                                  lots=lots, lot_size=self.lot_size))

        self.position = PaperPosition(entry_time=datetime.now(), legs=legs)
        print(f"[PAPER] Opened position: "
              f"{[(l.symbol, l.side, l.entry_price) for l in legs]}")
        return self.position

    def mark_to_market(self) -> float | None:
        if self.position is None:
            return None
        total = 0.0
        for leg in self.position.legs:
            current = self.prices.get(leg.symbol)
            if current is None:
                return None  # can't mark without a live price
            if leg.side == "SELL":
                total += (leg.entry_price - current) * leg.lots * leg.lot_size
            else:
                total += (current - leg.entry_price) * leg.lots * leg.lot_size
        return total

    def close_position(self, reason: str):
        if self.position is None:
            return
        pnl = self.mark_to_market()
        self.position.is_open = False
        self.position.exit_time = datetime.now()
        self.position.exit_pnl = pnl or 0.0
        self.position.exit_reason = reason
        self._log_trade(self.position)
        print(f"[PAPER] Closed position: pnl={self.position.exit_pnl:.0f} reason={reason}")
        self.position = None
