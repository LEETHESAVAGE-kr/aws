"""Bedrock 래퍼 타입 정의 — design.md §3 (spec:bedrock-client).

steering `engineering.md` §3 은 데이터 모델에 pydantic v2 를 권장하나, design.md §3 이
dataclass 를 명시하므로 spec 을 따랐다(gold-dataset 과 동일한 판단).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# ── 입력 타입 ────────────────────────────────────────────────────────────────


@dataclass
class ContentBlock:
    type: Literal["text", "tool_use", "tool_result", "image"]
    text: str | None = None
    tool_use_id: str | None = None
    tool_use_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_result_content: str | None = None


@dataclass
class Message:
    role: Literal["user", "assistant"]
    content: str | list[ContentBlock]


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema draft-07


# ── 응답 타입 ────────────────────────────────────────────────────────────────


@dataclass
class TokenUsage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ConverseResponse:
    content: str | None
    tool_use_blocks: list[ToolUseBlock] = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: TokenUsage = field(default_factory=TokenUsage)
    cost_usd: float = 0.0
    latency_s: float = 0.0
    call_id: str = ""
    confidence_override: str | None = None  # "review" — 스키마 검증 2회 실패 시


# ── 설정 타입 ────────────────────────────────────────────────────────────────


@dataclass
class ModelProfile:
    model_id: str
    temperature: float
    max_tokens: int
    prompt_caching: bool


@dataclass
class ModelConfig:
    region: str
    generation: ModelProfile
    verifier: ModelProfile
    embedding_model_id: str
    guardrails_id: str | None
    cost_limit_usd: float = 0.30
    # REQ-12: LLM 공급자. `anthropic` 이면 region·embedding·guardrails 는 쓰이지 않는다.
    provider: Literal["bedrock", "anthropic"] = "bedrock"
    # R-10: 가이드워드 판정 동시 호출 수(`generation.parallel_calls`). 1 이면 순차.
    parallel_calls: int = 4
