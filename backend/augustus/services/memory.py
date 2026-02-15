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
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from augustus.db.chroma_store import ChromaStore
from augustus.db.sqlite_store import SQLiteStore
from augustus.utils import flatten_transcript, utcnow_iso
from augustus.models import (
    ActivityEvent,
    AgentConfig,
    AgentStatus,
    Annotation,
    BasinClass,
    BasinConfig,
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

    @staticmethod
    def _now() -> str:
        """Return current UTC timestamp as ISO string."""
        return datetime.utcnow().isoformat()

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
            transcript_text = self._transcript_to_text(record.transcript)
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

    @staticmethod
    def _transcript_to_text(transcript: list[dict]) -> str:
        """Flatten a transcript into searchable plain text."""
        return flatten_transcript(transcript)

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
        """Get the current basin configuration for an agent."""
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
                b.basin_class.value if isinstance(b.basin_class, BasinClass) else b.basin_class,
                b.alpha,
                b.lambda_,
                b.eta,
                b.tier.value if isinstance(b.tier, TierLevel) else b.tier,
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

        sql = """
            INSERT OR REPLACE INTO tier_proposals
                (proposal_id, agent_id, basin_name, tier, proposal_type,
                 status, rationale, session_id, consecutive_count,
                 created_at, resolved_at, resolved_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        status_val = status.value if isinstance(status, ProposalStatus) else status
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
        )

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
        chroma_results: dict[str, Any], content_type: str
    ) -> list[SearchResult]:
        """Convert ChromaDB query results to SearchResult dataclass instances."""
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
        self, agent_id: str, session_id: str | None = None
    ) -> list[Annotation]:
        """Get annotations for an agent, optionally filtered to a session."""
        if session_id is not None:
            sql = """
                SELECT * FROM annotations
                WHERE agent_id = ? AND session_id = ?
                ORDER BY created_at DESC
            """
            rows = await self._run_sync(
                self.sqlite.fetch_all, sql, (agent_id, session_id)
            )
        else:
            sql = """
                SELECT * FROM annotations
                WHERE agent_id = ?
                ORDER BY created_at DESC
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
        """
        results: list[SearchResult] = []

        if query:
            # Semantic search across both collections
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
                            chroma_results, content_type
                        )
                    )
                except Exception as e:
                    logger.warning("Observation search (%s) failed: %s", collection, e)
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

    async def search_annotations(
        self, agent_id: str, query: str, n_results: int = 5
    ) -> list[Annotation]:
        """Search annotations for an agent by semantic similarity."""
        try:
            chroma_results = await self._run_sync(
                self.chroma.query,
                "annotations",
                query,
                n_results,
                {"agent_id": agent_id},
            )
        except Exception as e:
            logger.warning("Annotation search failed: %s", e)
            return []

        # Extract annotation IDs from results and fetch full records from SQLite
        ids = chroma_results.get("ids", [[]])[0]
        annotations = []
        for doc_id in ids:
            # doc_id format: "{agent_id}:annotation:{annotation_id}"
            parts = doc_id.split(":", 2)
            if len(parts) >= 3:
                annotation_id = parts[2]
                sql = """
                    SELECT * FROM annotations
                    WHERE annotation_id = ?
                """
                row = await self._run_sync(
                    self.sqlite.fetch_one, sql, (annotation_id,)
                )
                if row:
                    annotations.append(self._row_to_annotation(row))

        return annotations

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
        now = datetime.utcnow()
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
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

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
            "capabilities": config.capabilities,
            "session_interval": config.session_interval,
            "basins": [
                {
                    "name": b.name,
                    "basin_class": b.basin_class.value if isinstance(b.basin_class, BasinClass) else b.basin_class,
                    "alpha": b.alpha,
                    "lambda_": b.lambda_,
                    "eta": b.eta,
                    "tier": b.tier.value if isinstance(b.tier, TierLevel) else b.tier,
                }
                for b in config.basins
            ],
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
            # Detach usage records from session FK before cascading deletes.
            # Usage records are preserved independently for billing visibility.
            await self._run_sync(
                self.sqlite.execute,
                "UPDATE usage SET session_id = '' WHERE agent_id = ?",
                (agent_id,),
            )

            # Delete from agents table — CASCADE removes sessions, basin_snapshots,
            # basin_current, tier_proposals, annotations, flags, co_activation_log.
            # Usage records survive because the FK on agent_id has no CASCADE.
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
                    lambda_=b_data.get("lambda_", 0.95),
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

        # Check daily budget usage
        today_start = datetime.utcnow().replace(
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
