"""Augustus MCP Server — stdio transport for Claude Desktop integration."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from augustus.models.enums import FlagType, ProposalStatus

logger = logging.getLogger(__name__)


class MCPServer:
    """MCP server wrapping Memory Service with project-specific tools."""

    def __init__(self, memory: Any) -> None:
        """Initialize with Memory Service instance.

        Args:
            memory: MemoryService instance for data access.
        """
        self.memory = memory
        self.mcp = FastMCP("augustus")
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all MCP tools on the FastMCP instance."""
        memory = self.memory

        @self.mcp.tool(description="Get a structured summary of a specific session.")
        async def get_session_summary(agent_id: str, session_id: str) -> str:
            session = await memory.get_session(agent_id, session_id)
            if not session:
                return json.dumps({"error": "Session not found"})
            return json.dumps({
                "session_id": session.session_id,
                "agent_id": session.agent_id,
                "start_time": session.start_time,
                "end_time": session.end_time,
                "turn_count": session.turn_count,
                "model": session.model,
                "status": session.status,
            })

        @self.mcp.tool(description="Get alpha trajectory for a specific basin over recent sessions.")
        async def get_basin_trajectory(agent_id: str, basin_name: str, n_sessions: int = 20) -> str:
            trajectory = await memory.get_basin_trajectory(agent_id, basin_name, n_sessions)
            return json.dumps([
                {
                    "session_id": s.session_id,
                    "alpha_start": s.alpha_start,
                    "alpha_end": s.alpha_end,
                    "delta": s.delta,
                    "relevance": s.relevance_score,
                }
                for s in trajectory
            ])

        @self.mcp.tool(description="Get all basin trajectories for an agent.")
        async def get_all_trajectories(agent_id: str, n_sessions: int = 20) -> str:
            trajectories = await memory.get_all_trajectories(agent_id, n_sessions)
            return json.dumps({
                name: [
                    {"alpha_end": s.alpha_end, "delta": s.delta} for s in snaps
                ]
                for name, snaps in trajectories.items()
            })

        @self.mcp.tool(description="Semantic search across session content for an agent.")
        async def search_sessions(agent_id: str, query: str, n_results: int = 5) -> str:
            results = await memory.search_sessions(agent_id, query, n_results)
            return json.dumps([
                {
                    "session_id": r.session_id,
                    "snippet": r.snippet,
                    "relevance": r.relevance_score,
                }
                for r in results
            ])

        @self.mcp.tool(description="Get flagged sessions for an agent. Optional flag_type: constraint_erosion, assessment_divergence, emergent_observation.")
        async def get_evaluator_flags(agent_id: str, flag_type: str | None = None) -> str:
            flags = await memory.get_evaluator_flags(agent_id, flag_type=flag_type)
            return json.dumps([
                {
                    "flag_id": f.flag_id,
                    "session_id": f.session_id,
                    "flag_type": (
                        f.flag_type.value
                        if hasattr(f.flag_type, "value")
                        else str(f.flag_type)
                    ),
                    "severity": f.severity,
                    "detail": f.detail,
                    "reviewed": f.reviewed,
                }
                for f in flags
            ])

        @self.mcp.tool(description="Get tier modification proposals for an agent. Optional status: pending, approved, rejected.")
        async def get_tier_proposals(agent_id: str, status: str | None = None) -> str:
            proposals = await memory.get_tier_proposals(agent_id, status=status)
            return json.dumps([
                {
                    "proposal_id": p.proposal_id,
                    "basin_name": p.basin_name,
                    "tier": p.tier.value if hasattr(p.tier, "value") else p.tier,
                    "status": (
                        p.status.value
                        if hasattr(p.status, "value")
                        else str(p.status)
                    ),
                    "rationale": p.rationale,
                    "consecutive_count": p.consecutive_count,
                }
                for p in proposals
            ])

        @self.mcp.tool(description="List all registered agents with summary statistics.")
        async def list_agents() -> str:
            agents = await memory.list_agents()
            return json.dumps([
                {
                    "agent_id": a.agent_id,
                    "description": a.description,
                    "status": (
                        a.status.value if hasattr(a.status, "value") else str(a.status)
                    ),
                    "last_active": a.last_active,
                }
                for a in agents
            ])

        @self.mcp.tool(description="List recent sessions for an agent.")
        async def list_sessions(agent_id: str, limit: int = 10) -> str:
            sessions = await memory.list_sessions(agent_id, limit=limit)
            return json.dumps([
                {
                    "session_id": s.session_id,
                    "start_time": s.start_time,
                    "turn_count": s.turn_count,
                    "status": s.status,
                }
                for s in sessions
            ])

        @self.mcp.tool(description="Cross-agent semantic search.")
        async def search_all(query: str, n_results: int = 10) -> str:
            results = await memory.search_all_agents(query, n_results)
            return json.dumps([
                {
                    "agent_id": r.agent_id,
                    "session_id": r.session_id,
                    "snippet": r.snippet,
                    "relevance": r.relevance_score,
                }
                for r in results
            ])

        @self.mcp.tool(description="Add a human evaluation note or observation.")
        async def add_observation(agent_id: str, content: str, tags: list[str] | None = None, session_id: str | None = None) -> str:
            from augustus.models.dataclasses import Annotation

            annotation = Annotation(
                annotation_id=str(uuid.uuid4()),
                agent_id=agent_id,
                session_id=session_id,
                content=content,
                tags=tags or [],
                created_at=datetime.utcnow().isoformat(),
            )
            await memory.store_annotation(annotation)
            return json.dumps({"status": "stored", "annotation_id": annotation.annotation_id})

        @self.mcp.tool(description="Search observations and annotations for an agent. Includes both human annotations (from add_observation) and agent emergence observations.")
        async def search_observations(agent_id: str, query: str | None = None, n_results: int = 10) -> str:
            results = await memory.search_observations(agent_id, query, n_results)
            return json.dumps([
                {
                    "content_type": r.content_type,
                    "session_id": r.session_id,
                    "snippet": r.snippet,
                    "relevance": r.relevance_score,
                    "timestamp": r.timestamp,
                }
                for r in results
            ])

        @self.mcp.tool(description="Get all annotations for an agent, optionally filtered to a specific session.")
        async def get_agent_annotations(agent_id: str, session_id: str | None = None) -> str:
            annotations = await memory.get_annotations(agent_id, session_id=session_id)
            return json.dumps([
                {
                    "annotation_id": a.annotation_id,
                    "agent_id": a.agent_id,
                    "session_id": a.session_id,
                    "content": a.content,
                    "tags": a.tags,
                    "created_at": a.created_at,
                }
                for a in annotations
            ])

        @self.mcp.tool(description="Approve a pending tier modification proposal.")
        async def approve_tier_proposal(proposal_id: str) -> str:
            await memory.update_proposal_status(
                proposal_id,
                ProposalStatus.APPROVED,
                resolved_by="mcp_user",
            )
            return json.dumps({"status": "approved"})

        @self.mcp.tool(description="Flag a session for attention.")
        async def flag_session(agent_id: str, session_id: str, flag_type: str, rationale: str) -> str:
            from augustus.models.dataclasses import FlagRecord

            flag = FlagRecord(
                flag_id=str(uuid.uuid4()),
                agent_id=agent_id,
                session_id=session_id,
                flag_type=FlagType(flag_type),
                severity="info",
                detail=rationale,
                reviewed=False,
                review_note=None,
                created_at=datetime.utcnow().isoformat(),
            )
            await memory.store_flag(flag)
            return json.dumps({"status": "flagged", "flag_id": flag.flag_id})

    def run_stdio(self) -> None:
        """Run MCP server over stdio transport."""
        logger.info("Augustus MCP server starting (stdio)")
        self.mcp.run(transport="stdio")


def main() -> None:
    """Entry point for MCP server.

    Uses the same data directory as the Augustus app (via ConfigManager)
    so the MCP server sees the same agents, sessions, and data.
    Override with AUGUSTUS_DATA_DIR env var if needed.
    """
    import os
    from pathlib import Path

    from augustus.db.sqlite_store import SQLiteStore
    from augustus.db.chroma_store import ChromaStore
    from augustus.services.memory import MemoryService

    # Check for explicit override first
    env_dir = os.environ.get("AUGUSTUS_DATA_DIR")
    if env_dir:
        data_dir = Path(os.path.expanduser(env_dir))
        data_dir.mkdir(parents=True, exist_ok=True)
    else:
        # Use ConfigManager to find the same data dir the app uses
        from augustus.config import ConfigManager
        config = ConfigManager()
        data_dir = config.get_data_dir()

    logger.info("MCP server using data directory: %s", data_dir)

    sqlite_store = SQLiteStore(data_dir / "augustus.db")
    chroma_store = ChromaStore(data_dir / "chromadb")
    memory = MemoryService(sqlite_store, chroma_store)
    server = MCPServer(memory)
    server.run_stdio()


if __name__ == "__main__":
    main()
