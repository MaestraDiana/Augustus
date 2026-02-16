"""Augustus MCP Server — stdio transport for Claude Desktop integration."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from augustus.models.enums import FlagType, ProposalStatus, ProposalType
from augustus.utils import enum_val, utcnow_iso

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

        @self.mcp.tool(description="Retrieve the complete transcript for a session.")
        async def get_session_transcript(agent_id: str, session_id: str) -> str:
            session = await memory.get_session(agent_id, session_id)
            if not session:
                return json.dumps({"error": "Session not found"})
            if not session.transcript:
                return json.dumps({"error": "No transcript stored for this session"})
            # Return flattened human-readable text plus raw turn data
            from augustus.utils import flatten_transcript
            return json.dumps({
                "session_id": session.session_id,
                "agent_id": session.agent_id,
                "turn_count": session.turn_count,
                "text": flatten_transcript(session.transcript),
                "turns": session.transcript,
            })

        @self.mcp.tool(description="Retrieve the close report for a session.")
        async def get_close_report(agent_id: str, session_id: str) -> str:
            session = await memory.get_session(agent_id, session_id)
            if not session:
                return json.dumps({"error": "Session not found"})
            if not session.close_report:
                return json.dumps({"error": "No close report stored for this session"})
            return json.dumps({
                "session_id": session.session_id,
                "agent_id": session.agent_id,
                "close_report": session.close_report,
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
            await memory.refresh_chroma()
            results = await memory.search_sessions(agent_id, query, n_results)
            return json.dumps([
                {
                    "content_type": r.content_type,
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

        @self.mcp.tool(description="Get tier modification proposals for an agent. Optional status: pending, approved, rejected, approved_with_modifications.")
        async def get_tier_proposals(agent_id: str, status: str | None = None) -> str:
            proposals = await memory.get_tier_proposals(agent_id, status=status)
            results = []
            for p in proposals:
                entry: dict[str, Any] = {
                    "proposal_id": p.proposal_id,
                    "basin_name": p.basin_name,
                    "tier": p.tier.value if hasattr(p.tier, "value") else int(p.tier),
                    "proposal_type": enum_val(p.proposal_type),
                    "status": enum_val(p.status),
                    "rationale": p.rationale,
                    "session_id": p.session_id,
                    "consecutive_count": p.consecutive_count,
                    "created_at": p.created_at,
                    "resolved_at": p.resolved_at,
                    "resolved_by": p.resolved_by,
                }
                if p.proposed_config:
                    entry["suggested_params"] = p.proposed_config.to_dict()
                if p.rejection_rationale:
                    entry["rejection_rationale"] = p.rejection_rationale
                if p.modification_rationale:
                    entry["modification_rationale"] = p.modification_rationale
                if p.original_params:
                    entry["original_params"] = p.original_params.to_dict()
                results.append(entry)
            return json.dumps(results)

        @self.mcp.tool(description="List all registered agents with summary statistics.")
        async def list_agents() -> str:
            agents = await memory.list_agents()
            return json.dumps([
                {
                    "agent_id": a.agent_id,
                    "description": a.description,
                    "status": enum_val(a.status),
                    "last_active": a.last_active,
                }
                for a in agents
            ])

        @self.mcp.tool(description="List recent sessions for an agent. Includes pending review counts.")
        async def list_sessions(agent_id: str, limit: int = 10) -> str:
            sessions = await memory.list_sessions(agent_id, limit=limit)
            pending_proposals = await memory.get_tier_proposals(agent_id, status="pending")
            unreviewed_flags = await memory.get_evaluator_flags(agent_id, reviewed=False)
            return json.dumps({
                "sessions": [
                    {
                        "session_id": s.session_id,
                        "start_time": s.start_time,
                        "turn_count": s.turn_count,
                        "status": s.status,
                    }
                    for s in sessions
                ],
                "pending_review": {
                    "proposals": len(pending_proposals),
                    "flags": len(unreviewed_flags),
                },
            })

        @self.mcp.tool(description="Cross-agent semantic search.")
        async def search_all(query: str, n_results: int = 10) -> str:
            await memory.refresh_chroma()
            results = await memory.search_all_agents(query, n_results)
            return json.dumps([
                {
                    "content_type": r.content_type,
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
                created_at=utcnow_iso(),
            )
            await memory.store_annotation(annotation)
            return json.dumps({"status": "stored", "annotation_id": annotation.annotation_id})

        @self.mcp.tool(description="Search observations and annotations for an agent. Includes both human annotations (from add_observation) and agent emergence observations.")
        async def search_observations(agent_id: str, query: str | None = None, n_results: int = 10) -> str:
            await memory.refresh_chroma()
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
            # Apply the structural change
            proposal = await memory.get_tier_proposal(proposal_id)
            if proposal and proposal.proposed_config:
                await memory.apply_approved_proposal(proposal)
            return json.dumps({"status": "approved", "proposal_id": proposal_id})

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
                created_at=utcnow_iso(),
            )
            await memory.store_flag(flag)
            return json.dumps({"status": "flagged", "flag_id": flag.flag_id})

        # ------------------------------------------------------------------
        # Brain review workflow tools
        # ------------------------------------------------------------------

        @self.mcp.tool(description="Reject a pending tier proposal with rationale. The rationale is stored for the body to learn from.")
        async def reject_tier_proposal(agent_id: str, proposal_id: str, rationale: str) -> str:
            result = await memory.reject_proposal_with_rationale(
                proposal_id, rationale, resolved_by="brain"
            )
            if not result:
                return json.dumps({"error": "Proposal not found"})
            return json.dumps({
                "status": "rejected",
                "proposal_id": proposal_id,
                "basin_name": result.basin_name,
                "rationale": rationale,
            })

        @self.mcp.tool(description="Approve a proposal with modified parameters. Stores original values for comparison and applies the modified change.")
        async def modify_tier_proposal(agent_id: str, proposal_id: str, modifications: dict, rationale: str) -> str:
            result = await memory.modify_and_apply_proposal(
                proposal_id, modifications, rationale, resolved_by="brain"
            )
            if not result:
                return json.dumps({"error": "Proposal not found or has no proposed config"})
            response: dict[str, Any] = {
                "status": "approved_with_modifications",
                "proposal_id": proposal_id,
                "basin_name": result.basin_name,
                "rationale": rationale,
            }
            if result.original_params:
                response["original_params"] = result.original_params.to_dict()
            if result.proposed_config:
                response["modified_params"] = result.proposed_config.to_dict()
            return json.dumps(response)

        @self.mcp.tool(description="Get all items awaiting brain review for an agent: pending proposals and unresolved flags.")
        async def get_pending_review_items(agent_id: str) -> str:
            items = await memory.get_pending_review_items(agent_id)
            return json.dumps(items)

        @self.mcp.tool(description="Resolve an evaluator flag. Resolution types: acknowledged, addressed, dismissed.")
        async def resolve_flag(agent_id: str, flag_id: str, resolution: str, notes: str = "") -> str:
            await memory.resolve_flag(flag_id, resolution, notes, resolved_by="brain")
            return json.dumps({
                "status": "resolved",
                "flag_id": flag_id,
                "resolution": resolution,
            })

        # ------------------------------------------------------------------
        # Direct basin management tools
        # ------------------------------------------------------------------

        @self.mcp.tool(description="Brain-initiated basin creation (bypasses proposal flow). Creates a new basin directly.")
        async def create_basin(
            agent_id: str,
            basin_name: str,
            basin_class: str,
            tier: int,
            alpha: float,
            lambda_decay: float,
            eta: float,
            rationale: str,
        ) -> str:
            try:
                basin = await memory.create_basin_direct(
                    agent_id, basin_name, basin_class, tier, alpha, lambda_decay, eta, rationale
                )
                return json.dumps({
                    "status": "created",
                    "basin": basin.to_dict(),
                    "rationale": rationale,
                })
            except ValueError as e:
                return json.dumps({"error": str(e)})

        @self.mcp.tool(description="Direct basin parameter adjustment (bypasses proposal flow). Modifiable fields: alpha, lambda_decay, eta, tier, basin_class.")
        async def modify_basin(agent_id: str, basin_name: str, modifications: dict, rationale: str) -> str:
            try:
                basin = await memory.modify_basin_direct(
                    agent_id, basin_name, modifications, rationale
                )
                if not basin:
                    return json.dumps({"error": "Basin not found"})
                return json.dumps({
                    "status": "modified",
                    "basin": basin.to_dict(),
                    "rationale": rationale,
                })
            except ValueError as e:
                return json.dumps({"error": str(e)})

        @self.mcp.tool(description="Soft-deprecate a basin. Preserves history but excludes from future sessions. Can be undeprecated.")
        async def deprecate_basin(agent_id: str, basin_name: str, rationale: str) -> str:
            await memory.deprecate_basin(agent_id, basin_name, rationale)
            return json.dumps({
                "status": "deprecated",
                "basin_name": basin_name,
                "rationale": rationale,
            })

        @self.mcp.tool(description="Restore a deprecated basin to active tracking. Re-adds it to the agent config and clears deprecation flags.")
        async def undeprecate_basin(agent_id: str, basin_name: str) -> str:
            basin = await memory.undeprecate_basin(agent_id, basin_name)
            if not basin:
                return json.dumps({"error": f"Basin '{basin_name}' not found in basin_current"})
            return json.dumps({
                "status": "restored",
                "basin": basin.to_dict(),
            })

        # ------------------------------------------------------------------
        # Proposal creation tool
        # ------------------------------------------------------------------

        @self.mcp.tool(description=(
            "Create a proposal that sits in the pending queue for later review. "
            "Use this to flag 'consider changing X' without immediately applying it — "
            "for your own future review, for the body to see, or to mirror what the "
            "body can do (propose rather than dictate). "
            "Actions: create, modify, prune, merge. "
            "Optional suggested_params: {basin_class, alpha, lambda_decay, eta, tier}."
        ))
        async def create_proposal(
            agent_id: str,
            basin_name: str,
            action: str,
            rationale: str,
            suggested_params: dict | None = None,
        ) -> str:
            from augustus.models.dataclasses import BasinConfig, TierProposal
            from augustus.models.enums import BasinClass, TierLevel

            # Validate action
            try:
                proposal_type = ProposalType(action)
            except ValueError:
                return json.dumps({
                    "error": f"Invalid action '{action}'. Must be one of: create, modify, prune, merge"
                })

            # Determine tier from existing basin or default to T3
            current_basins = await memory.get_current_basins(agent_id)
            existing = next((b for b in current_basins if b.name == basin_name), None)

            if existing:
                tier = existing.tier
            else:
                tier = TierLevel.TIER_3

            # Build proposed_config from suggested_params
            proposed_config: BasinConfig | None = None
            if suggested_params:
                try:
                    bc_str = suggested_params.get("basin_class")
                    basin_class = BasinClass(bc_str) if bc_str else (
                        existing.basin_class if existing else BasinClass.PERIPHERAL
                    )
                    alpha = suggested_params.get("alpha",
                        existing.alpha if existing else 0.3
                    )
                    lambda_ = suggested_params.get("lambda_decay",
                        existing.lambda_ if existing else 0.95
                    )
                    eta = suggested_params.get("eta",
                        existing.eta if existing else 0.1
                    )
                    tier_val = suggested_params.get("tier")
                    if tier_val is not None:
                        tier = TierLevel(int(tier_val))

                    proposed_config = BasinConfig(
                        name=basin_name,
                        basin_class=basin_class,
                        alpha=max(0.05, min(1.0, float(alpha))),
                        lambda_=float(lambda_),
                        eta=float(eta),
                        tier=tier,
                    )
                except (ValueError, TypeError) as e:
                    return json.dumps({"error": f"Invalid suggested_params: {e}"})
            elif existing:
                # Store current config as reference even without suggestions
                proposed_config = existing

            proposal_id = f"prop-brain-{agent_id}-{basin_name}-{utcnow_iso()}"
            proposal = TierProposal(
                proposal_id=proposal_id,
                agent_id=agent_id,
                basin_name=basin_name,
                tier=tier,
                proposal_type=proposal_type,
                status=ProposalStatus.PENDING,
                rationale=rationale,
                created_at=utcnow_iso(),
                proposed_config=proposed_config,
            )

            await memory.store_tier_proposal(proposal)
            return json.dumps({
                "status": "created",
                "proposal_id": proposal_id,
                "basin_name": basin_name,
                "action": action,
                "rationale": rationale,
                "note": "Proposal is pending in review queue. Use get_pending_review_items to see it.",
            })

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
