"""Bedrock 래퍼 공개 인터페이스 — design.md §12 (spec:bedrock-client)."""

from __future__ import annotations

import os

from . import client as _client_mod
from .anthropic_client import AnthropicClient
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
    "AnthropicClient",
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
    """`HAZOP_USE_MOCK=true` 이면 Mock, 아니면 `models.yaml` 의 `provider` 로 분기한다 (REQ-12).

    설정은 여기서 한 번만 읽어 클라이언트에 주입한다 — 공급자 판정과 클라이언트가
    서로 다른 설정을 볼 여지를 없애기 위함이다. `client` 모듈을 경유하는 것은
    설정 해석 지점을 한 곳(`core.llm.client`)으로 유지하기 위해서다.
    """
    if os.environ.get("HAZOP_USE_MOCK", "false").lower() == "true":
        return MockBedrockClient()
    config = _client_mod.load_model_config()
    if config.provider == "anthropic":
        return AnthropicClient(config=config)
    return BedrockClient(config=config)
