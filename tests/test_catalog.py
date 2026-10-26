import os
import json
import pytest
from src.engine.schemas import Instrument
from src.engine.catalog import InstrumentCatalog, get_catalog

def test_load_all_20_instruments_from_default_catalog():
    """Verify loading the real universe_catalog.json yields exactly 20 instruments."""
    catalog = InstrumentCatalog()
    assert len(catalog) == 20
    all_instruments = catalog.get_all()
    assert len(all_instruments) == 20

    us_instruments = catalog.get_by_market("US")
    in_instruments = catalog.get_by_market("IN")
    assert len(us_instruments) == 10
    assert len(in_instruments) == 10

def test_lookup_by_internal_id():
    """Verify lookup by internal ID returns the exact instrument."""
    catalog = InstrumentCatalog()
    aapl = catalog.get_by_id("US_AAPL")
    assert aapl is not None
    assert aapl.display_ticker == "AAPL"
    assert aapl.currency == "USD"
    assert aapl.market == "US"
    assert aapl.exchange == "NASDAQ"

    reliance = catalog.get_by_id("IN_RELIANCE")
    assert reliance is not None
    assert reliance.display_ticker == "RELIANCE"
    assert reliance.provider_symbol == "RELIANCE.NS"
    assert reliance.currency == "INR"
    assert reliance.market == "IN"
    assert reliance.exchange == "NSE"

    assert catalog.get_by_id("NONEXISTENT_ID") is None

def test_lookup_by_provider_symbol():
    """Verify lookup by provider symbol."""
    catalog = InstrumentCatalog()
    tcs = catalog.get_by_provider_symbol("TCS.NS")
    assert tcs is not None
    assert tcs.id == "IN_TCS"

    nvda = catalog.get_by_provider_symbol("NVDA")
    assert nvda is not None
    assert nvda.id == "US_NVDA"

    assert catalog.get_by_provider_symbol("UNKNOWN.SYMBOL") is None

def test_lookup_by_display_ticker_unambiguous():
    """Verify lookup by display ticker is case-insensitive and unambiguous."""
    catalog = InstrumentCatalog()
    msft = catalog.get_by_ticker("msft")
    assert msft is not None
    assert msft.id == "US_MSFT"

    infy = catalog.get_by_ticker("INFY")
    assert infy is not None
    assert infy.id == "IN_INFY"

    assert catalog.get_by_ticker("UNKNOWN_TICKER") is None

def test_lookup_by_display_ticker_rejects_ambiguity():
    """If two instruments share a ticker (e.g. INFY on NYSE and NSE), lookup must reject ambiguity."""
    sample_data = [
        {
            "id": "US_INFY",
            "name": "Infosys ADR",
            "display_ticker": "INFY",
            "market": "US",
            "exchange": "NYSE",
            "provider_symbol": "INFY",
            "currency": "USD",
            "sector": "Information Technology"
        },
        {
            "id": "IN_INFY",
            "name": "Infosys Ltd.",
            "display_ticker": "INFY",
            "market": "IN",
            "exchange": "NSE",
            "provider_symbol": "INFY.NS",
            "currency": "INR",
            "sector": "Information Technology"
        }
    ]
    catalog = InstrumentCatalog.from_data(sample_data)
    with pytest.raises(ValueError, match="Ambiguous display ticker 'INFY'"):
        catalog.get_by_ticker("INFY")

def test_reject_duplicate_ids():
    """Catalog must reject data with duplicate instrument IDs."""
    sample_data = [
        {
            "id": "US_AAPL",
            "name": "Apple 1",
            "display_ticker": "AAPL",
            "market": "US",
            "exchange": "NASDAQ",
            "provider_symbol": "AAPL",
            "currency": "USD",
            "sector": "Technology"
        },
        {
            "id": "US_AAPL",
            "name": "Apple 2",
            "display_ticker": "AAPL",
            "market": "US",
            "exchange": "NASDAQ",
            "provider_symbol": "AAPL2",
            "currency": "USD",
            "sector": "Technology"
        }
    ]
    with pytest.raises(ValueError, match="Duplicate instrument ID detected: 'US_AAPL'"):
        InstrumentCatalog.from_data(sample_data)

def test_reject_duplicate_provider_symbols():
    """Catalog must reject data with duplicate provider symbols."""
    sample_data = [
        {
            "id": "US_AAPL",
            "name": "Apple",
            "display_ticker": "AAPL",
            "market": "US",
            "exchange": "NASDAQ",
            "provider_symbol": "AAPL",
            "currency": "USD",
            "sector": "Technology"
        },
        {
            "id": "US_AAPL_2",
            "name": "Apple Duplicate",
            "display_ticker": "AAPL2",
            "market": "US",
            "exchange": "NASDAQ",
            "provider_symbol": "AAPL",
            "currency": "USD",
            "sector": "Technology"
        }
    ]
    with pytest.raises(ValueError, match="Duplicate provider symbol detected: 'AAPL'"):
        InstrumentCatalog.from_data(sample_data)

def test_reject_missing_required_fields():
    """Catalog must reject instrument entries missing required fields."""
    sample_data = [
        {
            "id": "US_AAPL",
            "name": "Apple",
            # missing display_ticker
            "market": "US",
            "exchange": "NASDAQ",
            "provider_symbol": "AAPL",
            "currency": "USD",
            "sector": "Technology"
        }
    ]
    with pytest.raises(ValueError, match="Missing required field 'display_ticker'"):
        InstrumentCatalog.from_data(sample_data)

def test_reject_invalid_metadata():
    """Instrument model must reject invalid market, exchange, and currency."""
    # Invalid market
    with pytest.raises(ValueError, match="Invalid market 'UK'"):
        Instrument(
            id="UK_VOD", name="Vodafone", display_ticker="VOD",
            market="UK", exchange="LSE", provider_symbol="VOD.L",
            currency="GBP", sector="Telecom"
        )

    # Invalid exchange for US market
    with pytest.raises(ValueError, match="Invalid exchange 'NSE' for market 'US'"):
        Instrument(
            id="US_TEST", name="Test", display_ticker="TEST",
            market="US", exchange="NSE", provider_symbol="TEST",
            currency="USD", sector="Tech"
        )

    # Invalid currency
    with pytest.raises(ValueError, match="Invalid currency 'EUR'"):
        Instrument(
            id="US_TEST", name="Test", display_ticker="TEST",
            market="US", exchange="NASDAQ", provider_symbol="TEST",
            currency="EUR", sector="Tech"
        )

def test_default_selection_preserves_10_us_stocks():
    """Verify default selection contains the exact 10 original US stocks."""
    catalog = InstrumentCatalog()
    default_selection = catalog.get_default_selection()
    assert len(default_selection) == 10

    default_tickers = [inst.display_ticker for inst in default_selection]
    expected_tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    assert default_tickers == expected_tickers

    for inst in default_selection:
        assert inst.market == "US"
        assert inst.currency == "USD"

def test_validate_selection_valid_10_stocks():
    """Selection of exactly 10 distinct known instruments succeeds (mixed or single market)."""
    catalog = InstrumentCatalog()

    # All 10 US
    us_selection = catalog.validate_selection(catalog.get_default_selection_ids())
    assert len(us_selection) == 10

    # 5 US + 5 Indian
    mixed_ids = [
        "US_AAPL", "US_MSFT", "US_NVDA", "US_AMZN", "US_GOOGL",
        "IN_RELIANCE", "IN_TCS", "IN_HDFCBANK", "IN_INFY", "IN_ICICIBANK"
    ]
    mixed_selection = catalog.validate_selection(mixed_ids)
    assert len(mixed_selection) == 10
    assert {inst.id for inst in mixed_selection} == set(mixed_ids)

    # All 10 Indian
    in_ids = [
        "IN_RELIANCE", "IN_TCS", "IN_HDFCBANK", "IN_INFY", "IN_ICICIBANK",
        "IN_HINDUNILVR", "IN_ITC", "IN_BHARTIARTL", "IN_LT", "IN_SBIN"
    ]
    in_selection = catalog.validate_selection(in_ids)
    assert len(in_selection) == 10

def test_validate_selection_rejects_non_10_stocks():
    """Selection with 9 or 11 stocks must be rejected."""
    catalog = InstrumentCatalog()

    nine_ids = [
        "US_AAPL", "US_MSFT", "US_NVDA", "US_AMZN", "US_GOOGL",
        "US_META", "US_TSLA", "US_JPM", "US_JNJ"
    ]
    with pytest.raises(ValueError, match="must contain exactly 10 instruments, got 9"):
        catalog.validate_selection(nine_ids)

    eleven_ids = nine_ids + ["US_XOM", "IN_RELIANCE"]
    with pytest.raises(ValueError, match="must contain exactly 10 instruments, got 11"):
        catalog.validate_selection(eleven_ids)

def test_validate_selection_rejects_duplicates():
    """Selection with duplicate items must be rejected."""
    catalog = InstrumentCatalog()
    duplicate_ids = [
        "US_AAPL", "US_AAPL", "US_NVDA", "US_AMZN", "US_GOOGL",
        "US_META", "US_TSLA", "US_JPM", "US_JNJ", "US_XOM"
    ]
    with pytest.raises(ValueError, match="Selection contains duplicate instrument IDs"):
        catalog.validate_selection(duplicate_ids)

def test_validate_selection_rejects_unknown_ids():
    """Selection containing unknown instrument IDs must be rejected."""
    catalog = InstrumentCatalog()
    invalid_ids = [
        "US_AAPL", "US_MSFT", "US_NVDA", "US_AMZN", "US_GOOGL",
        "US_META", "US_TSLA", "US_JPM", "US_JNJ", "UNKNOWN_XYZ"
    ]
    with pytest.raises(ValueError, match="Selection contains unknown instrument ID"):
        catalog.validate_selection(invalid_ids)

def test_catalog_can_be_imported_and_loaded_offline(monkeypatch):
    """Ensure catalog works purely offline with zero network connectivity."""
    # Simulate completely disabled socket connection
    import socket
    def disabled_socket(*args, **kwargs):
        raise OSError("Network is disabled")
    monkeypatch.setattr(socket, "socket", disabled_socket)

    catalog = get_catalog(reload=True)
    assert len(catalog) == 20
    assert catalog.get_by_id("IN_RELIANCE").provider_symbol == "RELIANCE.NS"
