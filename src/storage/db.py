import hashlib
import os
import sqlite3
import json
from datetime import datetime, timezone
import pandas as pd

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
        dirname = os.path.dirname(self.db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False) if self.db_path == ":memory:" else None
        self._init_db()

    def _get_connection(self):
        if self._mem_conn is not None:
            return self._mem_conn
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
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
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_hash TEXT PRIMARY KEY,
                    canonical_group_id TEXT,
                    headline TEXT NOT NULL,
                    normalized_headline TEXT NOT NULL,
                    source TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    is_duplicate BOOLEAN,
                    duplicate_reason TEXT,
                    resolved_entities TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            # FIX 1: Idempotent migration to add document_hash to risk_signals
            cursor.execute("PRAGMA table_info(risk_signals)")
            columns = [info[1] for info in cursor.fetchall()]
            if "document_hash" not in columns:
                cursor.execute("ALTER TABLE risk_signals ADD COLUMN document_hash TEXT;")
            
            # FIX 3: Add index for temporal query
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_published_at ON documents(published_at)"
            )

            # Configuration table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS configuration (
                    id INTEGER PRIMARY KEY,
                    initial_capital REAL NOT NULL,
                    alpha_tilt REAL NOT NULL,
                    data_mode TEXT NOT NULL,
                    max_items INTEGER NOT NULL
                )
                """
            )

            # Holdings table for persistent portfolio accounting
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS holdings (
                    ticker TEXT PRIMARY KEY,
                    shares REAL NOT NULL
                )
                """
            )

            # Target weight history table for tracking rebalance trajectory over scans
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS target_weight_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_time TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    target_weight REAL NOT NULL
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_target_weights_scan ON target_weight_history(scan_time, ticker)"
            )

            # Latest rebalance orders table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS latest_orders (
                    ticker TEXT PRIMARY KEY,
                    price REAL,
                    prev_weight TEXT,
                    new_weight TEXT,
                    delta TEXT,
                    current_shares REAL,
                    pre_shares REAL,
                    target_shares REAL,
                    post_shares REAL,
                    action TEXT,
                    order_qty REAL,
                    signed_qty REAL,
                    trade_value REAL
                )
                """
            )

            # Portfolio cash balance tracking table (legacy single currency)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_cash (
                    id INTEGER PRIMARY KEY,
                    cash_balance REAL NOT NULL
                )
                """
            )

            # Multi-currency cash balance tracking table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_cash_balances (
                    currency TEXT PRIMARY KEY,
                    balance REAL NOT NULL
                )
                """
            )

            # Auditable FX currency conversions table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS fx_conversions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    from_currency TEXT NOT NULL,
                    to_currency TEXT NOT NULL,
                    from_amount REAL NOT NULL,
                    to_amount REAL NOT NULL,
                    rate REAL NOT NULL,
                    source TEXT NOT NULL,
                    is_live BOOLEAN NOT NULL,
                    observation_time TEXT,
                    notes TEXT
                )
                """
            )

            # Universe selection table for persistent stock selection
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS universe_selection (
                    id INTEGER PRIMARY KEY,
                    selected_ids TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            # Cumulative executed fees table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS cumulative_fees (
                    id INTEGER PRIMARY KEY,
                    fees_usd REAL NOT NULL,
                    fees_inr REAL NOT NULL
                )
                """
            )

            # Check if reporting_currency column exists in configuration table
            cursor.execute("PRAGMA table_info(configuration)")
            columns = [c[1] for c in cursor.fetchall()]
            if "reporting_currency" not in columns:
                cursor.execute("ALTER TABLE configuration ADD COLUMN reporting_currency TEXT DEFAULT 'INR'")

            conn.commit()

    def get_config(self) -> dict:
        """Fetches the persisted configuration if it exists."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT initial_capital, alpha_tilt, data_mode, max_items, reporting_currency FROM configuration WHERE id = 1")
            row = cursor.fetchone()
            if row:
                return {
                    "initial_capital": row[0],
                    "alpha_tilt": row[1],
                    "data_mode": row[2],
                    "max_items": row[3],
                    "reporting_currency": row[4] if row[4] else None
                }
            return None

    def save_config(self, config_data: dict):
        """Saves the configuration to the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO configuration 
                (id, initial_capital, alpha_tilt, data_mode, max_items, reporting_currency)
                VALUES (1, ?, ?, ?, ?, ?)
                """,
                (
                    config_data["initial_capital"],
                    config_data["alpha_tilt"],
                    config_data["data_mode"],
                    config_data["max_items"],
                    config_data.get("reporting_currency", None)
                )
            )
            conn.commit()

    def save_reporting_currency(self, currency: str):
        """Updates the reporting currency preference in the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE configuration SET reporting_currency = ? WHERE id = 1", (currency.upper(),))
            conn.commit()

    def get_cumulative_fees(self) -> dict:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT fees_usd, fees_inr FROM cumulative_fees WHERE id = 1")
            row = cursor.fetchone()
            if row:
                return {"USD": float(row[0] or 0.0), "INR": float(row[1] or 0.0)}
            return {"USD": 0.0, "INR": 0.0}

    def save_cumulative_fees(self, fees: dict):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO cumulative_fees (id, fees_usd, fees_inr) VALUES (1, ?, ?)",
                (float(fees.get("USD", 0.0)), float(fees.get("INR", 0.0)))
            )
            conn.commit()
            conn.commit()

    def get_holdings(self) -> dict:
        """Fetches persisted portfolio holdings."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ticker, shares FROM holdings")
            rows = cursor.fetchall()
            return {r[0]: r[1] for r in rows}

    def save_holdings(self, holdings: dict):
        """Saves current portfolio holdings, replacing any previous holdings."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM holdings")
            for ticker, shares in holdings.items():
                if shares is not None:
                    cursor.execute(
                        "INSERT INTO holdings (ticker, shares) VALUES (?, ?)",
                        (ticker, float(shares))
                    )
            conn.commit()

    def get_cash(self) -> float:
        """Fetches the persisted USD cash balance if set."""
        balances = self.get_cash_balances()
        return balances.get("USD", None)

    def save_cash(self, cash: float):
        """Saves current USD cash balance and syncs balances table."""
        balances = self.get_cash_balances()
        balances["USD"] = float(cash)
        self.save_cash_balances(balances)

    def get_cash_balances(self) -> dict:
        """Fetches all persisted currency cash balances as {currency: balance}."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT currency, balance FROM portfolio_cash_balances")
            rows = cursor.fetchall()
            if rows:
                return {str(r[0]).upper(): float(r[1]) for r in rows}
            
            # Check legacy portfolio_cash
            cursor.execute("SELECT cash_balance FROM portfolio_cash WHERE id = 1")
            row = cursor.fetchone()
            if row is not None:
                legacy_val = float(row[0])
                cursor.execute(
                    "INSERT OR REPLACE INTO portfolio_cash_balances (currency, balance) VALUES ('USD', ?)",
                    (legacy_val,)
                )
                conn.commit()
                return {"USD": legacy_val, "INR": 0.0}
            return {"USD": 0.0, "INR": 0.0}

    def save_cash_balances(self, balances: dict):
        """Persists separate currency cash balances and syncs legacy USD table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for curr, bal in balances.items():
                if bal is not None:
                    cursor.execute(
                        "INSERT OR REPLACE INTO portfolio_cash_balances (currency, balance) VALUES (?, ?)",
                        (str(curr).upper(), float(bal))
                    )
            usd_bal = balances.get("USD")
            if usd_bal is not None:
                cursor.execute(
                    "INSERT OR REPLACE INTO portfolio_cash (id, cash_balance) VALUES (1, ?)",
                    (float(usd_bal),)
                )
            conn.commit()

    def log_fx_conversion(
        self,
        from_currency: str,
        to_currency: str,
        from_amount: float,
        to_amount: float,
        rate: float,
        source: str,
        is_live: bool,
        observation_time: Optional[str] = None,
        notes: Optional[str] = None
    ) -> int:
        """Logs an auditable currency conversion record."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO fx_conversions 
                (timestamp, from_currency, to_currency, from_amount, to_amount, rate, source, is_live, observation_time, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_iso,
                    str(from_currency).upper(),
                    str(to_currency).upper(),
                    float(from_amount),
                    float(to_amount),
                    float(rate),
                    str(source),
                    bool(is_live),
                    str(observation_time) if observation_time else None,
                    str(notes) if notes else None
                )
            )
            conn.commit()
            return cursor.lastrowid

    def get_fx_conversions(self, limit: int = 50) -> list:
        """Fetches history of FX conversions."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, timestamp, from_currency, to_currency, from_amount, to_amount, rate, source, is_live, observation_time, notes
                FROM fx_conversions
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,)
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "timestamp": r[1],
                    "from_currency": r[2],
                    "to_currency": r[3],
                    "from_amount": r[4],
                    "to_amount": r[5],
                    "rate": r[6],
                    "source": r[7],
                    "is_live": bool(r[8]),
                    "observation_time": r[9],
                    "notes": r[10]
                }
                for r in rows
            ]

    def get_universe_selection(self) -> Optional[list]:
        """Fetches persisted list of 10 instrument IDs if configured."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT selected_ids FROM universe_selection WHERE id = 1")
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    data = json.loads(row[0])
                    if isinstance(data, list):
                        return data
                except Exception:
                    return None
            return None

    def save_universe_selection(self, selected_ids: list):
        """Persists the 10 selected instrument IDs."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO universe_selection (id, selected_ids, updated_at)
                VALUES (1, ?, ?)
                """,
                (json.dumps(list(selected_ids)), now_iso)
            )
            conn.commit()

    def save_target_weights_history(self, scan_time: str, target_weights: dict):
        """Saves constituent target weights for a given scan timestamp."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for ticker, weight in target_weights.items():
                if weight is not None:
                    cursor.execute(
                        """
                        INSERT INTO target_weight_history (scan_time, ticker, target_weight)
                        VALUES (?, ?, ?)
                        """,
                        (scan_time, ticker, float(weight))
                    )
            conn.commit()

    def get_target_weights_history(self) -> list:
        """Fetches full target weights history ordered by scan_time ascending."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT scan_time, ticker, target_weight
                FROM target_weight_history
                ORDER BY scan_time ASC, ticker ASC
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "scan_time": r[0],
                    "ticker": r[1],
                    "target_weight": r[2]
                }
                for r in rows
            ]

    def get_latest_target_weights(self) -> dict:
        """Fetches target weights from the most recent scan if available."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT ticker, target_weight FROM target_weight_history
                WHERE scan_time = (SELECT MAX(scan_time) FROM target_weight_history)
                """
            )
            rows = cursor.fetchall()
            if rows:
                return {r[0]: float(r[1]) for r in rows}
            return {}

    def save_latest_orders(self, orders_df: pd.DataFrame):
        """Persists the latest rebalance orders table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM latest_orders")
            if orders_df is None or orders_df.empty:
                conn.commit()
                return
            for _, row in orders_df.iterrows():
                cursor.execute(
                    """
                    INSERT INTO latest_orders 
                    (ticker, price, prev_weight, new_weight, delta, current_shares, pre_shares, target_shares, post_shares, action, order_qty, signed_qty, trade_value)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(row.get("Ticker", "")),
                        float(row.get("Price ($)", 0.0) or 0.0) if row.get("Price ($)") is not None and not pd.isna(row.get("Price ($)")) else None,
                        str(row.get("Prev Weight", "10.00%")),
                        str(row.get("New Weight", "10.00%")),
                        str(row.get("Delta", "0.00%")),
                        float(row.get("Current Shares", 0.0) or 0.0) if row.get("Current Shares") is not None and not pd.isna(row.get("Current Shares")) else None,
                        float(row.get("Pre Shares", 0.0) or 0.0) if row.get("Pre Shares") is not None and not pd.isna(row.get("Pre Shares")) else None,
                        float(row.get("Target Shares", 0.0) or 0.0) if row.get("Target Shares") is not None and not pd.isna(row.get("Target Shares")) else None,
                        float(row.get("Post Shares", 0.0) or 0.0) if row.get("Post Shares") is not None and not pd.isna(row.get("Post Shares")) else None,
                        str(row.get("Action", "HOLD")),
                        float(row.get("Order Qty", 0.0) or 0.0) if row.get("Order Qty") is not None and not pd.isna(row.get("Order Qty")) else 0.0,
                        float(row.get("Signed Qty", 0.0) or 0.0) if row.get("Signed Qty") is not None and not pd.isna(row.get("Signed Qty")) else 0.0,
                        float(row.get("Trade Value ($)", 0.0) or 0.0) if row.get("Trade Value ($)") is not None and not pd.isna(row.get("Trade Value ($)")) else 0.0,
                    )
                )
            conn.commit()

    def get_latest_orders(self) -> pd.DataFrame:
        """Fetches the latest persisted rebalance orders DataFrame."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT ticker, price, prev_weight, new_weight, delta, current_shares, pre_shares, target_shares, post_shares, action, order_qty, signed_qty, trade_value
                FROM latest_orders
                """
            )
            rows = cursor.fetchall()
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame(
                [
                    {
                        "Ticker": r[0],
                        "Price ($)": r[1],
                        "Prev Weight": r[2],
                        "New Weight": r[3],
                        "Delta": r[4],
                        "Current Shares": r[5],
                        "Pre Shares": r[6],
                        "Target Shares": r[7],
                        "Post Shares": r[8],
                        "Action": r[9],
                        "Order Qty": r[10],
                        "Signed Qty": r[11],
                        "Trade Value ($)": r[12]
                    }
                    for r in rows
                ]
            )
            return df

    def clear_scan_runtime_state(self):
        """
        Clears transient scan results (active signals, latest simulated orders, target weight history, 
        and transient session deduplication cache) while strictly preserving user configuration 
        and financial ledger records (holdings, cash balances, cumulative fees, and FX conversions).
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM risk_signals")
            cursor.execute("DELETE FROM latest_orders")
            cursor.execute("DELETE FROM target_weight_history")
            cursor.execute("DELETE FROM documents")
            conn.commit()

    def clear_runtime_data(self):
        """Clears all runtime signals and documents, preserving configuration."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM risk_signals")
            cursor.execute("DELETE FROM documents")
            cursor.execute("DELETE FROM holdings")
            cursor.execute("DELETE FROM target_weight_history")
            cursor.execute("DELETE FROM latest_orders")
            cursor.execute("DELETE FROM portfolio_cash")
            conn.commit()

    def get_recent_documents(self, hours: int = 24) -> list:
        """Fetches documents from the last N hours for deduplication."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # In SQLite, datetime('now', '-24 hours') works, but we store ISO8601 strings.
            # We can use datetime('now', '-24 hours') and compare against published_at directly if they are ISO8601.
            cursor.execute(
                """
                SELECT document_hash, canonical_group_id, normalized_headline, resolved_entities, published_at
                FROM documents 
                WHERE published_at >= datetime('now', ?) OR created_at >= datetime('now', ?)
                ORDER BY published_at DESC
                """, (f'-{hours} hours', f'-{hours} hours')
            )
            rows = cursor.fetchall()
            return [
                {
                    "document_hash": r[0],
                    "canonical_group_id": r[1],
                    "normalized_headline": r[2],
                    "resolved_entities": r[3],
                    "published_at": r[4]
                } for r in rows
            ]

    def log_document(self, doc_data: dict):
        """Saves the document metadata and duplication status."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO documents 
                (document_hash, canonical_group_id, headline, normalized_headline, source, published_at, is_duplicate, duplicate_reason, resolved_entities, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_data["document_hash"],
                    doc_data["canonical_group_id"],
                    doc_data["headline"],
                    doc_data["normalized_headline"],
                    doc_data["source"],
                    doc_data["published_at"],
                    doc_data["is_duplicate"],
                    doc_data["duplicate_reason"],
                    ",".join(doc_data["resolved_entities"]),
                    now
                )
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
        document_hash: str = None,
    ):
        """Saves the final Risk Engine output to the database."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO risk_signals 
                (article_hash, ticker, headline, source, event_type, sentiment, impact, confidence, evidence, model_version, published_at, created_at, document_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    document_hash,
                ),
            )
            conn.commit()
    def get_signal(self, article_hash: str) -> dict:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT ticker, event_type, sentiment, impact, confidence, evidence, model_version, headline, source, published_at FROM risk_signals WHERE article_hash = ?", (article_hash,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "entity": row[0],
                    "event_classification": row[1],
                    "sentiment_score": row[2],
                    "impact_score": row[3],
                    "confidence": row[4],
                    "evidence_span": row[5],
                    "model_version": row[6],
                    "headline": row[7],
                    "source": row[8],
                    "published_at": row[9],
                    "article_hash": article_hash
                }
            return None

    def get_all_signals(self) -> list:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT ticker, event_type, sentiment, impact, confidence, evidence, model_version, headline, source, published_at, article_hash FROM risk_signals ORDER BY published_at ASC, article_hash ASC"
            )
            rows = cursor.fetchall()
            signals = []
            for row in rows:
                signals.append({
                    "entity": row[0],
                    "ticker": row[0],
                    "event_classification": row[1],
                    "sentiment_score": row[2],
                    "impact_score": row[3],
                    "confidence": row[4],
                    "evidence_span": row[5],
                    "model_version": row[6],
                    "headline": row[7],
                    "source": row[8],
                    "published_at": row[9],
                    "article_hash": row[10]
                })
            return signals
