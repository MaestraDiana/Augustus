"""Queue Manager — filesystem polling and YAML lifecycle management."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from augustus.exceptions import QueueError, SchemaValidationError
from augustus.models.dataclasses import ParsedInstruction

logger = logging.getLogger(__name__)


class QueueManager:
    """Monitor agent instruction queue for new YAML files."""

    def __init__(self, agent_dir: Path, schema_parser) -> None:
        """Initialize queue manager with agent directory and schema parser."""
        self.agent_dir = agent_dir
        self.schema_parser = schema_parser
        self.pending_dir = agent_dir / "queue" / "pending"
        self.active_dir = agent_dir / "queue" / "active"
        self.archive_dir = agent_dir / "queue" / "archive"
        self.error_dir = agent_dir / "queue" / "error"

        # Ensure directories exist
        for d in [self.pending_dir, self.active_dir, self.archive_dir, self.error_dir]:
            d.mkdir(parents=True, exist_ok=True)

    async def poll(self) -> ParsedInstruction | None:
        """Check pending/ for new YAML files. Validate and move to active/."""
        # If active/ is non-empty, return None (one active at a time)
        active_files = list(self.active_dir.glob("*.yaml")) + list(self.active_dir.glob("*.yml"))
        if active_files:
            return None

        # List pending files, sorted by creation time for FIFO
        pending_files = sorted(
            list(self.pending_dir.glob("*.yaml")) + list(self.pending_dir.glob("*.yml")),
            key=lambda f: f.stat().st_ctime,
        )

        for file_path in pending_files:
            try:
                yaml_text = file_path.read_text(encoding="utf-8")
                instruction = self.schema_parser.parse(yaml_text)

                # Valid — move to active
                dest = self.active_dir / file_path.name
                shutil.move(str(file_path), str(dest))
                logger.info(f"Activated YAML: {file_path.name}")
                return instruction

            except SchemaValidationError as e:
                # Invalid — move to error
                logger.error(f"Schema validation failed for {file_path.name}: {e}")
                dest = self.error_dir / file_path.name
                shutil.move(str(file_path), str(dest))
                # Write error info
                error_info = self.error_dir / f"{file_path.stem}.error.txt"
                error_info.write_text(f"Validation error: {e}\nTimestamp: {datetime.utcnow().isoformat()}")
                continue

            except Exception as e:
                logger.error(f"Unexpected error processing {file_path.name}: {e}")
                dest = self.error_dir / file_path.name
                shutil.move(str(file_path), str(dest))
                continue

        return None

    async def complete_session(self, session_id: str, metadata: dict) -> None:
        """Move active YAML to archive/ with appended metadata."""
        active_files = list(self.active_dir.glob("*.yaml")) + list(self.active_dir.glob("*.yml"))

        for file_path in active_files:
            # Append metadata
            original = file_path.read_text(encoding="utf-8")
            metadata_text = f"\n\n# --- Session Metadata (appended by orchestrator) ---\n"
            metadata_text += f"# session_id: {session_id}\n"
            metadata_text += f"# completed_at: {datetime.utcnow().isoformat()}\n"
            for key, value in metadata.items():
                metadata_text += f"# {key}: {value}\n"

            # Move to archive with metadata
            archive_name = f"{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}_{file_path.name}"
            dest = self.archive_dir / archive_name
            dest.write_text(original + metadata_text, encoding="utf-8")
            file_path.unlink()

            logger.info(f"Archived YAML: {archive_name}")

    async def fail_session(self, session_id: str, error: str) -> None:
        """Move active YAML to error/ with error info."""
        active_files = list(self.active_dir.glob("*.yaml")) + list(self.active_dir.glob("*.yml"))

        for file_path in active_files:
            dest = self.error_dir / file_path.name
            shutil.move(str(file_path), str(dest))

            error_info = self.error_dir / f"{file_path.stem}.error.txt"
            error_info.write_text(
                f"Session failed: {error}\n" f"Session ID: {session_id}\n" f"Timestamp: {datetime.utcnow().isoformat()}"
            )
            logger.error(f"Failed YAML moved to error: {file_path.name}")

    async def write_yaml(self, yaml_content: str, filename: str) -> Path:
        """Write a new YAML to pending/ (validated first)."""
        # Validate
        try:
            self.schema_parser.parse(yaml_content)
        except SchemaValidationError as e:
            raise QueueError(f"YAML validation failed: {e}")

        # Write with timestamp prefix for ordering
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        safe_name = filename if filename.endswith((".yaml", ".yml")) else f"{filename}.yaml"
        dest = self.pending_dir / f"{ts}_{safe_name}"
        dest.write_text(yaml_content, encoding="utf-8")

        logger.info(f"Queued new YAML: {dest.name}")
        return dest

    def list_pending(self) -> list[Path]:
        """List pending YAML files."""
        return sorted(
            list(self.pending_dir.glob("*.yaml")) + list(self.pending_dir.glob("*.yml")),
            key=lambda f: f.stat().st_ctime,
        )

    def clear_pending(self) -> int:
        """Remove all pending YAML files. Returns count of files removed.

        Used when agent config changes invalidate queued instructions.
        Does NOT touch active/ (in-progress sessions complete normally).
        """
        pending = self.list_pending()
        for f in pending:
            f.unlink()
            logger.info(f"Cleared pending YAML: {f.name}")
        return len(pending)

    def get_active(self) -> Path | None:
        """Get currently active YAML file."""
        files = list(self.active_dir.glob("*.yaml")) + list(self.active_dir.glob("*.yml"))
        return files[0] if files else None
