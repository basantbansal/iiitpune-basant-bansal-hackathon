import os
import json
from typing import List, Dict, Optional, Sequence, Any
from src.engine.schemas import Instrument

class InstrumentCatalog:
    """
    Authoritative single source of truth for the 20-stock curated universe
    (10 US stocks and 10 Indian NSE stocks).
    Provides lookup, metadata validation, and 10-constituent portfolio selection validation.
    """

    DEFAULT_CATALOG_PATH = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "universe_catalog.json")
    )

    DEFAULT_SELECTION_IDS: Sequence[str] = (
        "US_AAPL",
        "US_MSFT",
        "US_NVDA",
        "US_AMZN",
        "US_GOOGL",
        "US_META",
        "US_TSLA",
        "US_JPM",
        "US_JNJ",
        "US_XOM",
    )

    REQUIRED_FIELDS = (
        "id",
        "name",
        "display_ticker",
        "market",
        "exchange",
        "provider_symbol",
        "currency",
        "sector",
    )

    def __init__(self, catalog_path: Optional[str] = None):
        self.catalog_path = catalog_path or self.DEFAULT_CATALOG_PATH
        self._instruments: List[Instrument] = []
        self._by_id: Dict[str, Instrument] = {}
        self._by_provider_symbol: Dict[str, Instrument] = {}
        self._by_ticker: Dict[str, List[Instrument]] = {}
        self._version: str = "1.0"
        self._load_from_path(self.catalog_path)

    @classmethod
    def from_data(cls, items: List[Dict[str, Any]], version: str = "1.0") -> "InstrumentCatalog":
        """Factory method to construct an in-memory catalog from raw dictionaries."""
        instance = cls.__new__(cls)
        instance.catalog_path = None
        instance._instruments = []
        instance._by_id = {}
        instance._by_provider_symbol = {}
        instance._by_ticker = {}
        instance._version = version
        instance._load_raw_items(items)
        return instance

    def _load_from_path(self, path: str):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Catalog file not found at: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            self._version = str(data.get("version", "1.0"))
            raw_items = data.get("instruments")
            if not isinstance(raw_items, list):
                raise ValueError("Catalog JSON root object must contain an 'instruments' array")
        elif isinstance(data, list):
            raw_items = data
        else:
            raise ValueError("Catalog JSON must be an object with 'instruments' key or an array of instruments")

        self._load_raw_items(raw_items)

    def _load_raw_items(self, raw_items: List[Dict[str, Any]]):
        self._instruments = []
        self._by_id = {}
        self._by_provider_symbol = {}
        self._by_ticker = {}

        for idx, item in enumerate(raw_items):
            if not isinstance(item, dict):
                raise ValueError(f"Instrument entry at index {idx} must be a dictionary")

            # Check missing required fields
            for field in self.REQUIRED_FIELDS:
                if field not in item or item[field] is None:
                    raise ValueError(f"Missing required field '{field}' in instrument at index {idx}")

            inst_id = str(item["id"]).strip()
            prov_sym = str(item["provider_symbol"]).strip()

            if inst_id in self._by_id:
                raise ValueError(f"Duplicate instrument ID detected: '{inst_id}'")

            if prov_sym in self._by_provider_symbol:
                raise ValueError(f"Duplicate provider symbol detected: '{prov_sym}'")

            aliases = item.get("aliases", ())
            if not isinstance(aliases, (list, tuple, set)):
                raise ValueError(f"Aliases for '{inst_id}' must be a list, tuple, or set of strings")

            instrument = Instrument(
                id=inst_id,
                name=str(item["name"]).strip(),
                display_ticker=str(item["display_ticker"]).strip(),
                market=str(item["market"]).strip(),
                exchange=str(item["exchange"]).strip(),
                provider_symbol=prov_sym,
                currency=str(item["currency"]).strip(),
                sector=str(item["sector"]).strip(),
                aliases=tuple(str(a).strip() for a in aliases),
            )

            self._instruments.append(instrument)
            self._by_id[instrument.id] = instrument
            self._by_provider_symbol[instrument.provider_symbol] = instrument

            ticker_key = instrument.display_ticker.upper()
            self._by_ticker.setdefault(ticker_key, []).append(instrument)

    @property
    def version(self) -> str:
        return self._version

    def get_by_id(self, instrument_id: str) -> Optional[Instrument]:
        """Lookup instrument by stable internal ID (e.g. 'US_AAPL', 'IN_RELIANCE')."""
        return self._by_id.get(instrument_id)

    def get_by_provider_symbol(self, provider_symbol: str) -> Optional[Instrument]:
        """Lookup instrument by data provider symbol (e.g. 'AAPL', 'RELIANCE.NS')."""
        return self._by_provider_symbol.get(provider_symbol)

    def get_by_ticker(self, ticker: str) -> Optional[Instrument]:
        """
        Unambiguous lookup by display ticker (e.g. 'AAPL', 'RELIANCE').
        Rejects ambiguous tickers matching multiple instruments by raising ValueError.
        Returns None if ticker is unknown.
        """
        if not ticker or not isinstance(ticker, str):
            return None
        matches = self._by_ticker.get(ticker.strip().upper(), [])
        if not matches:
            return None
        if len(matches) > 1:
            matched_ids = [m.id for m in matches]
            raise ValueError(
                f"Ambiguous display ticker '{ticker}': matched multiple instruments {matched_ids}. "
                "Use internal instrument ID or provider symbol to disambiguate."
            )
        return matches[0]

    def get_all(self) -> List[Instrument]:
        """Returns all registered instruments in catalog order."""
        return list(self._instruments)

    def get_all_ids(self) -> List[str]:
        """Returns a list of all internal instrument IDs."""
        return [inst.id for inst in self._instruments]

    def get_by_market(self, market: str) -> List[Instrument]:
        """Filter registered instruments by market code ('US' or 'IN')."""
        m_upper = market.strip().upper()
        return [inst for inst in self._instruments if inst.market == m_upper]

    def get_default_selection(self) -> List[Instrument]:
        """
        Returns the stable, deterministic default 10-stock portfolio selection
        (the original 10 US stocks).
        """
        return [self._by_id[inst_id] for inst_id in self.DEFAULT_SELECTION_IDS]

    def get_default_selection_ids(self) -> List[str]:
        """Returns the list of 10 internal IDs representing the default US selection."""
        return list(self.DEFAULT_SELECTION_IDS)

    def validate_selection(self, instrument_ids: Sequence[str]) -> List[Instrument]:
        """
        Validates that a portfolio selection contains exactly 10 distinct, known internal IDs.
        Raises ValueError with clear message if invalid.
        Returns the ordered list of 10 Instrument objects.
        """
        if not isinstance(instrument_ids, (list, tuple, set)):
            raise TypeError("Selection must be a sequence (list or tuple) of instrument IDs")

        id_list = list(instrument_ids)
        if len(id_list) != 10:
            raise ValueError(
                f"Portfolio selection must contain exactly 10 instruments, got {len(id_list)}"
            )

        seen = set()
        duplicates = []
        for inst_id in id_list:
            if inst_id in seen:
                duplicates.append(inst_id)
            seen.add(inst_id)

        if duplicates:
            raise ValueError(f"Selection contains duplicate instrument IDs: {duplicates}")

        selected_instruments = []
        unknown_ids = []
        for inst_id in id_list:
            inst = self.get_by_id(inst_id)
            if inst is None:
                unknown_ids.append(inst_id)
            else:
                selected_instruments.append(inst)

        if unknown_ids:
            raise ValueError(f"Selection contains unknown instrument ID(s): {unknown_ids}")

        return selected_instruments

    def __len__(self) -> int:
        return len(self._instruments)

    def __contains__(self, instrument_id: str) -> bool:
        return instrument_id in self._by_id

    def __iter__(self):
        return iter(self._instruments)


_GLOBAL_CATALOG: Optional[InstrumentCatalog] = None

def get_catalog(catalog_path: Optional[str] = None, reload: bool = False) -> InstrumentCatalog:
    """Access the cached singleton instance of InstrumentCatalog."""
    global _GLOBAL_CATALOG
    if _GLOBAL_CATALOG is None or reload or (catalog_path and catalog_path != _GLOBAL_CATALOG.catalog_path):
        _GLOBAL_CATALOG = InstrumentCatalog(catalog_path=catalog_path)
    return _GLOBAL_CATALOG
