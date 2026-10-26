import pytest
import math
from unittest.mock import patch
from src.rebalancer.fx_provider import FXRate, FXRateProvider, get_fx_provider

def test_fx_rate_dataclass_validations():
    """Verify FXRate fields and validation rules."""
    rate = FXRate(
        base_currency="USD",
        quote_currency="INR",
        rate=84.00,
        as_of="2026-10-14T00:00:00Z",
        source="Deterministic Fallback",
        is_fallback=True
    )
    assert rate.base_currency == "USD"
    assert rate.quote_currency == "INR"
    assert rate.rate == 84.00
    assert rate.is_fallback is True

    # Reject non-positive or NaN rates
    with pytest.raises(ValueError, match="rate must be finite and strictly positive"):
        FXRate(base_currency="USD", quote_currency="INR", rate=0.0, as_of="now", source="src", is_fallback=True)

    with pytest.raises(ValueError, match="rate must be finite and strictly positive"):
        FXRate(base_currency="USD", quote_currency="INR", rate=-84.0, as_of="now", source="src", is_fallback=True)

    with pytest.raises(ValueError, match="rate must be finite and strictly positive"):
        FXRate(base_currency="USD", quote_currency="INR", rate=float("nan"), as_of="now", source="src", is_fallback=True)

def test_fx_quote_direction_and_conversion():
    """
    Verify explicit quote direction:
    USD/INR represents number of INR per 1 USD (e.g. 84.0 means 1 USD = 84.0 INR).
    """
    provider = FXRateProvider(fallback_usd_inr=84.00)

    # 1. USD -> INR
    fx_usd_inr = provider.get_rate("USD", "INR")
    assert fx_usd_inr.rate == 84.00
    assert fx_usd_inr.base_currency == "USD"
    assert fx_usd_inr.quote_currency == "INR"
    assert fx_usd_inr.is_fallback is True

    converted_inr = provider.convert(100.0, "USD", "INR")
    assert converted_inr == 8400.00

    # 2. INR -> USD (reciprocal rate)
    fx_inr_usd = provider.get_rate("INR", "USD")
    assert fx_inr_usd.rate == pytest.approx(1.0 / 84.00, rel=1e-4)
    assert fx_inr_usd.base_currency == "INR"
    assert fx_inr_usd.quote_currency == "USD"

    converted_usd = provider.convert(8400.0, "INR", "USD")
    assert converted_usd == pytest.approx(100.0, abs=0.05)

    # 3. Identity conversions
    assert provider.get_rate("USD", "USD").rate == 1.0
    assert provider.get_rate("INR", "INR").rate == 1.0
    assert provider.convert(500.0, "USD", "USD") == 500.0
    assert provider.convert(500.0, "INR", "INR") == 500.0
    assert provider.convert(0.0, "USD", "INR") == 0.0

def test_fx_rejects_unsupported_currencies():
    """Verify provider rejects unsupported currencies."""
    provider = FXRateProvider()
    with pytest.raises(ValueError, match="Unsupported base currency 'EUR'"):
        provider.get_rate("EUR", "INR")

    with pytest.raises(ValueError, match="Unsupported quote currency 'GBP'"):
        provider.get_rate("USD", "GBP")

def test_fx_rejects_invalid_conversion_amounts():
    """Verify convert rejects negative or non-finite numbers."""
    provider = FXRateProvider()
    with pytest.raises(ValueError, match="amount must be a non-negative finite number"):
        provider.convert(-50.0, "USD", "INR")

    with pytest.raises(ValueError, match="amount must be a non-negative finite number"):
        provider.convert(float("nan"), "USD", "INR")

def test_fx_custom_fetcher_success():
    """Verify custom fetcher can inject live rates cleanly."""
    mock_fetcher = lambda: 85.50
    provider = FXRateProvider(fallback_usd_inr=84.00, fetcher=mock_fetcher)
    provider.refresh_rate()

    rate = provider.get_rate("USD", "INR")
    assert rate.rate == 85.50
    assert rate.is_fallback is False
    assert rate.source == "Custom Fetcher"
    assert provider.convert(10.0, "USD", "INR") == 855.0

def test_fx_custom_fetcher_failure_falls_back():
    """Verify invalid rates or exceptions from fetcher trigger graceful fallback without web calls."""
    # Fetcher raising exception
    def failing_fetcher():
        raise ConnectionError("Network unreachable")

    provider = FXRateProvider(fallback_usd_inr=84.00, fetcher=failing_fetcher)
    provider.refresh_rate()
    rate = provider.get_rate("USD", "INR")
    assert rate.rate == 84.00
    assert rate.is_fallback is True

    # Fetcher returning negative rate
    provider_neg = FXRateProvider(fallback_usd_inr=84.00, fetcher=lambda: -10.0)
    provider_neg.refresh_rate()
    assert provider_neg.get_rate("USD", "INR").rate == 84.00
    assert provider_neg.get_rate("USD", "INR").is_fallback is True

def test_fx_provider_offline():
    """Verify FXRateProvider works completely offline when online=False."""
    provider = FXRateProvider(online=False)
    provider.refresh_rate()
    assert provider.get_rate("USD", "INR").rate == 84.00
    assert provider.is_fallback is True
    assert provider.convert(200.0, "USD", "INR") == 16800.0

def test_require_live_rate_safety():
    """Verify require_live_rate raises RuntimeError on fallback rates and succeeds on live rates."""
    # 1. Fallback rate should raise RuntimeError
    provider_fallback = FXRateProvider(online=False)
    provider_fallback.refresh_rate()
    assert provider_fallback.is_fallback is True

    with pytest.raises(RuntimeError, match="Live exchange rate unavailable for USD/INR"):
        provider_fallback.require_live_rate("USD", "INR")

    with pytest.raises(RuntimeError, match="Live exchange rate unavailable for INR/USD"):
        provider_fallback.require_live_rate("INR", "USD")

    # Identity rate is always live
    id_rate = provider_fallback.require_live_rate("USD", "USD")
    assert id_rate.rate == 1.0
    assert id_rate.is_live is True

    # 2. Live rate should succeed
    provider_live = FXRateProvider(fetcher=lambda: (86.25, "2026-10-14T10:00:00Z"))
    provider_live.refresh_rate()
    assert provider_live.is_fallback is False
    assert provider_live.is_live is True

    live_rate = provider_live.require_live_rate("USD", "INR")
    assert live_rate.rate == 86.25
    assert live_rate.is_fallback is False
    assert live_rate.is_live is True
    assert live_rate.observation_time == "2026-10-14T10:00:00Z"

def test_convert_with_metadata_provenance():
    """Verify convert_with_metadata returns full provenance metadata including fallback, stale, and observation time."""
    # 1. Live conversion
    provider_live = FXRateProvider(fetcher=lambda: (85.00, "2026-10-14T12:00:00Z"))
    provider_live.refresh_rate()

    meta_live = provider_live.convert_with_metadata(100.0, "USD", "INR")
    assert meta_live["original_amount"] == 100.0
    assert meta_live["converted_amount"] == 8500.0
    assert meta_live["from_currency"] == "USD"
    assert meta_live["to_currency"] == "INR"
    assert meta_live["rate"] == 85.00
    assert meta_live["is_fallback"] is False
    assert meta_live["is_live"] is True
    assert meta_live["is_stale"] is False
    assert meta_live["observation_time"] == "2026-10-14T12:00:00Z"

    # 2. Fallback conversion
    provider_fallback = FXRateProvider(fallback_usd_inr=84.00, online=False)
    provider_fallback.refresh_rate()

    meta_fallback = provider_fallback.convert_with_metadata(100.0, "USD", "INR")
    assert meta_fallback["original_amount"] == 100.0
    assert meta_fallback["converted_amount"] == 8400.0
    assert meta_fallback["rate"] == 84.00
    assert meta_fallback["is_fallback"] is True
    assert meta_fallback["is_live"] is False
    assert meta_fallback["is_stale"] is True
    assert meta_fallback["observation_time"] == "2026-01-01T00:00:00Z"
    assert "Deterministic Fallback" in meta_fallback["source"]

    # 3. Zero amount conversion with metadata
    meta_zero = provider_fallback.convert_with_metadata(0.0, "USD", "INR")
    assert meta_zero["original_amount"] == 0.0
    assert meta_zero["converted_amount"] == 0.0

def test_fx_rate_to_dict_and_provenance_fields():
    """Verify FXRate to_dict method includes is_live, observation_time, and is_stale."""
    rate = FXRate(
        base_currency="USD",
        quote_currency="INR",
        rate=84.0,
        as_of="2026-10-14T00:00:00Z",
        source="Deterministic Fallback",
        is_fallback=True,
        observation_time="2026-01-01T00:00:00Z",
        is_stale=True
    )
    d = rate.to_dict()
    assert d["base_currency"] == "USD"
    assert d["quote_currency"] == "INR"
    assert d["rate"] == 84.0
    assert d["is_fallback"] is True
    assert d["is_live"] is False
    assert d["is_stale"] is True
    assert d["observation_time"] == "2026-01-01T00:00:00Z"

def test_fx_unavailable_malformed_and_stale_rates_provenance():
    """
    Verify handling of unavailable, malformed, and stale rates:
    - fetcher returning None or non-numeric triggers safe fallback.
    - fetcher returning NaN or inf triggers safe fallback.
    - fallback as_of reflects observation time (2026-01-01T00:00:00Z) rather than claiming current time.
    """
    # 1. Unavailable (fetcher returns None)
    provider_none = FXRateProvider(fetcher=lambda: None)
    provider_none.refresh_rate()
    rate_none = provider_none.get_rate("USD", "INR")
    assert rate_none.is_fallback is True
    assert rate_none.is_stale is True
    assert rate_none.is_live is False
    assert rate_none.as_of == FXRateProvider.FALLBACK_OBSERVATION_TIME
    assert rate_none.observation_time == FXRateProvider.FALLBACK_OBSERVATION_TIME

    # 2. Malformed: NaN
    provider_nan = FXRateProvider(fetcher=lambda: float("nan"))
    provider_nan.refresh_rate()
    rate_nan = provider_nan.get_rate("USD", "INR")
    assert rate_nan.is_fallback is True
    assert rate_nan.is_stale is True
    assert rate_nan.as_of == FXRateProvider.FALLBACK_OBSERVATION_TIME

    # 3. Malformed: Infinity
    provider_inf = FXRateProvider(fetcher=lambda: float("inf"))
    provider_inf.refresh_rate()
    assert provider_inf.get_rate("USD", "INR").is_fallback is True

    # 4. Malformed: non-numeric string tuple
    provider_bad_tuple = FXRateProvider(fetcher=lambda: ("not_a_number", "2026-10-14T00:00:00Z"))
    provider_bad_tuple.refresh_rate()
    assert provider_bad_tuple.get_rate("USD", "INR").is_fallback is True

    # 5. Fallback as_of does not misleadingly imply current time
    meta = provider_none.convert_with_metadata(100.0, "USD", "INR")
    assert meta["as_of"] == FXRateProvider.FALLBACK_OBSERVATION_TIME
    assert meta["observation_time"] == FXRateProvider.FALLBACK_OBSERVATION_TIME
    assert meta["is_stale"] is True


