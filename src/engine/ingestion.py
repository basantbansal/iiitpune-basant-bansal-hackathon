import os
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


class MarketNewsIngestion:
    """
    Direct news pipeline.
    Fetches the latest headlines for your 10 tickers via Google News RSS.
    Falls back to data/sample_news.json if offline.
    """

    TICKER_COMPANY_MAP = {
        "AAPL": "Apple",
        "MSFT": "Microsoft",
        "NVDA": "Nvidia",
        "AMZN": "Amazon",
        "GOOGL": "Alphabet Google",
        "META": "Meta Platforms",
        "TSLA": "Tesla",
        "JPM": "JPMorgan Chase",
        "JNJ": "Johnson & Johnson",
        "XOM": "ExxonMobil",
    }

    def __init__(self, fallback_path: str = "data/sample_news.json"):
        self.fallback_path = fallback_path

    def fetch_live_news(self, max_items_per_ticker: int = 1) -> list:
        """Pulls headlines and returns a list of dictionaries directly."""
        articles = []

        for ticker, company in self.TICKER_COMPANY_MAP.items():
            query = urllib.parse.quote(f"{company} stock OR earnings OR credit")
            url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    tree = ET.fromstring(resp.read())
                    items = tree.findall("./channel/item")[:max_items_per_ticker]

                    for item in items:
                        title = item.find("title").text if item.find("title") is not None else ""
                        pub_date = item.find("pubDate").text if item.find("pubDate") is not None else datetime.now(timezone.utc).isoformat()
                        
                        if " - " in title:
                            title = title.rsplit(" - ", 1)[0]

                        articles.append({
                            "ticker": ticker,
                            "headline": title.strip(),
                            "source": "GoogleNews-RSS",
                            "published_at": pub_date
                        })
            except Exception:
                pass

        # Offline fallback
        if not articles and os.path.exists(self.fallback_path):
            with open(self.fallback_path, "r") as f:
                articles = json.load(f)

        return articles


if __name__ == "__main__":
    ingestor = MarketNewsIngestion()
    news = ingestor.fetch_live_news(max_items_per_ticker=1)
    print(f"Fetched {len(news)} live articles:\n")
    for item in news:
        print(f"[{item['ticker']}] {item['headline']}")