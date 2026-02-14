"""Tests for Configuration Manager — settings persistence."""
import pytest
from pathlib import Path

from augustus.config import ConfigManager, Settings


def test_default_settings_values():
    """Test Settings dataclass has correct default values."""
    settings = Settings()

    assert settings.default_model == "claude-sonnet-4-20250514"
    assert settings.default_temperature == 1.0
    assert settings.default_max_tokens == 4096
    assert settings.poll_interval == 60
    assert settings.max_concurrent_agents == 3
    assert settings.evaluator_enabled is True
    assert settings.dashboard_port == 8080
    assert settings.mcp_enabled is True


def test_save_and_load_settings(tmp_path):
    """Test saving and loading settings from disk."""
    config_mgr = ConfigManager(tmp_path)

    # Update settings
    config_mgr.settings.default_model = "claude-opus-4"
    config_mgr.settings.poll_interval = 120
    config_mgr.save()

    # Create new manager instance to load from disk
    config_mgr2 = ConfigManager(tmp_path)

    assert config_mgr2.settings.default_model == "claude-opus-4"
    assert config_mgr2.settings.poll_interval == 120


def test_api_key_encryption_and_decryption(tmp_path):
    """Test API key encryption and decryption."""
    config_mgr = ConfigManager(tmp_path)

    # Set and encrypt API key
    test_key = "sk-test-key-12345"
    config_mgr.settings.set_api_key(test_key)

    # Encrypted value should not match original
    assert config_mgr.settings.api_key_encrypted != test_key

    # Decrypt should return original
    decrypted = config_mgr.settings.get_api_key()
    assert decrypted == test_key


def test_update_settings(tmp_path):
    """Test updating multiple settings at once."""
    config_mgr = ConfigManager(tmp_path)

    updates = {
        "default_model": "claude-sonnet-4",
        "poll_interval": 90,
        "evaluator_enabled": False,
    }

    config_mgr.update(updates)

    assert config_mgr.settings.default_model == "claude-sonnet-4"
    assert config_mgr.settings.poll_interval == 90
    assert config_mgr.settings.evaluator_enabled is False


def test_config_directory_creation(tmp_path):
    """Test config directory is created if it doesn't exist."""
    config_dir = tmp_path / "new_config"
    assert not config_dir.exists()

    config_mgr = ConfigManager(config_dir)

    assert config_dir.exists()
    # Config file is not created until first save
    config_mgr.save()
    assert config_mgr.config_file.exists()


def test_invalid_fernet_key_handling(tmp_path):
    """Test handling of invalid Fernet key."""
    settings = Settings()

    # Set invalid encrypted key
    settings.api_key_encrypted = "invalid-encrypted-data"
    settings._fernet_key = "invalid-key"

    # get_api_key should return empty string on error
    result = settings.get_api_key()
    assert result == ""


def test_get_data_dir(tmp_path):
    """Test getting data directory."""
    config_mgr = ConfigManager(tmp_path)

    data_dir = config_mgr.get_data_dir()

    assert data_dir.exists()
    assert data_dir.is_dir()


def test_get_data_dir_custom_path(tmp_path):
    """Test getting data directory with custom path."""
    config_mgr = ConfigManager(tmp_path)

    custom_path = tmp_path / "custom_data"
    config_mgr.settings.data_directory = str(custom_path)

    data_dir = config_mgr.get_data_dir()

    assert data_dir == custom_path
    assert data_dir.exists()
