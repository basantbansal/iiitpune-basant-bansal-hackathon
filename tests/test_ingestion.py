import pytest
from unittest.mock import patch, MagicMock
from src.engine.ingestion import MarketNewsIngestion
import xml.etree.ElementTree as ET
import urllib.error

def test_ingestion_feed_parsing():
    ingestor = MarketNewsIngestion()
    
    mock_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <item>
                <title>Apple releases new product - TechNews</title>
                <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
                <source url="http://example.com">TechNews</source>
                <link>http://example.com/apple</link>
            </item>
            <item>
                <title>Apple sales soar</title>
                <pubDate>Tue, 02 Jan 2024 14:00:00 GMT</pubDate>
                <source url="http://example.com">BizNews</source>
                <link>http://example.com/msft</link>
            </item>
        </channel>
    </rss>
    """
    
    def mock_urlopen(req, timeout=3):
        mock_resp = MagicMock()
        if "Apple" in req.full_url:
            mock_resp.read.return_value = mock_xml.encode('utf-8')
        else:
            mock_resp.read.return_value = b"<?xml version=\"1.0\"?><rss><channel></channel></rss>"
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch('urllib.request.urlopen', side_effect=mock_urlopen):
        with patch('os.path.exists', return_value=False):
            articles = ingestor.fetch_live_news(max_items_per_ticker=2, max_total=25)
            
            assert len(articles) == 2
            assert articles[0]["ticker"] == "AAPL"
            assert articles[0]["headline"] == "Apple releases new product"
            assert articles[1]["headline"] == "Apple sales soar"
            
            assert "AAPL" in ingestor.coverage_stats
            assert ingestor.coverage_stats["AAPL"] == 2

def test_ingestion_partial_failures():
    ingestor = MarketNewsIngestion()
    
    def mock_urlopen(req, timeout=3):
        if "Apple" in req.full_url:
            raise urllib.error.URLError("Timeout")
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<?xml version=\"1.0\"?><rss><channel></channel></rss>"
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch('urllib.request.urlopen', side_effect=mock_urlopen):
        with patch('os.path.exists', return_value=False):
            articles = ingestor.fetch_live_news(max_items_per_ticker=1)
            
            assert articles == []
            assert ingestor.coverage_stats["AAPL"] == 0
            assert "MSFT" in ingestor.coverage_stats

def test_ingestion_two_independent_sources():
    """Verify that both Google News RSS and Yahoo Finance RSS are independently ingested and labeled."""
    ingestor = MarketNewsIngestion()

    google_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <item>
                <title>Apple announces new chip architecture</title>
                <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
                <source url="http://google.com">TechNews</source>
                <link>http://news.google.com/item1</link>
            </item>
        </channel>
    </rss>"""

    yahoo_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <item>
                <title>Apple reports strong enterprise services growth</title>
                <pubDate>Mon, 01 Jan 2024 13:00:00 GMT</pubDate>
                <link>http://finance.yahoo.com/item2</link>
            </item>
        </channel>
    </rss>"""

    def mock_urlopen(req, timeout=3):
        mock_resp = MagicMock()
        if "news.google.com" in req.full_url and "Apple" in req.full_url:
            mock_resp.read.return_value = google_xml
        elif "feeds.finance.yahoo.com" in req.full_url and "s=AAPL" in req.full_url:
            mock_resp.read.return_value = yahoo_xml
        else:
            mock_resp.read.return_value = b"<?xml version=\"1.0\"?><rss><channel></channel></rss>"
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch('urllib.request.urlopen', side_effect=mock_urlopen), \
         patch('os.path.exists', return_value=False):
        articles = ingestor.fetch_live_news(max_items_per_ticker=2)

        # Must have articles from both sources
        sources = {a["source"] for a in articles}
        assert "TechNews" in sources or "GoogleNews-RSS" in sources
        assert "YahooFinance-RSS" in sources

        # Verify headlines and tickers
        google_article = next(a for a in articles if a["source"] in ["TechNews", "GoogleNews-RSS"])
        yahoo_article = next(a for a in articles if a["source"] == "YahooFinance-RSS")

        assert google_article["headline"] == "Apple announces new chip architecture"
        assert yahoo_article["headline"] == "Apple reports strong enterprise services growth"
        assert google_article["ticker"] == "AAPL"
        assert yahoo_article["ticker"] == "AAPL"

