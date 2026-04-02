"""Gemini implementation of LLMClient."""
from __future__ import annotations

import logging
import json
import google.generativeai as genai
from typing import Any

from augustus.services.llm.base import LLMClient

logger = logging.getLogger(__name__)

GEMINI_MODEL_MAPPING = {
    "gemini-1.5-pro": "models/gemini-1.5-pro",
    "gemini-1.5-flash": "models/gemini-1.5-flash",
    "gemini-2.0-flash": "models/gemini-2.0-flash-exp",
    "gemini-1.5-pro-latest": "models/gemini-1.5-pro-latest",
    "gemini-1.5-flash-latest": "models/gemini-1.5-flash-latest",
}

class GeminiClient(LLMClient):
    """Client for Gemini API."""

    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)

    async def generate_message(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 1.0,
        max_tokens: int = 4096,
    ) -> Any:
        full_model = self.get_full_model_name(model) if model else "models/gemini-1.5-pro"
        
        # Convert Anthropic-style messages to Gemini-style
        gemini_history = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            content = msg["content"]
            
            # Gemini expects parts
            parts = []
            if isinstance(content, str):
                parts.append({"text": content})
            elif isinstance(content, list):
                for block in content:
                    if block.get("type") == "text":
                        parts.append({"text": block["text"]})
                    elif block.get("type") == "tool_use":
                        # Gemini tool call format
                        parts.append({
                            "function_call": {
                                "name": block["name"],
                                "args": block["input"]
                            }
                        })
                    elif block.get("type") == "tool_result":
                        # Gemini tool response format
                        parts.append({
                            "function_response": {
                                "name": block.get("name") or "unknown", # We need the name here
                                "response": {"result": block["content"]}
                            }
                        })
            
            gemini_history.append({"role": role, "parts": parts})

        # Separate last message from history
        last_msg = gemini_history.pop()
        
        # Initialize model
        gemini_model = genai.GenerativeModel(
            model_name=full_model,
            system_instruction=system_prompt,
            tools=self._convert_tools(tools) if tools else None,
        )

        # Run chat
        chat = gemini_model.start_chat(history=gemini_history)
        
        config = genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        
        response = await chat.send_message_async(
            last_msg["parts"],
            generation_config=config
        )

        # We need to wrap Gemini response to look like Anthropic response for compatibility
        # Or refactor the caller to handle both. For now, let's try to mimic enough.
        return self._wrap_gemini_response(response)

    async def validate_key(self) -> bool:
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            model.generate_content("Hello")
            return True
        except Exception:
            return False

    def estimate_cost(
        self, tokens_in: int, tokens_out: int, model: str, **kwargs
    ) -> float:
        """Estimate cost based on Gemini pricing (very approximate)."""
        # Gemini is often free or has complex tiering. 
        # Using a conservative estimate for Gemini 1.5 Pro
        pi, po = 3.5, 10.5 # $ per 1M tokens
        return (tokens_in / 1_000_000) * pi + (tokens_out / 1_000_000) * po

    def get_full_model_name(self, model_alias: str) -> str:
        return GEMINI_MODEL_MAPPING.get(model_alias.lower().strip(), model_alias)

    def _convert_tools(self, tools: list[dict]) -> list[genai.types.FunctionDeclaration]:
        """Convert Anthropic tool schemas to Gemini FunctionDeclarations."""
        # This is a complex conversion. For now, a simplified version.
        declarations = []
        for tool in tools:
            declarations.append(genai.types.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                parameters=tool["input_schema"]
            ))
        return [genai.types.Tool(function_declarations=declarations)]

    def _wrap_gemini_response(self, response: genai.types.GenerateContentResponse) -> Any:
        """Wrap Gemini response to look like Anthropic's Message object."""
        # This is a bit hacky but helps maintain compatibility without refactoring everything.
        class WrappedResponse:
            def __init__(self, res):
                self.id = f"gem-{res.candidates[0].index}"
                self.role = "assistant"
                self.content = []
                
                # Extract text and tool calls
                for part in res.candidates[0].content.parts:
                    if part.text:
                        self.content.append(type('TextPart', (), {"type": "text", "text": part.text})())
                    if part.function_call:
                        self.content.append(type('ToolUsePart', (), {
                            "type": "tool_use", 
                            "id": f"call_{part.function_call.name}",
                            "name": part.function_call.name,
                            "input": dict(part.function_call.args)
                        })())
                
                self.usage = type('Usage', (), {
                    "input_tokens": res.usage_metadata.prompt_token_count,
                    "output_tokens": res.usage_metadata.candidates_token_count
                })()
        
        return WrappedResponse(response)
