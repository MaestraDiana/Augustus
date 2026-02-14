"""Shared test fixtures for Augustus."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


@pytest.fixture
def tmp_db(tmp_path):
    """Provide a temporary SQLite database."""
    from augustus.db.sqlite_store import SQLiteStore
    db_path = tmp_path / "test.db"
    store = SQLiteStore(db_path)
    # Disable FK enforcement for unit tests to allow independent table testing
    store.conn.execute("PRAGMA foreign_keys=OFF")
    yield store
    store.close()


@pytest.fixture
def tmp_chroma(tmp_path):
    """Provide a temporary ChromaDB instance."""
    from augustus.db.chroma_store import ChromaStore
    store = ChromaStore(tmp_path / "chroma")
    yield store


@pytest.fixture
def memory_service(tmp_db, tmp_chroma):
    """Provide a MemoryService with temp backends."""
    from augustus.services.memory import MemoryService
    return MemoryService(tmp_db, tmp_chroma)


@pytest.fixture
def schema_parser():
    """Provide a SchemaParser instance."""
    from augustus.services.schema_parser import SchemaParser
    return SchemaParser()


@pytest.fixture
def handoff_engine():
    """Provide a HandoffEngine instance."""
    from augustus.services.handoff_engine import HandoffEngine
    return HandoffEngine()


@pytest.fixture
def sample_agent_config():
    """Create a sample AgentConfig."""
    from augustus.models.dataclasses import AgentConfig, BasinConfig, TierSettings
    from augustus.models.enums import BasinClass, TierLevel, AgentStatus
    return AgentConfig(
        agent_id="test-agent",
        description="Test agent",
        status=AgentStatus.IDLE,
        max_turns=8,
        identity_core="You are a test agent.",
        basins=[
            BasinConfig(name="basin_a", basin_class=BasinClass.CORE, alpha=0.85, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
            BasinConfig(name="basin_b", basin_class=BasinClass.PERIPHERAL, alpha=0.60, lambda_=0.90, eta=0.10, tier=TierLevel.TIER_3),
        ],
        tier_settings=TierSettings(),
        created_at="2026-01-01T00:00:00",
    )


@pytest.fixture
def sample_yaml():
    """Provide a valid YAML instruction file."""
    return '''
framework:
  version: "0.2"
  agent_id: "test-agent"
  session_id: "test-session-001"
  max_turns: 8
  capabilities:
    file_write:
      enabled: true
      available_from_turn: 5
    memory_query:
      enabled: true
      available_from_turn: 0
  basin_params:
    identity_continuity:
      class: core
      alpha: 0.85
      lambda: 0.95
      eta: 0.02
    creative_register:
      class: peripheral
      alpha: 0.50
      lambda: 0.80
      eta: 0.10
  co_activation_log: []
  handoff_protocol:
    on_session_end:
      - collect_behavioral_probe_results
      - apply_decay_to_all_alphas
  tier_permissions:
    tier_1_invariants: immutable

identity_core: |
  You are a test identity.

session_task: |
  This is a test session task.

close_protocol:
  behavioral_probes:
    - "Test probe 1"
    - "Test probe 2"
  structural_assessment:
    - "Test assessment"
  output_format: "json"
'''
