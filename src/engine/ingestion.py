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
        self.coverage_stats = {}

    def fetch_live_news(self, max_items_per_ticker: int = 5, force_fallback: bool = False, max_total: int = None) -> list:
        """Pulls headlines for all 10 monitored constituents."""
        articles = []
        self.coverage_stats = {t: 0 for t in self.TICKER_COMPANY_MAP.keys()}

        fallback_articles = []
        if os.path.exists(self.fallback_path):
            try:
                with open(self.fallback_path, "r") as f:
                    fallback_articles = json.load(f)
            except Exception as e:
                print(f"Error loading fallback articles: {e}")

        if not force_fallback:
            for ticker, company in self.TICKER_COMPANY_MAP.items():
                ticker_articles = 0
                
                # --- SOURCE 1: Google News RSS (Search across global financial media) ---
                query = urllib.parse.quote(f'"{company}" OR "{ticker}" stock OR earnings OR credit')
                gn_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
                try:
                    req = urllib.request.Request(
                        gn_url, headers={"User-Agent": "Mozilla/5.0"}
                    )
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        tree = ET.fromstring(resp.read())
                        items = tree.findall("./channel/item")

                        for item in items:
                            if ticker_articles >= max_items_per_ticker:
                                break

                            title = item.find("title").text if item.find("title") is not None else ""
                            pub_date = item.find("pubDate").text if item.find("pubDate") is not None else datetime.now(timezone.utc).isoformat()
                            source = item.find("source").text if item.find("source") is not None else "GoogleNews-RSS"
                            url_link = item.find("link").text if item.find("link") is not None else ""

                            if " - " in title:
                                title = title.rsplit(" - ", 1)[0]

                            clean_title = title.strip()
                            if clean_title:
                                articles.append({
                                    "ticker": ticker,
                                    "headline": clean_title,
                                    "source": source,
                                    "url": url_link,
                                    "published_at": pub_date
                                })
                                ticker_articles += 1
                except Exception as e:
                    print(f"Error fetching Google News for {ticker}: {e}")

                # --- SOURCE 2: Yahoo Finance RSS (Direct constituent financial headline feed) ---
                yf_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}"
                try:
                    req_yf = urllib.request.Request(
                        yf_url, headers={"User-Agent": "Mozilla/5.0"}
                    )
                    with urllib.request.urlopen(req_yf, timeout=3) as resp_yf:
                        tree_yf = ET.fromstring(resp_yf.read())
                        items_yf = tree_yf.findall("./channel/item")

                        for item in items_yf:
                            if ticker_articles >= max_items_per_ticker * 2:
                                break

                            title = item.find("title").text if item.find("title") is not None else ""
                            pub_date = item.find("pubDate").text if item.find("pubDate") is not None else datetime.now(timezone.utc).isoformat()
                            url_link = item.find("link").text if item.find("link") is not None else ""

                            clean_title = title.strip()
                            if clean_title:
                                articles.append({
                                    "ticker": ticker,
                                    "headline": clean_title,
                                    "source": "YahooFinance-RSS",
                                    "url": url_link,
                                    "published_at": pub_date
                                })
                                ticker_articles += 1
                except Exception as e:
                    print(f"Error fetching Yahoo Finance for {ticker}: {e}")

                self.coverage_stats[ticker] = ticker_articles

        # Offline crisis replay fallback
        if force_fallback:
            articles = list(fallback_articles)
            for fb in fallback_articles:
                t = fb.get("ticker")
                if t in self.coverage_stats:
                    self.coverage_stats[t] += 1

            # Include synthetic demo social feed in replay mode
            try:
                social_path = "data/synthetic_social.json"
                if os.path.exists(social_path):
                    with open(social_path, "r") as f:
                        social_data = json.load(f)
                        for s_item in social_data:
                            s_item["is_synthetic"] = True
                            articles.append(s_item)
            except Exception as e:
                print(f"Error loading synthetic social feed: {e}")

        # Deduplicate by headline preserving ticker coverage
        seen = set()
        deduped_articles = []
        for a in articles:
            hd = a.get("headline", "").strip()
            if hd and hd not in seen:
                seen.add(hd)
                deduped_articles.append(a)

        if max_total is not None and max_total > 0:
            return deduped_articles[:max_total]

        return deduped_articles


if __name__ == "__main__":
    ingestor = MarketNewsIngestion()
    news = ingestor.fetch_live_news(max_items_per_ticker=2)
    print(f"Fetched {len(news)} live articles:\n")
    for item in news:
        print(f"[{item['ticker']}] {item['headline']}")
