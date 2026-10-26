import os
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Any, Optional, Tuple, List
import pandas as pd

DEFAULT_MAX_ARTICLE_AGE_HOURS = 72.0

def parse_publication_timestamp(pub_str: Optional[str], max_age_hours: float = DEFAULT_MAX_ARTICLE_AGE_HOURS) -> Dict[str, Any]:
    """
    Parses a publication date string into a structured UTC timestamp and validates freshness.
    Handles RFC 2822, ISO 8601, pandas formats, and flags missing, malformed, future, and stale dates.
    """
    now = datetime.now(timezone.utc)
    if not pub_str or not str(pub_str).strip():
        return {
            "published_at": None,
            "has_reliable_timestamp": False,
            "article_age_hours": None,
            "article_age_days": None,
            "is_fresh": False,
            "freshness_status": "MISSING_TIMESTAMP",
            "rejection_reason": "Article lacks a publication timestamp"
        }
    
    clean_str = str(pub_str).strip()
    dt = None
    # 1. RFC 2822 (e.g. 'Tue, 06 Oct 2026 12:00:00 GMT')
    try:
        parsed = parsedate_to_datetime(clean_str)
        if parsed is not None:
            if parsed.tzinfo is None:
                dt = parsed.replace(tzinfo=timezone.utc)
            else:
                dt = parsed.astimezone(timezone.utc)
    except Exception:
        pass
    
    # 2. ISO 8601 / pandas format
    if dt is None:
        try:
            p_dt = pd.to_datetime(clean_str, utc=True)
            if not pd.isna(p_dt):
                dt = p_dt.to_pydatetime()
        except Exception:
            pass

    if dt is None:
        return {
            "published_at": None,
            "has_reliable_timestamp": False,
            "article_age_hours": None,
            "article_age_days": None,
            "is_fresh": False,
            "freshness_status": "MALFORMED_TIMESTAMP",
            "rejection_reason": f"Malformed timestamp format: {clean_str}"
        }

    diff_seconds = (now - dt).total_seconds()
    # Reject implausible future-dated articles (> 2 hours in the future)
    if diff_seconds < -7200.0:
        return {
            "published_at": dt.isoformat(),
            "has_reliable_timestamp": False,
            "article_age_hours": round(diff_seconds / 3600.0, 1),
            "article_age_days": round(diff_seconds / 86400.0, 1),
            "is_fresh": False,
            "freshness_status": "IMPLAUSIBLE_FUTURE_DATE",
            "rejection_reason": f"Implausible future timestamp: {dt.isoformat()}"
        }

    age_hours = max(0.0, diff_seconds / 3600.0)
    age_days = round(age_hours / 24.0, 1)

    if age_hours > max_age_hours:
        return {
            "published_at": dt.isoformat(),
            "has_reliable_timestamp": True,
            "article_age_hours": round(age_hours, 1),
            "article_age_days": age_days,
            "is_fresh": False,
            "freshness_status": "STALE",
            "rejection_reason": f"Article age ({age_days}d / {age_hours:.1f}h) exceeds maximum allowed age ({max_age_hours}h)"
        }

    return {
        "published_at": dt.isoformat(),
        "has_reliable_timestamp": True,
        "article_age_hours": round(age_hours, 1),
        "article_age_days": age_days,
        "is_fresh": True,
        "freshness_status": "FRESH",
        "rejection_reason": None
    }

def is_irrelevant_or_seo_headline(headline: str) -> Tuple[bool, Optional[str]]:
    """
    Identifies generic SEO pages, stock quote pages, options chains, 
    and backward-looking fund filings that do not represent substantive market events.
    """
    if not headline or not headline.strip():
        return True, "EMPTY_HEADLINE"
    
    lower = headline.lower().strip()
    
    # 1. Backward-looking institutional fund holdings disclosures
    fund_patterns = [
        r"\b(lowers?|decreases?|raises?|increases?|trims?|boosts?|cuts?)\s+(stake|holdings?|position)\b",
        r"\b(stake|holdings?|position)\s+(in|of)\s+.*\s+(lowered|decreased|raised|increased|trimmed|boosted|cut)\b",
        r"\bshares\s+(purchased|sold|added|acquired)\s+(by|to)\b",
        r"\bshares\s+added\s+to\s+.*portfolio\b",
        r"\b(acquires?|sells?|purchases?)\s+[\d,]+\s+shares\s+of\b",
        r"\bposition\s+in\s+.*\b(llc|capital|advisors|management|group|fund|asset|wealth)\b",
        r"\bstake\s+in\s+.*\b(llc|capital|advisors|management|group|fund|asset|wealth)\b",
        r"\b(dupree|capital|financial|advisors|wealth|asset)\s+group\s+llc\b",
        r"\b(capital\s+management|capital\s+advisors|wealth\s+management|asset\s+management|holdings\s+llc|fund\s+llc)\b.*\b(stake|holdings?|shares?)\b",
        r"\b(13f|form\s+13-f|institutional\s+holdings?)\b",
        r"\bdiscloses?\s+.*(stake|holdings?)\b",
        r"\bdecreases\s+holdings\b",
        r"\blowers\s+stake\b",
        r"\b(futures\s+margins?|cme\s+margins?|margin\s+requirements?)\b"
    ]
    for p in fund_patterns:
        if re.search(p, lower):
            return True, "FUND_HOLDINGS_DISCLOSURE"
        
    # 2. Generic stock quote / SEO / technical chart aggregator pages
    seo_patterns = [
        r"\bstock\s+price\s+today\b",
        r"\bshare\s+price\s+today\b",
        r"\blive\s+bse\s*/\s*nse\s+updates\b",
        r"\boptions?\s+chain\b",
        r"\bshort\s+interest\b",
        r"\bshare\s+price\s*:\s*technical\s+analysis\b",
        r"\bstock\s+quote\b",
        r"\bprice\s+target\s+and\s+consensus\b",
        r"\b52[- ]week\s+(?:high|low)\b",
        r"\bex[- ]dividend\s+date\b",
        r"\bdividend\s+yield\s+history\b",
        r"\bhistorical\s+(?:share|stock)?\s*prices?\b",
        r"\btechnical\s+chart\s+analysis\b",
        r"\bpeers?\s+comparison\b",
        r"\bfinancial\s+statements?\s+overview\b",
        r"\bcompany\s+profile\s+(?:and|&)\s+overview\b",
        r"\bholdings?\s+disclosure\b",
        r"\bquarterly\s+results\s+calendar\b",
        r"\bstock\s+price,\s*news,\s*quote\s+(?:and|&)\s+history\b",
        r"\bstock\s+price\b.*\bquote\s+(?:and|&)\s+history\b",
        r"\binteractive\s+stock\s+chart\b",
        r"\bquote\s+(?:and|&)\s+history\b",
        r"\bvaluation,\s*fundamentals\s+(?:and|&)\s+technicals\b"
    ]
    for p in seo_patterns:
        if re.search(p, lower):
            return True, "GENERIC_STOCK_QUOTE_OR_SEO"
            
    return False, None

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

    ALL_TICKER_COMPANY_MAP = {
        **TICKER_COMPANY_MAP,
        "RELIANCE": "Reliance Industries",
        "TCS": "Tata Consultancy Services",
        "HDFCBANK": "HDFC Bank",
        "INFY": "Infosys",
        "ICICIBANK": "ICICI Bank",
        "HINDUNILVR": "Hindustan Unilever",
        "ITC": "ITC Limited",
        "BHARTIARTL": "Bharti Airtel",
        "LT": "Larsen & Toubro",
        "SBIN": "State Bank of India",
    }

    def get_company_name(self, ticker: str) -> str:
        if ticker in self.ALL_TICKER_COMPANY_MAP:
            return self.ALL_TICKER_COMPANY_MAP[ticker]
        try:
            from src.engine.catalog import get_catalog
            inst = get_catalog().get_by_ticker(ticker) or get_catalog().get_by_id(ticker)
            if inst:
                return inst.name
        except Exception:
            pass
        return ticker

    def __init__(self, fallback_path: str = "data/sample_news.json"):
        self.fallback_path = fallback_path
        self.coverage_stats = {}
        self.provider_status = {"GoogleNews-RSS": "OK", "YahooFinance-RSS": "OK"}

    def fetch_live_news(
        self,
        max_items_per_ticker: int = 5,
        force_fallback: bool = False,
        max_total: int = None,
        tickers: list = None,
        enforce_freshness: bool = False,
        max_age_hours: float = DEFAULT_MAX_ARTICLE_AGE_HOURS
    ) -> list:
        """Pulls headlines for monitored constituents."""
        articles = []
        target_tickers = tickers or list(self.TICKER_COMPANY_MAP.keys())
        self.coverage_stats = {t: 0 for t in target_tickers}
        self.provider_status = {"GoogleNews-RSS": "OK", "YahooFinance-RSS": "OK"}

        fallback_articles = []
        if os.path.exists(self.fallback_path):
            try:
                with open(self.fallback_path, "r") as f:
                    fallback_articles = json.load(f)
            except Exception as e:
                print(f"Error loading fallback articles: {e}")

        if not force_fallback:
            from src.engine.catalog import get_catalog
            cat = get_catalog()

            for ticker in target_tickers:
                company = self.get_company_name(ticker)
                inst = cat.get_by_ticker(ticker) if cat else None
                is_indian = (inst and inst.market == "IN") or (ticker in ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC", "BHARTIARTL", "LT", "SBIN"])
                prov_sym = inst.provider_symbol if inst else (f"{ticker}.NS" if is_indian else ticker)

                ticker_articles = 0
                
                # --- SOURCE 1: Google News RSS (Search across global financial media) ---
                if is_indian:
                    # Target genuine Indian business news with regional IN edition and proper aliases
                    if ticker == "SBIN":
                        query = urllib.parse.quote('("State Bank of India" OR "SBI") (stock OR shares OR profit OR earnings OR results OR bank)')
                    elif ticker in ["LT", "ITC", "TCS"]:
                        query = urllib.parse.quote(f'"{company}" (stock OR earnings OR shares OR profit OR results)')
                    else:
                        query = urllib.parse.quote(f'("{company}" OR "{ticker}") (stock OR earnings OR shares OR profit OR results)')
                    gn_url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
                else:
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
                            pub_date = item.find("pubDate").text if item.find("pubDate") is not None else None
                            source = item.find("source").text if item.find("source") is not None else "GoogleNews-RSS"
                            url_link = item.find("link").text if item.find("link") is not None else ""

                            if " - " in title:
                                title = title.rsplit(" - ", 1)[0]

                            clean_title = title.strip()
                            if clean_title:
                                is_seo, _ = is_irrelevant_or_seo_headline(clean_title)
                                if is_seo:
                                    continue
                                fresh_meta = parse_publication_timestamp(pub_date, max_age_hours=max_age_hours)
                                if enforce_freshness and not fresh_meta["is_fresh"]:
                                    continue
                                articles.append({
                                    "ticker": ticker,
                                    "headline": clean_title,
                                    "source": source,
                                    "url": url_link,
                                    "published_at": fresh_meta["published_at"] or pub_date,
                                    "raw_published_at": pub_date,
                                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                                    "has_reliable_timestamp": fresh_meta["has_reliable_timestamp"],
                                    "article_age_hours": fresh_meta["article_age_hours"],
                                    "article_age_days": fresh_meta["article_age_days"],
                                    "freshness_status": fresh_meta["freshness_status"],
                                    "is_fresh": fresh_meta["is_fresh"]
                                })
                                ticker_articles += 1
                except Exception as e:
                    self.provider_status["GoogleNews-RSS"] = "DEGRADED"
                    print(f"Error fetching Google News for {ticker}: {e}")

                # --- SOURCE 2: Yahoo Finance RSS (Direct constituent financial headline feed) ---
                yf_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={prov_sym}"
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
                            pub_date = item.find("pubDate").text if item.find("pubDate") is not None else None
                            url_link = item.find("link").text if item.find("link") is not None else ""

                            clean_title = title.strip()
                            if clean_title:
                                is_seo, _ = is_irrelevant_or_seo_headline(clean_title)
                                if is_seo:
                                    continue
                                fresh_meta = parse_publication_timestamp(pub_date, max_age_hours=max_age_hours)
                                if enforce_freshness and not fresh_meta["is_fresh"]:
                                    continue
                                articles.append({
                                    "ticker": ticker,
                                    "headline": clean_title,
                                    "source": "YahooFinance-RSS",
                                    "url": url_link,
                                    "published_at": fresh_meta["published_at"] or pub_date,
                                    "raw_published_at": pub_date,
                                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                                    "has_reliable_timestamp": fresh_meta["has_reliable_timestamp"],
                                    "article_age_hours": fresh_meta["article_age_hours"],
                                    "article_age_days": fresh_meta["article_age_days"],
                                    "freshness_status": fresh_meta["freshness_status"],
                                    "is_fresh": fresh_meta["is_fresh"]
                                })
                                ticker_articles += 1
                except Exception as e:
                    self.provider_status["YahooFinance-RSS"] = "DEGRADED"
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
