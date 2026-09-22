"""Anthropic Messages API 공급자 어댑터 — REQ-12 / T-15 (spec:bedrock-client).

`config/models.yaml` 의 `provider` 가 `anthropic` 일 때 `BedrockClient` 와 동일한
`converse()` 계약(시스템 프롬프트·메시지·tool·JSON 스키마 강제·재시도·토큰/비용/지연
로깅)을 수행한다. 호출부는 `AbstractBedrockClient` 만 보므로 `core/agent`·`core/export`
는 한 줄도 바뀌지 않는다(AC-12-1).

`anthropic` SDK 를 직접 호출하는 지점은 `AnthropicClient._call_messages()` 한 곳뿐이다
(client.py 의 NFR-B04 와 같은 원칙). `anthropic` import 도 이 모듈 안에서만, 그것도
지연 import 로 한다 — 패키지가 없는 환경에서도 `core.llm` 전체가 import 돼야 한다.
재시도 대상 예외 판정은 `client.is_throttling_error()` 가 클래스 이름 문자열로 처리한다.

API 키는 환경변수 `ANTHROPIC_API_KEY` 로만 읽는다(AC-12-3). SDK 의 기본 자격증명 해석에
맡기므로 이 파일·`config/models.yaml`·로그 어디에도 키가 나타나지 않는다.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, Final

from .client import (
    STRUCTURED_OUTPUT_TOOL,
    AbstractBedrockClient,
    CostCalculator,
    bedrock_retry,
    build_structured_output_tool,
)
from .config import load_model_config
from .types import ConverseResponse, TokenUsage, ToolUseBlock

if TYPE_CHECKING:
    from .types import ContentBlock, Message, ModelConfig, ToolDefinition

logger = logging.getLogger(__name__)

#: `model_short` 는 로그 가독성용이다 — 전체 id 를 짧게 자른 값 (steering aws.md §5).
_MODEL_SHORT_MAX: Final[int] = 24


def build_system_blocks(system: str, caching_on: bool) -> list[dict[str, Any]]:
    """Anthropic 시스템 블록. `prompt_caching: true` 이면 `cache_control` 을 붙인다(AC-12-4).

    Bedrock 의 `cachePoint: {"type": "default"}` 에 대응하는 마커다
    (`client.CachingBuilder.build_system_blocks` 와 같은 자리).
    """
    block: dict[str, Any] = {"type": "text", "text": system}
    if caching_on:
        block["cache_control"] = {"type": "ephemeral"}
    return [block]


def short_model_id(model_id: str) -> str:
    """로그용 축약 모델 id. 값이 비면 `unknown`."""
    short = model_id.rsplit("/", 1)[-1].split(":")[0].strip()
    return short[:_MODEL_SHORT_MAX] or "unknown"


class AnthropicClient(AbstractBedrockClient):
    """실 Anthropic Messages API 클라이언트.

    `config/models.yaml` 의 `model_id` 가 비어 있는 동안(2단계 미완료) 생성자가
    `ConfigValidationError` 로 실패한다 — 값을 추측해 채우지 않는다.
    """

    def __init__(self, config: ModelConfig | None = None, profile: str = "generation") -> None:
        self._cfg = config or load_model_config()
        self._profile = getattr(self._cfg, profile)
        self.model_short = short_model_id(self._profile.model_id)
        self.cost_limit_usd = self._cfg.cost_limit_usd
        self._sdk_client: Any = None  # 지연 생성 — 오프라인 테스트에서는 만들어지지 않는다

    # ── SDK 경계 ────────────────────────────────────────────────────────────
    def _sdk(self) -> Any:
        """`anthropic.Anthropic()` 을 처음 필요할 때 만든다.

        지연 생성 이유 두 가지: (1) `anthropic` 미설치 환경에서도 이 모듈이 import 돼야
        하고, (2) 자격증명 없이 생성자를 호출하면 실패하므로 오프라인 테스트가
        `_call_messages`/`_sdk` 만 대체하면 되게 한다.
        """
        if self._sdk_client is None:
            import anthropic

            # api_key 를 넘기지 않는다 — SDK 가 ANTHROPIC_API_KEY 환경변수에서 읽는다(AC-12-3).
            self._sdk_client = anthropic.Anthropic()
        return self._sdk_client

    @bedrock_retry
    def _call_messages(self, **kwargs: Any) -> Any:
        """anthropic SDK 를 직접 호출하는 유일한 지점 (NFR-B04 와 같은 원칙)."""
        return self._sdk().messages.create(**kwargs)

    # ── converse 구현 ───────────────────────────────────────────────────────
    def _do_converse(
        self,
        call_id: str,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition],
        response_schema: dict[str, Any] | None,
    ) -> ConverseResponse:
        all_tools = list(tools)
        tool_choice: dict[str, Any] | None = None
        if response_schema is not None:
            # BedrockClient 와 동일한 승격 규칙 — tool input 을 content JSON 으로 올린다.
            all_tools.append(build_structured_output_tool(response_schema))
            tool_choice = {"type": "tool", "name": STRUCTURED_OUTPUT_TOOL}

        kwargs: dict[str, Any] = {
            "model": self._profile.model_id,
            "system": build_system_blocks(system, self._profile.prompt_caching),
            "messages": _to_anthropic_messages(messages),
            "max_tokens": self._profile.max_tokens,
        }
        # `temperature` 는 일부러 보내지 않는다. Anthropic 최신 모델(Opus 4.7/4.8·Sonnet 5·
        # Fable 5)에서 sampling 파라미터가 제거돼 400 을 돌려주기 때문이다
        # (claude-api 스킬 shared/model-migration.md). 2단계에서 모델이 확정되면
        # 그 모델이 temperature 를 받는지 확인한 뒤 되살릴지 판단한다.
        if all_tools:
            kwargs["tools"] = _build_tools(all_tools)
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        started = time.perf_counter()
        raw = self._call_messages(**kwargs)
        latency_s = time.perf_counter() - started
        return self._parse_message(raw, call_id, latency_s)

    def _parse_message(self, raw: Any, call_id: str, latency_s: float) -> ConverseResponse:
        texts: list[str] = []
        tool_uses: list[ToolUseBlock] = []
        for block in getattr(raw, "content", None) or []:
            block_type = getattr(block, "type", "")
            if block_type == "text":
                texts.append(str(getattr(block, "text", "")))
            elif block_type == "tool_use":
                tool_uses.append(
                    ToolUseBlock(
                        id=str(getattr(block, "id", "")),
                        name=str(getattr(block, "name", "")),
                        input=dict(getattr(block, "input", None) or {}),
                    )
                )

        usage_raw = getattr(raw, "usage", None)
        usage = TokenUsage(
            input=_int_attr(usage_raw, "input_tokens"),
            output=_int_attr(usage_raw, "output_tokens"),
            cache_read=_int_attr(usage_raw, "cache_read_input_tokens"),
            cache_write=_int_attr(usage_raw, "cache_creation_input_tokens"),
        )

        # structured_output tool 로 강제한 JSON 은 content 로 승격해 스키마 검증 대상이 되게 한다.
        content: str | None = "\n".join(texts) if texts else None
        structured = next((t for t in tool_uses if t.name == STRUCTURED_OUTPUT_TOOL), None)
        if structured is not None:
            content = json.dumps(structured.input, ensure_ascii=False)

        return ConverseResponse(
            content=content,
            tool_use_blocks=[t for t in tool_uses if t.name != STRUCTURED_OUTPUT_TOOL],
            # stop_reason 은 Anthropic 값 그대로 둔다(end_turn·tool_use·max_tokens).
            stop_reason=str(getattr(raw, "stop_reason", None) or "end_turn"),
            usage=usage,
            cost_usd=CostCalculator.calculate(self._profile.model_id, usage),
            latency_s=latency_s,
            call_id=call_id,
        )


def _int_attr(obj: Any, name: str) -> int:
    """usage 필드는 SDK 에서 `None` 으로 올 수 있다(캐시 미사용 시)."""
    value = getattr(obj, name, None)
    return int(value) if isinstance(value, int) else 0


def _to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message.content, str):
            content: list[dict[str, Any]] = [{"type": "text", "text": message.content}]
        else:
            content = [_to_anthropic_block(b) for b in message.content]
        out.append({"role": message.role, "content": content})
    return out


def _to_anthropic_block(block: ContentBlock) -> dict[str, Any]:
    if block.type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.tool_use_id,
            "name": block.tool_use_name,
            "input": block.tool_input or {},
        }
    if block.type == "tool_result":
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": [{"type": "text", "text": block.tool_result_content or ""}],
        }
    return {"type": "text", "text": block.text or ""}


def _build_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]
