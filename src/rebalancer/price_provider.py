import json
import os
import math

class PriceProvider:
    """
    Deterministic local price provider for portfolio calculations.
    Ensures reproducibility and separates market data from portfolio logic.
    """
    
    DEFAULT_DATA_PATH = os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "reference_prices.json"
    )

    def __init__(self, data_path: str = None):
        self.data_path = data_path or self.DEFAULT_DATA_PATH
        self._as_of = None
        self._currency = None
        self._prices = {}
        self._load_data()

    def _load_data(self):
        with open(self.data_path, "r") as f:
            data = json.load(f)
            self._as_of = data.get("as_of")
            self._currency = data.get("currency", "USD")
            self._prices = data.get("prices", {})

    @property
    def as_of(self) -> str:
        return self._as_of

    def get_price(self, ticker: str) -> float:
        if ticker not in self._prices:
            raise ValueError(f"Unknown ticker: {ticker}")
        
        price = self._prices[ticker]
        
        if not isinstance(price, (int, float)):
            raise ValueError(f"Invalid non-numeric price for {ticker}: {price}")
        if math.isnan(price) or math.isinf(price):
            raise ValueError(f"Invalid NaN/inf price for {ticker}: {price}")
        if price <= 0:
            raise ValueError(f"Invalid non-positive price for {ticker}: {price}")
            
        return float(price)

    def get_prices(self, tickers: list) -> dict:
        return {t: self.get_price(t) for t in tickers}
