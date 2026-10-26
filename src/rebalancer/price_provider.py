import json
import os
import math
from datetime import datetime, timezone
import yfinance as yf
import pandas as pd
from typing import List, Dict, Optional, Any

from src.engine.catalog import get_catalog

class PriceProvider:
    """
    Price provider for portfolio calculations.
    Integrates with InstrumentCatalog to resolve both US and Indian (NSE) provider symbols.
    Fetches real prices via yfinance and provides explicit fallback status and metadata.
    """

    DEFAULT_DATA_PATH = os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "reference_prices.json"
    )
    REFERENCE_PRICE_FALLBACK = 100.0

    DEFAULT_CACHE_TTL_SECONDS = 900  # 15 minutes

    def __init__(self, data_path: str = None, catalog = None, cache_ttl: int = 900):
        self.data_path = data_path or self.DEFAULT_DATA_PATH
        self._catalog = catalog
        self._cache_ttl = cache_ttl
        self._as_of = None
        self._currency = "USD"
        self._prices: Dict[str, Optional[float]] = {}
        self._price_cache: Dict[str, Dict[str, Any]] = {}
        self._reference_prices = self._load_reference_prices()

    @property
    def catalog(self):
        if self._catalog is None:
            self._catalog = get_catalog()
        return self._catalog

    @property
    def as_of(self) -> Optional[str]:
        return self._as_of

    def _load_reference_prices(self) -> Dict[str, float]:
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._reference_as_of = data.get("as_of", "2026-01-01T00:00:00Z")
                    return data.get("prices", {})
            except Exception:
                pass
        self._reference_as_of = "2026-01-01T00:00:00Z"
        return {}

    def _resolve_instrument(self, identifier: str):
        """Resolves an identifier (ID, display ticker, or provider symbol) via catalog."""
        cat = self.catalog
        if cat is None or not identifier:
            return None
        return (
            cat.get_by_id(identifier)
            or cat.get_by_ticker(identifier)
            or cat.get_by_provider_symbol(identifier)
        )

    def _resolve_provider_symbol(self, identifier: str) -> str:
        """Maps an identifier to its market data provider symbol."""
        inst = self._resolve_instrument(identifier)
        if inst is not None:
            return inst.provider_symbol
        return identifier

    def get_price(self, ticker: str) -> Optional[float]:
        if ticker in self._prices:
            return self._prices.get(ticker)
        # Try resolving via instrument
        inst = self._resolve_instrument(ticker)
        if inst is not None:
            if inst.provider_symbol in self._prices:
                return self._prices.get(inst.provider_symbol)
            if inst.id in self._prices:
                return self._prices.get(inst.id)
            if inst.display_ticker in self._prices:
                return self._prices.get(inst.display_ticker)
        return None

    def get_prices(self, tickers: list) -> dict:
        return {t: self.get_price(t) for t in tickers}

    def get_live_price(self, ticker: str) -> Optional[float]:
        """
        Strictly returns verified live market price for ticker, or None.
        Never returns a deterministic fallback or placeholder price.
        """
        p = self.get_prices([ticker]).get(ticker)
        if p is not None and not math.isnan(p) and not math.isinf(p) and p > 0:
            return float(p)
        return None

    def get_live_prices(self, tickers: list) -> Dict[str, Optional[float]]:
        """
        Returns a mapping of ticker -> live market price.
        Any constituent lacking verified live data maps to None.
        """
        return {t: self.get_live_price(t) for t in tickers}

    def require_live_prices(self, tickers: list) -> Dict[str, float]:
        """
        Returns verified live market quotes for all requested tickers.
        Raises RuntimeError if any constituent lacks a verified live price,
        preventing operations from silently consuming deterministic reference fallbacks.
        """
        live_prices = self.get_live_prices(tickers)
        missing = [t for t, p in live_prices.items() if p is None]
        if missing:
            raise RuntimeError(
                f"Verified live market quotes unavailable for: {missing}. "
                "Operation requires live market data and refuses to silently proceed with deterministic fallback prices."
            )
        return {t: float(p) for t, p in live_prices.items()}

    def get_valuation_price(self, ticker: str) -> Dict[str, Any]:
        """
        Returns the best available valuation quote for portfolio metrics:
        1. Live verified market price (if refreshed & valid)
        2. Validated cached market price (if previously fetched within session)
        3. Deterministic reference fallback price from reference_prices.json
        """
        inst = self._resolve_instrument(ticker)
        currency = inst.currency if inst else "USD"
        currency_sym = "$" if currency == "USD" else "₹"
        live_p = self.get_live_price(ticker)

        if live_p is not None and live_p > 0:
            exchange_label = f" ({inst.exchange})" if inst and inst.exchange else ""
            return {
                "price": float(live_p),
                "currency": currency,
                "is_fallback": False,
                "is_stale": False,
                "is_live": True,
                "execution_eligible": True,
                "source": f"Live Market (Yahoo Finance{exchange_label})",
                "as_of": self._as_of or datetime.now(timezone.utc).isoformat()
            }

        # Check in-memory cache
        cached = (
            self._price_cache.get(ticker)
            or (self._price_cache.get(inst.id) if inst else None)
            or (self._price_cache.get(inst.display_ticker) if inst else None)
            or (self._price_cache.get(inst.provider_symbol) if inst else None)
        )
        if cached and cached.get("price") is not None and cached["price"] > 0:
            as_of_str = cached.get("as_of", "")
            try:
                as_of_dt = datetime.fromisoformat(as_of_str.replace("Z", "+00:00"))
                age_secs = (datetime.now(timezone.utc) - as_of_dt).total_seconds()
            except Exception:
                age_secs = 999999
            is_stale = age_secs > self._cache_ttl
            return {
                "price": float(cached["price"]),
                "currency": currency,
                "is_fallback": False,
                "is_stale": is_stale,
                "is_live": not is_stale,
                "execution_eligible": not is_stale,
                "source": f"Cached Market Quote ({cached.get('source', 'Yahoo Finance')})",
                "as_of": as_of_str
            }

        # Deterministic reference fallback
        default_ref = 100.0 if currency == "USD" else 1000.0
        ref_price = (
            self._reference_prices.get(ticker)
            or (self._reference_prices.get(inst.id) if inst else None)
            or (self._reference_prices.get(inst.display_ticker) if inst else None)
            or (self._reference_prices.get(inst.provider_symbol) if inst else None)
            or default_ref
        )
        return {
            "price": float(ref_price),
            "currency": currency,
            "is_fallback": True,
            "is_stale": False,
            "is_live": False,
            "execution_eligible": False,
            "source": f"Deterministic Reference ({currency_sym}{float(ref_price):.2f})",
            "as_of": getattr(self, "_reference_as_of", "2026-01-01T00:00:00Z")
        }

    def get_valuation_prices(self, tickers: list) -> Dict[str, float]:
        """Returns mapping of ticker -> valuation price (live, cached, or reference fallback)."""
        return {t: float(self.get_valuation_price(t)["price"]) for t in tickers}

    def get_prices_with_metadata(self, tickers: list) -> dict:
        """
        Returns constituent prices with explicit disclosure of live vs reference fallback status,
        source exchange, currency, and retrieval timestamp.
        """
        result = {}
        for t in tickers:
            result[t] = self.get_valuation_price(t)

        all_live = all(item["is_live"] and not item["is_fallback"] for item in result.values())
        any_fallback = any(item["is_fallback"] for item in result.values())
        any_stale = any(item.get("is_stale", False) for item in result.values())
        return {
            "all_live": all_live,
            "any_fallback": any_fallback,
            "any_stale": any_stale,
            "constituents": result
        }

    def refresh_prices(self, tickers: list, timeout: int = 5, max_retries: int = 2, enable_secondary: bool = False) -> None:
        if not tickers:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        self._as_of = now_iso

        # Build mapping from requested ticker to provider symbol
        ticker_map = {t: self._resolve_provider_symbol(t) for t in tickers}
        unique_provider_symbols = list(set(ticker_map.values()))

        data = None
        # Bounded retry loop for bulk download
        for attempt in range(max_retries):
            try:
                data = yf.download(
                    unique_provider_symbols,
                    period="5d",
                    interval="1d",
                    auto_adjust=True,
                    progress=False,
                    timeout=timeout
                )
                if data is not None and not data.empty:
                    break
            except Exception:
                data = None

        close_data = None
        if data is not None and not data.empty:
            if "Close" in data.columns:
                close_data = data["Close"]
            else:
                close_data = data

            if isinstance(close_data, (pd.DataFrame, pd.Series)):
                close_data = close_data.ffill()

        missing_tickers = []
        for t in tickers:
            prov_sym = ticker_map[t]
            raw_p = None
            if close_data is not None:
                try:
                    if isinstance(close_data, pd.DataFrame):
                        col = prov_sym if prov_sym in close_data.columns else (t if t in close_data.columns else None)
                        if col is not None:
                            series = close_data[col].dropna()
                            if not series.empty:
                                raw_p = series.iloc[-1]
                    elif isinstance(close_data, pd.Series):
                        if prov_sym in close_data.index:
                            raw_p = close_data[prov_sym]
                        elif t in close_data.index:
                            raw_p = close_data[t]
                        elif len(unique_provider_symbols) == 1:
                            raw_p = close_data.iloc[-1]
                    elif isinstance(close_data, dict):
                        raw_p = close_data.get(prov_sym, close_data.get(t))
                except Exception:
                    raw_p = None

            val = None
            if raw_p is not None and not pd.isna(raw_p):
                try:
                    numeric_val = float(raw_p.item() if hasattr(raw_p, "item") else raw_p)
                    if not math.isnan(numeric_val) and not math.isinf(numeric_val) and numeric_val > 0:
                        val = numeric_val
                except Exception:
                    val = None

            if val is not None:
                self._prices[t] = val
                inst = self._resolve_instrument(t)
                exchange_label = f" ({inst.exchange})" if inst and inst.exchange else ""
                cache_entry = {
                    "price": val,
                    "as_of": now_iso,
                    "source": f"Live Market (Yahoo Finance{exchange_label})",
                    "currency": inst.currency if inst else "USD",
                    "is_live": True
                }
                self._price_cache[t] = cache_entry
                if prov_sym != t:
                    self._prices[prov_sym] = val
                    self._price_cache[prov_sym] = cache_entry
                if inst is not None:
                    self._prices[inst.id] = val
                    self._prices[inst.display_ticker] = val
                    self._price_cache[inst.id] = cache_entry
                    self._price_cache[inst.display_ticker] = cache_entry
            else:
                missing_tickers.append(t)

        # Secondary fallback: individual Ticker fast_info for tickers missing from bulk download
        if enable_secondary:
            for t in missing_tickers:
                prov_sym = ticker_map[t]
                val = None
                try:
                    t_obj = yf.Ticker(prov_sym)
                    if hasattr(t_obj, "fast_info") and t_obj.fast_info:
                        raw_p = t_obj.fast_info.get("lastPrice") or t_obj.fast_info.get("last_price")
                        if raw_p is not None and not pd.isna(raw_p):
                            num_p = float(raw_p)
                            if not math.isnan(num_p) and not math.isinf(num_p) and num_p > 0:
                                val = num_p
                except Exception:
                    val = None

                if val is not None:
                    self._prices[t] = val
                    inst = self._resolve_instrument(t)
                    exchange_label = f" ({inst.exchange})" if inst and inst.exchange else ""
                    cache_entry = {
                        "price": val,
                        "as_of": now_iso,
                        "source": f"Live Market (Yahoo Finance FastQuote{exchange_label})",
                        "currency": inst.currency if inst else "USD",
                        "is_live": True
                    }
                    self._price_cache[t] = cache_entry
                    if prov_sym != t:
                        self._prices[prov_sym] = val
                        self._price_cache[prov_sym] = cache_entry
                    if inst is not None:
                        self._prices[inst.id] = val
                        self._prices[inst.display_ticker] = val
                        self._price_cache[inst.id] = cache_entry
                        self._price_cache[inst.display_ticker] = cache_entry
                else:
                    self._prices[t] = None
        else:
            for t in missing_tickers:
                self._prices[t] = None
