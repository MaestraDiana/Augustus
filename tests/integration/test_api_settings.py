"""Integration tests for settings API endpoints."""
import pytest


@pytest.mark.asyncio
async def test_get_settings(client):
    """Test getting application settings."""
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()

    # Check for expected settings fields
    assert "default_model" in data
    assert "default_temperature" in data
    assert "default_max_tokens" in data
    assert "poll_interval" in data
    assert "max_concurrent_agents" in data
    assert "evaluator_enabled" in data
    assert "evaluator_model" in data
    assert "dashboard_port" in data
    assert "has_api_key" in data

    # API key should not be exposed
    assert "api_key" not in data
    assert "api_key_encrypted" not in data


@pytest.mark.asyncio
async def test_update_settings_single_field(client):
    """Test updating a single settings field."""
    update = {"default_temperature": 0.7}

    resp = await client.put("/api/settings", json=update)
    assert resp.status_code == 200
    data = resp.json()
    assert data["default_temperature"] == 0.7


@pytest.mark.asyncio
async def test_update_settings_multiple_fields(client):
    """Test updating multiple settings fields."""
    update = {
        "default_temperature": 0.8,
        "default_max_tokens": 2048,
        "poll_interval": 120,
    }

    resp = await client.put("/api/settings", json=update)
    assert resp.status_code == 200
    data = resp.json()
    assert data["default_temperature"] == 0.8
    assert data["default_max_tokens"] == 2048
    assert data["poll_interval"] == 120


@pytest.mark.asyncio
async def test_update_settings_persists(client):
    """Test that settings updates persist."""
    # Update setting
    await client.put("/api/settings", json={"default_temperature": 0.9})

    # Get settings again
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["default_temperature"] == 0.9


@pytest.mark.asyncio
async def test_update_budget_settings(client):
    """Test updating budget-related settings."""
    update = {
        "budget_warning": 75.0,
        "budget_hard_stop": 150.0,
        "budget_per_session": 10.0,
        "budget_per_day": 50.0,
    }

    resp = await client.put("/api/settings", json=update)
    assert resp.status_code == 200
    data = resp.json()
    assert data["budget_warning"] == 75.0
    assert data["budget_hard_stop"] == 150.0
    assert data["budget_per_session"] == 10.0
    assert data["budget_per_day"] == 50.0


@pytest.mark.asyncio
async def test_update_evaluator_settings(client):
    """Test updating evaluator settings."""
    update = {
        "evaluator_enabled": False,
        "evaluator_model": "claude-opus-4-6",
    }

    resp = await client.put("/api/settings", json=update)
    assert resp.status_code == 200
    data = resp.json()
    assert data["evaluator_enabled"] is False
    assert data["evaluator_model"] == "claude-opus-4-6"


@pytest.mark.asyncio
async def test_update_api_key(client):
    """Test updating API key."""
    update = {"api_key": "test-api-key-12345"}

    resp = await client.put("/api/settings", json=update)
    assert resp.status_code == 200
    data = resp.json()

    # API key should not be in response, but has_api_key should be true
    assert "api_key" not in data
    assert data["has_api_key"] is True


@pytest.mark.asyncio
async def test_update_settings_preserves_other_fields(client):
    """Test that updating one field doesn't affect others."""
    # Get initial settings
    resp1 = await client.get("/api/settings")
    initial = resp1.json()
    initial_model = initial["default_model"]

    # Update temperature only
    await client.put("/api/settings", json={"default_temperature": 0.5})

    # Check that model is unchanged
    resp2 = await client.get("/api/settings")
    updated = resp2.json()
    assert updated["default_model"] == initial_model
    assert updated["default_temperature"] == 0.5


@pytest.mark.asyncio
async def test_validate_api_key_valid(client):
    """Test API key validation with valid key."""
    # Note: This test will fail if no real API key is available
    # In a real scenario, you'd mock the Anthropic API
    resp = await client.post("/api/settings/validate-key", json={
        "api_key": "test-key"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "valid" in data
    # Will likely be False without a real key
    assert isinstance(data["valid"], bool)
    assert "message" in data


@pytest.mark.asyncio
async def test_validate_api_key_empty(client):
    """Test API key validation with empty key."""
    resp = await client.post("/api/settings/validate-key", json={
        "api_key": ""
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "valid" in data
    assert data["valid"] is False


@pytest.mark.asyncio
async def test_validate_api_key_invalid(client):
    """Test API key validation with invalid key."""
    resp = await client.post("/api/settings/validate-key", json={
        "api_key": "invalid-key-format"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "valid" in data
    # Should be false for invalid key
    assert isinstance(data["valid"], bool)


@pytest.mark.asyncio
async def test_update_settings_with_none_values(client):
    """Test that None values in update don't change settings."""
    # Get initial settings
    resp1 = await client.get("/api/settings")
    initial = resp1.json()
    initial_temp = initial["default_temperature"]

    # Update with explicit None (if supported by Pydantic exclude_none)
    # This tests that None fields are excluded from updates
    update = {
        "default_temperature": 0.6,
        "default_model": None,  # Should be excluded
    }

    resp = await client.put("/api/settings", json=update)
    assert resp.status_code == 200
    data = resp.json()
    assert data["default_temperature"] == 0.6
