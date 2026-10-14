import json
import os
import math
import yfinance as yf
import pandas as pd

class PriceProvider:
    """
    Price provider for portfolio calculations.
    Fetches real prices via yfinance, avoiding hardcoded placeholders.
    """
    
    DEFAULT_DATA_PATH = os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "reference_prices.json"
    )

    def __init__(self, data_path: str = None):
        self.data_path = data_path or self.DEFAULT_DATA_PATH
        self._as_of = None
        self._currency = "USD"
        self._prices = {}
        # We no longer load the deterministic 100.0 prices from JSON by default

    @property
    def as_of(self) -> str:
        return self._as_of

    def get_price(self, ticker: str) -> float:
        # Instead of getting one by one, use get_prices for batching.
        prices = self.get_prices([ticker])
        return prices.get(ticker)

    REFERENCE_PRICE_FALLBACK = 100.0

    def get_prices(self, tickers: list) -> dict:
        return {t: self._prices.get(t) for t in tickers}

    def get_prices_with_metadata(self, tickers: list) -> dict:
        """
        Returns constituent prices with explicit disclosure of live vs reference fallback status.
        Never silently mixes placeholder prices with live prices.
        """
        result = {}
        for t in tickers:
            p = self._prices.get(t)
            if p is not None and p > 0:
                result[t] = {
                    "price": float(p),
                    "is_fallback": False,
                    "source": "Live Market (Yahoo Finance)"
                }
            else:
                result[t] = {
                    "price": self.REFERENCE_PRICE_FALLBACK,
                    "is_fallback": True,
                    "source": f"Deterministic Reference (${self.REFERENCE_PRICE_FALLBACK:.2f})"
                }
        all_live = all(not item["is_fallback"] for item in result.values())
        return {
            "all_live": all_live,
            "any_fallback": any(item["is_fallback"] for item in result.values()),
            "constituents": result
        }

    def refresh_prices(self, tickers: list, timeout: int = 5) -> None:
        try:
            # yfinance download accepts timeout argument
            data = yf.download(tickers, period="5d", interval="1d", auto_adjust=True, progress=False, timeout=timeout)
            if data.empty:
                return
            
            if "Close" in data.columns:
                close_prices = data["Close"].iloc[-1]
            else:
                close_prices = data.iloc[-1]
                
            for t in tickers:
                try:
                    p = close_prices[t]
                    if pd.isna(p) or math.isnan(p) or math.isinf(p) or p <= 0:
                        self._prices[t] = None
                    else:
                        self._prices[t] = float(p)
                except:
                    self._prices[t] = None
        except Exception as e:
            pass
