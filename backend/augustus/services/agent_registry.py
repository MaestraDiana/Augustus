"""Agent Registry — manages agent lifecycle and directory structure."""

from __future__ import annotations

import json
import logging
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from augustus.exceptions import AgentNotFoundError
from augustus.models.dataclasses import AgentConfig
from augustus.models.enums import AgentStatus
from augustus.utils import DEFAULT_CONTINUATION_TASK, enum_val, utcnow_iso

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Manage multiple independent agents with isolated state."""

    QUEUE_DIRS = ["pending", "active", "archive", "error"]

    def __init__(self, data_dir: Path, memory) -> None:
        """Initialize agent registry with data directory and memory service."""
        self.data_dir = data_dir
        self.memory = memory
        self.agents_dir = data_dir / "agents"
        self.agents_dir.mkdir(parents=True, exist_ok=True)

    async def create_agent(self, config: AgentConfig) -> None:
        """Create agent directory tree and register in memory service."""
        agent_dir = self.get_agent_dir(config.agent_id)
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Create queue subdirectories
        for qdir in self.QUEUE_DIRS:
            (agent_dir / "queue" / qdir).mkdir(parents=True, exist_ok=True)

        # Create logs directory
        (agent_dir / "logs").mkdir(parents=True, exist_ok=True)

        # Set timestamps
        config.created_at = config.created_at or utcnow_iso()
        config.status = config.status or AgentStatus.IDLE

        # Store in memory service
        await self.memory.store_agent(config)

        # Store initial basins if provided
        if config.basins:
            await self.memory.update_current_basins(config.agent_id, config.basins)

        # Seed basin_definitions for new agents (v0.9.5)
        if config.basins:
            for basin in config.basins:
                await self.memory.insert_basin_definition(
                    agent_id=config.agent_id,
                    name=basin.name,
                    basin_class=enum_val(basin.basin_class),
                    alpha=basin.alpha,
                    lambda_decay=basin.lambda_,
                    eta=basin.eta,
                    tier=basin.tier.value if hasattr(basin.tier, "value") else int(basin.tier),
                    created_by="import",
                    rationale="Created with agent",
                )
            await self.memory.set_agent_basin_source(config.agent_id, "database")

        # Generate bootstrap YAML and write to queue/pending/
        self._write_bootstrap_yaml(config, agent_dir)

        logger.info(f"Created agent '{config.agent_id}'")

    async def get_agent(self, agent_id: str) -> AgentConfig | None:
        """Get agent configuration."""
        return await self.memory.get_agent(agent_id)

    async def list_agents(self) -> list[AgentConfig]:
        """List all agents."""
        return await self.memory.list_agents()

    async def update_agent(self, agent_id: str, updates: dict) -> None:
        """Update agent configuration."""
        agent = await self.memory.get_agent(agent_id)
        if not agent:
            raise AgentNotFoundError(f"Agent '{agent_id}' not found")
        await self.memory.update_agent(agent_id, updates)
        logger.info(f"Updated agent '{agent_id}': {list(updates.keys())}")

    async def regenerate_pending_yaml(
        self, agent_id: str, changed_fields: set[str] | None = None
    ) -> None:
        """Update any pending handoff YAML to reflect agent config changes.

        Called after agent edits so the next session uses the updated config.
        Does not touch active sessions — they complete with the old config.

        If a pending handoff YAML exists (agent-authored content), only the
        fields present in ``changed_fields`` are patched into it.  Fields not
        in ``changed_fields`` are left exactly as the agent wrote them.
        The original file is archived before being replaced.

        If no pending YAML exists, a fresh one is generated from current config.

        Args:
            agent_id: The agent to update.
            changed_fields: Set of field names that were actually changed by the
                human edit (e.g. ``{"max_turns", "close_protocol"}``).  When
                None (called outside of an edit context), all applicable fields
                are treated as changed.
        """
        import yaml as _yaml
        from augustus.services.queue_manager import QueueManager
        from augustus.services.yaml_generator import (
            generate_next_session_yaml,
            merge_close_protocol,
            SCHEMA_VERSION,
        )
        from augustus.utils import enum_val

        agent = await self.memory.get_agent(agent_id)
        if not agent:
            raise AgentNotFoundError(f"Agent '{agent_id}' not found")

        agent_dir = self.get_agent_dir(agent_id)
        queue = QueueManager(agent_dir, None)  # schema_parser not needed here

        pending_files = queue.list_pending()

        if not pending_files:
            # No pending YAML at all — generate a fresh one from current config
            session_count = await self.memory.count_sessions(agent_id)
            if session_count == 0:
                self._write_bootstrap_yaml(agent, agent_dir)
            else:
                basins = await self.memory.get_current_basins(agent_id)
                if not basins:
                    basins = agent.basins or []

                structural_sections = {}
                if agent.session_protocol:
                    structural_sections["session_protocol"] = agent.session_protocol
                if agent.relational_grounding:
                    structural_sections["relational_grounding"] = agent.relational_grounding

                yaml_content = generate_next_session_yaml(
                    agent_id=agent_id,
                    session_number=session_count + 1,
                    max_turns=agent.max_turns or 8,
                    basins=basins,
                    session_task=DEFAULT_CONTINUATION_TASK,
                    close_protocol=agent.close_protocol,
                    capabilities=agent.capabilities,
                    structural_sections=structural_sections or None,
                )

                ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                dest = agent_dir / "queue" / "pending" / f"{ts}_edited.yaml"
                dest.write_text(yaml_content, encoding="utf-8")
                logger.info(f"Wrote new pending YAML for '{agent_id}': {dest.name}")
            return

        # A pending handoff YAML exists — patch it in place, preserving agent content.
        # Process only the first (oldest) pending file; extras are left untouched.
        handoff_path = pending_files[0]
        original_text = handoff_path.read_text(encoding="utf-8")

        try:
            doc = _yaml.safe_load(original_text)
        except _yaml.YAMLError as exc:
            logger.warning(
                f"Could not parse pending YAML for '{agent_id}' ({handoff_path.name}): {exc}. "
                "Falling back to full replacement."
            )
            # Corrupt YAML — safe to replace it
            handoff_path.unlink()
            await self.regenerate_pending_yaml(agent_id)
            return

        if not isinstance(doc, dict):
            # Not a mapping — replace it
            handoff_path.unlink()
            await self.regenerate_pending_yaml(agent_id)
            return

        # Sentinel: if changed_fields is None, treat every field as changed
        # (called outside a specific edit context — apply all applicable updates).
        all_fields = changed_fields is None

        # ── Patch framework section ──────────────────────────────────────
        framework = doc.get("framework")
        if not isinstance(framework, dict):
            framework = {}
            doc["framework"] = framework

        # Always keep version current
        framework["version"] = SCHEMA_VERSION
        framework["agent_id"] = agent_id

        # max_turns: only update if it was changed in this edit
        if (all_fields or "max_turns" in changed_fields) and agent.max_turns:
            framework["max_turns"] = agent.max_turns

        # capabilities: only update if changed in this edit
        if (all_fields or "capabilities" in changed_fields) and agent.capabilities is not None:
            caps: dict = {}
            for name, val in agent.capabilities.items():
                if isinstance(val, dict):
                    caps[name] = val.get("enabled", True)
                elif isinstance(val, bool):
                    caps[name] = val
                else:
                    caps[name] = True
            if not caps:
                caps = {"mcp": True, "rag": True, "web_search": False}
            framework["capabilities"] = caps

        # basin_params: only update if basins were changed in this edit.
        # Preserve alpha from existing YAML (post-handoff value);
        # update structural params (class, lambda, eta, tier) from current config.
        if all_fields or "basins" in changed_fields:
            basins = await self.memory.get_current_basins(agent_id)
            if not basins:
                basins = agent.basins or []
            if basins:
                existing_basin_params = framework.get("basin_params", {}) or {}
                new_basin_params: dict = {}
                for b in basins:
                    name = b.name
                    existing = existing_basin_params.get(name, {})
                    new_basin_params[name] = {
                        "class": enum_val(b.basin_class),
                        "alpha": existing.get("alpha", round(b.alpha, 4)),
                        "lambda": round(b.lambda_, 4),
                        "eta": round(b.eta, 4),
                        "tier": b.tier.value if hasattr(b.tier, "value") else int(b.tier),
                    }
                framework["basin_params"] = new_basin_params

        # ── Patch structural sections ────────────────────────────────────
        # Only touch these fields if they were actually changed by the human edit.
        if all_fields or "session_protocol" in changed_fields:
            if agent.session_protocol:
                doc["session_protocol"] = agent.session_protocol
            elif "session_protocol" in doc and not agent.session_protocol:
                # Human cleared it — remove from YAML too
                doc.pop("session_protocol", None)

        if all_fields or "relational_grounding" in changed_fields:
            if agent.relational_grounding:
                doc["relational_grounding"] = agent.relational_grounding
            elif "relational_grounding" in doc and not agent.relational_grounding:
                doc.pop("relational_grounding", None)

        # ── close_protocol: merge agent template with agent-written content ──
        # The handoff YAML may contain agent-written close_protocol answers.
        # Merge so the human's template structure is preserved while agent
        # content (if any) is not lost.
        # Only applied if close_protocol was actually changed in this edit.
        if all_fields or "close_protocol" in changed_fields:
            if agent.close_protocol:
                existing_cp = doc.get("close_protocol")
                merged_cp = merge_close_protocol(agent.close_protocol, existing_cp)
                if merged_cp:
                    doc["close_protocol"] = merged_cp

        # ── session_task: never overwrite agent-authored content ─────────
        # The agent wrote the session_task for their next session.  Leave it.
        # (If the human wants to override it they should do so via the queue.)

        # ── Write updated YAML ───────────────────────────────────────────
        # Archive the original first
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        archive_name = f"{ts}_pre-edit_{handoff_path.name}"
        archive_dest = agent_dir / "queue" / "archive" / archive_name
        archive_dest.write_text(original_text, encoding="utf-8")
        logger.info(f"Archived original pending YAML to '{archive_name}'")

        # Write patched YAML back to pending
        updated_text = _yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)
        handoff_path.write_text(updated_text, encoding="utf-8")
        logger.info(f"Patched pending handoff YAML for '{agent_id}': {handoff_path.name}")

    async def delete_agent(self, agent_id: str, hard_delete: bool = False) -> None:
        """Delete agent (archive or hard delete)."""
        agent = await self.memory.get_agent(agent_id)
        if not agent:
            raise AgentNotFoundError(f"Agent '{agent_id}' not found")

        if hard_delete:
            # Remove directory and DB records
            agent_dir = self.get_agent_dir(agent_id)
            if agent_dir.exists():
                shutil.rmtree(agent_dir)
            await self.memory.delete_agent(agent_id, hard_delete=True)
            logger.info(f"Hard-deleted agent '{agent_id}'")
        else:
            # Soft delete — mark as deleted, keep data
            await self.memory.update_agent(agent_id, {"status": "deleted"})
            logger.info(f"Archived agent '{agent_id}'")

    async def pause_agent(self, agent_id: str) -> None:
        """Pause agent queue polling."""
        await self.memory.update_agent(
            agent_id,
            {
                "status": AgentStatus.PAUSED.value,
            },
        )
        logger.info(f"Paused agent '{agent_id}'")

    async def resume_agent(self, agent_id: str) -> None:
        """Resume agent queue polling."""
        await self.memory.update_agent(
            agent_id,
            {
                "status": AgentStatus.ACTIVE.value,
            },
        )
        logger.info(f"Resumed agent '{agent_id}'")

    async def clone_agent(self, source_id: str, new_id: str) -> None:
        """Clone agent with independent copy of configuration and current basins."""
        source = await self.memory.get_agent(source_id)
        if not source:
            raise AgentNotFoundError(f"Source agent '{source_id}' not found")

        # Get current basins
        basins = await self.memory.get_current_basins(source_id)

        # Create new agent config
        new_config = AgentConfig(
            agent_id=new_id,
            description=f"Clone of {source_id}: {source.description}",
            status=AgentStatus.IDLE,
            model_override=source.model_override,
            temperature_override=source.temperature_override,
            max_tokens_override=source.max_tokens_override,
            max_turns=source.max_turns,
            identity_core=source.identity_core,
            session_task=source.session_task,
            close_protocol=source.close_protocol,
            capabilities=source.capabilities.copy() if source.capabilities else {},
            basins=basins,
            tier_settings=source.tier_settings,
        )

        await self.create_agent(new_config)
        logger.info(f"Cloned agent '{source_id}' to '{new_id}'")

    async def export_agent(self, agent_id: str) -> Path:
        """Export agent data as ZIP archive."""
        agent = await self.memory.get_agent(agent_id)
        if not agent:
            raise AgentNotFoundError(f"Agent '{agent_id}' not found")

        export_path = self.data_dir / "exports"
        export_path.mkdir(parents=True, exist_ok=True)
        zip_path = export_path / f"{agent_id}-export-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.zip"

        agent_dir = self.get_agent_dir(agent_id)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add agent directory contents
            if agent_dir.exists():
                for file_path in agent_dir.rglob("*"):
                    if file_path.is_file():
                        arcname = f"{agent_id}/{file_path.relative_to(agent_dir)}"
                        zf.writestr(arcname, file_path.read_text(errors="replace"))

            # Add importable split-schema YAML (primary export artifact)
            from augustus.services.yaml_generator import generate_bootstrap_yaml

            # Use basin_definitions when agent is migrated (v0.9.5+)
            basin_source = await self.memory.get_agent_basin_source(agent_id)
            if basin_source == "database":
                basin_defs = await self.memory.get_basin_definitions(agent_id, include_deprecated=False)
                agent.basins = [bd.to_basin_config() for bd in basin_defs] if basin_defs else (agent.basins or [])
            else:
                agent.basins = await self.memory.get_current_basins(agent_id) or agent.basins
            yaml_content = generate_bootstrap_yaml(agent)
            zf.writestr(f"{agent_id}/{agent_id}.yaml", yaml_content)

            # Add agent metadata as JSON (supplementary — not used for import)
            config_data = {
                "agent_id": agent.agent_id,
                "description": agent.description,
                "status": enum_val(agent.status),
                "model_override": agent.model_override,
                "temperature_override": agent.temperature_override,
                "max_turns": agent.max_turns,
                "created_at": agent.created_at,
            }
            zf.writestr(f"{agent_id}/metadata.json", json.dumps(config_data, indent=2))

        logger.info(f"Exported agent '{agent_id}' to {zip_path}")
        return zip_path

    def _write_bootstrap_yaml(self, config: AgentConfig, agent_dir: Path) -> None:
        """Generate and write bootstrap YAML to the agent's pending queue."""
        from augustus.services.yaml_generator import generate_bootstrap_yaml

        try:
            yaml_content = generate_bootstrap_yaml(config)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            filename = f"{ts}_bootstrap.yaml"
            dest = agent_dir / "queue" / "pending" / filename
            dest.write_text(yaml_content, encoding="utf-8")
            logger.info(f"Wrote bootstrap YAML for '{config.agent_id}': {filename}")
        except Exception as e:
            logger.error(f"Failed to write bootstrap YAML for '{config.agent_id}': {e}")

    def get_agent_dir(self, agent_id: str) -> Path:
        """Get agent's root directory."""
        return self.agents_dir / agent_id

