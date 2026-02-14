"""Tests for Evaluator Service — independent session evaluation."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from augustus.models.dataclasses import BasinConfig
from augustus.models.enums import BasinClass, TierLevel
from augustus.services.evaluator import (
    EvaluatorService,
    DEFAULT_EVALUATOR_PROMPT,
    DEFAULT_EVALUATOR_PROMPT_VERSION,
)


@pytest.fixture
def mock_anthropic_client():
    """Create a mock Anthropic client."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock()
    return client


def test_default_evaluator_prompt():
    """Test default evaluator prompt is a valid string."""
    assert isinstance(DEFAULT_EVALUATOR_PROMPT, str)
    assert len(DEFAULT_EVALUATOR_PROMPT) > 0
    assert "evaluation" in DEFAULT_EVALUATOR_PROMPT.lower()
    assert "json" in DEFAULT_EVALUATOR_PROMPT.lower()


def test_default_evaluator_prompt_version():
    """Test default evaluator prompt version is set."""
    assert DEFAULT_EVALUATOR_PROMPT_VERSION == "v0.1"


def test_build_evaluation_request():
    """Test building evaluation request includes basins."""
    evaluator = EvaluatorService(api_key="test-key")
    basins = [
        BasinConfig(
            name="test_basin",
            basin_class=BasinClass.CORE,
            alpha=0.85,
            lambda_=0.95,
            eta=0.02,
            tier=TierLevel.TIER_2,
        ),
    ]
    transcript = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]

    request = evaluator.build_evaluation_request(
        identity_core="You are a test agent.",
        transcript=transcript,
        close_report="Test close report",
        basin_params=basins,
    )

    assert "test_basin" in request
    assert "Identity Configuration" in request
    assert "Session Transcript" in request
    assert "[user]: Hello" in request


def test_parse_valid_json_response():
    """Test parsing valid JSON response."""
    evaluator = EvaluatorService(api_key="test-key")
    response_text = json.dumps({
        "basin_relevance": {"basin_a": 0.8, "basin_b": 0.3},
        "basin_rationale": {"basin_a": "High", "basin_b": "Low"},
        "co_activation_characters": {},
        "constraint_erosion_flag": False,
        "constraint_erosion_detail": None,
        "assessment_divergence_flag": False,
        "assessment_divergence_detail": None,
        "emergent_observations": ["Test observation"],
    })

    output = evaluator.parse_evaluation_response(response_text)

    assert output.basin_relevance["basin_a"] == 0.8
    assert output.basin_relevance["basin_b"] == 0.3
    assert len(output.emergent_observations) == 1


def test_parse_malformed_json_returns_empty_output():
    """Test malformed JSON returns empty EvaluatorOutput."""
    evaluator = EvaluatorService(api_key="test-key")
    response_text = "This is not JSON"

    output = evaluator.parse_evaluation_response(response_text)

    assert output.basin_relevance == {}
    assert output.emergent_observations == []


def test_parse_json_in_code_block():
    """Test parsing JSON wrapped in code block."""
    evaluator = EvaluatorService(api_key="test-key")
    response_text = '''
```json
{
    "basin_relevance": {"basin_a": 0.5},
    "basin_rationale": {},
    "co_activation_characters": {},
    "constraint_erosion_flag": false,
    "constraint_erosion_detail": null,
    "assessment_divergence_flag": false,
    "assessment_divergence_detail": null,
    "emergent_observations": []
}
```
'''

    output = evaluator.parse_evaluation_response(response_text)

    assert output.basin_relevance["basin_a"] == 0.5


@pytest.mark.asyncio
async def test_evaluate_session_handles_api_error():
    """Test that API errors are handled gracefully."""
    # Create a mock client that raises an error
    evaluator = EvaluatorService(api_key="test-key")

    # Mock the client to raise an error
    import anthropic
    evaluator.client = MagicMock()
    evaluator.client.messages = MagicMock()

    async def raise_error(*args, **kwargs):
        raise anthropic.APIError("Test error")

    evaluator.client.messages.create = raise_error

    basins = [
        BasinConfig(
            name="test",
            basin_class=BasinClass.CORE,
            alpha=0.8,
            lambda_=0.95,
            eta=0.02,
            tier=TierLevel.TIER_2,
        ),
    ]

    output = await evaluator.evaluate_session(
        identity_core="Test",
        transcript=[],
        close_report="",
        basin_params=basins,
    )

    # Should return empty output on error but still have prompt version
    assert output.basin_relevance == {}
    assert output.evaluator_prompt_version == DEFAULT_EVALUATOR_PROMPT_VERSION
