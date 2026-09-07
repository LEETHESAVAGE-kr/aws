"""Bedrock 래퍼 공개 인터페이스 — design.md §12 (spec:bedrock-client)."""

from __future__ import annotations

import os

from .client import (
    AbstractBedrockClient,
    BedrockCallError,
    BedrockClient,
    CachingBuilder,
    CostCalculator,
    SchemaValidator,
    build_structured_output_tool,
    calculate_cost,
    is_throttling_error,
)
from .config import ConfigValidationError, load_model_config
from .mock import MockBedrockClient, MockExhaustedError
from .types import (
    ContentBlock,
    ConverseResponse,
    Message,
    ModelConfig,
    ModelProfile,
    TokenUsage,
    ToolDefinition,
    ToolUseBlock,
)

__all__ = [
    "AbstractBedrockClient",
    "BedrockCallError",
    "BedrockClient",
    "CachingBuilder",
    "ConfigValidationError",
    "ContentBlock",
    "ConverseResponse",
    "CostCalculator",
    "Message",
    "MockBedrockClient",
    "MockExhaustedError",
    "ModelConfig",
    "ModelProfile",
    "SchemaValidator",
    "TokenUsage",
    "ToolDefinition",
    "ToolUseBlock",
    "build_structured_output_tool",
    "calculate_cost",
    "get_bedrock_client",
    "is_throttling_error",
    "load_model_config",
]


def get_bedrock_client() -> AbstractBedrockClient:
    """`HAZOP_USE_MOCK=true` 이면 `MockBedrockClient`, 아니면 실 `BedrockClient`."""
    if os.environ.get("HAZOP_USE_MOCK", "false").lower() == "true":
        return MockBedrockClient()
    return BedrockClient()
