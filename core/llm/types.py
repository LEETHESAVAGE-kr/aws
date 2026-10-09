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
    provider: Literal["bedrock", "anthropic", "gateway"] = "bedrock"
    # R-10: 가이드워드 판정 동시 호출 수(`generation.parallel_calls`). 1 이면 순차.
    parallel_calls: int = 4
    # R-12: 열거 프롬프트에 공개 HAZOP 예시(data/kb/hazop_param_examples.json)를 덧붙일지. 기본 false.
    enumerate_examples: bool = False
    # Y-3: 판정 호출에 넣는 공식 문서 발췌 — 파라미터당 검색 수. 0 이면 근거 인용 끔(프롬프트 바이트 불변).
    evidence_k: int = 0
    # Z-1~Z-3: 추론 경계(정보 4단계·노드 유형별 경계표·셀 보류). 기본 false — 프롬프트 바이트 불변.
    inference_boundary: bool = False
    # 대회 AI 모델 게이트웨이(OpenAI 호환) — base_url · generation_model_id · verifier_model_id (별칭)
    gateway: dict[str, str] = field(default_factory=dict)
