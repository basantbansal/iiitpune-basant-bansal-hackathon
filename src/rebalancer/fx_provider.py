import math
import os
from dataclasses import dataclass, asdict
from typing import Optional, Callable, Dict, Any
from datetime import datetime, timezone

@dataclass(frozen=True)
class FXRate:
    """
    Represents an exchange rate between two currencies with provenance tracking.
    Quote Direction Convention:
      The 'rate' field specifies the amount of quote_currency equivalent to 1 unit of base_currency.
      Formula: amount_in_quote = amount_in_base * rate
      Example:
        base_currency = "USD", quote_currency = "INR", rate = 84.00
        means: 1 USD = 84.00 INR.
    """
    base_currency: str
    quote_currency: str
    rate: float
    as_of: str
    source: str
    is_fallback: bool
    observation_time: Optional[str] = None
    is_stale: bool = False

    def __post_init__(self):
        if not self.base_currency or not str(self.base_currency).strip():
            raise ValueError("base_currency must be a non-empty string")
        if not self.quote_currency or not str(self.quote_currency).strip():
            raise ValueError("quote_currency must be a non-empty string")
        if self.rate is None or math.isnan(self.rate) or math.isinf(self.rate) or self.rate <= 0:
            raise ValueError(f"rate must be finite and strictly positive, got {self.rate}")

    @property
    def is_live(self) -> bool:
        """True strictly when rate is live, verified, and not a fallback."""
        return not self.is_fallback and not self.is_stale

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["is_live"] = self.is_live
        return d


class FXRateProvider:
    """
    FX Rate Provider for USD and INR conversions with explicit provenance tracking.
    Quote Direction:
      USD/INR specifies the number of Indian Rupees per 1 US Dollar.
      Default deterministic fallback is 84.00 INR per USD.
    """

    SUPPORTED_CURRENCIES = frozenset({"USD", "INR"})
    DEFAULT_USD_INR_FALLBACK = 84.00
    FALLBACK_OBSERVATION_TIME = "2026-01-01T00:00:00Z"

    def __init__(
        self,
        fallback_usd_inr: float = DEFAULT_USD_INR_FALLBACK,
        fetcher: Optional[Callable[[], Optional[float]]] = None,
        online: bool = True
    ):
        if fallback_usd_inr <= 0 or math.isnan(fallback_usd_inr) or math.isinf(fallback_usd_inr):
            raise ValueError(f"fallback_usd_inr must be positive and finite, got {fallback_usd_inr}")
        self.fallback_usd_inr = float(fallback_usd_inr)
        self._cached_usd_inr: Optional[float] = None
        self._last_as_of: Optional[str] = None
        self._observation_time: Optional[str] = None
        self._last_source: Optional[str] = None
        self._is_fallback: bool = True
        self._is_stale: bool = False
        self._custom_fetcher = fetcher
        self.online = online

    @property
    def is_fallback(self) -> bool:
        return self._is_fallback

    @property
    def is_live(self) -> bool:
        return not self._is_fallback and not self._is_stale

    @property
    def as_of(self) -> Optional[str]:
        return self._last_as_of

    @property
    def observation_time(self) -> Optional[str]:
        return self._observation_time

    @property
    def source(self) -> Optional[str]:
        return self._last_source

    def refresh_rate(self, timeout: int = 5) -> None:
        """
        Refreshes live USD/INR exchange rate.
        Preserves observation timestamp from market quote when available.
        Fails safely to explicit fallback rate on network errors, invalid responses, or when offline.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        # 1. Custom fetcher takes precedence
        if self._custom_fetcher is not None:
            try:
                result = self._custom_fetcher()
                rate_val = None
                obs_val = now_iso
                if isinstance(result, tuple) and len(result) == 2:
                    rate_val, obs_val = result
                elif result is not None:
                    rate_val = result

                if rate_val is not None and not math.isnan(rate_val) and not math.isinf(rate_val) and rate_val > 0:
                    self._cached_usd_inr = float(rate_val)
                    self._last_as_of = now_iso
                    self._observation_time = str(obs_val)
                    self._last_source = "Custom Fetcher"
                    self._is_fallback = False
                    self._is_stale = False
                    return
            except Exception:
                pass

            # If custom fetcher failed, do not fall through to web request
            self._cached_usd_inr = self.fallback_usd_inr
            self._last_as_of = now_iso
            self._observation_time = self.FALLBACK_OBSERVATION_TIME
            self._last_source = f"Deterministic Fallback (1 USD = {self.fallback_usd_inr:.2f} INR)"
            self._is_fallback = True
            self._is_stale = True
            return

        # 2. Query Yahoo Finance if online
        if self.online:
            try:
                import yfinance as yf
                data = yf.download("USDINR=X", period="1d", interval="1d", progress=False, timeout=timeout)
                if data is not None and not data.empty:
                    if "Close" in data.columns:
                        c = data["Close"].iloc[-1]
                    else:
                        c = data.iloc[-1]
                    val = float(c.item() if hasattr(c, "item") else c)
                    if not math.isnan(val) and not math.isinf(val) and val > 0:
                        obs_date = data.index[-1]
                        obs_str = obs_date.isoformat() if hasattr(obs_date, "isoformat") else str(obs_date)
                        self._cached_usd_inr = val
                        self._last_as_of = now_iso
                        self._observation_time = obs_str
                        self._last_source = "Live Market (Yahoo Finance USDINR=X)"
                        self._is_fallback = False
                        self._is_stale = False
                        return
            except Exception:
                pass

        # 3. Fallback on error or offline
        self._cached_usd_inr = self.fallback_usd_inr
        self._last_as_of = now_iso
        self._observation_time = self.FALLBACK_OBSERVATION_TIME
        self._last_source = f"Deterministic Fallback (1 USD = {self.fallback_usd_inr:.2f} INR)"
        self._is_fallback = True
        self._is_stale = True

    def get_rate(self, base_currency: str, quote_currency: str) -> FXRate:
        """
        Retrieves the FXRate object for base_currency -> quote_currency.
        Quote direction: number of quote_currency per 1 unit of base_currency.
        """
        base = (base_currency or "").strip().upper()
        quote = (quote_currency or "").strip().upper()

        if base not in self.SUPPORTED_CURRENCIES:
            raise ValueError(f"Unsupported base currency '{base}'. Supported: {sorted(self.SUPPORTED_CURRENCIES)}")
        if quote not in self.SUPPORTED_CURRENCIES:
            raise ValueError(f"Unsupported quote currency '{quote}'. Supported: {sorted(self.SUPPORTED_CURRENCIES)}")

        now_iso = datetime.now(timezone.utc).isoformat()

        if base == quote:
            return FXRate(
                base_currency=base,
                quote_currency=quote,
                rate=1.0,
                as_of=self._last_as_of or now_iso,
                source="Identity",
                is_fallback=False,
                observation_time=self._observation_time or now_iso,
                is_stale=False
            )

        usd_inr = self._cached_usd_inr or self.fallback_usd_inr
        source = self._last_source or f"Deterministic Fallback (1 USD = {self.fallback_usd_inr:.2f} INR)"
        is_fallback = self._is_fallback
        obs_time = self._observation_time or self.FALLBACK_OBSERVATION_TIME
        is_stale = self._is_stale
        effective_as_of = obs_time if is_fallback else (self._last_as_of or now_iso)

        if base == "USD" and quote == "INR":
            return FXRate(
                base_currency="USD",
                quote_currency="INR",
                rate=round(usd_inr, 4),
                as_of=effective_as_of,
                source=source,
                is_fallback=is_fallback,
                observation_time=obs_time,
                is_stale=is_stale
            )
        elif base == "INR" and quote == "USD":
            return FXRate(
                base_currency="INR",
                quote_currency="USD",
                rate=round(1.0 / usd_inr, 8),
                as_of=effective_as_of,
                source=source,
                is_fallback=is_fallback,
                observation_time=obs_time,
                is_stale=is_stale
            )

    def require_live_rate(self, base_currency: str, quote_currency: str) -> FXRate:
        """
        Returns the FXRate strictly if it is live and verified.
        Raises RuntimeError if a fallback or stale rate is in use.
        """
        fx = self.get_rate(base_currency, quote_currency)
        base = (base_currency or "").strip().upper()
        quote = (quote_currency or "").strip().upper()
        if base != quote and fx.is_fallback:
            raise RuntimeError(
                f"Live exchange rate unavailable for {base}/{quote}. "
                f"Active rate is a fallback ({fx.source}). Live-rate-dependent operations cannot proceed."
            )
        return fx

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        """
        Converts amount from from_currency to to_currency using get_rate().
        """
        if amount is None or math.isnan(amount) or math.isinf(amount) or amount < 0:
            raise ValueError(f"amount must be a non-negative finite number, got {amount}")
        if amount == 0.0:
            return 0.0

        fx = self.get_rate(from_currency, to_currency)
        return round(amount * fx.rate, 4)

    def convert_with_metadata(self, amount: float, from_currency: str, to_currency: str) -> Dict[str, Any]:
        """
        Converts amount and returns explicit provenance metadata including fallback status,
        source, rate, as_of timestamp, and observation time.
        """
        if amount is None or math.isnan(amount) or math.isinf(amount) or amount < 0:
            raise ValueError(f"amount must be a non-negative finite number, got {amount}")

        from_c = (from_currency or "").strip().upper()
        to_c = (to_currency or "").strip().upper()

        fx = self.get_rate(from_c, to_c)
        converted = round(amount * fx.rate, 4) if amount > 0 else 0.0

        return {
            "original_amount": float(amount),
            "converted_amount": float(converted),
            "from_currency": from_c,
            "to_currency": to_c,
            "rate": fx.rate,
            "is_fallback": fx.is_fallback,
            "is_live": fx.is_live,
            "is_stale": fx.is_stale,
            "source": fx.source,
            "as_of": fx.as_of,
            "observation_time": fx.observation_time
        }


_GLOBAL_FX_PROVIDER: Optional[FXRateProvider] = None

def get_fx_provider(reload: bool = False) -> FXRateProvider:
    """Returns singleton instance of FXRateProvider."""
    global _GLOBAL_FX_PROVIDER
    if _GLOBAL_FX_PROVIDER is None or reload:
        _GLOBAL_FX_PROVIDER = FXRateProvider()
    return _GLOBAL_FX_PROVIDER
