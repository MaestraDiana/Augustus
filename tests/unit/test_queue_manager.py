"""Tests for Queue Manager — YAML lifecycle management."""
import pytest
from pathlib import Path

from augustus.exceptions import SchemaValidationError, QueueError
from augustus.services.queue_manager import QueueManager
from augustus.services.schema_parser import SchemaParser


@pytest.mark.asyncio
async def test_poll_finds_pending_yaml(tmp_path, schema_parser, sample_yaml):
    """Test polling finds and activates pending YAML files."""
    queue_mgr = QueueManager(tmp_path, schema_parser)

    # Write valid YAML to pending
    (queue_mgr.pending_dir / "test.yaml").write_text(sample_yaml)

    # Poll should find and activate it
    instruction = await queue_mgr.poll()

    assert instruction is not None
    assert instruction.framework.agent_id == "test-agent"
    assert len(list(queue_mgr.active_dir.glob("*.yaml"))) == 1
    assert len(list(queue_mgr.pending_dir.glob("*.yaml"))) == 0


@pytest.mark.asyncio
async def test_poll_returns_none_when_active_exists(tmp_path, schema_parser, sample_yaml):
    """Test poll returns None when active file already exists."""
    queue_mgr = QueueManager(tmp_path, schema_parser)

    # Create active file
    (queue_mgr.active_dir / "active.yaml").write_text(sample_yaml)

    # Poll should return None
    instruction = await queue_mgr.poll()
    assert instruction is None


@pytest.mark.asyncio
async def test_invalid_yaml_moves_to_error(tmp_path, schema_parser):
    """Test invalid YAML moves to error directory."""
    queue_mgr = QueueManager(tmp_path, schema_parser)

    invalid_yaml = """
framework:
  version: "0.1"  # Invalid version
  agent_id: "test"
"""
    (queue_mgr.pending_dir / "invalid.yaml").write_text(invalid_yaml)

    # Poll should move to error
    instruction = await queue_mgr.poll()

    assert instruction is None
    assert len(list(queue_mgr.error_dir.glob("*.yaml"))) == 1
    assert len(list(queue_mgr.error_dir.glob("*.error.txt"))) == 1


@pytest.mark.asyncio
async def test_fifo_ordering(tmp_path, schema_parser, sample_yaml):
    """Test FIFO ordering of pending files."""
    queue_mgr = QueueManager(tmp_path, schema_parser)

    # Create multiple YAML files with different timestamps
    import time
    for i in range(3):
        (queue_mgr.pending_dir / f"file{i}.yaml").write_text(sample_yaml)
        time.sleep(0.01)  # Ensure different timestamps

    # First poll should get oldest file
    files_before = sorted(queue_mgr.pending_dir.glob("*.yaml"), key=lambda f: f.stat().st_ctime)
    first_file = files_before[0].name

    instruction = await queue_mgr.poll()
    assert instruction is not None

    # Check that the first file was activated
    assert (queue_mgr.active_dir / first_file).exists()


@pytest.mark.asyncio
async def test_complete_session_moves_to_archive(tmp_path, schema_parser, sample_yaml):
    """Test completing a session moves YAML to archive."""
    queue_mgr = QueueManager(tmp_path, schema_parser)

    (queue_mgr.active_dir / "session.yaml").write_text(sample_yaml)

    await queue_mgr.complete_session("session-001", {"status": "complete", "turns": 8})

    assert len(list(queue_mgr.archive_dir.glob("*.yaml"))) == 1
    assert len(list(queue_mgr.active_dir.glob("*.yaml"))) == 0

    # Check metadata was appended
    archived = list(queue_mgr.archive_dir.glob("*.yaml"))[0]
    content = archived.read_text()
    assert "session_id: session-001" in content
    assert "status: complete" in content


@pytest.mark.asyncio
async def test_failed_session_moves_to_error(tmp_path, schema_parser, sample_yaml):
    """Test failed session moves YAML to error directory."""
    queue_mgr = QueueManager(tmp_path, schema_parser)

    (queue_mgr.active_dir / "session.yaml").write_text(sample_yaml)

    await queue_mgr.fail_session("session-002", "API error")

    assert len(list(queue_mgr.error_dir.glob("*.yaml"))) == 1
    assert len(list(queue_mgr.error_dir.glob("*.error.txt"))) == 1
    assert len(list(queue_mgr.active_dir.glob("*.yaml"))) == 0


@pytest.mark.asyncio
async def test_write_yaml_validates_first(tmp_path, schema_parser, sample_yaml):
    """Test write_yaml validates before writing."""
    queue_mgr = QueueManager(tmp_path, schema_parser)

    # Valid YAML should write successfully
    path = await queue_mgr.write_yaml(sample_yaml, "test.yaml")
    assert path.exists()
    assert path.parent == queue_mgr.pending_dir

    # Invalid YAML should raise error
    invalid_yaml = "framework:\n  version: invalid"
    with pytest.raises(QueueError, match="validation failed"):
        await queue_mgr.write_yaml(invalid_yaml, "invalid.yaml")


@pytest.mark.asyncio
async def test_list_pending(tmp_path, schema_parser, sample_yaml):
    """Test listing pending files."""
    queue_mgr = QueueManager(tmp_path, schema_parser)

    # Create pending files
    (queue_mgr.pending_dir / "pending1.yaml").write_text(sample_yaml)
    (queue_mgr.pending_dir / "pending2.yaml").write_text(sample_yaml)

    pending = queue_mgr.list_pending()

    assert len(pending) == 2
