"""
Thin wrapper around fyers_apiv3.fyersModel.FyersModel.

Everything downstream (backtester, paper trader, live bot) should go
through this class rather than touching the SDK directly - it's the one
place that knows about token loading, retries, and response-shape quirks.
"""

from __future__ import annotations

import pandas as pd
from fyers_apiv3 import fyersModel

import auth
import config


class FyersClient:
    def __init__(self):
        token = auth.load_cached_token()
        if not token:
            raise RuntimeError(
                "No cached access token found. Run `python auth.py` first."
            )
        self._fyers = fyersModel.FyersModel(
            client_id=config.FYERS_CLIENT_ID,
            token=token,
            is_async=False,
            log_path=config.LOG_PATH,
        )

    # ---- account / connectivity -------------------------------------

    def get_profile(self) -> dict:
        return self._fyers.get_profile()

    def get_funds(self) -> dict:
        return self._fyers.funds()

    def is_connected(self) -> bool:
        """Cheap sanity check that the cached token is still valid."""
        resp = self.get_profile()
        return resp.get("s") == "ok"

    # ---- market data ---------------------------------------------------

    def get_historical_candles(
        self,
        symbol: str,
        resolution: str,
        range_from: str,
        range_to: str,
        cont_flag: str = "1",
    ) -> pd.DataFrame:
        """
        symbol: e.g. "NSE:NIFTYBANK-INDEX" or "NSE:NIFTY50-INDEX"
        resolution: candle size in minutes as a string, e.g. "1", "5", "15",
                    or "D" for daily
        range_from / range_to: "YYYY-MM-DD"
        """
        data = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": "1",
            "range_from": range_from,
            "range_to": range_to,
            "cont_flag": cont_flag,
        }
        response = self._fyers.history(data=data)

        if response.get("s") != "ok":
            raise RuntimeError(f"History fetch failed: {response}")

        df = pd.DataFrame(
            response["candles"],
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df["timestamp"] = df["timestamp"].dt.tz_convert("Asia/Kolkata")
        return df

    def get_option_chain(self, symbol: str, strike_count: int = 20) -> dict:
        """
        symbol: underlying, e.g. "NSE:NIFTY50-INDEX" or "NSE:NIFTYBANK-INDEX"
        strike_count: number of strikes to fetch on each side of ATM

        Returns the raw response - contains 'optionsChain' (list of strikes
        with CE/PE OI, LTP, bid/ask) and 'expiryData'.
        """
        data = {
            "symbol": symbol,
            "strikecount": str(strike_count),
            "timestamp": "",
        }
        response = self._fyers.optionchain(data=data)

        if response.get("s") != "ok":
            raise RuntimeError(f"Option chain fetch failed: {response}")

        return response


if __name__ == "__main__":
    # quick manual smoke test - run after auth.py
    client = FyersClient()
    print("Connected:", client.is_connected())
    print(client.get_profile())
