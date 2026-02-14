"""SQLite storage interface for Augustus."""

import sqlite3
import logging
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
        self.conn.commit()
        logger.debug("Migrations complete")

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
