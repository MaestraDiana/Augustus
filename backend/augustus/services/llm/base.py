"""Base LLMClient interface for Augustus."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator

from augustus.models.dataclasses import EvaluatorOutput


class LLMClient(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate_message(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 1.0,
        max_tokens: int = 4096,
    ) -> Any:
        """Execute a completion request."""
        pass

    @abstractmethod
    async def validate_key(self) -> bool:
        """Validate the configured API key."""
        pass

    @abstractmethod
    def estimate_cost(
        self, tokens_in: int, tokens_out: int, model: str, **kwargs
    ) -> float:
        """Estimate the cost of a session."""
        pass

    @abstractmethod
    def get_full_model_name(self, model_alias: str) -> str:
        """Resolve a short model name to a provider-specific ID."""
        pass
