"""SQLite storage interface for Augustus."""

import sqlite3
import logging
import sys
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SQLiteStore:
    """SQLite database interface with WAL mode and automatic schema initialization.

    A threading lock serializes all DB operations so that the single
    connection can be safely shared across the asyncio thread-pool
    executor (API handlers) and the orchestrator loop.
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize SQLite connection and schema.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            isolation_level=None,  # Autocommit mode
            timeout=10,  # Wait up to 10s if DB is locked
        )
        self.conn.row_factory = sqlite3.Row
        self._init_db()
        logger.info(f"SQLite store initialized at {db_path}")

    def _init_db(self) -> None:
        """Execute schema DDL, run migrations, and enable WAL mode."""
        # In a PyInstaller frozen bundle, data files are extracted to
        # sys._MEIPASS.  In development, __file__ resolves normally.
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            schema_path = Path(sys._MEIPASS) / "augustus" / "db" / "schema.sql"
        else:
            schema_path = Path(__file__).parent / "schema.sql"
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        with open(schema_path, encoding="utf-8") as f:
            schema = f.read()

        self.conn.executescript(schema)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.commit()
        self._run_migrations()
        logger.debug("Database schema initialized")

    def _run_migrations(self) -> None:
        """Run schema migrations for existing databases.

        Each migration is idempotent — safe to run multiple times.
        SQLite doesn't support IF NOT EXISTS for ALTER TABLE,
        so we catch errors for already-existing columns.
        """
        migrations = [
            # v0.2.1: Add reviewed_at and reviewed_by to flags table
            "ALTER TABLE flags ADD COLUMN reviewed_at TEXT DEFAULT ''",
            "ALTER TABLE flags ADD COLUMN reviewed_by TEXT DEFAULT ''",
            # v0.9.1: Store proposed basin config with tier proposals
            "ALTER TABLE tier_proposals ADD COLUMN proposed_config_json TEXT DEFAULT ''",
        ]
        for sql in migrations:
            try:
                self.conn.execute(sql)
            except Exception:
                # Column already exists or other expected error — skip
                pass

        # v0.6.2: Remove ALL foreign keys from usage table so usage records
        # survive both agent and session deletion (billing data preservation).
        # SQLite can't ALTER foreign keys, so we recreate the table if FKs remain.
        self._migrate_usage_table_drop_cascades()

        self.conn.commit()
        logger.debug("Migrations complete")

    def _migrate_usage_table_drop_cascades(self) -> None:
        """Recreate usage table without any CASCADE foreign keys.

        Usage records must survive both agent AND session deletion so billing
        data is always preserved.  The original schema had CASCADE on both
        session_id→sessions and agent_id→agents.  An earlier migration removed
        the agent_id CASCADE but kept session_id CASCADE — which still caused
        usage records to vanish when sessions were cascade-deleted, and also
        caused hard-delete to fail (UPDATE session_id='' violates FK).

        This migration removes ALL foreign keys from the usage table.
        It is idempotent — runs only if any REFERENCES clause remains.
        """
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='usage'"
        ).fetchone()
        if not row:
            return  # Table doesn't exist yet (schema.sql will create it correctly)

        create_sql = row[0] if row else ""
        if "REFERENCES" not in create_sql:
            return  # Already fully migrated — no FKs remain

        logger.info("Migrating usage table: removing all foreign key constraints")
        try:
            self.conn.executescript("""
                BEGIN TRANSACTION;

                CREATE TABLE usage_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL DEFAULT '',
                    agent_id TEXT NOT NULL DEFAULT '',
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    estimated_cost REAL DEFAULT 0.0,
                    model TEXT DEFAULT '',
                    timestamp TEXT DEFAULT (datetime('now'))
                );

                INSERT INTO usage_new (id, session_id, agent_id, tokens_in, tokens_out, estimated_cost, model, timestamp)
                    SELECT id, session_id, agent_id, tokens_in, tokens_out, estimated_cost, model, timestamp FROM usage;

                DROP TABLE usage;
                ALTER TABLE usage_new RENAME TO usage;

                CREATE INDEX IF NOT EXISTS idx_usage_agent ON usage(agent_id);
                CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage(timestamp);
                CREATE INDEX IF NOT EXISTS idx_usage_session ON usage(session_id);

                COMMIT;
            """)
            logger.info("Usage table migration complete — all foreign keys removed")
        except Exception as e:
            logger.error("Failed to migrate usage table: %s", e)
            try:
                self.conn.execute("ROLLBACK")
            except Exception:
                pass

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        """Execute a single SQL statement.

        Args:
            sql: SQL statement
            params: Query parameters

        Returns:
            Cursor with results
        """
        with self._lock:
            return self.conn.execute(sql, params)

    def executemany(
        self, sql: str, params_list: list[tuple[Any, ...]]
    ) -> sqlite3.Cursor:
        """Execute a SQL statement multiple times with different parameters.

        Args:
            sql: SQL statement
            params_list: List of parameter tuples

        Returns:
            Cursor with results
        """
        with self._lock:
            return self.conn.executemany(sql, params_list)

    def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        """Execute query and fetch one row as a dictionary.

        Args:
            sql: SQL query
            params: Query parameters

        Returns:
            Row as dictionary or None if no results
        """
        with self._lock:
            cursor = self.conn.execute(sql, params)
            row = cursor.fetchone()
            return dict(row) if row else None

    def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Execute query and fetch all rows as dictionaries.

        Args:
            sql: SQL query
            params: Query parameters

        Returns:
            List of rows as dictionaries
        """
        with self._lock:
            cursor = self.conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def commit(self) -> None:
        """Explicitly commit current transaction."""
        with self._lock:
            self.conn.commit()

    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            self.conn.close()
        logger.info("SQLite store closed")
