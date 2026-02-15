"""SQLite storage interface for Augustus."""

import sqlite3
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SQLiteStore:
    """SQLite database interface with WAL mode and automatic schema initialization."""

    def __init__(self, db_path: Path) -> None:
        """Initialize SQLite connection and schema.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            isolation_level=None,  # Autocommit mode
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
        ]
        for sql in migrations:
            try:
                self.conn.execute(sql)
            except Exception:
                # Column already exists or other expected error — skip
                pass

        # v0.6.1: Remove CASCADE on usage.agent_id FK so usage records survive agent deletion.
        # SQLite can't ALTER foreign keys, so we recreate the table if the old FK exists.
        self._migrate_usage_table_drop_agent_cascade()

        self.conn.commit()
        logger.debug("Migrations complete")

    def _migrate_usage_table_drop_agent_cascade(self) -> None:
        """Recreate usage table without CASCADE on agent_id FK.

        Usage records must survive agent deletion so billing data is preserved.
        This is idempotent — if the table already lacks the CASCADE, it's a no-op.
        """
        # Check if usage table has the old CASCADE FK by inspecting the SQL used to create it
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='usage'"
        ).fetchone()
        if not row:
            return  # Table doesn't exist yet (schema.sql will create it correctly)

        create_sql = row[0] if row else ""
        if "agents(agent_id) ON DELETE CASCADE" not in create_sql:
            return  # Already migrated or never had CASCADE

        logger.info("Migrating usage table: removing CASCADE on agent_id FK")
        try:
            self.conn.executescript("""
                BEGIN TRANSACTION;

                CREATE TABLE usage_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    estimated_cost REAL DEFAULT 0.0,
                    model TEXT DEFAULT '',
                    timestamp TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
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
            logger.info("Usage table migration complete — CASCADE on agent_id FK removed")
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
        return self.conn.executemany(sql, params_list)

    def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        """Execute query and fetch one row as a dictionary.

        Args:
            sql: SQL query
            params: Query parameters

        Returns:
            Row as dictionary or None if no results
        """
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
        cursor = self.conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def commit(self) -> None:
        """Explicitly commit current transaction."""
        self.conn.commit()

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()
        logger.info("SQLite store closed")
