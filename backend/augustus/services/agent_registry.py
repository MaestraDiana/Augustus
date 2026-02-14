"""Agent Registry — manages agent lifecycle and directory structure."""

from __future__ import annotations

import json
import logging
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from augustus.exceptions import AgentNotFoundError
from augustus.models.dataclasses import AgentConfig
from augustus.models.enums import AgentStatus
from augustus.utils import DEFAULT_CONTINUATION_TASK

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
        config.created_at = config.created_at or datetime.utcnow().isoformat()
        config.status = config.status or AgentStatus.IDLE

        # Store in memory service
        await self.memory.store_agent(config)

        # Store initial basins if provided
        if config.basins:
            await self.memory.update_current_basins(config.agent_id, config.basins)

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

    async def regenerate_pending_yaml(self, agent_id: str) -> None:
        """Clear stale pending YAML and write a fresh one from current agent config.

        Called after agent edits so the next session uses the updated
        identity_core, session_task, basins, capabilities, etc.
        Does not touch active sessions — they complete with the old config.
        """
        from augustus.services.queue_manager import QueueManager
        from augustus.services.yaml_generator import generate_instruction_yaml

        agent = await self.memory.get_agent(agent_id)
        if not agent:
            raise AgentNotFoundError(f"Agent '{agent_id}' not found")

        agent_dir = self.get_agent_dir(agent_id)
        queue = QueueManager(agent_dir, None)  # schema_parser not needed for clear

        # Clear any pending YAML built from old config
        cleared = queue.clear_pending()
        if cleared:
            logger.info(f"Cleared {cleared} stale pending YAML(s) for '{agent_id}'")

        # Get current basins (may have been updated by handoff or by the edit)
        basins = await self.memory.get_current_basins(agent_id)
        if not basins:
            basins = agent.basins or []

        # Determine session number
        session_count = await self.memory.count_sessions(agent_id)

        if session_count == 0:
            # No sessions yet — regenerate as bootstrap
            self._write_bootstrap_yaml(agent, agent_dir)
        else:
            # Has session history — write a continuation YAML
            from augustus.services.yaml_generator import generate_next_session_yaml

            identity_core = agent.identity_core or f"You are {agent_id}."
            session_task = DEFAULT_CONTINUATION_TASK

            yaml_content = generate_next_session_yaml(
                agent_id=agent_id,
                session_number=session_count + 1,
                max_turns=agent.max_turns or 8,
                basins=basins,
                identity_core=identity_core,
                session_task=session_task,
                close_protocol=agent.close_protocol,
                capabilities=agent.capabilities,
            )

            ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            dest = agent_dir / "queue" / "pending" / f"{ts}_edited.yaml"
            dest.write_text(yaml_content, encoding="utf-8")
            logger.info(f"Wrote regenerated YAML for '{agent_id}': {dest.name}")

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
        zip_path = export_path / f"{agent_id}-export-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.zip"

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

            agent.basins = await self.memory.get_current_basins(agent_id) or agent.basins
            yaml_content = generate_bootstrap_yaml(agent)
            zf.writestr(f"{agent_id}/{agent_id}.yaml", yaml_content)

            # Add agent metadata as JSON (supplementary — not used for import)
            config_data = {
                "agent_id": agent.agent_id,
                "description": agent.description,
                "status": agent.status.value if hasattr(agent.status, "value") else str(agent.status),
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
            ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            filename = f"{ts}_bootstrap.yaml"
            dest = agent_dir / "queue" / "pending" / filename
            dest.write_text(yaml_content, encoding="utf-8")
            logger.info(f"Wrote bootstrap YAML for '{config.agent_id}': {filename}")
        except Exception as e:
            logger.error(f"Failed to write bootstrap YAML for '{config.agent_id}': {e}")

    def get_agent_dir(self, agent_id: str) -> Path:
        """Get agent's root directory."""
        return self.agents_dir / agent_id

