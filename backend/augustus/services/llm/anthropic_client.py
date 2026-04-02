"""Anthropic implementation of LLMClient."""
from __future__ import annotations

import logging
import anthropic
from typing import Any

from augustus.services.llm.base import LLMClient
from augustus.utils import normalize_model

logger = logging.getLogger(__name__)

class AnthropicClient(LLMClient):
    """Client for Anthropic API."""

    def __init__(self, api_key: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate_message(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 1.0,
        max_tokens: int = 4096,
    ) -> Any:
        # Anthropic expects tool_result in the content list of a user message
        # The session_manager already formats them this way.
        
        # Build kwargs for Anthropic
        kwargs = {
            "model": self.get_full_model_name(model) if model else "claude-sonnet-4-6",
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools

        # Inject beta headers if web search is present (Anthropic specific)
        # This is currently handled in session_manager, but maybe should move here.
        # For now, we just pass through.
        
        return await self.client.messages.create(**kwargs)

    async def validate_key(self) -> bool:
        try:
            # Sync client for simple validation
            client = anthropic.Anthropic(api_key=self.client.api_key)
            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=10,
                messages=[{"role": "user", "content": "Hello"}],
            )
            return True
        except Exception:
            return False

    def estimate_cost(
        self, tokens_in: int, tokens_out: int, model: str, **kwargs
    ) -> float:
        """Estimate cost based on Anthropic pricing."""
        full_model = self.get_full_model_name(model)
        
        # Simplified pricing table
        if "opus" in full_model:
            pi, po = 15.0, 75.0
        elif "sonnet-4-5" in full_model:
             pi, po = 3.0, 15.0
        elif "sonnet" in full_model:
            pi, po = 3.0, 15.0
        elif "haiku-4-5" in full_model:
            pi, po = 0.80, 4.0
        elif "haiku-35" in full_model:
            pi, po = 0.25, 1.25
        else:
            pi, po = 3.0, 15.0  # Default to sonnet

        cost = (tokens_in / 1_000_000) * pi + (tokens_out / 1_000_000) * po
        
        # Add web search cost if applicable
        web_search_requests = kwargs.get("web_search_requests", 0)
        cost += web_search_requests * 0.01  # $0.01 per search
        
        return cost

    def get_full_model_name(self, model_alias: str) -> str:
        return normalize_model(model_alias)
