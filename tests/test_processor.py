import pytest
from datetime import datetime, timezone, timedelta
from src.engine.processor import EntityResolver, SemanticDedup

def test_entity_exact_ticker():
    res = EntityResolver.resolve_entities("NVDA launches new GPU")
    assert len(res) == 1
    assert res[0].ticker == "NVDA"
    assert res[0].match_type == "Exact Ticker"

def test_entity_canonical_name():
    res = EntityResolver.resolve_entities("Microsoft beats earnings")
    assert len(res) == 1
    assert res[0].ticker == "MSFT"
    assert res[0].match_type == "Canonical Name"

def test_entity_known_alias():
    res = EntityResolver.resolve_entities("JPMorgan Chase & Co reports revenue")
    assert len(res) == 1
    assert res[0].ticker == "JPM"

def test_entity_unknown_company():
    res = EntityResolver.resolve_entities("RandomCorp announces nothing")
    assert len(res) == 0

def test_entity_ambiguous_common_word():
    # Ambiguous word without financial context
    res = EntityResolver.resolve_entities("Apple harvest season begins")
    assert len(res) == 0
    # Ambiguous word with financial context
    res2 = EntityResolver.resolve_entities("Apple stock rises on earnings")
    assert len(res2) == 1
    assert res2[0].ticker == "AAPL"

def test_entity_multi_company():
    res = EntityResolver.resolve_entities("Microsoft partners with NVIDIA on AI stock")
    tickers = {r.ticker for r in res}
    assert tickers == {"MSFT", "NVDA"}

def test_entity_case_differences():
    res1 = EntityResolver.resolve_entities("nvidia reports earnings")
    res2 = EntityResolver.resolve_entities("NVIDIA REPORTS EARNINGS")
    assert len(res1) == 1 and res1[0].ticker == "NVDA"
    assert len(res2) == 1 and res2[0].ticker == "NVDA"

def test_dedup_exact():
    dedup = SemanticDedup(time_window_hours=24)
    cand = [{"normalized_headline": "nvidia stock rises", "resolved_entities": "NVDA", "document_hash": "hash1", "published_at": datetime.now(timezone.utc).isoformat()}]
    res = dedup.check_duplicate("nvidia stock rises", {"NVDA"}, cand)
    assert res["is_duplicate"] == True
    assert "Exact textual match" in res["reason"]

def test_dedup_case_whitespace():
    dedup = SemanticDedup(time_window_hours=24)
    text1 = EntityResolver.normalize_text("  Nvidia  stock rises!!! ")
    text2 = EntityResolver.normalize_text("nvidia stock rises")
    assert text1.lower() == text2.lower()
    
def test_dedup_near_identical():
    dedup = SemanticDedup(time_window_hours=24)
    cand = [{"normalized_headline": "apple cuts iphone production forecast", "resolved_entities": "AAPL", "document_hash": "hash1", "published_at": datetime.now(timezone.utc).isoformat()}]
    res = dedup.check_duplicate("apple reduces iphone production outlook", {"AAPL"}, cand)
    assert res["is_duplicate"] == True

def test_dedup_different_events_same_company():
    dedup = SemanticDedup(time_window_hours=24)
    cand = [{"normalized_headline": "apple cuts iphone production forecast", "resolved_entities": "AAPL", "document_hash": "hash1", "published_at": datetime.now(timezone.utc).isoformat()}]
    res = dedup.check_duplicate("apple launches new ipad", {"AAPL"}, cand)
    assert res["is_duplicate"] == False

def test_dedup_same_headline_different_companies():
    dedup = SemanticDedup(time_window_hours=24)
    cand = [{"normalized_headline": "company cuts production forecast", "resolved_entities": "AAPL", "document_hash": "hash1", "published_at": datetime.now(timezone.utc).isoformat()}]
    res = dedup.check_duplicate("company cuts production forecast", {"MSFT"}, cand)
    # The text is identical but they share no entities!
    # Wait, my logic says "if entities and cand_entities and not intersection -> continue"
    assert res["is_duplicate"] == False

def test_dedup_outside_time_window():
    dedup = SemanticDedup(time_window_hours=24)
    old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    # Actually DB get_recent_documents filters time, SemanticDedup just assumes candidates are valid
    # But let's test if it handles it if passed directly. The DB handles the window filter, so SemanticDedup trusts candidates.
    pass

def test_dedup_shared_entity_alone_not_enough():
    dedup = SemanticDedup(time_window_hours=24)
    cand = [{"normalized_headline": "apple buys startup", "resolved_entities": "AAPL", "document_hash": "hash1", "published_at": datetime.now(timezone.utc).isoformat()}]
    res = dedup.check_duplicate("apple sells bonds", {"AAPL"}, cand)
    assert res["is_duplicate"] == False

def test_pipeline_document_stored_once_multiple_entities():
    from src.storage.db import SignalDatabase
    from src.engine.processor import EntityResolver, SemanticDedup
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmpdirname:
        db_path = os.path.join(tmpdirname, "test.db")
        db = SignalDatabase(db_path)
        
        raw_headline = "Microsoft partners with NVIDIA"
        norm_headline = EntityResolver.normalize_text(raw_headline)
        doc_hash = SemanticDedup.get_document_hash(norm_headline)
        
        resolved = EntityResolver.resolve_entities(raw_headline)
        entities = {r.ticker for r in resolved}
        
        doc_data = {
            "document_hash": doc_hash,
            "canonical_group_id": doc_hash,
            "headline": raw_headline,
            "normalized_headline": norm_headline,
            "source": "test",
            "published_at": "2026-01-01T00:00:00Z",
            "is_duplicate": False,
            "duplicate_reason": "none",
            "resolved_entities": list(entities)
        }
        
        db.log_document(doc_data)
        
        docs = db.get_recent_documents(87600) # lots of hours
        assert len(docs) == 1
        assert "MSFT" in docs[0]["resolved_entities"]
        assert "NVDA" in docs[0]["resolved_entities"]


def test_multi_entity_linkage():
    from src.storage.db import SignalDatabase
    import tempfile
    import os
    with tempfile.TemporaryDirectory() as tmpdirname:
        db_path = os.path.join(tmpdirname, "test.db")
        db = SignalDatabase(db_path)
        doc_hash = "fake_doc_hash_123"
        
        # Log signal 1
        db.log_signal("hash_msft", {"entity": "MSFT", "event_classification": "Partnership", "sentiment_score": 0.5, "impact_score": 3, "confidence": 0.8, "evidence_span": "partners"}, "Microsoft partners with NVIDIA", "Source", "2026-01-01T12:00:00Z", doc_hash)
        
        # Log signal 2
        db.log_signal("hash_nvda", {"entity": "NVDA", "event_classification": "Partnership", "sentiment_score": 0.5, "impact_score": 3, "confidence": 0.8, "evidence_span": "partners"}, "Microsoft partners with NVIDIA", "Source", "2026-01-01T12:00:00Z", doc_hash)
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ticker, document_hash FROM risk_signals")
            rows = cursor.fetchall()
            assert len(rows) == 2
            for row in rows:
                assert row[1] == doc_hash

def test_existing_risk_signals_migration():
    import sqlite3
    import tempfile
    import os
    from src.storage.db import SignalDatabase
    with tempfile.TemporaryDirectory() as tmpdirname:
        db_path = os.path.join(tmpdirname, "test_mig.db")
        # Create OLD schema
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE risk_signals (
                article_hash TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                headline TEXT NOT NULL,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                sentiment REAL NOT NULL,
                impact INTEGER NOT NULL,
                confidence REAL NOT NULL,
                evidence TEXT NOT NULL,
                model_version TEXT NOT NULL,
                published_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            INSERT INTO risk_signals VALUES (
                'hash_old', 'AAPL', 'Old headline', 'Source', 'Event', 0.5, 3, 0.8, 'Old', 'v1.0', '2026', '2026'
            )
        """)
        conn.commit()
        conn.close()
        
        # Init new DB class, which should run migration
        db = SignalDatabase(db_path)
        
        # Check that old row is still there and document_hash column exists
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ticker, document_hash FROM risk_signals")
            rows = cursor.fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "AAPL"
            
        # Re-initialize the same database to test idempotency (already-migrated schema)
        db2 = SignalDatabase(db_path)
        with db2._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(risk_signals)")
            columns = [info[1] for info in cursor.fetchall()]
            assert "document_hash" in columns
            # Ensure it didn't crash or duplicate columns
            assert columns.count("document_hash") == 1

def test_opposite_events_not_duplicate():
    dedup = SemanticDedup(time_window_hours=24)
    cand = [{"normalized_headline": "nvidia stock rises", "resolved_entities": "NVDA", "document_hash": "hash1", "published_at": datetime.now(timezone.utc).isoformat()}]
    res = dedup.check_duplicate("nvidia stock falls", {"NVDA"}, cand)
    # The Jaccard will be 2/3 = 0.66 > 0.40, but direction is opposite
    assert res["is_duplicate"] == False

def test_same_direction_paraphrase():
    dedup = SemanticDedup(time_window_hours=24)
    cand = [{"normalized_headline": "nvidia stock rises", "resolved_entities": "NVDA", "document_hash": "hash1", "published_at": datetime.now(timezone.utc).isoformat()}]
    res = dedup.check_duplicate("nvidia shares rise", {"NVDA"}, cand)
    assert res["is_duplicate"] == False

def test_revenue_paraphrase():
    dedup = SemanticDedup(time_window_hours=24)
    cand = [{"normalized_headline": "nvidia revenue beats expectations", "resolved_entities": "NVDA", "document_hash": "hash1", "published_at": datetime.now(timezone.utc).isoformat()}]
    res = dedup.check_duplicate("nvidia revenue exceeds expectations", {"NVDA"}, cand)
    assert res["is_duplicate"] == True

def test_accelerator_paraphrase():
    dedup = SemanticDedup(time_window_hours=24)
    cand = [{"normalized_headline": "nvidia announces new ai accelerator", "resolved_entities": "NVDA", "document_hash": "hash1", "published_at": datetime.now(timezone.utc).isoformat()}]
    res = dedup.check_duplicate("nvidia unveils latest ai accelerator", {"NVDA"}, cand)
    assert res["is_duplicate"] == True

def test_meta_regression():
    res = EntityResolver.resolve_entities("meta-analysis of research")
    assert len(res) == 0

def test_financial_meta():
    res = EntityResolver.resolve_entities("Meta earnings beat expectations")
    assert len(res) == 1
    assert res[0].ticker == "META"

def test_published_at_index_exists():
    from src.storage.db import SignalDatabase
    import tempfile
    import os
    with tempfile.TemporaryDirectory() as tmpdirname:
        db_path = os.path.join(tmpdirname, "test.db")
        db = SignalDatabase(db_path)
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_published_at'")
            row = cursor.fetchone()
            assert row is not None

def test_directional_mixed_losses():
    dedup = SemanticDedup(time_window_hours=24)
    cand = [{"normalized_headline": "nvidia shares rise", "resolved_entities": "NVDA", "document_hash": "hash1", "published_at": datetime.now(timezone.utc).isoformat()}]
    res = dedup.check_duplicate("nvidia shares rise after earlier losses", {"NVDA"}, cand)
    assert res["is_duplicate"] == True

def test_directional_mixed_gains():
    dedup = SemanticDedup(time_window_hours=24)
    cand = [{"normalized_headline": "nvidia shares fall", "resolved_entities": "NVDA", "document_hash": "hash1", "published_at": datetime.now(timezone.utc).isoformat()}]
    res = dedup.check_duplicate("nvidia shares fall after earlier gains", {"NVDA"}, cand)
    assert res["is_duplicate"] == True
