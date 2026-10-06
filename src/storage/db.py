import hashlib
import os
import sqlite3
from datetime import datetime, timezone

# Resolve project root (two levels up from src/storage)
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "risk_data.db")


class SignalDatabase:
    """
    Single-table SQLite persistence layer.
    Stores the final output of the Risk Engine along with the original headline
    and its cryptographic hash to prevent double-processing.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # We now only have ONE table that holds everything.
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_signals (
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
            """
            )
            conn.commit()

    @staticmethod
    def generate_hash(headline: str, ticker: str) -> str:
        """Creates a unique fingerprint for a specific headline and company."""
        return hashlib.sha256(f"{ticker}:{headline}".encode("utf-8")).hexdigest()

    def is_article_processed(self, article_hash: str) -> bool:
        """Checks if we have already scored this exact headline."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM risk_signals WHERE article_hash = ?", (article_hash,)
            )
            return cursor.fetchone() is not None

    def log_signal(
        self,
        article_hash: str,
        signal_dict: dict,
        headline: str,
        source: str,
        published_at: str,
    ):
        """Saves the final Risk Engine output to the database."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO risk_signals 
                (article_hash, ticker, headline, source, event_type, sentiment, impact, confidence, evidence, model_version, published_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    article_hash,
                    signal_dict["entity"],
                    headline,
                    source,
                    signal_dict["event_classification"],
                    signal_dict["sentiment_score"],
                    signal_dict["impact_score"],
                    signal_dict["confidence"],
                    signal_dict["evidence_span"],
                    signal_dict.get("model_version", "v1.0"),
                    published_at,
                    now,
                ),
            )
            conn.commit()