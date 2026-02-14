"""Main Orchestrator Loop — manages concurrent agent sessions."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from augustus.models.enums import AgentStatus, OrchestratorStatus
from augustus.utils import DEFAULT_CONTINUATION_TASK

logger = logging.getLogger(__name__)


class Orchestrator:
    """Manage the main orchestration loop for all agents."""

    def __init__(
        self,
        agent_registry,
        memory,
        session_manager,
        evaluator,
        handoff,
        schema_parser,
        config,
    ) -> None:
        self.agent_registry = agent_registry
        self.memory = memory
        self.session_manager = session_manager
        self.evaluator = evaluator
        self.handoff = handoff
        self.schema_parser = schema_parser
        self.config = config

        self._status = OrchestratorStatus.PAUSED
        self._running = False
        self._tasks: dict[str, asyncio.Task] = {}
        self._active_sessions: dict[str, str] = {}  # agent_id -> session_id

    @property
    def status(self) -> OrchestratorStatus:
        """Return current orchestrator status."""
        return self._status

    @property
    def active_session_count(self) -> int:
        """Return number of currently active sessions."""
        return len(self._active_sessions)

    async def start(self) -> None:
        """Start the orchestration loop."""
        if self._running:
            return
        self._running = True
        self._status = OrchestratorStatus.RUNNING
        logger.info("Orchestrator starting")

        try:
            while self._running:
                if self._status == OrchestratorStatus.PAUSED:
                    await asyncio.sleep(1)
                    continue

                # Get all active agents
                agents = await self.agent_registry.list_agents()
                active_agents = [
                    a for a in agents
                    if a.status == AgentStatus.ACTIVE or a.status == "active"
                ]

                logger.debug(
                    "ORCH TICK: status=%s, agents=%d active, tasks=%s, active_sessions=%s",
                    self._status.value,
                    len(active_agents),
                    list(self._tasks.keys()),
                    dict(self._active_sessions),
                )

                # Clean up finished tasks FIRST so we can respawn
                finished = [
                    aid for aid, task in self._tasks.items()
                    if task.done()
                ]
                for aid in finished:
                    task = self._tasks.pop(aid)
                    exc = task.exception() if not task.cancelled() else None
                    if exc:
                        logger.error("Agent loop for %s failed: %s", aid, exc)
                    else:
                        logger.info("Agent loop for %s finished cleanly", aid)
                    self._active_sessions.pop(aid, None)

                # Start polling loops for new/restarted agents
                max_concurrent = getattr(self.config, 'max_concurrent_agents', 3) if self.config else 3
                for agent in active_agents:
                    if agent.agent_id not in self._tasks:
                        if len(self._active_sessions) < max_concurrent:
                            logger.info(
                                "ORCH: spawning agent loop for %s", agent.agent_id
                            )
                            task = asyncio.create_task(
                                self._agent_loop(agent.agent_id),
                                name=f"agent-{agent.agent_id}",
                            )
                            self._tasks[agent.agent_id] = task

                poll_interval = getattr(self.config, 'poll_interval', 60) if self.config else 60
                await asyncio.sleep(min(poll_interval, 5))

        except asyncio.CancelledError:
            logger.info("Orchestrator cancelled")
        except Exception as e:
            logger.error("Orchestrator error: %s", e, exc_info=True)
            self._status = OrchestratorStatus.ERROR
        finally:
            self._running = False

    async def stop(self, timeout: float = 5.0) -> None:
        """Graceful shutdown with timeout to prevent hanging."""
        logger.info("Orchestrator stopping")
        self._running = False
        self._status = OrchestratorStatus.PAUSED

        # Cancel all agent loops
        for aid, task in self._tasks.items():
            task.cancel()

        # Wait for all to finish, but don't hang forever
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks.values(), return_exceptions=True),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Orchestrator stop timed out after %.1fs — %d tasks still running",
                    timeout, len(self._tasks),
                )

        self._tasks.clear()
        self._active_sessions.clear()
        logger.info("Orchestrator stopped")

    async def pause(self) -> None:
        """Pause orchestration (active sessions complete)."""
        self._status = OrchestratorStatus.PAUSED
        logger.info("Orchestrator paused")

    async def resume(self) -> None:
        """Resume orchestration."""
        self._status = OrchestratorStatus.RUNNING
        logger.info("Orchestrator resumed")

    async def _agent_loop(self, agent_id: str) -> None:
        """Per-agent polling and session execution loop."""
        from augustus.services.queue_manager import QueueManager
        from augustus.services.yaml_generator import generate_bootstrap_yaml

        logger.info("AGENT LOOP START: %s", agent_id)
        agent_dir = self.agent_registry.get_agent_dir(agent_id)
        queue = QueueManager(agent_dir, self.schema_parser)

        try:
            while self._running and self._status == OrchestratorStatus.RUNNING:
                # Check agent is still active
                agent = await self.agent_registry.get_agent(agent_id)
                if not agent:
                    logger.info("AGENT LOOP: %s — agent not found, exiting", agent_id)
                    break
                if agent.status != AgentStatus.ACTIVE and agent.status != "active":
                    logger.info(
                        "AGENT LOOP: %s — status is '%s', exiting",
                        agent_id,
                        agent.status.value if hasattr(agent.status, 'value') else agent.status,
                    )
                    break

                # Check concurrent session limit
                max_concurrent = getattr(self.config, 'max_concurrent_agents', 3) if self.config else 3
                if len(self._active_sessions) >= max_concurrent and agent_id not in self._active_sessions:
                    logger.debug(
                        "AGENT LOOP: %s — at concurrency limit (%d/%d), waiting",
                        agent_id, len(self._active_sessions), max_concurrent,
                    )
                    await asyncio.sleep(5)
                    continue

                # Poll for new YAML
                pending_count = len(queue.list_pending())
                active_yaml = queue.get_active()
                logger.info(
                    "AGENT LOOP: %s — polling queue: %d pending, active=%s",
                    agent_id,
                    pending_count,
                    active_yaml.name if active_yaml else "none",
                )

                instruction = await queue.poll()
                if instruction is None:
                    # If queue is completely empty, check if we should regenerate
                    if pending_count == 0 and active_yaml is None:
                        logger.info(
                            "AGENT LOOP: %s — queue empty, regenerating YAML",
                            agent_id,
                        )
                        await self._regenerate_yaml_for_agent(agent_id, agent)

                    poll_interval = getattr(self.config, 'poll_interval', 60) if self.config else 60
                    logger.info(
                        "AGENT LOOP: %s — no instruction ready, sleeping %ds",
                        agent_id, poll_interval,
                    )
                    await asyncio.sleep(poll_interval)
                    continue

                # Check session interval — wait if too soon since last session
                interval = getattr(agent, 'session_interval', 0) or 0
                if interval > 0 and agent.last_active:
                    try:
                        last = datetime.fromisoformat(agent.last_active)
                        elapsed = (datetime.utcnow() - last).total_seconds()
                        remaining = interval - elapsed
                        if remaining > 0:
                            logger.info(
                                "AGENT LOOP: %s — interval not reached "
                                "(%.0fs remaining of %ds), sleeping",
                                agent_id, remaining, interval,
                            )
                            # Sleep in 60s chunks so loop stays responsive to
                            # pause/stop signals (re-checks _running each iter)
                            await asyncio.sleep(min(remaining, 60))
                            continue
                    except (ValueError, TypeError):
                        pass  # Malformed last_active — skip interval check

                # Execute session
                session_id = instruction.framework.session_id
                self._active_sessions[agent_id] = session_id
                logger.info(
                    "AGENT LOOP: %s — executing session %s (%d turns)",
                    agent_id, session_id, instruction.framework.max_turns,
                )

                try:
                    if self.session_manager is None:
                        raise RuntimeError(
                            "SessionManager is None — no API key configured. "
                            "Set your Anthropic API key in Settings."
                        )

                    record = await self.session_manager.execute_session(
                        instruction, agent_config=agent
                    )
                    await queue.complete_session(session_id, {
                        "turn_count": str(record.turn_count),
                        "status": record.status,
                    })

                    logger.info(
                        "AGENT LOOP: %s — session %s completed (%d turns, status=%s)",
                        agent_id, session_id, record.turn_count, record.status,
                    )

                except Exception as e:
                    logger.error(
                        "AGENT LOOP: %s — session %s FAILED: %s",
                        agent_id, session_id, e, exc_info=True,
                    )
                    await queue.fail_session(session_id, str(e))
                finally:
                    self._active_sessions.pop(agent_id, None)
                    # Always update last_active, even on error — the agent
                    # *was* active, and the timestamp drives "last run" in the UI
                    try:
                        await self.agent_registry.update_agent(agent_id, {
                            "last_active": datetime.utcnow().isoformat(),
                        })
                    except Exception as e:
                        logger.error(
                            "AGENT LOOP: %s — failed to update last_active: %s",
                            agent_id, e,
                        )

        except asyncio.CancelledError:
            logger.info("AGENT LOOP: %s — cancelled", agent_id)
        except Exception as e:
            logger.error("AGENT LOOP: %s — unhandled error: %s", agent_id, e, exc_info=True)
        finally:
            self._active_sessions.pop(agent_id, None)
            logger.info("AGENT LOOP EXIT: %s", agent_id)

    async def _regenerate_yaml_for_agent(self, agent_id: str, agent) -> None:
        """Regenerate a YAML instruction when the queue is empty.

        This covers the case where a session failed before _execute_close
        could write the next YAML, or where the bootstrap was consumed
        but nothing was queued after it.
        """
        from augustus.services.yaml_generator import generate_bootstrap_yaml, generate_next_session_yaml

        try:
            session_count = await self.memory.count_sessions(agent_id)

            if session_count == 0:
                # No sessions ever ran successfully — regenerate bootstrap
                yaml_content = generate_bootstrap_yaml(agent)
            else:
                # Has history — write continuation
                basins = await self.memory.get_current_basins(agent_id)
                if not basins:
                    basins = agent.basins or []

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

            # Write directly to pending
            agent_dir = self.agent_registry.get_agent_dir(agent_id)
            ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            dest = agent_dir / "queue" / "pending" / f"{ts}_regenerated.yaml"
            dest.write_text(yaml_content, encoding="utf-8")
            logger.info("AGENT LOOP: %s — regenerated YAML: %s", agent_id, dest.name)

        except Exception as e:
            logger.error(
                "AGENT LOOP: %s — YAML regeneration failed: %s",
                agent_id, e, exc_info=True,
            )
