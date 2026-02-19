"""Tests for Basin Definitions — v0.9.5 basin architecture overhaul.

Covers:
  - Schema & table existence
  - BasinDefinition CRUD (insert, get, update, upsert, to_basin_config)
  - Lock & alpha bounds enforcement
  - Deprecation workflow
  - Audit trail (basin_modifications)
  - Lazy per-agent migration from YAML to database
  - Race-condition-like scenarios (brain lock persistence)
"""

import json

import pytest

from augustus.models.dataclasses import (
    AgentConfig,
    BasinConfig,
    BasinDefinition,
    BasinModification,
    TierSettings,
)
from augustus.models.enums import (
    AgentStatus,
    BasinClass,
    TierLevel,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_agent(agent_id: str = "test-agent", basins: list[BasinConfig] | None = None) -> AgentConfig:
    """Build a minimal AgentConfig for testing."""
    if basins is None:
        basins = [
            BasinConfig(
                name="basin_a",
                basin_class=BasinClass.CORE,
                alpha=0.85,
                lambda_=0.95,
                eta=0.02,
                tier=TierLevel.TIER_2,
            ),
            BasinConfig(
                name="basin_b",
                basin_class=BasinClass.PERIPHERAL,
                alpha=0.60,
                lambda_=0.90,
                eta=0.10,
                tier=TierLevel.TIER_3,
            ),
        ]
    return AgentConfig(
        agent_id=agent_id,
        description="Test agent for basin definitions",
        status=AgentStatus.IDLE,
        max_turns=8,
        identity_core="You are a test agent.",
        basins=basins,
        tier_settings=TierSettings(),
        created_at="2026-01-01T00:00:00",
    )


# ======================================================================
# 1. Schema & Migration Tests
# ======================================================================


@pytest.mark.asyncio
class TestBasinSchema:
    """Test that new tables, columns, and indexes exist."""

    async def test_basin_definitions_table_exists(self, tmp_db):
        """Verify basin_definitions table was created by schema init."""
        row = tmp_db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='basin_definitions'"
        )
        assert row is not None
        assert row["name"] == "basin_definitions"

    async def test_basin_modifications_table_exists(self, tmp_db):
        """Verify basin_modifications table was created by schema init."""
        row = tmp_db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='basin_modifications'"
        )
        assert row is not None
        assert row["name"] == "basin_modifications"

    async def test_agents_basin_source_column(self, tmp_db):
        """Verify agents.basin_source column exists and defaults to 'yaml'."""
        # Insert a minimal agent row without specifying basin_source
        tmp_db.execute(
            "INSERT INTO agents (agent_id, description) VALUES (?, ?)",
            ("schema-test", "Schema test agent"),
        )
        row = tmp_db.fetch_one(
            "SELECT basin_source FROM agents WHERE agent_id = ?",
            ("schema-test",),
        )
        assert row is not None
        assert row["basin_source"] == "yaml"

    async def test_basin_definitions_indexes(self, tmp_db):
        """Verify indexes on basin_definitions were created."""
        rows = tmp_db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='basin_definitions'"
        )
        index_names = {r["name"] for r in rows}
        assert "idx_basin_definitions_agent" in index_names
        assert "idx_basin_definitions_deprecated" in index_names

    async def test_basin_modifications_indexes(self, tmp_db):
        """Verify indexes on basin_modifications were created."""
        rows = tmp_db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='basin_modifications'"
        )
        index_names = {r["name"] for r in rows}
        assert "idx_basin_modifications_basin" in index_names
        assert "idx_basin_modifications_agent" in index_names
        assert "idx_basin_modifications_session" in index_names

    async def test_basin_definitions_unique_constraint(self, tmp_db):
        """Verify (agent_id, name) uniqueness constraint on basin_definitions."""
        tmp_db.execute(
            "INSERT INTO agents (agent_id) VALUES (?)", ("uniq-agent",)
        )
        tmp_db.execute(
            "INSERT INTO basin_definitions (agent_id, name) VALUES (?, ?)",
            ("uniq-agent", "unique_basin"),
        )
        with pytest.raises(Exception):
            tmp_db.execute(
                "INSERT INTO basin_definitions (agent_id, name) VALUES (?, ?)",
                ("uniq-agent", "unique_basin"),
            )


# ======================================================================
# 2. BasinDefinition CRUD Tests
# ======================================================================


@pytest.mark.asyncio
class TestBasinDefinitionCRUD:
    """Test CRUD operations on basin_definitions."""

    async def test_insert_basin_definition(self, memory_service, sample_agent_config):
        """Insert a basin definition and verify all fields."""
        await memory_service.store_agent(sample_agent_config)

        bd = await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="test_basin",
            basin_class="core",
            alpha=0.85,
            lambda_decay=0.95,
            eta=0.02,
            tier=2,
            created_by="brain",
            rationale="Test creation",
        )

        assert bd is not None
        assert bd.name == "test_basin"
        assert bd.basin_class == BasinClass.CORE
        assert bd.alpha == 0.85
        assert bd.lambda_ == 0.95
        assert bd.eta == 0.02
        assert bd.tier == TierLevel.TIER_2
        assert bd.locked_by_brain is False
        assert bd.deprecated is False
        assert bd.created_by == "brain"
        assert bd.last_modified_by == "brain"
        assert bd.last_rationale == "Test creation"
        assert bd.alpha_floor is None
        assert bd.alpha_ceiling is None
        assert bd.agent_id == sample_agent_config.agent_id
        assert bd.id is not None

    async def test_get_basin_definitions_excludes_deprecated(self, memory_service, sample_agent_config):
        """Default query excludes deprecated basins."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="active_basin",
            basin_class="core",
            alpha=0.80,
            created_by="brain",
        )
        bd_deprecated = await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="deprecated_basin",
            basin_class="peripheral",
            alpha=0.50,
            created_by="brain",
        )
        # Deprecate the second basin
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "deprecated_basin",
            {"deprecated": 1, "deprecated_at": "2026-02-01", "deprecation_rationale": "No longer relevant"},
            modified_by="brain",
        )

        basins = await memory_service.get_basin_definitions(sample_agent_config.agent_id)
        names = [b.name for b in basins]
        assert "active_basin" in names
        assert "deprecated_basin" not in names

    async def test_get_basin_definitions_includes_deprecated(self, memory_service, sample_agent_config):
        """include_deprecated=True returns all basins."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="active_basin",
            created_by="brain",
        )
        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="deprecated_basin",
            created_by="brain",
        )
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "deprecated_basin",
            {"deprecated": 1},
            modified_by="brain",
        )

        basins = await memory_service.get_basin_definitions(
            sample_agent_config.agent_id, include_deprecated=True
        )
        names = [b.name for b in basins]
        assert "active_basin" in names
        assert "deprecated_basin" in names

    async def test_get_single_basin_definition(self, memory_service, sample_agent_config):
        """Get a specific basin by name."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="specific_basin",
            basin_class="core",
            alpha=0.77,
            lambda_decay=0.92,
            eta=0.05,
            tier=2,
            created_by="brain",
        )

        bd = await memory_service.get_basin_definition(
            sample_agent_config.agent_id, "specific_basin"
        )
        assert bd is not None
        assert bd.name == "specific_basin"
        assert bd.alpha == 0.77
        assert bd.lambda_ == 0.92
        assert bd.eta == 0.05
        assert bd.basin_class == BasinClass.CORE

    async def test_get_nonexistent_basin_returns_none(self, memory_service, sample_agent_config):
        """Getting a nonexistent basin returns None."""
        await memory_service.store_agent(sample_agent_config)

        bd = await memory_service.get_basin_definition(
            sample_agent_config.agent_id, "does_not_exist"
        )
        assert bd is None

    async def test_update_basin_definition(self, memory_service, sample_agent_config):
        """Update basin fields and verify changes persisted."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="updatable",
            basin_class="peripheral",
            alpha=0.50,
            lambda_decay=0.90,
            eta=0.10,
            tier=3,
            created_by="brain",
        )

        updated = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "updatable",
            {"alpha": 0.75, "basin_class": "core", "tier": 2},
            modified_by="brain",
            rationale="Promoting basin to core",
        )

        assert updated is not None
        assert updated.alpha == 0.75
        assert updated.basin_class == BasinClass.CORE
        assert updated.tier == TierLevel.TIER_2
        assert updated.last_modified_by == "brain"
        assert updated.last_rationale == "Promoting basin to core"
        # lambda_ and eta should be unchanged
        assert updated.lambda_ == 0.90
        assert updated.eta == 0.10

    async def test_update_nonexistent_basin_returns_none(self, memory_service, sample_agent_config):
        """Updating a nonexistent basin returns None."""
        await memory_service.store_agent(sample_agent_config)

        result = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "ghost_basin",
            {"alpha": 0.99},
            modified_by="brain",
        )
        assert result is None

    async def test_upsert_creates_if_not_exists(self, memory_service, sample_agent_config):
        """Upsert creates a new basin when it doesn't exist."""
        await memory_service.store_agent(sample_agent_config)

        bd = await memory_service.upsert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="new_upserted",
            params={"basin_class": "core", "alpha": 0.70, "lambda": 0.88, "eta": 0.05, "tier": 2},
            modified_by="import",
            rationale="Created via upsert",
        )

        assert bd is not None
        assert bd.name == "new_upserted"
        assert bd.basin_class == BasinClass.CORE
        assert bd.alpha == 0.70
        assert bd.lambda_ == 0.88
        assert bd.eta == 0.05
        assert bd.tier == TierLevel.TIER_2

    async def test_upsert_updates_if_exists(self, memory_service, sample_agent_config):
        """Upsert updates an existing basin."""
        await memory_service.store_agent(sample_agent_config)

        # First create
        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="existing_upsert",
            basin_class="peripheral",
            alpha=0.40,
            created_by="import",
        )

        # Now upsert with new values
        bd = await memory_service.upsert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="existing_upsert",
            params={"alpha": 0.65, "basin_class": "core"},
            modified_by="body",
            rationale="Body updated via upsert",
        )

        assert bd is not None
        assert bd.alpha == 0.65
        assert bd.basin_class == BasinClass.CORE
        assert bd.last_modified_by == "body"

    async def test_to_basin_config_conversion(self, memory_service, sample_agent_config):
        """BasinDefinition.to_basin_config() creates correct BasinConfig."""
        await memory_service.store_agent(sample_agent_config)

        bd = await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="convertible",
            basin_class="core",
            alpha=0.82,
            lambda_decay=0.93,
            eta=0.03,
            tier=2,
            created_by="brain",
        )

        bc = bd.to_basin_config()
        assert isinstance(bc, BasinConfig)
        assert bc.name == "convertible"
        assert bc.basin_class == BasinClass.CORE
        assert bc.alpha == 0.82
        assert bc.lambda_ == 0.93
        assert bc.eta == 0.03
        assert bc.tier == TierLevel.TIER_2

    async def test_to_dict_serialization(self, memory_service, sample_agent_config):
        """BasinDefinition.to_dict() produces expected JSON-serializable dict."""
        await memory_service.store_agent(sample_agent_config)

        bd = await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="serializable",
            basin_class="core",
            alpha=0.88,
            lambda_decay=0.91,
            eta=0.04,
            tier=2,
            created_by="brain",
        )

        d = bd.to_dict()
        assert d["name"] == "serializable"
        assert d["basin_class"] == "core"
        assert d["alpha"] == 0.88
        assert d["lambda"] == 0.91
        assert d["eta"] == 0.04
        assert d["tier"] == 2
        assert d["locked_by_brain"] is False
        assert d["deprecated"] is False
        assert d["alpha_floor"] is None
        assert d["alpha_ceiling"] is None
        # Verify JSON-serializable
        json.dumps(d)

    async def test_insert_multiple_basins_for_same_agent(self, memory_service, sample_agent_config):
        """Multiple basins can be inserted for the same agent."""
        await memory_service.store_agent(sample_agent_config)

        for i in range(5):
            await memory_service.insert_basin_definition(
                agent_id=sample_agent_config.agent_id,
                name=f"multi_{i}",
                alpha=0.5 + i * 0.1,
                created_by="brain",
            )

        basins = await memory_service.get_basin_definitions(sample_agent_config.agent_id)
        assert len(basins) == 5
        names = sorted([b.name for b in basins])
        assert names == ["multi_0", "multi_1", "multi_2", "multi_3", "multi_4"]


# ======================================================================
# 3. Lock & Bounds Tests
# ======================================================================


@pytest.mark.asyncio
class TestBasinLocking:
    """Test brain lock and alpha bounds."""

    async def test_lock_basin(self, memory_service, sample_agent_config):
        """Locking a basin sets locked_by_brain=True."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="lockable",
            alpha=0.80,
            created_by="brain",
        )

        updated = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "lockable",
            {"locked_by_brain": 1},
            modified_by="brain",
            rationale="Locking for stability",
        )

        assert updated is not None
        assert updated.locked_by_brain is True

    async def test_locked_basin_rejects_body_modification(self, memory_service, sample_agent_config):
        """Body cannot modify a locked basin (returns None)."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="locked_basin",
            alpha=0.80,
            created_by="brain",
        )

        # Lock it
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "locked_basin",
            {"locked_by_brain": 1},
            modified_by="brain",
        )

        # Body tries to update — should be rejected
        result = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "locked_basin",
            {"alpha": 0.99},
            modified_by="body",
        )
        assert result is None

        # Verify original alpha unchanged
        bd = await memory_service.get_basin_definition(
            sample_agent_config.agent_id, "locked_basin"
        )
        assert bd.alpha == 0.80

    async def test_brain_can_modify_locked_basin(self, memory_service, sample_agent_config):
        """Brain can modify a locked basin (brain is the locker)."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="brain_locked",
            alpha=0.80,
            created_by="brain",
        )
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "brain_locked",
            {"locked_by_brain": 1},
            modified_by="brain",
        )

        # Brain modifies it — should succeed since modified_by='brain'
        result = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "brain_locked",
            {"alpha": 0.90},
            modified_by="brain",
        )
        assert result is not None
        assert result.alpha == 0.90

    async def test_brain_can_override_lock(self, memory_service, sample_agent_config):
        """Brain can modify locked basin with override_lock=True."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="override_test",
            alpha=0.80,
            created_by="brain",
        )
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "override_test",
            {"locked_by_brain": 1},
            modified_by="brain",
        )

        # A non-brain actor uses override_lock=True
        result = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "override_test",
            {"alpha": 0.55},
            modified_by="import",
            override_lock=True,
        )
        assert result is not None
        assert result.alpha == 0.55

    async def test_set_alpha_bounds(self, memory_service, sample_agent_config):
        """Setting alpha floor and ceiling."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="bounded",
            alpha=0.70,
            created_by="brain",
        )

        updated = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "bounded",
            {"alpha_floor": 0.30, "alpha_ceiling": 0.90},
            modified_by="brain",
            rationale="Setting safety bounds",
        )

        assert updated is not None
        assert updated.alpha_floor == 0.30
        assert updated.alpha_ceiling == 0.90
        assert updated.alpha == 0.70  # unchanged

    async def test_alpha_floor_enforced_on_body_update(self, memory_service, sample_agent_config):
        """Alpha floor is clamped when body tries to write below it."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="floored",
            alpha=0.70,
            created_by="brain",
        )
        # Set floor
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "floored",
            {"alpha_floor": 0.40},
            modified_by="brain",
            rationale="Setting floor",
        )

        # Body posts a handoff alpha below the floor
        result = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "floored",
            {"alpha": 0.316},
            modified_by="body",
            rationale="Post-handoff update",
        )

        assert result is not None
        assert result.alpha == 0.40  # clamped to floor

    async def test_alpha_floor_enforced_logs_warning(self, memory_service, sample_agent_config, caplog):
        """A warning is logged when alpha is clamped to the floor."""
        import logging
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="floored_log",
            alpha=0.70,
            created_by="brain",
        )
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "floored_log",
            {"alpha_floor": 0.40},
            modified_by="brain",
        )

        with caplog.at_level(logging.WARNING, logger="augustus.services.memory"):
            await memory_service.update_basin_definition(
                sample_agent_config.agent_id,
                "floored_log",
                {"alpha": 0.25},
                modified_by="body",
                rationale="Post-handoff update",
            )

        assert any("below floor" in r.message for r in caplog.records)

    async def test_alpha_ceiling_enforced_on_body_update(self, memory_service, sample_agent_config):
        """Alpha ceiling is clamped when body tries to write above it."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="ceilinged",
            alpha=0.50,
            created_by="brain",
        )
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "ceilinged",
            {"alpha_ceiling": 0.70},
            modified_by="brain",
            rationale="Setting ceiling",
        )

        result = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "ceilinged",
            {"alpha": 0.85},
            modified_by="body",
            rationale="Post-handoff update",
        )

        assert result is not None
        assert result.alpha == 0.70  # clamped to ceiling

    async def test_alpha_within_bounds_passes_through(self, memory_service, sample_agent_config):
        """Alpha within floor/ceiling range is written unchanged."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="in_bounds",
            alpha=0.50,
            created_by="brain",
        )
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "in_bounds",
            {"alpha_floor": 0.30, "alpha_ceiling": 0.80},
            modified_by="brain",
        )

        result = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "in_bounds",
            {"alpha": 0.55},
            modified_by="body",
            rationale="Post-handoff update",
        )

        assert result is not None
        assert result.alpha == 0.55  # no clamping

    async def test_alpha_no_bounds_passes_through(self, memory_service, sample_agent_config):
        """Alpha writes are unconstrained when no bounds are set."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="unbounded",
            alpha=0.70,
            created_by="brain",
        )

        result = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "unbounded",
            {"alpha": 0.12},
            modified_by="body",
            rationale="Post-handoff update",
        )

        assert result is not None
        assert result.alpha == 0.12  # no bounds, passes through

    async def test_unlock_basin(self, memory_service, sample_agent_config):
        """Unlocking a basin clears the lock."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="unlockable",
            alpha=0.80,
            created_by="brain",
        )

        # Lock
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "unlockable",
            {"locked_by_brain": 1},
            modified_by="brain",
        )
        bd = await memory_service.get_basin_definition(
            sample_agent_config.agent_id, "unlockable"
        )
        assert bd.locked_by_brain is True

        # Unlock
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "unlockable",
            {"locked_by_brain": 0},
            modified_by="brain",
            rationale="Releasing lock",
        )
        bd = await memory_service.get_basin_definition(
            sample_agent_config.agent_id, "unlockable"
        )
        assert bd.locked_by_brain is False

    async def test_body_can_modify_after_unlock(self, memory_service, sample_agent_config):
        """After unlocking, body can modify the basin again."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="lock_unlock",
            alpha=0.80,
            created_by="brain",
        )

        # Lock, then unlock
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "lock_unlock",
            {"locked_by_brain": 1},
            modified_by="brain",
        )
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "lock_unlock",
            {"locked_by_brain": 0},
            modified_by="brain",
        )

        # Body now modifies
        result = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "lock_unlock",
            {"alpha": 0.65},
            modified_by="body",
        )
        assert result is not None
        assert result.alpha == 0.65


# ======================================================================
# 4. Deprecation Tests
# ======================================================================


@pytest.mark.asyncio
class TestBasinDeprecation:
    """Test deprecation workflow via basin_definitions."""

    async def test_deprecate_basin_via_definition(self, memory_service, sample_agent_config):
        """Deprecating sets deprecated=True with timestamp and rationale."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="to_deprecate",
            alpha=0.50,
            created_by="brain",
        )

        updated = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "to_deprecate",
            {
                "deprecated": 1,
                "deprecated_at": "2026-02-17T10:00:00",
                "deprecation_rationale": "No longer relevant to identity",
            },
            modified_by="brain",
            rationale="Deprecation decision",
        )

        assert updated is not None
        assert updated.deprecated is True
        assert updated.deprecated_at == "2026-02-17T10:00:00"
        assert updated.deprecation_rationale == "No longer relevant to identity"

    async def test_undeprecate_basin_via_definition(self, memory_service, sample_agent_config):
        """Undeprecating clears deprecation fields."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="to_undeprecate",
            alpha=0.50,
            created_by="brain",
        )

        # Deprecate
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "to_undeprecate",
            {
                "deprecated": 1,
                "deprecated_at": "2026-02-17T10:00:00",
                "deprecation_rationale": "Temporary deprecation",
            },
            modified_by="brain",
        )

        # Verify deprecated
        bd = await memory_service.get_basin_definition(
            sample_agent_config.agent_id, "to_undeprecate"
        )
        assert bd.deprecated is True

        # Undeprecate
        updated = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "to_undeprecate",
            {
                "deprecated": 0,
                "deprecated_at": None,
                "deprecation_rationale": None,
            },
            modified_by="brain",
            rationale="Restoring basin",
        )

        assert updated is not None
        assert updated.deprecated is False

    async def test_deprecated_basin_excluded_from_default_query(self, memory_service, sample_agent_config):
        """Deprecated basins are excluded from default get_basin_definitions."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="visible",
            created_by="brain",
        )
        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="hidden",
            created_by="brain",
        )
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "hidden",
            {"deprecated": 1},
            modified_by="brain",
        )

        default_basins = await memory_service.get_basin_definitions(sample_agent_config.agent_id)
        all_basins = await memory_service.get_basin_definitions(
            sample_agent_config.agent_id, include_deprecated=True
        )

        assert len(default_basins) == 1
        assert default_basins[0].name == "visible"
        assert len(all_basins) == 2


# ======================================================================
# 5. Audit Trail Tests
# ======================================================================


@pytest.mark.asyncio
class TestBasinAuditTrail:
    """Test modification audit trail."""

    async def test_create_generates_audit_entry(self, memory_service, sample_agent_config):
        """Creating a basin generates a 'create' audit entry."""
        await memory_service.store_agent(sample_agent_config)

        bd = await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="audited_create",
            basin_class="core",
            alpha=0.80,
            created_by="brain",
            rationale="Initial creation",
        )

        mods = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="audited_create"
        )
        assert len(mods) >= 1
        create_mod = mods[-1]  # Should be oldest (list is reverse chronological)
        assert create_mod.modification_type == "create"
        assert create_mod.modified_by == "brain"
        assert create_mod.rationale == "Initial creation"
        assert create_mod.previous_values is None
        assert create_mod.new_values is not None
        assert create_mod.new_values["alpha"] == 0.80
        assert create_mod.new_values["basin_class"] == "core"

    async def test_update_generates_audit_entry(self, memory_service, sample_agent_config):
        """Updating a basin generates an 'update' audit entry with previous values."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="audited_update",
            alpha=0.60,
            created_by="brain",
        )

        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "audited_update",
            {"alpha": 0.75, "eta": 0.05},
            modified_by="body",
            rationale="Adjusting alpha",
        )

        mods = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="audited_update"
        )
        # Find the update entry (timestamps may collide within the same test)
        update_mods = [m for m in mods if m.modification_type == "update"]
        assert len(update_mods) == 1
        update_mod = update_mods[0]
        assert update_mod.modified_by == "body"
        assert update_mod.rationale == "Adjusting alpha"
        # Previous values captured
        assert update_mod.previous_values is not None
        assert update_mod.previous_values["alpha"] == 0.60
        # New values
        assert update_mod.new_values["alpha"] == 0.75
        assert update_mod.new_values["eta"] == 0.05

    async def test_lock_generates_audit_entry(self, memory_service, sample_agent_config):
        """Locking generates a 'lock' audit entry."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="audited_lock",
            alpha=0.70,
            created_by="brain",
        )

        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "audited_lock",
            {"locked_by_brain": 1},
            modified_by="brain",
            rationale="Protecting core basin",
        )

        mods = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="audited_lock"
        )
        lock_mods = [m for m in mods if m.modification_type == "lock"]
        assert len(lock_mods) == 1
        lock_mod = lock_mods[0]
        assert lock_mod.modified_by == "brain"
        assert lock_mod.previous_values["locked_by_brain"] is False

    async def test_unlock_generates_audit_entry(self, memory_service, sample_agent_config):
        """Unlocking generates an 'unlock' audit entry."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="audited_unlock",
            alpha=0.70,
            created_by="brain",
        )
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "audited_unlock",
            {"locked_by_brain": 1},
            modified_by="brain",
        )
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "audited_unlock",
            {"locked_by_brain": 0},
            modified_by="brain",
            rationale="Releasing lock",
        )

        mods = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="audited_unlock"
        )
        unlock_mods = [m for m in mods if m.modification_type == "unlock"]
        assert len(unlock_mods) == 1

    async def test_deprecate_generates_audit_entry(self, memory_service, sample_agent_config):
        """Deprecation generates a 'deprecate' audit entry."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="audited_deprecate",
            alpha=0.50,
            created_by="brain",
        )

        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "audited_deprecate",
            {"deprecated": 1, "deprecated_at": "2026-02-17"},
            modified_by="brain",
            rationale="Deprecating for cleanup",
        )

        mods = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="audited_deprecate"
        )
        dep_mods = [m for m in mods if m.modification_type == "deprecate"]
        assert len(dep_mods) == 1
        assert dep_mods[0].rationale == "Deprecating for cleanup"

    async def test_undeprecate_generates_audit_entry(self, memory_service, sample_agent_config):
        """Undeprecation generates an 'undeprecate' audit entry."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="audited_undep",
            alpha=0.50,
            created_by="brain",
        )
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "audited_undep",
            {"deprecated": 1},
            modified_by="brain",
        )
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "audited_undep",
            {"deprecated": 0},
            modified_by="brain",
            rationale="Restoring basin",
        )

        mods = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="audited_undep"
        )
        undep_mods = [m for m in mods if m.modification_type == "undeprecate"]
        assert len(undep_mods) == 1

    async def test_set_bounds_generates_audit_entry(self, memory_service, sample_agent_config):
        """Setting alpha bounds generates a 'set_bounds' audit entry."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="audited_bounds",
            alpha=0.70,
            created_by="brain",
        )

        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "audited_bounds",
            {"alpha_floor": 0.20, "alpha_ceiling": 0.95},
            modified_by="brain",
            rationale="Setting bounds",
        )

        mods = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="audited_bounds"
        )
        bounds_mods = [m for m in mods if m.modification_type == "set_bounds"]
        assert len(bounds_mods) == 1

    async def test_audit_trail_ordered_by_time(self, memory_service, sample_agent_config):
        """Modifications returned in reverse chronological order (or equal timestamps)."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="ordered",
            alpha=0.50,
            created_by="brain",
        )

        # Perform multiple updates
        for i in range(5):
            await memory_service.update_basin_definition(
                sample_agent_config.agent_id,
                "ordered",
                {"alpha": 0.50 + (i + 1) * 0.05},
                modified_by="body",
                rationale=f"Update {i}",
            )

        mods = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="ordered"
        )
        # Total: 1 create + 5 updates = 6
        assert len(mods) == 6
        # Verify reverse chronological ordering (>= because same-second timestamps possible)
        for i in range(len(mods) - 1):
            assert mods[i].created_at >= mods[i + 1].created_at
        # Verify types present
        types = [m.modification_type for m in mods]
        assert types.count("create") == 1
        assert types.count("update") == 5

    async def test_audit_trail_limit(self, memory_service, sample_agent_config):
        """Limit parameter restricts number of returned modifications."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="limited",
            alpha=0.50,
            created_by="brain",
        )

        for i in range(10):
            await memory_service.update_basin_definition(
                sample_agent_config.agent_id,
                "limited",
                {"alpha": 0.50 + (i + 1) * 0.04},
                modified_by="body",
            )

        mods_limited = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="limited", limit=3
        )
        assert len(mods_limited) == 3

        mods_all = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="limited", limit=50
        )
        assert len(mods_all) == 11  # 1 create + 10 updates

    async def test_audit_previous_values_preserved(self, memory_service, sample_agent_config):
        """Previous values JSON captures the state before modification."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="prev_vals",
            basin_class="peripheral",
            alpha=0.60,
            lambda_decay=0.90,
            eta=0.10,
            tier=3,
            created_by="brain",
        )

        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "prev_vals",
            {"alpha": 0.75, "basin_class": "core", "tier": 2},
            modified_by="brain",
        )

        mods = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="prev_vals"
        )
        update_mods = [m for m in mods if m.modification_type == "update"]
        assert len(update_mods) == 1
        update_mod = update_mods[0]
        assert update_mod.previous_values["alpha"] == 0.60
        assert update_mod.previous_values["basin_class"] == "peripheral"
        assert update_mod.previous_values["tier"] == 3
        assert update_mod.new_values["alpha"] == 0.75
        assert update_mod.new_values["basin_class"] == "core"
        assert update_mod.new_values["tier"] == 2

    async def test_audit_session_id_recorded(self, memory_service, sample_agent_config):
        """Session ID is recorded when provided to update."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="with_session",
            alpha=0.60,
            created_by="brain",
        )

        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "with_session",
            {"alpha": 0.70},
            modified_by="body",
            session_id="session-042",
        )

        mods = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="with_session"
        )
        update_mods = [m for m in mods if m.modification_type == "update"]
        assert len(update_mods) == 1
        assert update_mods[0].session_id == "session-042"

    async def test_audit_agent_level_query(self, memory_service, sample_agent_config):
        """get_basin_modifications without basin_name returns all agent modifications."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="agent_mod_a",
            created_by="brain",
        )
        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="agent_mod_b",
            created_by="brain",
        )

        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "agent_mod_a",
            {"alpha": 0.70},
            modified_by="body",
        )

        # Query at agent level (no basin_name filter)
        mods = await memory_service.get_basin_modifications(sample_agent_config.agent_id)
        # 2 create entries + 1 update = 3
        assert len(mods) == 3

    async def test_audit_for_nonexistent_basin_returns_empty(self, memory_service, sample_agent_config):
        """Querying modifications for a nonexistent basin returns empty list."""
        await memory_service.store_agent(sample_agent_config)

        mods = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="no_such_basin"
        )
        assert mods == []

    async def test_modification_to_dict(self, memory_service, sample_agent_config):
        """BasinModification.to_dict() produces expected output."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="mod_dict",
            alpha=0.60,
            created_by="brain",
            rationale="For dict test",
        )

        mods = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="mod_dict"
        )
        d = mods[0].to_dict()
        assert "id" in d
        assert "basin_id" in d
        assert "agent_id" in d
        assert d["modification_type"] == "create"
        assert d["modified_by"] == "brain"
        assert d["rationale"] == "For dict test"
        # Verify JSON-serializable
        json.dumps(d)


# ======================================================================
# 6. Migration Tests
# ======================================================================


@pytest.mark.asyncio
class TestBasinMigration:
    """Test lazy per-agent migration from YAML/basin_current to basin_definitions."""

    async def test_ensure_migration_creates_definitions(self, memory_service, sample_agent_config):
        """Migration populates basin_definitions from basin_current."""
        await memory_service.store_agent(sample_agent_config)
        # store_agent already calls update_current_basins, populating basin_current
        # Agent starts with basin_source='yaml' (default column value)

        # Manually ensure source is 'yaml' (store_agent uses INSERT OR REPLACE
        # which may inherit the default)
        await memory_service.set_agent_basin_source(sample_agent_config.agent_id, "yaml")

        migrated = await memory_service.ensure_basin_migration(sample_agent_config.agent_id)
        assert migrated is True

        defs = await memory_service.get_basin_definitions(sample_agent_config.agent_id)
        names = sorted([d.name for d in defs])
        assert "basin_a" in names
        assert "basin_b" in names
        assert len(defs) == 2

        # Verify values match the original config
        basin_a = next(d for d in defs if d.name == "basin_a")
        assert basin_a.basin_class == BasinClass.CORE
        assert basin_a.alpha == 0.85
        assert basin_a.lambda_ == 0.95
        assert basin_a.eta == 0.02
        assert basin_a.tier == TierLevel.TIER_2
        assert basin_a.created_by == "migration"

    async def test_migration_sets_source_to_database(self, memory_service, sample_agent_config):
        """After migration, basin_source='database'."""
        await memory_service.store_agent(sample_agent_config)
        await memory_service.set_agent_basin_source(sample_agent_config.agent_id, "yaml")

        await memory_service.ensure_basin_migration(sample_agent_config.agent_id)

        source = await memory_service.get_agent_basin_source(sample_agent_config.agent_id)
        assert source == "database"

    async def test_migration_is_idempotent(self, memory_service, sample_agent_config):
        """Running migration twice doesn't duplicate basins."""
        await memory_service.store_agent(sample_agent_config)
        await memory_service.set_agent_basin_source(sample_agent_config.agent_id, "yaml")

        first = await memory_service.ensure_basin_migration(sample_agent_config.agent_id)
        assert first is True

        # Second call should see basin_source='database' and return False
        second = await memory_service.ensure_basin_migration(sample_agent_config.agent_id)
        assert second is False

        defs = await memory_service.get_basin_definitions(sample_agent_config.agent_id)
        assert len(defs) == 2  # Still only 2

    async def test_already_migrated_agent_skips(self, memory_service, sample_agent_config):
        """Agent with basin_source='database' returns False immediately."""
        await memory_service.store_agent(sample_agent_config)
        await memory_service.set_agent_basin_source(sample_agent_config.agent_id, "database")

        result = await memory_service.ensure_basin_migration(sample_agent_config.agent_id)
        assert result is False

    async def test_migration_preserves_deprecation_status(self, memory_service, sample_agent_config):
        """Deprecated basins in basin_current migrate with deprecation info."""
        await memory_service.store_agent(sample_agent_config)

        # Deprecate basin_b in basin_current directly
        memory_service.sqlite.execute(
            """UPDATE basin_current SET deprecated = 1,
               deprecated_at = '2026-02-15T00:00:00',
               deprecation_rationale = 'No longer used'
               WHERE agent_id = ? AND basin_name = ?""",
            (sample_agent_config.agent_id, "basin_b"),
        )

        await memory_service.set_agent_basin_source(sample_agent_config.agent_id, "yaml")
        await memory_service.ensure_basin_migration(sample_agent_config.agent_id)

        # basin_b should be deprecated in basin_definitions
        bd = await memory_service.get_basin_definition(
            sample_agent_config.agent_id, "basin_b"
        )
        assert bd is not None
        assert bd.deprecated is True
        assert bd.deprecated_at == "2026-02-15T00:00:00"
        assert bd.deprecation_rationale == "No longer used"

    async def test_migration_without_current_basins_uses_agent_config(self, memory_service):
        """When basin_current is empty, migration falls back to agent config basins."""
        agent = _make_agent("fallback-agent")
        await memory_service.store_agent(agent)

        # Clear basin_current to force fallback
        memory_service.sqlite.execute(
            "DELETE FROM basin_current WHERE agent_id = ?",
            ("fallback-agent",),
        )
        await memory_service.set_agent_basin_source("fallback-agent", "yaml")

        migrated = await memory_service.ensure_basin_migration("fallback-agent")
        assert migrated is True

        defs = await memory_service.get_basin_definitions("fallback-agent")
        assert len(defs) == 2
        names = sorted([d.name for d in defs])
        assert "basin_a" in names
        assert "basin_b" in names

    async def test_get_agent_basin_source_default(self, memory_service, sample_agent_config):
        """New agents default to basin_source='yaml'."""
        await memory_service.store_agent(sample_agent_config)

        source = await memory_service.get_agent_basin_source(sample_agent_config.agent_id)
        assert source == "yaml"

    async def test_set_agent_basin_source(self, memory_service, sample_agent_config):
        """set_agent_basin_source correctly updates the column."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.set_agent_basin_source(sample_agent_config.agent_id, "database")
        source = await memory_service.get_agent_basin_source(sample_agent_config.agent_id)
        assert source == "database"

        await memory_service.set_agent_basin_source(sample_agent_config.agent_id, "yaml")
        source = await memory_service.get_agent_basin_source(sample_agent_config.agent_id)
        assert source == "yaml"

    async def test_nonexistent_agent_basin_source_returns_yaml(self, memory_service):
        """Querying basin_source for a nonexistent agent returns 'yaml'."""
        source = await memory_service.get_agent_basin_source("no-such-agent")
        assert source == "yaml"


# ======================================================================
# 7. Race Condition / Persistence Tests
# ======================================================================


@pytest.mark.asyncio
class TestRaceConditions:
    """Test that database-sourced basins prevent race conditions."""

    async def test_brain_modification_persists_across_reads(self, memory_service, sample_agent_config):
        """Brain modifies basin -> read back -> modification present."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="persistent",
            basin_class="core",
            alpha=0.80,
            lambda_decay=0.95,
            eta=0.02,
            tier=2,
            created_by="brain",
        )

        # Brain modifies
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "persistent",
            {"alpha": 0.90, "tier": 1},
            modified_by="brain",
            rationale="Promoting to tier 1",
        )

        # Read back from scratch
        bd = await memory_service.get_basin_definition(
            sample_agent_config.agent_id, "persistent"
        )
        assert bd.alpha == 0.90
        assert bd.tier == TierLevel.TIER_1
        assert bd.last_modified_by == "brain"

    async def test_body_modification_to_locked_basin_rejected(self, memory_service, sample_agent_config):
        """Body tries to update locked basin -- returns None and does not modify."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="locked_persist",
            basin_class="core",
            alpha=0.80,
            created_by="brain",
        )

        # Lock
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "locked_persist",
            {"locked_by_brain": 1},
            modified_by="brain",
        )

        # Body attempts update
        result = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "locked_persist",
            {"alpha": 0.30, "basin_class": "peripheral"},
            modified_by="body",
        )
        assert result is None

        # Verify unchanged
        bd = await memory_service.get_basin_definition(
            sample_agent_config.agent_id, "locked_persist"
        )
        assert bd.alpha == 0.80
        assert bd.basin_class == BasinClass.CORE
        assert bd.locked_by_brain is True

    async def test_sequential_modifications_accumulate(self, memory_service, sample_agent_config):
        """Multiple sequential modifications all persist correctly."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="sequential",
            alpha=0.50,
            lambda_decay=0.90,
            eta=0.10,
            tier=3,
            basin_class="peripheral",
            created_by="brain",
        )

        # Step 1: Body adjusts alpha
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "sequential",
            {"alpha": 0.65},
            modified_by="body",
            session_id="s1",
        )

        # Step 2: Brain promotes to core
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "sequential",
            {"basin_class": "core", "tier": 2},
            modified_by="brain",
        )

        # Step 3: Brain locks
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "sequential",
            {"locked_by_brain": 1},
            modified_by="brain",
        )

        # Step 4: Brain sets bounds
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "sequential",
            {"alpha_floor": 0.40, "alpha_ceiling": 0.85},
            modified_by="brain",
        )

        # Verify final state
        bd = await memory_service.get_basin_definition(
            sample_agent_config.agent_id, "sequential"
        )
        assert bd.alpha == 0.65
        assert bd.basin_class == BasinClass.CORE
        assert bd.tier == TierLevel.TIER_2
        assert bd.locked_by_brain is True
        assert bd.alpha_floor == 0.40
        assert bd.alpha_ceiling == 0.85
        assert bd.lambda_ == 0.90  # unchanged from creation
        assert bd.eta == 0.10  # unchanged from creation

        # Verify full audit trail
        mods = await memory_service.get_basin_modifications(
            sample_agent_config.agent_id, basin_name="sequential"
        )
        # 1 create + 4 updates = 5
        assert len(mods) == 5
        types = [m.modification_type for m in mods]
        assert "create" in types
        assert "update" in types
        assert "lock" in types
        assert "set_bounds" in types

    async def test_cross_agent_isolation(self, memory_service):
        """Basin definitions are isolated between agents."""
        agent_a = _make_agent("agent-alpha")
        agent_b = _make_agent("agent-beta")
        await memory_service.store_agent(agent_a)
        await memory_service.store_agent(agent_b)

        await memory_service.insert_basin_definition(
            agent_id="agent-alpha",
            name="shared_name",
            alpha=0.80,
            created_by="brain",
        )
        await memory_service.insert_basin_definition(
            agent_id="agent-beta",
            name="shared_name",
            alpha=0.40,
            created_by="brain",
        )

        bd_a = await memory_service.get_basin_definition("agent-alpha", "shared_name")
        bd_b = await memory_service.get_basin_definition("agent-beta", "shared_name")

        assert bd_a.alpha == 0.80
        assert bd_b.alpha == 0.40

        # Modifying one doesn't affect the other
        await memory_service.update_basin_definition(
            "agent-alpha",
            "shared_name",
            {"alpha": 0.99},
            modified_by="brain",
        )

        bd_a = await memory_service.get_basin_definition("agent-alpha", "shared_name")
        bd_b = await memory_service.get_basin_definition("agent-beta", "shared_name")
        assert bd_a.alpha == 0.99
        assert bd_b.alpha == 0.40  # unchanged

    async def test_upsert_on_locked_basin_uses_override(self, memory_service, sample_agent_config):
        """Upsert on an existing locked basin succeeds because it uses override_lock=True."""
        await memory_service.store_agent(sample_agent_config)

        await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="upsert_locked",
            alpha=0.70,
            created_by="brain",
        )
        await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "upsert_locked",
            {"locked_by_brain": 1},
            modified_by="brain",
        )

        # Upsert should succeed even though basin is locked (uses override_lock=True internally)
        bd = await memory_service.upsert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="upsert_locked",
            params={"alpha": 0.55},
            modified_by="import",
            rationale="Upsert override",
        )
        assert bd is not None
        assert bd.alpha == 0.55

    async def test_update_with_no_valid_modifications_returns_original(self, memory_service, sample_agent_config):
        """Updating with only invalid keys returns the basin unchanged."""
        await memory_service.store_agent(sample_agent_config)

        bd = await memory_service.insert_basin_definition(
            agent_id=sample_agent_config.agent_id,
            name="no_change",
            alpha=0.60,
            created_by="brain",
        )

        result = await memory_service.update_basin_definition(
            sample_agent_config.agent_id,
            "no_change",
            {"invalid_key": "invalid_value"},
            modified_by="brain",
        )
        # Should return original basin unchanged
        assert result is not None
        assert result.alpha == 0.60
