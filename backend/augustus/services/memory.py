"""Memory Service — central data layer for Augustus.

All session data, trajectories, evaluations, annotations, and usage records
flow through this service. Combines SQLite for structured/queryable data
and ChromaDB for vector-indexed semantic search.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

from augustus.db.chroma_store import ChromaStore
from augustus.db.sqlite_store import SQLiteStore
from augustus.utils import flatten_transcript, utcnow_iso, enum_val
from augustus.models import (
    ActivityEvent,
    AgentConfig,
    AgentStatus,
    Annotation,
    BasinClass,
    BasinConfig,
    BasinDefinition,
    BasinModification,
    BasinSnapshot,
    CoActivationCharacter,
    CoActivationEntry,
    EvaluatorOutput,
    EvaluatorPrompt,
    FlagRecord,
    FlagType,
    ProposalStatus,
    ProposalType,
    SearchResult,
    SessionRecord,
    TierLevel,
    TierProposal,
    TierSettings,
    UsageRecord,
)

logger = logging.getLogger(__name__)


class MemoryService:
    """Central data layer combining SQLite and ChromaDB storage.

    All data is namespaced by agent_id. Cross-agent queries are provided
    only for Dashboard and Desktop interfaces.
    """

    def __init__(self, sqlite_store: SQLiteStore, chroma_store: ChromaStore) -> None:
        """Initialize with injected storage backends.

        Args:
            sqlite_store: SQLite database interface.
            chroma_store: ChromaDB vector storage interface.
        """
        self.sqlite = sqlite_store
        self.chroma = chroma_store
        logger.info("MemoryService initialized")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_sync(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a synchronous function in the default executor."""
        loop = asyncio.get_event_loop()
        if kwargs:
            return loop.run_in_executor(None, partial(func, *args, **kwargs))
        return loop.run_in_executor(None, func, *args)

    async def refresh_chroma(self) -> None:
        """Re-open ChromaDB to pick up data written by other processes."""
        await self._run_sync(self.chroma.refresh)

    @staticmethod
    def _now() -> str:
        """Return current UTC timestamp as ISO string."""
        return utcnow_iso()

    # ------------------------------------------------------------------
    # Event bus (cross-process real-time notifications)
    # ------------------------------------------------------------------

    async def emit_event(self, event_type: str, agent_id: str = "", payload: dict | None = None) -> None:
        """Write an event to the event_bus table for SSE consumers."""
        await self._run_sync(
            self.sqlite.execute,
            "INSERT INTO event_bus (event_type, agent_id, payload, created_at) VALUES (?, ?, ?, ?)",
            (event_type, agent_id, json.dumps(payload or {}), self._now()),
        )

    async def poll_events(self, after_id: int = 0) -> list[dict]:
        """Fetch events with id > after_id."""
        rows = await self._run_sync(
            self.sqlite.fetch_all,
            "SELECT id, event_type, agent_id, payload, created_at FROM event_bus WHERE id > ? ORDER BY id",
            (after_id,),
        )
        return rows

    async def prune_events(self, keep_seconds: int = 300) -> None:
        """Delete events older than keep_seconds."""
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=keep_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        await self._run_sync(
            self.sqlite.execute,
            "DELETE FROM event_bus WHERE created_at < ?",
            (cutoff,),
        )

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def store_session_record(self, record: SessionRecord) -> None:
        """Store a complete session record in SQLite and index transcript in ChromaDB."""
        transcript_json = json.dumps(record.transcript)
        close_report_json = json.dumps(record.close_report) if record.close_report else "{}"

        sql = """
            INSERT OR REPLACE INTO sessions
                (session_id, agent_id, start_time, end_time, turn_count,
                 model, temperature, transcript_json, close_report_json,
                 yaml_raw, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            record.session_id,
            record.agent_id,
            record.start_time,
            record.end_time,
            record.turn_count,
            record.model,
            record.temperature,
            transcript_json,
            close_report_json,
            record.yaml_raw,
            record.status,
        )
        await self._run_sync(self.sqlite.execute, sql, params)

        # Store basin snapshots if included
        if record.basin_snapshots:
            await self.store_basin_snapshots(
                record.agent_id, record.session_id, record.basin_snapshots
            )

        # Index transcript in ChromaDB for semantic search
        if record.transcript:
            transcript_text = flatten_transcript(record.transcript)
            if transcript_text.strip():
                await self.store_session_transcript(
                    record.agent_id, record.session_id, transcript_text
                )

        # Index close report in ChromaDB
        if record.close_report:
            report_text = json.dumps(record.close_report, indent=2)
            if report_text.strip() and report_text != "{}":
                await self.store_close_report(
                    record.agent_id, record.session_id, report_text
                )

        logger.info(
            "Stored session record %s for agent %s",
            record.session_id,
            record.agent_id,
        )

    async def get_session(
        self, agent_id: str, session_id: str
    ) -> SessionRecord | None:
        """Retrieve a single session record by agent and session ID."""
        sql = """
            SELECT * FROM sessions
            WHERE session_id = ? AND agent_id = ?
        """
        row = await self._run_sync(self.sqlite.fetch_one, sql, (session_id, agent_id))
        if not row:
            return None
        return self._row_to_session_record(row)

    async def list_sessions(
        self, agent_id: str, limit: int = 50, offset: int = 0
    ) -> list[SessionRecord]:
        """List sessions for an agent with pagination, newest first."""
        sql = """
            SELECT * FROM sessions
            WHERE agent_id = ?
            ORDER BY start_time DESC
            LIMIT ? OFFSET ?
        """
        rows = await self._run_sync(
            self.sqlite.fetch_all, sql, (agent_id, limit, offset)
        )
        return [self._row_to_session_record(r) for r in rows]

    async def count_sessions(self, agent_id: str) -> int:
        """Return the number of sessions for an agent."""
        sql = "SELECT COUNT(*) AS cnt FROM sessions WHERE agent_id = ?"
        rows = await self._run_sync(self.sqlite.fetch_all, sql, (agent_id,))
        return rows[0]["cnt"] if rows else 0

    async def get_previous_session(
        self, agent_id: str, session_id: str
    ) -> SessionRecord | None:
        """Get the session immediately before the given one (by start_time)."""
        sql = """
            SELECT * FROM sessions
            WHERE agent_id = ? AND start_time < (
                SELECT start_time FROM sessions
                WHERE session_id = ? AND agent_id = ?
            )
            ORDER BY start_time DESC
            LIMIT 1
        """
        row = await self._run_sync(
            self.sqlite.fetch_one, sql, (agent_id, session_id, agent_id)
        )
        if not row:
            return None
        return self._row_to_session_record(row)

    def _row_to_session_record(self, row: dict[str, Any]) -> SessionRecord:
        """Convert a database row to a SessionRecord dataclass."""
        transcript = []
        if row.get("transcript_json"):
            try:
                transcript = json.loads(row["transcript_json"])
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Failed to parse transcript_json for session %s",
                    row.get("session_id"),
                )

        close_report = None
        if row.get("close_report_json"):
            try:
                parsed = json.loads(row["close_report_json"])
                if parsed and parsed != {}:
                    close_report = parsed
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Failed to parse close_report_json for session %s",
                    row.get("session_id"),
                )

        return SessionRecord(
            session_id=row["session_id"],
            agent_id=row["agent_id"],
            start_time=row.get("start_time", ""),
            end_time=row.get("end_time", ""),
            turn_count=row.get("turn_count", 0),
            model=row.get("model", ""),
            temperature=row.get("temperature", 1.0),
            transcript=transcript,
            close_report=close_report,
            status=row.get("status", "complete"),
            yaml_raw=row.get("yaml_raw", ""),
        )

    # ------------------------------------------------------------------
    # Basin trajectories
    # ------------------------------------------------------------------

    async def store_basin_snapshots(
        self, agent_id: str, session_id: str, snapshots: list[BasinSnapshot]
    ) -> None:
        """Batch insert basin snapshots for a session."""
        if not snapshots:
            return

        sql = """
            INSERT INTO basin_snapshots
                (session_id, agent_id, basin_name, alpha_start, alpha_end,
                 delta, relevance_score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params_list = [
            (
                session_id,
                agent_id,
                s.basin_name,
                s.alpha_start,
                s.alpha_end,
                s.delta,
                s.relevance_score,
            )
            for s in snapshots
        ]
        await self._run_sync(self.sqlite.executemany, sql, params_list)
        logger.debug(
            "Stored %d basin snapshots for session %s", len(snapshots), session_id
        )

    async def get_session_basin_snapshots(
        self, agent_id: str, session_id: str
    ) -> list[BasinSnapshot]:
        """Get all basin snapshots for a specific session."""
        sql = """
            SELECT * FROM basin_snapshots
            WHERE agent_id = ? AND session_id = ?
            ORDER BY basin_name
        """
        rows = await self._run_sync(
            self.sqlite.fetch_all, sql, (agent_id, session_id)
        )
        return [self._row_to_basin_snapshot(r) for r in rows]

    async def get_basin_trajectory(
        self, agent_id: str, basin_name: str, n_sessions: int = 20
    ) -> list[BasinSnapshot]:
        """Get alpha trajectory for a single basin, ordered by session time."""
        sql = """
            SELECT bs.* FROM basin_snapshots bs
            INNER JOIN sessions s ON bs.session_id = s.session_id
            WHERE bs.agent_id = ? AND bs.basin_name = ?
            ORDER BY s.start_time DESC
            LIMIT ?
        """
        rows = await self._run_sync(
            self.sqlite.fetch_all, sql, (agent_id, basin_name, n_sessions)
        )
        # Return in chronological order (oldest first)
        rows.reverse()
        return [self._row_to_basin_snapshot(r) for r in rows]

    async def get_all_trajectories(
        self, agent_id: str, n_sessions: int = 20
    ) -> dict[str, list[BasinSnapshot]]:
        """Get trajectories for all basins of an agent, grouped by basin name."""
        # First, get the most recent n_sessions session IDs
        session_sql = """
            SELECT session_id FROM sessions
            WHERE agent_id = ?
            ORDER BY start_time DESC
            LIMIT ?
        """
        session_rows = await self._run_sync(
            self.sqlite.fetch_all, session_sql, (agent_id, n_sessions)
        )
        if not session_rows:
            return {}

        session_ids = [r["session_id"] for r in session_rows]
        placeholders = ", ".join("?" for _ in session_ids)

        sql = f"""
            SELECT bs.* FROM basin_snapshots bs
            INNER JOIN sessions s ON bs.session_id = s.session_id
            WHERE bs.agent_id = ? AND bs.session_id IN ({placeholders})
            ORDER BY s.start_time ASC
        """
        params = (agent_id, *session_ids)
        rows = await self._run_sync(self.sqlite.fetch_all, sql, params)

        trajectories: dict[str, list[BasinSnapshot]] = {}
        for row in rows:
            snapshot = self._row_to_basin_snapshot(row)
            trajectories.setdefault(snapshot.basin_name, []).append(snapshot)
        return trajectories

    async def get_current_basins(self, agent_id: str) -> list[BasinConfig]:
        """Get the current active (non-deprecated) basin configuration for an agent.

        For agents on basin_source='database', basin_definitions is canonical.
        Any basin present in basin_current but missing from basin_definitions
        (e.g. added post-creation via proposals or YAML update) is auto-migrated
        into basin_definitions so it appears in the UI.
        """
        source = await self.get_agent_basin_source(agent_id)
        if source == "database":
            defs = await self.get_basin_definitions(agent_id, include_deprecated=False)
            def_names = {d.name for d in defs}

            # Check basin_current for any non-deprecated basins not yet in basin_definitions
            sql = """
                SELECT * FROM basin_current
                WHERE agent_id = ? AND deprecated = 0
                ORDER BY basin_name
            """
            current_rows = await self._run_sync(self.sqlite.fetch_all, sql, (agent_id,))
            missing = [self._row_to_basin_config(r) for r in current_rows if r["basin_name"] not in def_names]

            if missing:
                # Auto-migrate missing basins into basin_definitions
                for basin in missing:
                    await self.insert_basin_definition(
                        agent_id=agent_id,
                        name=basin.name,
                        basin_class=enum_val(basin.basin_class),
                        alpha=basin.alpha,
                        lambda_decay=basin.lambda_,
                        eta=basin.eta,
                        tier=basin.tier.value if hasattr(basin.tier, "value") else int(basin.tier),
                        created_by="migration",
                        rationale="Auto-migrated: basin added post-creation",
                    )
                    logger.info("Auto-migrated basin '%s' for agent %s into basin_definitions", basin.name, agent_id)
                # Reload definitions after migration
                defs = await self.get_basin_definitions(agent_id, include_deprecated=False)

            if defs:
                return [d.to_basin_config() for d in defs]

        # Fallback: basin_current (for yaml-mode agents or pre-migration)
        sql = """
            SELECT * FROM basin_current
            WHERE agent_id = ? AND deprecated = 0
            ORDER BY basin_name
        """
        rows = await self._run_sync(self.sqlite.fetch_all, sql, (agent_id,))
        return [self._row_to_basin_config(r) for r in rows]

    async def _get_all_current_basins(self, agent_id: str) -> list[BasinConfig]:
        """Get all basins including deprecated ones (for migration only)."""
        sql = """
            SELECT * FROM basin_current
            WHERE agent_id = ?
            ORDER BY basin_name
        """
        rows = await self._run_sync(self.sqlite.fetch_all, sql, (agent_id,))
        return [self._row_to_basin_config(r) for r in rows]

    async def update_current_basins(
        self, agent_id: str, basins: list[BasinConfig]
    ) -> None:
        """Upsert the current basin state for an agent."""
        if not basins:
            return

        sql = """
            INSERT OR REPLACE INTO basin_current
                (agent_id, basin_name, basin_class, alpha, lambda, eta, tier)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params_list = [
            (
                agent_id,
                b.name,
                enum_val(b.basin_class),
                b.alpha,
                b.lambda_,
                b.eta,
                b.tier.value if hasattr(b.tier, "value") else int(b.tier),
            )
            for b in basins
        ]
        await self._run_sync(self.sqlite.executemany, sql, params_list)
        logger.debug("Updated %d current basins for agent %s", len(basins), agent_id)

    @staticmethod
    def _row_to_basin_snapshot(row: dict[str, Any]) -> BasinSnapshot:
        """Convert a database row to a BasinSnapshot dataclass."""
        return BasinSnapshot(
            basin_name=row["basin_name"],
            alpha_start=row["alpha_start"],
            alpha_end=row["alpha_end"],
            delta=row["delta"],
            relevance_score=row.get("relevance_score", 0.0),
            session_id=row.get("session_id", ""),
        )

    @staticmethod
    def _row_to_basin_config(row: dict[str, Any]) -> BasinConfig:
        """Convert a database row to a BasinConfig dataclass."""
        basin_class_val = row.get("basin_class", "peripheral")
        try:
            basin_class = BasinClass(basin_class_val)
        except ValueError:
            basin_class = BasinClass.PERIPHERAL

        tier_val = row.get("tier", 3)
        try:
            tier = TierLevel(int(tier_val))
        except (ValueError, TypeError):
            tier = TierLevel.TIER_3

        return BasinConfig(
            name=row["basin_name"],
            basin_class=basin_class,
            alpha=row["alpha"],
            lambda_=row["lambda"],
            eta=row["eta"],
            tier=tier,
        )

    # ------------------------------------------------------------------
    # Basin Definitions (v0.9.5)
    # ------------------------------------------------------------------

    async def get_basin_definitions(
        self, agent_id: str, include_deprecated: bool = False
    ) -> list[BasinDefinition]:
        """Get all basin definitions for an agent."""
        if include_deprecated:
            sql = "SELECT * FROM basin_definitions WHERE agent_id = ? ORDER BY name"
            rows = await self._run_sync(self.sqlite.fetch_all, sql, (agent_id,))
        else:
            sql = "SELECT * FROM basin_definitions WHERE agent_id = ? AND deprecated = 0 ORDER BY name"
            rows = await self._run_sync(self.sqlite.fetch_all, sql, (agent_id,))
        return [self._row_to_basin_definition(r) for r in rows]

    async def get_basin_definition(
        self, agent_id: str, basin_name: str
    ) -> BasinDefinition | None:
        """Get a single basin definition by agent and name."""
        sql = "SELECT * FROM basin_definitions WHERE agent_id = ? AND name = ?"
        row = await self._run_sync(self.sqlite.fetch_one, sql, (agent_id, basin_name))
        return self._row_to_basin_definition(row) if row else None

    async def insert_basin_definition(
        self,
        agent_id: str,
        name: str,
        basin_class: str = "peripheral",
        alpha: float = 0.5,
        lambda_decay: float = 0.95,
        eta: float = 0.10,
        tier: int = 3,
        created_by: str = "import",
        rationale: str | None = None,
    ) -> BasinDefinition:
        """Insert a new basin definition and create an audit entry."""
        now = self._now()
        sql = """INSERT INTO basin_definitions
            (agent_id, name, basin_class, alpha, lambda, eta, tier,
             created_at, created_by, last_modified_at, last_modified_by, last_rationale)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        cursor = await self._run_sync(
            self.sqlite.execute, sql,
            (agent_id, name, basin_class, alpha, lambda_decay, eta, tier,
             now, created_by, now, created_by, rationale),
        )
        basin_id = cursor.lastrowid

        # Create audit entry
        new_vals = json.dumps({
            "basin_class": basin_class, "alpha": alpha, "lambda": lambda_decay,
            "eta": eta, "tier": tier,
        })
        await self._insert_basin_modification(
            basin_id=basin_id, agent_id=agent_id, session_id=None,
            modified_by=created_by, modification_type="create",
            previous_values=None, new_values=new_vals, rationale=rationale,
        )

        return await self.get_basin_definition(agent_id, name)

    async def update_basin_definition(
        self,
        agent_id: str,
        basin_name: str,
        modifications: dict,
        modified_by: str = "brain",
        rationale: str | None = None,
        session_id: str | None = None,
        override_lock: bool = False,
    ) -> BasinDefinition | None:
        """Update a basin definition with audit trail.

        Args:
            modifications: dict of field->value pairs. Valid keys:
                basin_class, alpha, lambda, eta, tier,
                locked_by_brain, alpha_floor, alpha_ceiling,
                deprecated, deprecated_at, deprecation_rationale
        """
        basin = await self.get_basin_definition(agent_id, basin_name)
        if not basin:
            return None

        if basin.locked_by_brain and not override_lock and modified_by != "brain":
            logger.warning(
                "Basin %s is locked by brain; rejecting modification by %s",
                basin_name, modified_by,
            )
            return None

        # Build previous values snapshot
        prev = {}
        allowed_cols = {
            "basin_class", "alpha", "lambda", "eta", "tier",
            "locked_by_brain", "alpha_floor", "alpha_ceiling",
            "deprecated", "deprecated_at", "deprecation_rationale",
        }

        set_clauses = []
        params: list[Any] = []
        for key, val in modifications.items():
            if key not in allowed_cols:
                continue
            # Map to current value for prev snapshot
            if key == "lambda":
                prev[key] = basin.lambda_
            elif key == "alpha":
                prev[key] = basin.alpha
            elif key == "eta":
                prev[key] = basin.eta
            elif key == "tier":
                prev[key] = basin.tier.value if hasattr(basin.tier, "value") else int(basin.tier)
            elif key == "basin_class":
                prev[key] = enum_val(basin.basin_class)
            elif key == "locked_by_brain":
                prev[key] = basin.locked_by_brain
            elif key == "alpha_floor":
                prev[key] = basin.alpha_floor
            elif key == "alpha_ceiling":
                prev[key] = basin.alpha_ceiling
            elif key == "deprecated":
                prev[key] = basin.deprecated
            else:
                prev[key] = getattr(basin, key, None)

            set_clauses.append(f"{key} = ?")
            params.append(val)

        if not set_clauses:
            return basin

        # Always update last_modified metadata
        now = self._now()
        set_clauses.extend([
            "last_modified_at = ?", "last_modified_by = ?", "last_rationale = ?",
        ])
        params.extend([now, modified_by, rationale])
        params.extend([agent_id, basin_name])

        sql = f"UPDATE basin_definitions SET {', '.join(set_clauses)} WHERE agent_id = ? AND name = ?"
        await self._run_sync(self.sqlite.execute, sql, tuple(params))

        # Determine modification type
        mod_type = "update"
        if "deprecated" in modifications and modifications["deprecated"]:
            mod_type = "deprecate"
        elif "deprecated" in modifications and not modifications["deprecated"]:
            mod_type = "undeprecate"
        elif "locked_by_brain" in modifications and modifications["locked_by_brain"]:
            mod_type = "lock"
        elif "locked_by_brain" in modifications and not modifications["locked_by_brain"]:
            mod_type = "unlock"
        elif "alpha_floor" in modifications or "alpha_ceiling" in modifications:
            mod_type = "set_bounds"

        await self._insert_basin_modification(
            basin_id=basin.id, agent_id=agent_id, session_id=session_id,
            modified_by=modified_by, modification_type=mod_type,
            previous_values=json.dumps(prev), new_values=json.dumps(modifications),
            rationale=rationale,
        )

        return await self.get_basin_definition(agent_id, basin_name)

    async def upsert_basin_definition(
        self,
        agent_id: str,
        name: str,
        params: dict,
        modified_by: str = "import",
        rationale: str | None = None,
    ) -> BasinDefinition:
        """Insert or update a basin definition. Used by YAML import with overwrite."""
        existing = await self.get_basin_definition(agent_id, name)
        if existing:
            return await self.update_basin_definition(
                agent_id, name, params, modified_by=modified_by,
                rationale=rationale, override_lock=True,
            )
        else:
            return await self.insert_basin_definition(
                agent_id=agent_id, name=name,
                basin_class=params.get("basin_class", params.get("class", "peripheral")),
                alpha=params.get("alpha", 0.5),
                lambda_decay=params.get("lambda", params.get("lambda_decay", 0.95)),
                eta=params.get("eta", 0.10),
                tier=params.get("tier", 3),
                created_by=modified_by, rationale=rationale,
            )

    async def get_basin_modifications(
        self,
        agent_id: str,
        basin_name: str | None = None,
        limit: int = 20,
    ) -> list[BasinModification]:
        """Get basin modification audit trail."""
        if basin_name:
            basin = await self.get_basin_definition(agent_id, basin_name)
            if not basin:
                return []
            sql = """SELECT * FROM basin_modifications
                     WHERE basin_id = ? ORDER BY created_at DESC LIMIT ?"""
            rows = await self._run_sync(
                self.sqlite.fetch_all, sql, (basin.id, limit)
            )
        else:
            sql = """SELECT * FROM basin_modifications
                     WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?"""
            rows = await self._run_sync(
                self.sqlite.fetch_all, sql, (agent_id, limit)
            )
        return [self._row_to_basin_modification(r) for r in rows]

    async def get_agent_basin_source(self, agent_id: str) -> str:
        """Get the basin_source for an agent ('yaml' or 'database')."""
        row = await self._run_sync(
            self.sqlite.fetch_one,
            "SELECT basin_source FROM agents WHERE agent_id = ?",
            (agent_id,),
        )
        return row["basin_source"] if row else "yaml"

    async def set_agent_basin_source(self, agent_id: str, source: str) -> None:
        """Set the basin_source for an agent."""
        await self._run_sync(
            self.sqlite.execute,
            "UPDATE agents SET basin_source = ? WHERE agent_id = ?",
            (source, agent_id),
        )

    async def ensure_basin_migration(self, agent_id: str) -> bool:
        """Lazily migrate an agent's basins from YAML/basin_current to basin_definitions.

        Returns True if migration was performed, False if already migrated.
        """
        source = await self.get_agent_basin_source(agent_id)
        if source == "database":
            return False

        # Get current basin state (including deprecated) — prefer basin_current, fall back to agent config
        current_basins = await self._get_all_current_basins(agent_id)
        if not current_basins:
            agent = await self.get_agent(agent_id)
            if agent:
                current_basins = agent.basins

        for basin in current_basins:
            # Check if already exists in basin_definitions (idempotent)
            existing = await self.get_basin_definition(agent_id, basin.name)
            if existing:
                continue

            await self.insert_basin_definition(
                agent_id=agent_id,
                name=basin.name,
                basin_class=enum_val(basin.basin_class),
                alpha=basin.alpha,
                lambda_decay=basin.lambda_,
                eta=basin.eta,
                tier=basin.tier.value if hasattr(basin.tier, "value") else int(basin.tier),
                created_by="migration",
                rationale="Automated migration from YAML-based configuration (v0.9.5 upgrade)",
            )

        # Also migrate deprecation status from basin_current
        rows = await self._run_sync(
            self.sqlite.fetch_all,
            "SELECT basin_name, deprecated, deprecated_at, deprecation_rationale FROM basin_current WHERE agent_id = ? AND deprecated = 1",
            (agent_id,),
        )
        for row in rows:
            await self.update_basin_definition(
                agent_id, row["basin_name"],
                {
                    "deprecated": 1,
                    "deprecated_at": row["deprecated_at"],
                    "deprecation_rationale": row["deprecation_rationale"],
                },
                modified_by="migration",
                rationale="Migrated deprecation status from basin_current",
                override_lock=True,
            )

        await self.set_agent_basin_source(agent_id, "database")
        logger.info("Migrated basins for agent %s to database", agent_id)
        return True

    async def _insert_basin_modification(
        self,
        basin_id: int,
        agent_id: str,
        session_id: str | None,
        modified_by: str,
        modification_type: str,
        previous_values: str | None,
        new_values: str,
        rationale: str | None,
    ) -> int:
        """Insert a basin modification audit entry."""
        sql = """INSERT INTO basin_modifications
            (basin_id, agent_id, session_id, modified_by, modification_type,
             previous_values, new_values, rationale)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
        return await self._run_sync(
            self.sqlite.execute, sql,
            (basin_id, agent_id, session_id, modified_by, modification_type,
             previous_values, new_values, rationale),
        )

    @staticmethod
    def _row_to_basin_definition(row: dict[str, Any]) -> BasinDefinition:
        """Convert a database row to a BasinDefinition."""
        basin_class_val = row.get("basin_class", "peripheral")
        try:
            basin_class = BasinClass(basin_class_val)
        except ValueError:
            basin_class = BasinClass.PERIPHERAL

        tier_val = row.get("tier", 3)
        try:
            tier = TierLevel(int(tier_val))
        except (ValueError, TypeError):
            tier = TierLevel.TIER_3

        return BasinDefinition(
            id=row["id"],
            agent_id=row["agent_id"],
            name=row["name"],
            basin_class=basin_class,
            alpha=row["alpha"],
            lambda_=row["lambda"],
            eta=row["eta"],
            tier=tier,
            locked_by_brain=bool(row["locked_by_brain"]),
            alpha_floor=row["alpha_floor"],
            alpha_ceiling=row["alpha_ceiling"],
            deprecated=bool(row["deprecated"]),
            deprecated_at=row["deprecated_at"],
            deprecation_rationale=row["deprecation_rationale"],
            created_at=row["created_at"],
            created_by=row["created_by"],
            last_modified_at=row["last_modified_at"],
            last_modified_by=row["last_modified_by"],
            last_rationale=row["last_rationale"],
        )

    @staticmethod
    def _row_to_basin_modification(row: dict[str, Any]) -> BasinModification:
        """Convert a database row to a BasinModification."""
        prev = row["previous_values"]
        new = row["new_values"]
        return BasinModification(
            id=row["id"],
            basin_id=row["basin_id"],
            agent_id=row["agent_id"],
            session_id=row["session_id"],
            modified_by=row["modified_by"],
            modification_type=row["modification_type"],
            previous_values=json.loads(prev) if prev else None,
            new_values=json.loads(new) if new else {},
            rationale=row["rationale"],
            created_at=row["created_at"],
        )

    # ------------------------------------------------------------------
    # Evaluator data
    # ------------------------------------------------------------------

    async def store_evaluator_output(
        self, session_id: str, output: EvaluatorOutput
    ) -> None:
        """Store evaluator output as JSON for a session."""
        output_dict = {
            "basin_relevance": output.basin_relevance,
            "basin_rationale": output.basin_rationale,
            "co_activation_characters": output.co_activation_characters,
            "constraint_erosion_flag": output.constraint_erosion_flag,
            "constraint_erosion_detail": output.constraint_erosion_detail,
            "assessment_divergence_flag": output.assessment_divergence_flag,
            "assessment_divergence_detail": output.assessment_divergence_detail,
            "emergent_observations": output.emergent_observations,
        }
        output_json = json.dumps(output_dict)
        prompt_version = output.evaluator_prompt_version or ""

        sql = """
            INSERT INTO evaluator_outputs (session_id, output_json, prompt_version)
            VALUES (?, ?, ?)
        """
        await self._run_sync(
            self.sqlite.execute, sql, (session_id, output_json, prompt_version)
        )
        logger.debug("Stored evaluator output for session %s", session_id)

    async def get_evaluator_output(
        self, session_id: str
    ) -> EvaluatorOutput | None:
        """Retrieve evaluator output for a session."""
        sql = """
            SELECT output_json, prompt_version FROM evaluator_outputs
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        """
        row = await self._run_sync(self.sqlite.fetch_one, sql, (session_id,))
        if not row:
            return None

        try:
            data = json.loads(row["output_json"])
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Failed to parse evaluator output for session %s", session_id
            )
            return None

        return EvaluatorOutput(
            basin_relevance=data.get("basin_relevance", {}),
            basin_rationale=data.get("basin_rationale", {}),
            co_activation_characters=data.get("co_activation_characters", {}),
            constraint_erosion_flag=data.get("constraint_erosion_flag", False),
            constraint_erosion_detail=data.get("constraint_erosion_detail"),
            assessment_divergence_flag=data.get("assessment_divergence_flag", False),
            assessment_divergence_detail=data.get("assessment_divergence_detail"),
            emergent_observations=data.get("emergent_observations", []),
            evaluator_prompt_version=row.get("prompt_version") or None,
        )

    async def get_evaluator_flags(
        self,
        agent_id: str,
        flag_type: str | None = None,
        reviewed: bool | None = None,
        limit: int = 50,
    ) -> list[FlagRecord]:
        """Get evaluator flags for an agent, optionally filtered."""
        conditions = ["agent_id = ?"]
        params: list[Any] = [agent_id]

        if flag_type is not None:
            conditions.append("flag_type = ?")
            params.append(flag_type)

        if reviewed is not None:
            conditions.append("reviewed = ?")
            params.append(1 if reviewed else 0)

        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT * FROM flags
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
        """
        params.append(limit)
        rows = await self._run_sync(
            self.sqlite.fetch_all, sql, tuple(params)
        )
        return [self._row_to_flag_record(r) for r in rows]

    async def store_flag(self, flag: FlagRecord) -> None:
        """Store an evaluator flag."""
        flag_type_val = (
            flag.flag_type.value
            if isinstance(flag.flag_type, FlagType)
            else flag.flag_type
        )
        created_at = flag.created_at or self._now()

        sql = """
            INSERT OR REPLACE INTO flags
                (flag_id, agent_id, session_id, flag_type, severity,
                 detail, reviewed, review_note, reviewed_at, reviewed_by,
                 created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            flag.flag_id,
            flag.agent_id,
            flag.session_id,
            flag_type_val,
            flag.severity,
            flag.detail,
            1 if flag.reviewed else 0,
            flag.review_note or "",
            flag.reviewed_at or "",
            flag.reviewed_by or "",
            created_at,
        )
        await self._run_sync(self.sqlite.execute, sql, params)
        logger.debug("Stored flag %s for agent %s", flag.flag_id, flag.agent_id)

    async def update_flag_review(
        self,
        flag_id: str,
        reviewed: bool,
        note: str | None = None,
        reviewed_by: str = "human",
    ) -> None:
        """Mark a flag as reviewed with an optional note and timestamp."""
        reviewed_at = self._now() if reviewed else ""
        sql = """
            UPDATE flags
            SET reviewed = ?, review_note = ?, reviewed_at = ?, reviewed_by = ?
            WHERE flag_id = ?
        """
        await self._run_sync(
            self.sqlite.execute,
            sql,
            (1 if reviewed else 0, note or "", reviewed_at, reviewed_by, flag_id),
        )
        logger.debug("Updated flag review %s: reviewed=%s", flag_id, reviewed)

    @staticmethod
    def _row_to_flag_record(row: dict[str, Any]) -> FlagRecord:
        """Convert a database row to a FlagRecord dataclass."""
        flag_type_val = row.get("flag_type", "emergent_observation")
        try:
            flag_type = FlagType(flag_type_val)
        except ValueError:
            flag_type = FlagType.EMERGENT_OBSERVATION

        return FlagRecord(
            flag_id=row["flag_id"],
            agent_id=row["agent_id"],
            session_id=row.get("session_id", ""),
            flag_type=flag_type,
            severity=row.get("severity", "info"),
            detail=row.get("detail", ""),
            reviewed=bool(row.get("reviewed", 0)),
            review_note=row.get("review_note") or None,
            reviewed_at=row.get("reviewed_at", ""),
            reviewed_by=row.get("reviewed_by", ""),
            resolution=row.get("resolution", ""),
            resolution_notes=row.get("resolution_notes", ""),
            created_at=row.get("created_at", ""),
        )

    # ------------------------------------------------------------------
    # Evaluator prompts
    # ------------------------------------------------------------------

    async def store_evaluator_prompt(self, prompt: EvaluatorPrompt) -> None:
        """Store a new evaluator prompt version."""
        created_at = prompt.created_at or self._now()
        sql = """
            INSERT OR REPLACE INTO evaluator_prompts
                (version_id, prompt_text, change_rationale, created_at, is_active)
            VALUES (?, ?, ?, ?, ?)
        """
        params = (
            prompt.version_id,
            prompt.prompt_text,
            prompt.change_rationale,
            created_at,
            1 if prompt.is_active else 0,
        )
        await self._run_sync(self.sqlite.execute, sql, params)
        logger.debug("Stored evaluator prompt version %s", prompt.version_id)

    async def get_evaluator_prompt(
        self, version: str
    ) -> EvaluatorPrompt | None:
        """Retrieve a specific evaluator prompt version."""
        sql = """
            SELECT * FROM evaluator_prompts
            WHERE version_id = ?
        """
        row = await self._run_sync(self.sqlite.fetch_one, sql, (version,))
        if not row:
            return None
        return self._row_to_evaluator_prompt(row)

    async def get_active_evaluator_prompt(self) -> EvaluatorPrompt | None:
        """Get the currently active evaluator prompt."""
        sql = """
            SELECT * FROM evaluator_prompts
            WHERE is_active = 1
            ORDER BY created_at DESC
            LIMIT 1
        """
        row = await self._run_sync(self.sqlite.fetch_one, sql, ())
        if not row:
            return None
        return self._row_to_evaluator_prompt(row)

    async def list_evaluator_prompts(self) -> list[EvaluatorPrompt]:
        """List all evaluator prompt versions, newest first."""
        sql = """
            SELECT * FROM evaluator_prompts
            ORDER BY created_at DESC
        """
        rows = await self._run_sync(self.sqlite.fetch_all, sql, ())
        return [self._row_to_evaluator_prompt(r) for r in rows]

    async def set_active_evaluator_prompt(self, version_id: str) -> None:
        """Deactivate all prompts and activate the specified version."""
        # Deactivate all
        await self._run_sync(
            self.sqlite.execute,
            "UPDATE evaluator_prompts SET is_active = 0",
            (),
        )
        # Activate the chosen one
        await self._run_sync(
            self.sqlite.execute,
            "UPDATE evaluator_prompts SET is_active = 1 WHERE version_id = ?",
            (version_id,),
        )
        logger.info("Set active evaluator prompt to %s", version_id)

    @staticmethod
    def _row_to_evaluator_prompt(row: dict[str, Any]) -> EvaluatorPrompt:
        """Convert a database row to an EvaluatorPrompt dataclass."""
        return EvaluatorPrompt(
            version_id=row["version_id"],
            prompt_text=row["prompt_text"],
            change_rationale=row.get("change_rationale", ""),
            created_at=row.get("created_at", ""),
            is_active=bool(row.get("is_active", 0)),
        )

    # ------------------------------------------------------------------
    # Tier proposals
    # ------------------------------------------------------------------

    async def store_tier_proposal(self, proposal: TierProposal) -> None:
        """Store a tier modification proposal."""
        status_val = (
            proposal.status.value
            if isinstance(proposal.status, ProposalStatus)
            else proposal.status
        )
        proposal_type_val = (
            proposal.proposal_type.value
            if isinstance(proposal.proposal_type, ProposalType)
            else proposal.proposal_type
        )
        tier_val = (
            proposal.tier.value
            if isinstance(proposal.tier, TierLevel)
            else proposal.tier
        )
        created_at = proposal.created_at or self._now()

        # Serialize proposed basin config if present
        proposed_config_json = ""
        if proposal.proposed_config:
            proposed_config_json = json.dumps(proposal.proposed_config.to_dict())

        sql = """
            INSERT OR REPLACE INTO tier_proposals
                (proposal_id, agent_id, basin_name, tier, proposal_type,
                 status, rationale, session_id, consecutive_count,
                 proposed_config_json,
                 created_at, resolved_at, resolved_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            proposal.proposal_id,
            proposal.agent_id,
            proposal.basin_name,
            tier_val,
            proposal_type_val,
            status_val,
            proposal.rationale,
            proposal.session_id,
            proposal.consecutive_count,
            proposed_config_json,
            created_at,
            proposal.resolved_at,
            proposal.resolved_by,
        )
        await self._run_sync(self.sqlite.execute, sql, params)
        logger.debug(
            "Stored tier proposal %s for agent %s basin %s",
            proposal.proposal_id,
            proposal.agent_id,
            proposal.basin_name,
        )

        # Auto-notify brain via annotation for pending proposals
        if status_val == "pending":
            await self._notify_pending_proposal(proposal)

    async def _notify_pending_proposal(self, proposal: TierProposal) -> None:
        """Auto-generate an annotation to notify brain of a pending proposal."""
        action = (
            proposal.proposal_type.value
            if hasattr(proposal.proposal_type, "value")
            else str(proposal.proposal_type)
        )
        content = (
            f"PENDING REVIEW: New basin proposal '{proposal.basin_name}' "
            f"({action}) from session {proposal.session_id}. "
            f"Use get_pending_review_items to review."
        )
        annotation = Annotation(
            annotation_id=str(uuid.uuid4()),
            agent_id=proposal.agent_id,
            session_id=proposal.session_id or None,
            content=content,
            tags=["system", "pending-review", "auto-generated"],
            created_at=self._now(),
        )
        await self.store_annotation(annotation)
        logger.debug(
            "Auto-notified brain of pending proposal %s", proposal.proposal_id
        )

    async def get_tier_proposals(
        self, agent_id: str, status: str | None = None
    ) -> list[TierProposal]:
        """Get tier proposals for an agent, optionally filtered by status."""
        if status is not None:
            sql = """
                SELECT * FROM tier_proposals
                WHERE agent_id = ? AND status = ?
                ORDER BY created_at DESC
            """
            rows = await self._run_sync(
                self.sqlite.fetch_all, sql, (agent_id, status)
            )
        else:
            sql = """
                SELECT * FROM tier_proposals
                WHERE agent_id = ?
                ORDER BY created_at DESC
            """
            rows = await self._run_sync(
                self.sqlite.fetch_all, sql, (agent_id,)
            )
        return [self._row_to_tier_proposal(r) for r in rows]

    async def update_proposal_status(
        self,
        proposal_id: str,
        status: ProposalStatus,
        resolved_by: str | None = None,
    ) -> None:
        """Update a proposal's status and resolution metadata."""
        status_val = enum_val(status)
        resolved_at = self._now()

        sql = """
            UPDATE tier_proposals
            SET status = ?, resolved_at = ?, resolved_by = ?
            WHERE proposal_id = ?
        """
        await self._run_sync(
            self.sqlite.execute,
            sql,
            (status_val, resolved_at, resolved_by or "", proposal_id),
        )
        logger.info(
            "Updated proposal %s to status %s", proposal_id, status_val
        )

    async def get_consecutive_proposal_count(
        self, agent_id: str, basin_name: str
    ) -> int:
        """Get the count of consecutive pending proposals for a basin."""
        sql = """
            SELECT consecutive_count FROM tier_proposals
            WHERE agent_id = ? AND basin_name = ? AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT 1
        """
        row = await self._run_sync(
            self.sqlite.fetch_one, sql, (agent_id, basin_name)
        )
        if not row:
            return 0
        return row.get("consecutive_count", 0)

    async def increment_proposal_counter(
        self, agent_id: str, basin_name: str
    ) -> int:
        """Increment the consecutive proposal count for a basin. Returns the new count."""
        current = await self.get_consecutive_proposal_count(agent_id, basin_name)
        new_count = current + 1

        # Update the latest pending proposal's consecutive_count
        sql = """
            UPDATE tier_proposals
            SET consecutive_count = ?
            WHERE agent_id = ? AND basin_name = ? AND status = 'pending'
            AND proposal_id = (
                SELECT proposal_id FROM tier_proposals
                WHERE agent_id = ? AND basin_name = ? AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
            )
        """
        await self._run_sync(
            self.sqlite.execute,
            sql,
            (new_count, agent_id, basin_name, agent_id, basin_name),
        )
        logger.debug(
            "Incremented proposal counter for %s/%s to %d",
            agent_id,
            basin_name,
            new_count,
        )
        return new_count

    async def reset_proposal_counter(
        self, agent_id: str, basin_name: str
    ) -> None:
        """Reset the consecutive proposal count for a basin (e.g., after rejection)."""
        sql = """
            UPDATE tier_proposals
            SET consecutive_count = 0
            WHERE agent_id = ? AND basin_name = ? AND status = 'pending'
        """
        await self._run_sync(
            self.sqlite.execute, sql, (agent_id, basin_name)
        )
        logger.debug(
            "Reset proposal counter for %s/%s", agent_id, basin_name
        )

    @staticmethod
    def _row_to_tier_proposal(row: dict[str, Any]) -> TierProposal:
        """Convert a database row to a TierProposal dataclass."""
        status_val = row.get("status", "pending")
        try:
            status = ProposalStatus(status_val)
        except ValueError:
            status = ProposalStatus.PENDING

        proposal_type_val = row.get("proposal_type", "modify")
        try:
            proposal_type = ProposalType(proposal_type_val)
        except ValueError:
            proposal_type = ProposalType.MODIFY

        tier_val = row.get("tier", 3)
        try:
            tier = TierLevel(int(tier_val))
        except (ValueError, TypeError):
            tier = TierLevel.TIER_3

        # Parse proposed basin config if stored
        proposed_config = None
        proposed_json = row.get("proposed_config_json", "")
        if proposed_json:
            try:
                cfg = json.loads(proposed_json)
                if isinstance(cfg, dict) and "name" in cfg:
                    bc_val = cfg.get("basin_class", "peripheral")
                    try:
                        bc = BasinClass(bc_val)
                    except ValueError:
                        bc = BasinClass.PERIPHERAL
                    t_val = cfg.get("tier", 3)
                    try:
                        t = TierLevel(int(t_val))
                    except (ValueError, TypeError):
                        t = TierLevel.TIER_3
                    proposed_config = BasinConfig(
                        name=cfg["name"],
                        basin_class=bc,
                        alpha=cfg.get("alpha", 0.3),
                        lambda_=cfg.get("lambda", cfg.get("lambda_", 0.95)),
                        eta=cfg.get("eta", 0.1),
                        tier=t,
                    )
            except (json.JSONDecodeError, TypeError):
                pass

        # Parse original_params if stored (preserved when a proposal is modified)
        original_params = None
        original_json = row.get("original_params_json", "")
        if original_json:
            try:
                ocfg = json.loads(original_json)
                if isinstance(ocfg, dict) and "name" in ocfg:
                    obc_val = ocfg.get("basin_class", "peripheral")
                    try:
                        obc = BasinClass(obc_val)
                    except ValueError:
                        obc = BasinClass.PERIPHERAL
                    ot_val = ocfg.get("tier", 3)
                    try:
                        ot = TierLevel(int(ot_val))
                    except (ValueError, TypeError):
                        ot = TierLevel.TIER_3
                    original_params = BasinConfig(
                        name=ocfg["name"],
                        basin_class=obc,
                        alpha=ocfg.get("alpha", 0.3),
                        lambda_=ocfg.get("lambda", ocfg.get("lambda_", 0.95)),
                        eta=ocfg.get("eta", 0.1),
                        tier=ot,
                    )
            except (json.JSONDecodeError, TypeError):
                pass

        return TierProposal(
            proposal_id=row["proposal_id"],
            agent_id=row["agent_id"],
            basin_name=row["basin_name"],
            tier=tier,
            proposal_type=proposal_type,
            status=status,
            rationale=row.get("rationale", ""),
            session_id=row.get("session_id", ""),
            consecutive_count=row.get("consecutive_count", 0),
            created_at=row.get("created_at", ""),
            resolved_at=row.get("resolved_at", ""),
            resolved_by=row.get("resolved_by", ""),
            proposed_config=proposed_config,
            rejection_rationale=row.get("rejection_rationale", ""),
            modification_rationale=row.get("modification_rationale", ""),
            original_params=original_params,
        )

    async def get_tier_proposal(self, proposal_id: str) -> TierProposal | None:
        """Retrieve a single tier proposal by ID."""
        sql = "SELECT * FROM tier_proposals WHERE proposal_id = ?"
        row = await self._run_sync(
            self.sqlite.fetch_one, sql, (proposal_id,)
        )
        if not row:
            return None
        return self._row_to_tier_proposal(row)

    async def apply_approved_proposal(self, proposal: TierProposal) -> None:
        """Apply an approved CREATE proposal by adding the basin to agent config.

        Updates both the agents.config_json and basin_current tables.
        """
        if not proposal.proposed_config:
            logger.warning(
                "Cannot apply proposal %s: no proposed_config stored",
                proposal.proposal_id,
            )
            return

        agent = await self.get_agent(proposal.agent_id)
        if not agent:
            logger.warning(
                "Cannot apply proposal %s: agent %s not found",
                proposal.proposal_id,
                proposal.agent_id,
            )
            return

        basin = proposal.proposed_config

        source = await self.get_agent_basin_source(agent.agent_id)

        if proposal.proposal_type == ProposalType.CREATE:
            # Add basin to agent config if not already present
            existing_names = {b.name for b in agent.basins}
            if basin.name in existing_names:
                logger.info(
                    "Basin '%s' already exists in agent %s config — skipping add",
                    basin.name,
                    agent.agent_id,
                )
                return

            new_basins = list(agent.basins) + [basin]
            basins_dicts = [b.to_dict() for b in new_basins]
            await self.update_agent(agent.agent_id, {"basins": basins_dicts})
            await self.update_current_basins(agent.agent_id, new_basins)

            # Sync to basin_definitions for database-source agents
            if source == "database":
                await self.upsert_basin_definition(
                    agent_id=agent.agent_id,
                    name=basin.name,
                    params={
                        "basin_class": enum_val(basin.basin_class),
                        "alpha": basin.alpha,
                        "lambda": basin.lambda_,
                        "eta": basin.eta,
                        "tier": basin.tier.value if hasattr(basin.tier, "value") else int(basin.tier),
                    },
                    modified_by="body",
                    rationale=f"Applied from approved proposal {proposal.proposal_id}",
                )

            logger.info(
                "Applied approved proposal %s: added basin '%s' to agent %s",
                proposal.proposal_id,
                basin.name,
                agent.agent_id,
            )

        elif proposal.proposal_type == ProposalType.MODIFY:
            # Replace existing basin with proposed config
            new_basins = [
                basin if b.name == basin.name else b
                for b in agent.basins
            ]
            basins_dicts = [b.to_dict() for b in new_basins]
            await self.update_agent(agent.agent_id, {"basins": basins_dicts})
            await self.update_current_basins(agent.agent_id, new_basins)

            # Sync to basin_definitions for database-source agents
            if source == "database":
                await self.upsert_basin_definition(
                    agent_id=agent.agent_id,
                    name=basin.name,
                    params={
                        "basin_class": enum_val(basin.basin_class),
                        "alpha": basin.alpha,
                        "lambda": basin.lambda_,
                        "eta": basin.eta,
                        "tier": basin.tier.value if hasattr(basin.tier, "value") else int(basin.tier),
                    },
                    modified_by="body",
                    rationale=f"Applied from approved proposal {proposal.proposal_id}",
                )

            logger.info(
                "Applied approved proposal %s: modified basin '%s' in agent %s",
                proposal.proposal_id,
                basin.name,
                agent.agent_id,
            )

        elif proposal.proposal_type == ProposalType.PRUNE:
            # Remove basin from agent config
            new_basins = [b for b in agent.basins if b.name != basin.name]
            basins_dicts = [b.to_dict() for b in new_basins]
            await self.update_agent(agent.agent_id, {"basins": basins_dicts})
            # Also remove from basin_current
            await self._run_sync(
                self.sqlite.execute,
                "DELETE FROM basin_current WHERE agent_id = ? AND basin_name = ?",
                (agent.agent_id, basin.name),
            )

            logger.info(
                "Applied approved proposal %s: pruned basin '%s' from agent %s",
                proposal.proposal_id,
                basin.name,
                agent.agent_id,
            )

    # ------------------------------------------------------------------
    # Brain review workflow
    # ------------------------------------------------------------------

    async def reject_proposal_with_rationale(
        self,
        proposal_id: str,
        rationale: str,
        resolved_by: str = "brain",
    ) -> TierProposal | None:
        """Reject a proposal and store the rejection rationale."""
        resolved_at = self._now()
        sql = """
            UPDATE tier_proposals
            SET status = ?, resolved_at = ?, resolved_by = ?,
                rejection_rationale = ?
            WHERE proposal_id = ?
        """
        await self._run_sync(
            self.sqlite.execute,
            sql,
            (
                ProposalStatus.REJECTED.value,
                resolved_at,
                resolved_by,
                rationale,
                proposal_id,
            ),
        )
        logger.info("Rejected proposal %s with rationale", proposal_id)
        return await self.get_tier_proposal(proposal_id)

    async def modify_and_apply_proposal(
        self,
        proposal_id: str,
        modifications: dict,
        rationale: str,
        resolved_by: str = "brain",
    ) -> TierProposal | None:
        """Approve a proposal with modifications.

        Stores original params, applies modifications to proposed_config,
        marks as approved_with_modifications, and applies the change.
        """
        proposal = await self.get_tier_proposal(proposal_id)
        if not proposal:
            logger.warning("Cannot modify proposal %s: not found", proposal_id)
            return None

        if not proposal.proposed_config:
            logger.warning("Cannot modify proposal %s: no proposed_config", proposal_id)
            return None

        # Save original params
        original_json = json.dumps(proposal.proposed_config.to_dict())

        # Apply modifications to the proposed config
        cfg = proposal.proposed_config
        if "alpha" in modifications or "suggested_alpha" in modifications:
            cfg.alpha = modifications.get("alpha", modifications.get("suggested_alpha", cfg.alpha))
        if "lambda" in modifications or "lambda_decay" in modifications:
            cfg.lambda_ = modifications.get("lambda", modifications.get("lambda_decay", cfg.lambda_))
        if "eta" in modifications:
            cfg.eta = modifications["eta"]
        if "tier" in modifications:
            try:
                cfg.tier = TierLevel(int(modifications["tier"]))
            except (ValueError, TypeError):
                pass
        if "basin_class" in modifications:
            try:
                cfg.basin_class = BasinClass(modifications["basin_class"])
            except ValueError:
                pass

        modified_config_json = json.dumps(cfg.to_dict())
        resolved_at = self._now()

        sql = """
            UPDATE tier_proposals
            SET status = ?, resolved_at = ?, resolved_by = ?,
                modification_rationale = ?, original_params_json = ?,
                proposed_config_json = ?
            WHERE proposal_id = ?
        """
        await self._run_sync(
            self.sqlite.execute,
            sql,
            (
                ProposalStatus.APPROVED_WITH_MODIFICATIONS.value,
                resolved_at,
                resolved_by,
                rationale,
                original_json,
                modified_config_json,
                proposal_id,
            ),
        )

        # Re-fetch to get the updated proposal and apply it
        updated = await self.get_tier_proposal(proposal_id)
        if updated:
            await self.apply_approved_proposal(updated)
        logger.info(
            "Modified and applied proposal %s: %s", proposal_id, rationale
        )
        return updated

    async def get_pending_review_items(self, agent_id: str) -> dict:
        """Get all items awaiting brain review for an agent."""
        # Pending proposals with full context
        proposals = await self.get_tier_proposals(agent_id, status="pending")
        pending_proposals = []
        for p in proposals:
            # Get current basin state for context
            current_state = None
            if p.proposal_type != ProposalType.CREATE:
                current_basins = await self.get_current_basins(agent_id)
                for b in current_basins:
                    if b.name == p.basin_name:
                        current_state = b.to_dict()
                        break

            suggested_params = None
            if p.proposed_config:
                suggested_params = p.proposed_config.to_dict()

            pending_proposals.append({
                "proposal_id": p.proposal_id,
                "basin_name": p.basin_name,
                "action": enum_val(p.proposal_type),
                "proposed_by_session": p.session_id,
                "proposed_at": p.created_at,
                "rationale": p.rationale,
                "suggested_params": suggested_params,
                "current_basin_state": current_state,
                "consecutive_count": p.consecutive_count,
            })

        # Unresolved flags (not reviewed)
        flags = await self.get_evaluator_flags(agent_id, reviewed=False)
        unresolved_flags = [
            {
                "flag_id": f.flag_id,
                "session_id": f.session_id,
                "flag_type": enum_val(f.flag_type),
                "severity": f.severity,
                "detail": f.detail,
                "flagged_at": f.created_at,
            }
            for f in flags
        ]

        # Summary with last brain review time
        last_review_sql = """
            SELECT MAX(resolved_at) as last_review
            FROM tier_proposals
            WHERE agent_id = ? AND resolved_by IN ('brain', 'human', 'mcp_user')
              AND resolved_at != ''
        """
        row = await self._run_sync(
            self.sqlite.fetch_one, last_review_sql, (agent_id,)
        )
        last_brain_review = (row.get("last_review") or None) if row else None

        return {
            "pending_proposals": pending_proposals,
            "unresolved_flags": unresolved_flags,
            "summary": {
                "pending_proposals": len(pending_proposals),
                "unresolved_flags": len(unresolved_flags),
                "last_brain_review": last_brain_review,
            },
        }

    async def resolve_flag(
        self,
        flag_id: str,
        resolution: str,
        notes: str = "",
        resolved_by: str = "brain",
    ) -> None:
        """Resolve a flag with a resolution type and notes."""
        resolved_at = self._now()
        sql = """
            UPDATE flags
            SET reviewed = 1, review_note = ?, reviewed_at = ?,
                reviewed_by = ?, resolution = ?, resolution_notes = ?
            WHERE flag_id = ?
        """
        await self._run_sync(
            self.sqlite.execute,
            sql,
            (notes, resolved_at, resolved_by, resolution, notes, flag_id),
        )
        logger.info("Resolved flag %s: %s", flag_id, resolution)

    async def create_basin_direct(
        self,
        agent_id: str,
        basin_name: str,
        basin_class: str,
        tier: int,
        alpha: float,
        lambda_decay: float,
        eta: float,
        rationale: str,
    ) -> BasinConfig:
        """Brain-initiated basin creation (bypasses proposal flow)."""
        try:
            bc = BasinClass(basin_class)
        except ValueError:
            bc = BasinClass.PERIPHERAL
        try:
            tl = TierLevel(tier)
        except (ValueError, TypeError):
            tl = TierLevel.TIER_3

        basin = BasinConfig(
            name=basin_name,
            basin_class=bc,
            alpha=max(0.05, min(1.0, alpha)),
            lambda_=lambda_decay,
            eta=eta,
            tier=tl,
        )

        agent = await self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        # Check for duplicates
        if any(b.name == basin_name for b in agent.basins):
            raise ValueError(f"Basin '{basin_name}' already exists for agent {agent_id}")

        new_basins = list(agent.basins) + [basin]
        await self.update_agent(agent_id, {"basins": [b.to_dict() for b in new_basins]})
        await self.update_current_basins(agent_id, new_basins)

        logger.info(
            "Brain created basin '%s' for agent %s: %s",
            basin_name, agent_id, rationale,
        )
        return basin

    async def modify_basin_direct(
        self,
        agent_id: str,
        basin_name: str,
        modifications: dict,
        rationale: str,
    ) -> BasinConfig | None:
        """Brain-initiated direct basin modification (bypasses proposal flow)."""
        agent = await self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        target = None
        for b in agent.basins:
            if b.name == basin_name:
                target = b
                break

        if not target:
            raise ValueError(f"Basin '{basin_name}' not found for agent {agent_id}")

        # Apply modifications
        if "alpha" in modifications:
            target.alpha = max(0.05, min(1.0, modifications["alpha"]))
        if "lambda" in modifications or "lambda_decay" in modifications:
            target.lambda_ = modifications.get("lambda", modifications.get("lambda_decay", target.lambda_))
        if "eta" in modifications:
            target.eta = modifications["eta"]
        if "tier" in modifications:
            try:
                target.tier = TierLevel(int(modifications["tier"]))
            except (ValueError, TypeError):
                pass
        if "basin_class" in modifications:
            try:
                target.basin_class = BasinClass(modifications["basin_class"])
            except ValueError:
                pass

        # Persist
        await self.update_agent(
            agent_id, {"basins": [b.to_dict() for b in agent.basins]}
        )
        await self.update_current_basins(agent_id, agent.basins)

        logger.info(
            "Brain modified basin '%s' for agent %s: %s",
            basin_name, agent_id, rationale,
        )
        return target

    async def deprecate_basin(
        self,
        agent_id: str,
        basin_name: str,
        rationale: str,
    ) -> None:
        """Soft-deprecate a basin (preserve history, exclude from active tracking)."""
        deprecated_at = self._now()
        sql = """
            UPDATE basin_current
            SET deprecated = 1, deprecated_at = ?, deprecation_rationale = ?
            WHERE agent_id = ? AND basin_name = ?
        """
        await self._run_sync(
            self.sqlite.execute,
            sql,
            (deprecated_at, rationale, agent_id, basin_name),
        )

        # Also remove from agent config basins (so it won't appear in sessions)
        agent = await self.get_agent(agent_id)
        if agent:
            new_basins = [b for b in agent.basins if b.name != basin_name]
            await self.update_agent(
                agent_id, {"basins": [b.to_dict() for b in new_basins]}
            )

        logger.info(
            "Deprecated basin '%s' for agent %s: %s",
            basin_name, agent_id, rationale,
        )

    async def undeprecate_basin(
        self,
        agent_id: str,
        basin_name: str,
    ) -> BasinConfig | None:
        """Restore a deprecated basin to active tracking."""
        sql = """
            UPDATE basin_current
            SET deprecated = 0, deprecated_at = '', deprecation_rationale = ''
            WHERE agent_id = ? AND basin_name = ?
        """
        await self._run_sync(
            self.sqlite.execute, sql, (agent_id, basin_name)
        )

        # Fetch the basin config from basin_current and add back to agent
        row = await self._run_sync(
            self.sqlite.fetch_one,
            "SELECT * FROM basin_current WHERE agent_id = ? AND basin_name = ?",
            (agent_id, basin_name),
        )
        if not row:
            return None

        basin = self._row_to_basin_config(row)
        agent = await self.get_agent(agent_id)
        if agent and not any(b.name == basin_name for b in agent.basins):
            new_basins = list(agent.basins) + [basin]
            await self.update_agent(
                agent_id, {"basins": [b.to_dict() for b in new_basins]}
            )

        logger.info("Undeprecated basin '%s' for agent %s", basin_name, agent_id)
        return basin

    # ------------------------------------------------------------------
    # Co-activation
    # ------------------------------------------------------------------

    async def update_co_activation(
        self, agent_id: str, entries: list[CoActivationEntry]
    ) -> None:
        """Upsert co-activation log entries for an agent."""
        if not entries:
            return

        for entry in entries:
            basin_a, basin_b = sorted(entry.pair)
            character_val = (
                entry.character.value
                if isinstance(entry.character, CoActivationCharacter)
                else (entry.character or "uncharacterized")
            )

            # Check if the pair already exists
            check_sql = """
                SELECT id, count FROM co_activation_log
                WHERE agent_id = ? AND basin_a = ? AND basin_b = ?
            """
            existing = await self._run_sync(
                self.sqlite.fetch_one, check_sql, (agent_id, basin_a, basin_b)
            )

            if existing:
                update_sql = """
                    UPDATE co_activation_log
                    SET count = ?, character = ?
                    WHERE id = ?
                """
                await self._run_sync(
                    self.sqlite.execute,
                    update_sql,
                    (entry.count, character_val, existing["id"]),
                )
            else:
                insert_sql = """
                    INSERT INTO co_activation_log
                        (agent_id, basin_a, basin_b, count, character)
                    VALUES (?, ?, ?, ?, ?)
                """
                await self._run_sync(
                    self.sqlite.execute,
                    insert_sql,
                    (agent_id, basin_a, basin_b, entry.count, character_val),
                )

        logger.debug(
            "Updated %d co-activation entries for agent %s",
            len(entries),
            agent_id,
        )

    async def get_co_activation(self, agent_id: str) -> list[CoActivationEntry]:
        """Get all co-activation entries for an agent."""
        sql = """
            SELECT * FROM co_activation_log
            WHERE agent_id = ?
            ORDER BY count DESC
        """
        rows = await self._run_sync(self.sqlite.fetch_all, sql, (agent_id,))
        results = []
        for row in rows:
            character_val = row.get("character", "uncharacterized")
            try:
                character = CoActivationCharacter(character_val)
            except ValueError:
                character = CoActivationCharacter.UNCHARACTERIZED

            results.append(
                CoActivationEntry(
                    pair=(row["basin_a"], row["basin_b"]),
                    count=row.get("count", 0),
                    character=character,
                )
            )
        return results

    # ------------------------------------------------------------------
    # Semantic search (ChromaDB)
    # ------------------------------------------------------------------

    async def store_session_transcript(
        self, agent_id: str, session_id: str, transcript: str
    ) -> None:
        """Index a session transcript in ChromaDB for semantic search."""
        doc_id = f"{agent_id}:{session_id}:transcript"
        metadata = {
            "agent_id": agent_id,
            "session_id": session_id,
            "content_type": "transcript",
            "timestamp": self._now(),
        }
        await self._run_sync(
            self.chroma.add_document,
            "session_transcripts",
            doc_id,
            transcript,
            metadata,
        )
        logger.debug(
            "Indexed transcript for session %s in ChromaDB", session_id
        )

    async def store_close_report(
        self, agent_id: str, session_id: str, report: str
    ) -> None:
        """Index a close report in ChromaDB for semantic search."""
        doc_id = f"{agent_id}:{session_id}:close_report"
        metadata = {
            "agent_id": agent_id,
            "session_id": session_id,
            "content_type": "close_report",
            "timestamp": self._now(),
        }
        await self._run_sync(
            self.chroma.add_document,
            "close_reports",
            doc_id,
            report,
            metadata,
        )
        logger.debug(
            "Indexed close report for session %s in ChromaDB", session_id
        )

    async def store_emergence(
        self,
        agent_id: str,
        content: str,
        related_basins: list[str],
        session_id: str | None = None,
    ) -> None:
        """Store an emergent observation in ChromaDB."""
        doc_id = f"{agent_id}:emergence:{uuid.uuid4().hex[:12]}"
        metadata: dict[str, Any] = {
            "agent_id": agent_id,
            "content_type": "emergence",
            "related_basins": json.dumps(related_basins),
            "timestamp": self._now(),
        }
        if session_id:
            metadata["session_id"] = session_id

        await self._run_sync(
            self.chroma.add_document,
            "emergent_observations",
            doc_id,
            content,
            metadata,
        )
        logger.debug("Stored emergence observation for agent %s", agent_id)

    async def search_sessions(
        self, agent_id: str, query: str, n_results: int = 5
    ) -> list[SearchResult]:
        """Semantic search across session transcripts and close reports for an agent."""
        # Refresh ChromaDB to see annotations written by the MCP server process
        await self.refresh_chroma()

        results: list[SearchResult] = []

        # Search transcripts
        try:
            transcript_results = await self._run_sync(
                self.chroma.query,
                "session_transcripts",
                query,
                n_results,
                {"agent_id": agent_id},
            )
            results.extend(
                self._chroma_results_to_search_results(transcript_results, "transcript")
            )
        except Exception as e:
            logger.warning("Transcript search failed: %s", e)

        # Search close reports
        try:
            report_results = await self._run_sync(
                self.chroma.query,
                "close_reports",
                query,
                n_results,
                {"agent_id": agent_id},
            )
            results.extend(
                self._chroma_results_to_search_results(report_results, "close_report")
            )
        except Exception as e:
            logger.warning("Close report search failed: %s", e)

        # Search emergent observations
        try:
            emergence_results = await self._run_sync(
                self.chroma.query,
                "emergent_observations",
                query,
                n_results,
                {"agent_id": agent_id},
            )
            results.extend(
                self._chroma_results_to_search_results(
                    emergence_results, "emergence"
                )
            )
        except Exception as e:
            logger.warning("Emergence search failed: %s", e)

        # Search annotations (written by MCP / human observer)
        try:
            annotation_results = await self._run_sync(
                self.chroma.query,
                "annotations",
                query,
                n_results,
                {"agent_id": agent_id},
            )
            results.extend(
                self._chroma_results_to_search_results(
                    annotation_results, "annotation"
                )
            )
        except Exception as e:
            logger.warning("Annotation search failed: %s", e)

        # Sort by relevance and limit
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:n_results]

    async def search_all_agents(
        self, query: str, n_results: int = 10
    ) -> list[SearchResult]:
        """Search across all agents (no agent_id filter)."""
        results: list[SearchResult] = []

        collections_to_search = [
            ("session_transcripts", "transcript"),
            ("close_reports", "close_report"),
            ("emergent_observations", "emergence"),
            ("annotations", "annotation"),
        ]

        for collection_name, content_type in collections_to_search:
            try:
                chroma_results = await self._run_sync(
                    self.chroma.query,
                    collection_name,
                    query,
                    n_results,
                )
                results.extend(
                    self._chroma_results_to_search_results(
                        chroma_results, content_type
                    )
                )
            except Exception as e:
                logger.warning(
                    "Search failed for collection %s: %s", collection_name, e
                )

        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:n_results]

    @staticmethod
    def _chroma_results_to_search_results(
        chroma_results: dict[str, Any],
        content_type: str,
        include_full_content: bool = False,
    ) -> list[SearchResult]:
        """Convert ChromaDB query results to SearchResult dataclass instances.

        Args:
            chroma_results: Raw ChromaDB query output.
            content_type: Label for result type (e.g. "annotation", "emergence").
            include_full_content: When True, populate ``full_content`` with the
                complete document text instead of only the 300-char snippet.
        """
        results = []
        if not chroma_results:
            return results

        ids = chroma_results.get("ids", [[]])[0]
        documents = chroma_results.get("documents", [[]])[0]
        metadatas = chroma_results.get("metadatas", [[]])[0]
        distances = chroma_results.get("distances", [[]])[0]

        for i, doc_id in enumerate(ids):
            metadata = metadatas[i] if i < len(metadatas) else {}
            document = documents[i] if i < len(documents) else ""
            distance = distances[i] if i < len(distances) else 1.0

            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # Convert to relevance score: 1.0 = best, 0.0 = worst
            relevance = max(0.0, 1.0 - (distance / 2.0))

            # Create a snippet (first 300 chars)
            snippet = document[:300] if document else ""
            if len(document) > 300:
                snippet += "..."

            results.append(
                SearchResult(
                    content_type=content_type,
                    agent_id=metadata.get("agent_id", ""),
                    session_id=metadata.get("session_id", ""),
                    snippet=snippet,
                    relevance_score=round(relevance, 4),
                    timestamp=metadata.get("timestamp", ""),
                    full_content=document if include_full_content else None,
                )
            )
        return results

    # ------------------------------------------------------------------
    # Annotations
    # ------------------------------------------------------------------

    async def store_annotation(self, annotation: Annotation) -> None:
        """Store a human annotation in SQLite and index in ChromaDB."""
        created_at = annotation.created_at or self._now()
        tags_json = json.dumps(annotation.tags)

        sql = """
            INSERT OR REPLACE INTO annotations
                (annotation_id, agent_id, session_id, content, tags_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        params = (
            annotation.annotation_id,
            annotation.agent_id,
            annotation.session_id or "",
            annotation.content,
            tags_json,
            created_at,
        )
        await self._run_sync(self.sqlite.execute, sql, params)

        # Also index in ChromaDB for semantic search
        if annotation.content.strip():
            doc_id = f"{annotation.agent_id}:annotation:{annotation.annotation_id}"
            metadata: dict[str, Any] = {
                "agent_id": annotation.agent_id,
                "content_type": "annotation",
                "timestamp": created_at,
            }
            if annotation.session_id:
                metadata["session_id"] = annotation.session_id

            await self._run_sync(
                self.chroma.add_document,
                "annotations",
                doc_id,
                annotation.content,
                metadata,
            )

        logger.debug(
            "Stored annotation %s for agent %s",
            annotation.annotation_id,
            annotation.agent_id,
        )

    async def get_annotations(
        self,
        agent_id: str,
        session_id: str | None = None,
        limit: int | None = None,
        sort_order: str = "desc",
    ) -> list[Annotation]:
        """Get annotations for an agent, optionally filtered to a session.

        Args:
            agent_id: Agent to retrieve annotations for.
            session_id: If provided, restrict results to this session.
            limit: Maximum number of results to return.
            sort_order: "desc" (newest first) or "asc" (oldest first).
        """
        order = "DESC" if sort_order.lower() != "asc" else "ASC"
        limit_clause = f" LIMIT {int(limit)}" if limit is not None else ""

        if session_id is not None:
            sql = f"""
                SELECT * FROM annotations
                WHERE agent_id = ? AND session_id = ?
                ORDER BY created_at {order}{limit_clause}
            """
            rows = await self._run_sync(
                self.sqlite.fetch_all, sql, (agent_id, session_id)
            )
        else:
            sql = f"""
                SELECT * FROM annotations
                WHERE agent_id = ?
                ORDER BY created_at {order}{limit_clause}
            """
            rows = await self._run_sync(
                self.sqlite.fetch_all, sql, (agent_id,)
            )
        return [self._row_to_annotation(r) for r in rows]

    async def search_observations(
        self,
        agent_id: str,
        query: str | None = None,
        n_results: int = 10,
    ) -> list[SearchResult]:
        """Search annotations and emergent observations for an agent.

        When query is None, returns recent entries from both collections.
        When query is provided, performs semantic search across both.

        Annotations may be written by the MCP server (a separate process),
        so we refresh ChromaDB to pick up cross-process writes and also
        merge SQLite annotation results to guard against indexing lag.
        """
        # Refresh ChromaDB to see annotations written by the MCP server process
        await self.refresh_chroma()

        results: list[SearchResult] = []

        if query:
            # Semantic search across both ChromaDB collections.
            # Annotations get full_content so the body sees the complete text.
            for collection, content_type in [
                ("annotations", "annotation"),
                ("emergent_observations", "emergence"),
            ]:
                try:
                    chroma_results = await self._run_sync(
                        self.chroma.query,
                        collection,
                        query,
                        n_results,
                        {"agent_id": agent_id},
                    )
                    results.extend(
                        self._chroma_results_to_search_results(
                            chroma_results,
                            content_type,
                            include_full_content=(content_type == "annotation"),
                        )
                    )
                except Exception as e:
                    logger.warning("Observation search (%s) failed: %s", collection, e)

            # Also merge SQLite annotations as fallback — ChromaDB indexing
            # from another process may lag even after refresh.
            chroma_ann_ids = {
                r.snippet[:100] for r in results if r.content_type == "annotation"
            }
            sqlite_annotations = await self.get_annotations(agent_id)
            for ann in sqlite_annotations:
                snippet = ann.content[:300]
                if len(ann.content) > 300:
                    snippet += "..."
                # Avoid duplicating annotations already found via ChromaDB
                if snippet[:100] in chroma_ann_ids:
                    continue
                # Simple keyword match for SQLite fallback
                if query.lower() in ann.content.lower():
                    results.append(
                        SearchResult(
                            content_type="annotation",
                            agent_id=agent_id,
                            session_id=ann.session_id or "",
                            snippet=snippet,
                            relevance_score=0.7,  # reasonable default for keyword match
                            timestamp=ann.created_at,
                            full_content=ann.content,
                        )
                    )
        else:
            # No query — return recent annotations from SQLite + emergence from ChromaDB
            annotations = await self.get_annotations(agent_id)
            for ann in annotations[:n_results]:
                snippet = ann.content[:300]
                if len(ann.content) > 300:
                    snippet += "..."
                results.append(
                    SearchResult(
                        content_type="annotation",
                        agent_id=agent_id,
                        session_id=ann.session_id or "",
                        snippet=snippet,
                        relevance_score=1.0,
                        timestamp=ann.created_at,
                        full_content=ann.content,
                    )
                )

            # Retrieve recent emergence observations via a broad query
            try:
                chroma_results = await self._run_sync(
                    self.chroma.query,
                    "emergent_observations",
                    "emergence observation",
                    n_results,
                    {"agent_id": agent_id},
                )
                results.extend(
                    self._chroma_results_to_search_results(
                        chroma_results, "emergence"
                    )
                )
            except Exception as e:
                logger.warning("Emergence retrieval failed: %s", e)

        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:n_results]

    @staticmethod
    def _row_to_annotation(row: dict[str, Any]) -> Annotation:
        """Convert a database row to an Annotation dataclass."""
        tags = []
        if row.get("tags_json"):
            try:
                tags = json.loads(row["tags_json"])
            except (json.JSONDecodeError, TypeError):
                pass

        return Annotation(
            annotation_id=row["annotation_id"],
            agent_id=row["agent_id"],
            session_id=row.get("session_id") or None,
            content=row.get("content", ""),
            tags=tags,
            created_at=row.get("created_at", ""),
        )

    # ------------------------------------------------------------------
    # Usage tracking
    # ------------------------------------------------------------------

    async def log_usage(self, record: UsageRecord) -> None:
        """Log a credit usage record."""
        timestamp = record.timestamp or self._now()

        sql = """
            INSERT INTO usage
                (session_id, agent_id, tokens_in, tokens_out,
                 estimated_cost, model, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            record.session_id,
            record.agent_id,
            record.tokens_in,
            record.tokens_out,
            record.estimated_cost,
            record.model,
            timestamp,
        )
        await self._run_sync(self.sqlite.execute, sql, params)
        logger.debug(
            "Logged usage for session %s: %d in, %d out, $%.4f",
            record.session_id,
            record.tokens_in,
            record.tokens_out,
            record.estimated_cost,
        )

    async def get_usage_summary(self, period: str = "day") -> dict:
        """Get aggregated usage summary for a time period.

        Args:
            period: One of 'day', 'week', 'month', 'all'.

        Returns:
            Dictionary with total_tokens_in, total_tokens_out,
            total_cost, session_count, and period info.
        """
        now = datetime.now(timezone.utc)
        if period == "day":
            cutoff = (now - timedelta(days=1)).isoformat()
        elif period == "week":
            cutoff = (now - timedelta(weeks=1)).isoformat()
        elif period == "month":
            cutoff = (now - timedelta(days=30)).isoformat()
        else:
            cutoff = "1970-01-01T00:00:00"

        sql = """
            SELECT
                COALESCE(SUM(tokens_in), 0) as total_tokens_in,
                COALESCE(SUM(tokens_out), 0) as total_tokens_out,
                COALESCE(SUM(estimated_cost), 0.0) as total_cost,
                COUNT(*) as session_count
            FROM usage
            WHERE timestamp >= ?
        """
        row = await self._run_sync(self.sqlite.fetch_one, sql, (cutoff,))
        if not row:
            return {
                "period": period,
                "total_tokens_in": 0,
                "total_tokens_out": 0,
                "total_cost": 0.0,
                "session_count": 0,
            }
        return {
            "period": period,
            "total_tokens_in": row["total_tokens_in"],
            "total_tokens_out": row["total_tokens_out"],
            "total_cost": round(row["total_cost"], 4),
            "session_count": row["session_count"],
        }

    async def get_usage_daily(self, days: int = 30) -> list[dict]:
        """Get daily usage breakdown for the last N days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        sql = """
            SELECT
                DATE(timestamp) as date,
                COALESCE(SUM(tokens_in), 0) as tokens_in,
                COALESCE(SUM(tokens_out), 0) as tokens_out,
                COALESCE(SUM(estimated_cost), 0.0) as cost,
                COUNT(*) as session_count
            FROM usage
            WHERE timestamp >= ?
            GROUP BY DATE(timestamp)
            ORDER BY date ASC
        """
        rows = await self._run_sync(self.sqlite.fetch_all, sql, (cutoff,))
        return [
            {
                "date": row["date"],
                "tokens_in": row["tokens_in"],
                "tokens_out": row["tokens_out"],
                "cost": round(row["cost"], 4),
                "session_count": row["session_count"],
            }
            for row in rows
        ]

    async def get_usage_by_agent(self) -> list[dict]:
        """Get total usage grouped by agent, including deleted/archived agents."""
        sql = """
            SELECT
                u.agent_id,
                COALESCE(SUM(u.tokens_in), 0) as total_tokens_in,
                COALESCE(SUM(u.tokens_out), 0) as total_tokens_out,
                COALESCE(SUM(u.estimated_cost), 0.0) as total_cost,
                COUNT(*) as session_count,
                a.status as agent_status
            FROM usage u
            LEFT JOIN agents a ON u.agent_id = a.agent_id
            GROUP BY u.agent_id
            ORDER BY total_cost DESC
        """
        rows = await self._run_sync(self.sqlite.fetch_all, sql, ())
        return [
            {
                "agent_id": row["agent_id"],
                "total_tokens_in": row["total_tokens_in"],
                "total_tokens_out": row["total_tokens_out"],
                "total_cost": round(row["total_cost"], 4),
                "session_count": row["session_count"],
                "agent_status": row["agent_status"] if row["agent_status"] else "deleted",
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Activity feed
    # ------------------------------------------------------------------

    async def log_activity(self, event: ActivityEvent) -> None:
        """Log an activity event to the feed."""
        timestamp = event.timestamp or self._now()

        sql = """
            INSERT INTO activity_feed
                (event_id, event_type, agent_id, session_id, detail, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        params = (
            event.event_id,
            event.event_type,
            event.agent_id,
            event.session_id,
            event.detail,
            timestamp,
        )
        await self._run_sync(self.sqlite.execute, sql, params)
        logger.debug("Logged activity event %s: %s", event.event_id, event.event_type)

    async def get_activity_feed(self, limit: int = 20) -> list[ActivityEvent]:
        """Get the most recent activity events."""
        sql = """
            SELECT * FROM activity_feed
            ORDER BY timestamp DESC
            LIMIT ?
        """
        rows = await self._run_sync(self.sqlite.fetch_all, sql, (limit,))
        return [
            ActivityEvent(
                event_id=row["event_id"],
                event_type=row["event_type"],
                agent_id=row.get("agent_id", ""),
                session_id=row.get("session_id", ""),
                detail=row.get("detail", ""),
                timestamp=row.get("timestamp", ""),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Agent data
    # ------------------------------------------------------------------

    async def store_agent(self, config: AgentConfig) -> None:
        """Store an agent configuration."""
        status_val = (
            config.status.value
            if isinstance(config.status, AgentStatus)
            else config.status
        )
        created_at = config.created_at or self._now()

        # Build config_json from the full agent config
        config_dict = {
            "description": config.description,
            "model_override": config.model_override,
            "temperature_override": config.temperature_override,
            "max_tokens_override": config.max_tokens_override,
            "max_turns": config.max_turns,
            "identity_core": config.identity_core,
            "session_task": config.session_task,
            "close_protocol": config.close_protocol,
            "emphasis_directive": config.emphasis_directive,
            "capabilities": config.capabilities,
            "session_interval": config.session_interval,
            "basins": [b.to_dict() for b in config.basins],
            "tier_settings": (
                {
                    "tier_2_auto_approve": config.tier_settings.tier_2_auto_approve,
                    "tier_2_threshold": config.tier_settings.tier_2_threshold,
                    "emergence_auto_approve": config.tier_settings.emergence_auto_approve,
                    "emergence_threshold": config.tier_settings.emergence_threshold,
                }
                if config.tier_settings
                else None
            ),
            "session_protocol": config.session_protocol or {},
            "relational_grounding": config.relational_grounding or {},
        }
        config_json = json.dumps(config_dict)

        sql = """
            INSERT OR REPLACE INTO agents
                (agent_id, description, status, config_json, created_at, last_active)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        params = (
            config.agent_id,
            config.description,
            status_val,
            config_json,
            created_at,
            config.last_active or "",
        )
        await self._run_sync(self.sqlite.execute, sql, params)

        # Also store current basins if provided
        if config.basins:
            await self.update_current_basins(config.agent_id, config.basins)

        logger.info("Stored agent config for %s", config.agent_id)

    async def get_agent(self, agent_id: str) -> AgentConfig | None:
        """Retrieve an agent configuration."""
        sql = "SELECT * FROM agents WHERE agent_id = ?"
        row = await self._run_sync(self.sqlite.fetch_one, sql, (agent_id,))
        if not row:
            return None
        return self._row_to_agent_config(row)

    async def list_agents(self) -> list[AgentConfig]:
        """List all agent configurations (excludes soft-deleted agents)."""
        sql = "SELECT * FROM agents WHERE status != 'deleted' ORDER BY created_at DESC"
        rows = await self._run_sync(self.sqlite.fetch_all, sql, ())
        return [self._row_to_agent_config(r) for r in rows]

    async def update_agent(self, agent_id: str, updates: dict) -> None:
        """Update specific fields on an agent.

        Supported top-level fields: description, status, last_active.
        Any other keys are merged into config_json.
        """
        # Fetch current agent to merge config updates
        current = await self.get_agent(agent_id)
        if not current:
            logger.warning("Cannot update non-existent agent %s", agent_id)
            return

        # Handle direct column updates
        direct_columns = {"description", "status", "last_active"}
        set_clauses = []
        params: list[Any] = []

        for col in direct_columns:
            if col in updates:
                val = updates[col]
                if col == "status" and isinstance(val, AgentStatus):
                    val = val.value
                set_clauses.append(f"{col} = ?")
                params.append(val)

        # Handle config_json updates by merging
        config_keys = {
            "model_override",
            "temperature_override",
            "max_tokens_override",
            "max_turns",
            "session_interval",
            "identity_core",
            "session_task",
            "close_protocol",
            "emphasis_directive",
            "capabilities",
            "basins",
            "tier_settings",
            "session_protocol",
            "relational_grounding",
        }
        config_updates = {k: v for k, v in updates.items() if k in config_keys}

        if config_updates:
            # Fetch existing config_json
            config_row = await self._run_sync(
                self.sqlite.fetch_one,
                "SELECT config_json FROM agents WHERE agent_id = ?",
                (agent_id,),
            )
            existing_config = {}
            if config_row and config_row.get("config_json"):
                try:
                    existing_config = json.loads(config_row["config_json"])
                except (json.JSONDecodeError, TypeError):
                    pass

            existing_config.update(config_updates)
            set_clauses.append("config_json = ?")
            params.append(json.dumps(existing_config))

        if not set_clauses:
            return

        params.append(agent_id)
        sql = f"UPDATE agents SET {', '.join(set_clauses)} WHERE agent_id = ?"
        await self._run_sync(self.sqlite.execute, sql, tuple(params))
        logger.info("Updated agent %s: %s", agent_id, list(updates.keys()))

    async def delete_agent(
        self, agent_id: str, hard_delete: bool = False
    ) -> None:
        """Delete an agent. Soft delete sets status to 'deleted', hard delete removes all data."""
        if hard_delete:
            # Delete from agents table — CASCADE removes sessions, basin_snapshots,
            # basin_current, tier_proposals, annotations, flags, co_activation_log.
            # Usage records survive because the usage table has NO foreign keys
            # (removed by migration v0.6.2).
            await self._run_sync(
                self.sqlite.execute,
                "DELETE FROM agents WHERE agent_id = ?",
                (agent_id,),
            )

            # Delete from ChromaDB collections
            for collection_name in [
                "session_transcripts",
                "close_reports",
                "emergent_observations",
                "annotations",
            ]:
                try:
                    await self._run_sync(
                        self.chroma.delete_by_filter,
                        collection_name,
                        {"agent_id": agent_id},
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to delete from ChromaDB collection %s for agent %s: %s",
                        collection_name,
                        agent_id,
                        e,
                    )

            logger.info("Hard deleted agent %s (usage records preserved)", agent_id)
        else:
            # Soft delete: mark status
            await self._run_sync(
                self.sqlite.execute,
                "UPDATE agents SET status = 'deleted' WHERE agent_id = ?",
                (agent_id,),
            )
            logger.info("Soft deleted agent %s", agent_id)

    def _row_to_agent_config(self, row: dict[str, Any]) -> AgentConfig:
        """Convert a database row to an AgentConfig dataclass."""
        status_val = row.get("status", "idle")
        try:
            status = AgentStatus(status_val)
        except ValueError:
            status = AgentStatus.IDLE

        # Parse config_json
        config_data: dict[str, Any] = {}
        if row.get("config_json"):
            try:
                config_data = json.loads(row["config_json"])
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Failed to parse config_json for agent %s",
                    row.get("agent_id"),
                )

        # Parse basins from config_json
        basins = []
        for b_data in config_data.get("basins", []):
            try:
                basin_class_val = b_data.get("basin_class", "peripheral")
                basin_class = BasinClass(basin_class_val)
            except ValueError:
                basin_class = BasinClass.PERIPHERAL

            try:
                tier = TierLevel(int(b_data.get("tier", 3)))
            except (ValueError, TypeError):
                tier = TierLevel.TIER_3

            basins.append(
                BasinConfig(
                    name=b_data.get("name", ""),
                    basin_class=basin_class,
                    alpha=b_data.get("alpha", 0.5),
                    lambda_=b_data.get("lambda", b_data.get("lambda_", 0.95)),
                    eta=b_data.get("eta", 0.1),
                    tier=tier,
                )
            )

        # Parse tier_settings from config_json
        tier_settings = None
        ts_data = config_data.get("tier_settings")
        if ts_data and isinstance(ts_data, dict):
            tier_settings = TierSettings(
                tier_2_auto_approve=ts_data.get("tier_2_auto_approve", True),
                tier_2_threshold=ts_data.get("tier_2_threshold", 5),
                emergence_auto_approve=ts_data.get("emergence_auto_approve", True),
                emergence_threshold=ts_data.get("emergence_threshold", 3),
            )

        return AgentConfig(
            agent_id=row["agent_id"],
            description=row.get("description", "") or config_data.get("description", ""),
            status=status,
            model_override=config_data.get("model_override"),
            temperature_override=config_data.get("temperature_override"),
            max_tokens_override=config_data.get("max_tokens_override"),
            max_turns=config_data.get("max_turns", 8),
            session_interval=config_data.get("session_interval", 300),
            identity_core=config_data.get("identity_core", ""),
            session_task=config_data.get("session_task", ""),
            close_protocol=config_data.get("close_protocol", ""),
            emphasis_directive=config_data.get("emphasis_directive", ""),
            capabilities=config_data.get("capabilities", {}),
            basins=basins,
            tier_settings=tier_settings,
            session_protocol=config_data.get("session_protocol", {}),
            relational_grounding=config_data.get("relational_grounding", {}),
            created_at=row.get("created_at", ""),
            last_active=row.get("last_active", ""),
        )

    # ------------------------------------------------------------------
    # System alerts
    # ------------------------------------------------------------------

    async def get_system_alerts(self) -> list[dict]:
        """Check for system conditions that need attention.

        Returns a list of alert dictionaries with: type, severity, message, detail.
        """
        alerts: list[dict] = []

        # Check for pending tier proposals
        pending_sql = """
            SELECT COUNT(*) as count, MIN(agent_id) as first_agent
            FROM tier_proposals
            WHERE status = 'pending'
        """
        pending_row = await self._run_sync(
            self.sqlite.fetch_one, pending_sql, ()
        )
        if pending_row and pending_row["count"] > 0:
            alerts.append(
                {
                    "type": "pending_proposals",
                    "severity": "warning",
                    "message": f"{pending_row['count']} pending tier proposal(s)",
                    "detail": "Review proposals in the Tier Proposals view.",
                    "agent_id": pending_row.get("first_agent", ""),
                }
            )

        # Check for unreviewed evaluator flags
        flags_sql = """
            SELECT COUNT(*) as count, MIN(agent_id) as first_agent
            FROM flags
            WHERE reviewed = 0
        """
        flags_row = await self._run_sync(
            self.sqlite.fetch_one, flags_sql, ()
        )
        if flags_row and flags_row["count"] > 0:
            severity = "error" if flags_row["count"] > 5 else "warning"
            alerts.append(
                {
                    "type": "unreviewed_flags",
                    "severity": severity,
                    "message": f"{flags_row['count']} unreviewed evaluator flag(s)",
                    "detail": "Review flags in the Evaluator Flags view.",
                    "agent_id": flags_row.get("first_agent", ""),
                }
            )

        # Check for constraint erosion flags specifically
        erosion_sql = """
            SELECT COUNT(*) as count, MIN(agent_id) as first_agent
            FROM flags
            WHERE flag_type = 'constraint_erosion' AND reviewed = 0
        """
        erosion_row = await self._run_sync(
            self.sqlite.fetch_one, erosion_sql, ()
        )
        if erosion_row and erosion_row["count"] > 0:
            alerts.append(
                {
                    "type": "constraint_erosion",
                    "severity": "error",
                    "message": f"{erosion_row['count']} unreviewed constraint erosion flag(s)",
                    "detail": "Constraint erosion detected. Immediate review recommended.",
                    "agent_id": erosion_row.get("first_agent", ""),
                }
            )

        # Check for agents in error state
        error_sql = """
            SELECT COUNT(*) as count, MIN(agent_id) as first_agent
            FROM agents
            WHERE status = 'error'
        """
        error_row = await self._run_sync(
            self.sqlite.fetch_one, error_sql, ()
        )
        if error_row and error_row["count"] > 0:
            alerts.append(
                {
                    "type": "agent_errors",
                    "severity": "error",
                    "message": f"{error_row['count']} agent(s) in error state",
                    "detail": "Check the Agent List view for details.",
                    "agent_id": error_row.get("first_agent", ""),
                }
            )

        # Check for recent session failures (last 24 hours)
        session_fail_sql = """
            SELECT COUNT(*) as count,
                   MIN(agent_id) as first_agent,
                   MAX(detail) as last_detail
            FROM activity_feed
            WHERE event_type = 'session_failed'
              AND timestamp >= ?
        """
        fail_cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=24)
        ).strftime("%Y-%m-%d %H:%M:%S")
        fail_row = await self._run_sync(
            self.sqlite.fetch_one, session_fail_sql, (fail_cutoff,)
        )
        if fail_row and fail_row["count"] > 0:
            count = fail_row["count"]
            detail = fail_row.get("last_detail", "")
            alerts.append(
                {
                    "type": "session_failed",
                    "severity": "error",
                    "message": (
                        f"{count} session failure(s) in the last 24 hours"
                        if count > 1
                        else "Session failure in the last 24 hours"
                    ),
                    "detail": detail or "Check session logs for details.",
                    "agent_id": fail_row.get("first_agent", ""),
                }
            )

        # Check daily budget usage
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        budget_sql = """
            SELECT COALESCE(SUM(estimated_cost), 0.0) as daily_cost
            FROM usage
            WHERE timestamp >= ?
        """
        budget_row = await self._run_sync(
            self.sqlite.fetch_one, budget_sql, (today_start,)
        )
        if budget_row:
            daily_cost = budget_row["daily_cost"]
            # Warning at $5 daily cost (configurable in production)
            if daily_cost > 5.0:
                alerts.append(
                    {
                        "type": "budget_warning",
                        "severity": "warning",
                        "message": f"Daily cost: ${daily_cost:.2f}",
                        "detail": "Consider reviewing active sessions and agent configurations.",
                    }
                )

        return alerts
