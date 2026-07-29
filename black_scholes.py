"""
Black-Scholes option pricing - used ONLY for backtesting, to synthesize
option premiums from historical underlying price + realized volatility.

Why: Fyers doesn't give reliable historical option premium data (expired
weekly contracts drop out of the symbol master, and community reports show
the weekly symbol format itself is inconsistent/error-prone across
expiries). Rather than pretend we have real historical premiums, we
estimate them from the underlying's price path. This is a standard
approach for retail options backtesting, but it's an approximation:
- Assumes lognormal returns, doesn't capture volatility skew near expiry
- Real fills will differ, especially in the last day or two before expiry
  when gamma/theta dominate and the model is least reliable

Use this to sanity-check strategy *logic* (entry/exit timing, stop-loss
behavior, rough win rate) - not to estimate exact expected P&L.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

RISK_FREE_RATE = 0.065  # approx Indian short-term risk-free rate; adjust as needed


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


@dataclass
class OptionQuote:
    price: float
    delta: float


def bs_price(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    volatility: float,
    option_type: str,  # "CE" or "PE"
    risk_free_rate: float = RISK_FREE_RATE,
) -> OptionQuote:
    """
    Black-Scholes European option price + delta.

    time_to_expiry_years: e.g. 3 trading days out of ~252/year = 3/252
    volatility: annualized, e.g. 0.13 for 13%
    """
    if time_to_expiry_years <= 0 or volatility <= 0:
        # At/past expiry - intrinsic value only
        if option_type == "CE":
            price = max(spot - strike, 0.0)
            delta = 1.0 if spot > strike else 0.0
        else:
            price = max(strike - spot, 0.0)
            delta = -1.0 if spot < strike else 0.0
        return OptionQuote(price=price, delta=delta)

    d1 = (
        math.log(spot / strike)
        + (risk_free_rate + 0.5 * volatility**2) * time_to_expiry_years
    ) / (volatility * math.sqrt(time_to_expiry_years))
    d2 = d1 - volatility * math.sqrt(time_to_expiry_years)

    if option_type == "CE":
        price = spot * _norm_cdf(d1) - strike * math.exp(
            -risk_free_rate * time_to_expiry_years
        ) * _norm_cdf(d2)
        delta = _norm_cdf(d1)
    elif option_type == "PE":
        price = strike * math.exp(-risk_free_rate * time_to_expiry_years) * _norm_cdf(
            -d2
        ) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
    else:
        raise ValueError(f"option_type must be 'CE' or 'PE', got {option_type}")

    return OptionQuote(price=max(price, 0.0), delta=delta)


def realized_volatility(closes: list[float], annualize: bool = True) -> float:
    """
    Annualized realized volatility from a list of closing prices
    (simple close-to-close log returns, sample stddev).
    Used as the volatility input to bs_price when no live IV/VIX is on hand.
    """
    if len(closes) < 2:
        raise ValueError("Need at least 2 closes to compute volatility")

    log_returns = [
        math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))
    ]
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    daily_vol = math.sqrt(variance)

    return daily_vol * math.sqrt(252) if annualize else daily_vol


def years_between(start: datetime, end: datetime) -> float:
    """Trading-time-to-expiry in years, using calendar days / 365.
    (Simplification - doesn't account for weekends/holidays specifically;
    fine for backtest approximation purposes.)"""
    return max((end - start).total_seconds() / (365 * 24 * 3600), 0.0)
