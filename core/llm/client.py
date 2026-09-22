"""Bedrock Converse API 단일 진입 래퍼 — REQ-02~REQ-09 (spec:bedrock-client).

design.md 는 `base.py` / `cost.py` / `retry.py` / `caching.py` / `schema_validator.py` 로
쪼개지만, 지시문 B("압축 구현")에 따라 이 파일 하나에 담는다. design.md 의 이름
(AbstractBedrockClient, CachingBuilder, SchemaValidator, CostCalculator, RetryHandler,
BedrockClient)은 그대로 유지해 추적성을 보존한다.

boto3 직접 호출은 `BedrockClient._call_converse()` 한 곳뿐이다 (NFR-B04).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from functools import lru_cache, wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import boto3
import yaml
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from jsonschema import Draft7Validator

from .config import load_model_config
from .types import (
    ConverseResponse,
    Message,
    ModelConfig,
    TokenUsage,
    ToolDefinition,
    ToolUseBlock,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)  # core.llm.client (steering aws.md §5)

DEFAULT_COST_LIMIT_USD: Final[float] = 0.30
STRUCTURED_OUTPUT_TOOL: Final[str] = "structured_output"
_PRICES_PATH: Final[Path] = Path(__file__).parent.parent.parent / "config" / "prices.yaml"
_RETRY_MAX_ATTEMPTS: Final[int] = 3
_RETRY_WAIT_MIN_S: Final[float] = 1.0
_RETRY_WAIT_MAX_S: Final[float] = 10.0
_THROTTLING_CODES: Final[frozenset[str]] = frozenset(
    {"ThrottlingException", "ServiceUnavailableException"}
)
# anthropic SDK 의 HTTP 예외(REQ-12 / AC-12-5). `anthropic` 을 import 하지 않고 판정해야
# 한다 — 패키지가 없는 환경에서도 이 모듈이 import 돼야 하기 때문이다. `RateLimitError`·
# `InternalServerError` 는 둘 다 `APIStatusError` 의 하위 클래스라 MRO 이름으로 잡힌다.
_ANTHROPIC_HTTP_ERROR_NAMES: Final[frozenset[str]] = frozenset(
    {"APIStatusError", "RateLimitError", "InternalServerError"}
)


class BedrockCallError(RuntimeError):
    """재시도를 모두 소진하고도 Bedrock 호출이 실패했다."""


# ────────────────────────────────────────────────────────────────────────────
# RetryHandler (REQ-05) — design.md §7
# ────────────────────────────────────────────────────────────────────────────
def _anthropic_status(exc: BaseException) -> int | None:
    """anthropic SDK 의 HTTP 예외이면 상태코드, 아니면 `None` (클래스 이름 문자열로 판정)."""
    names = {cls.__name__ for cls in type(exc).__mro__}
    if not names & _ANTHROPIC_HTTP_ERROR_NAMES:
        return None
    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


def retry_reason(exc: BaseException) -> str | None:
    """재시도 대상이면 로그에 찍을 reason 문자열, 아니면 `None`.

    - Bedrock: `ThrottlingException`·`ServiceUnavailableException` (REQ-05)
    - Anthropic: 429(rate limit)·529(overloaded)·5xx → reason 은 HTTP 상태코드 문자열 (AC-12-5)
    """
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
        return code if code in _THROTTLING_CODES else None
    status = _anthropic_status(exc)
    if status is not None and (status == 429 or 500 <= status <= 599):
        return str(status)
    return None


def is_throttling_error(exc: BaseException) -> bool:
    """백오프 재시도 대상인가. Bedrock throttling + anthropic 429/5xx/529."""
    return retry_reason(exc) is not None


_sleep = time.sleep  # 테스트에서 monkeypatch 하여 대기 없이 재시도를 검증한다


def bedrock_retry[T](func: Callable[..., T]) -> Callable[..., T]:
    """지수 백오프(1s → 2s → …, 최대 10s) 최대 3회. design.md §7 의 tenacity 대체 구현.

    tenacity 를 쓰지 않는 이유: AC-05 가 요구하는 로그 형식
    (`재시도 attempt=<n>/3 reason=<code>`)이 `before_sleep_log` 기본 출력과 다르고,
    이 20줄을 위해 새 의존성을 추가하지 않기 위해서다(CLAUDE.md 규칙 9).
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        last: BaseException | None = None
        for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — 판정 후 재raise
                reason = retry_reason(exc)
                if reason is None:
                    raise
                last = exc
                logger.warning("재시도 attempt=%d/%d reason=%s", attempt, _RETRY_MAX_ATTEMPTS, reason)
                if attempt < _RETRY_MAX_ATTEMPTS:
                    _sleep(min(_RETRY_WAIT_MIN_S * 2 ** (attempt - 1), _RETRY_WAIT_MAX_S))
        raise BedrockCallError(f"Bedrock 호출 실패 ({_RETRY_MAX_ATTEMPTS}회 재시도 소진)") from last

    return wrapper


# ────────────────────────────────────────────────────────────────────────────
# CostCalculator (REQ-09) — 가격표는 config/prices.yaml (지시문 B)
# ────────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=4)
def load_price_table(path: Path = _PRICES_PATH) -> dict[str, dict[str, float]]:
    if not path.is_file():
        logger.warning("가격표 없음: %s — 모든 비용을 0 으로 기록한다", path)
        return {}
    # design.md §10: 최상위가 곧 `<model_id>: {input, output, cache_read, cache_write}` 매핑이다.
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        str(model_id): {str(k): float(v) for k, v in entry.items()}
        for model_id, entry in raw.items()
        if isinstance(entry, dict)
    }


_warned_models: set[str] = set()


def calculate_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """USD 비용. 가격표에 없는 모델은 예외 대신 비용 0 + WARNING 1회 (CLAUDE.md 범위 규율)."""
    prices = load_price_table()
    entry = prices.get(model_id)
    if entry is None:
        if model_id not in _warned_models:
            logger.warning("가격표에 없는 모델: %s — 비용 0 으로 기록", model_id)
            _warned_models.add(model_id)
        return 0.0
    return (
        input_tokens / 1000 * entry.get("input", 0.0)
        + output_tokens / 1000 * entry.get("output", 0.0)
        + cache_read_tokens / 1000 * entry.get("cache_read", 0.0)
        + cache_write_tokens / 1000 * entry.get("cache_write", 0.0)
    )


class CostCalculator:
    """`calculate_cost` 의 얇은 래퍼 (design.md §10 이름 보존)."""

    @staticmethod
    def calculate(model_id: str, usage: TokenUsage) -> float:
        return calculate_cost(
            model_id, usage.input, usage.output, usage.cache_read, usage.cache_write
        )


# ────────────────────────────────────────────────────────────────────────────
# CachingBuilder (REQ-08) — design.md §8
# ────────────────────────────────────────────────────────────────────────────
class CachingBuilder:
    @staticmethod
    def build_system_blocks(system: str, caching_on: bool) -> list[dict[str, Any]]:
        block: dict[str, Any] = {"text": system}
        if caching_on:
            block["cachePoint"] = {"type": "default"}
        return [block]


# ────────────────────────────────────────────────────────────────────────────
# SchemaValidator (REQ-04) — design.md §9
# ────────────────────────────────────────────────────────────────────────────
def build_structured_output_tool(schema: dict[str, Any]) -> ToolDefinition:
    return ToolDefinition(
        name=STRUCTURED_OUTPUT_TOOL,
        description="결과를 이 스키마에 맞는 JSON 오브젝트로 반환한다.",
        input_schema=schema,
    )


class SchemaValidator:
    @staticmethod
    def passes(content: str | None, schema: dict[str, Any]) -> bool:
        if content is None:
            return False
        try:
            instance = json.loads(content)
        except (TypeError, ValueError):
            return False
        return not list(Draft7Validator(schema).iter_errors(instance))

    @classmethod
    def validate_and_retry(
        cls,
        response: ConverseResponse,
        schema: dict[str, Any],
        retry_fn: Callable[[], ConverseResponse],
    ) -> ConverseResponse:
        if cls.passes(response.content, schema):
            return response
        logger.warning("schema validation failed, retry 1/1")
        retried = retry_fn()
        if cls.passes(retried.content, schema):
            return retried
        retried.content = None
        retried.confidence_override = "review"
        return retried


# ────────────────────────────────────────────────────────────────────────────
# AbstractBedrockClient (REQ-02·04·06·07) — design.md §5
# ────────────────────────────────────────────────────────────────────────────
class AbstractBedrockClient(ABC):
    """`BedrockClient` 와 `MockBedrockClient` 의 공통 인터페이스 및 pre/post 훅."""

    model_short: str = "unknown"
    cost_limit_usd: float = DEFAULT_COST_LIMIT_USD

    def converse(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        response_schema: dict[str, Any] | None = None,
        context: dict[str, str] | None = None,
    ) -> ConverseResponse:
        if not system:
            raise ValueError("system prompt must not be empty")
        if not messages:
            raise ValueError("messages must not be empty")

        call_id = str(uuid.uuid4())
        node_id = (context or {}).get("node", "unknown")
        started = time.perf_counter()

        def _invoke() -> ConverseResponse:
            return self._do_converse(
                call_id=call_id,
                system=system,
                messages=messages,
                tools=tools or [],
                response_schema=response_schema,
            )

        response = _invoke()
        if response_schema is not None:
            # REQ-04 는 두 클라이언트 모두에 적용되므로 design.md §6(7) 대신 여기서 조율한다.
            response = SchemaValidator.validate_and_retry(response, response_schema, _invoke)

        response.latency_s = max(response.latency_s, time.perf_counter() - started)
        response.call_id = call_id
        self._log_call(response, node_id)
        self._check_cost_limit(response.cost_usd, node_id)
        return response

    @abstractmethod
    def _do_converse(
        self,
        call_id: str,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition],
        response_schema: dict[str, Any] | None,
    ) -> ConverseResponse: ...

    def _log_call(self, response: ConverseResponse, node_id: str) -> None:
        logger.info(
            "call_id=%s node=%s model=%s tokens_in=%d tokens_out=%d "
            "cache_read=%d cost_usd=%.4f latency_s=%.1f",
            response.call_id,
            node_id,
            self.model_short,
            response.usage.input,
            response.usage.output,
            response.usage.cache_read,
            response.cost_usd,
            response.latency_s,
        )

    def _check_cost_limit(self, cost: float, node_id: str) -> None:
        if cost > self.cost_limit_usd:
            logger.warning(
                "node=%s cumulative_cost_usd=%.4f EXCEEDS LIMIT %.2f",
                node_id,
                cost,
                self.cost_limit_usd,
            )


# ────────────────────────────────────────────────────────────────────────────
# BedrockClient (REQ-02·03·05·08) — design.md §6
# ────────────────────────────────────────────────────────────────────────────
class BedrockClient(AbstractBedrockClient):
    """실 Bedrock Converse API 클라이언트.

    주의: 2026-09-06 현재 `config/models.yaml` 의 모델 ID 가 비어 있어(G0 미완료)
    생성자가 `ConfigValidationError` 로 실패한다. 실호출 경로는 미검증이다.
    """

    def __init__(self, config: ModelConfig | None = None, profile: str = "generation") -> None:
        self._cfg = config or load_model_config()
        self._profile = getattr(self._cfg, profile)
        self.model_short = self._profile.model_id.split(".")[-1].split(":")[0] or "unknown"
        self.cost_limit_usd = self._cfg.cost_limit_usd
        self._boto = boto3.client(
            "bedrock-runtime",
            region_name=self._cfg.region,
            # 재시도는 bedrock_retry 가 담당하므로 boto3 자체 재시도는 1회로 제한한다.
            config=BotoConfig(retries={"mode": "standard", "max_attempts": 1}),
        )

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
            all_tools.append(build_structured_output_tool(response_schema))
            tool_choice = {"tool": {"name": STRUCTURED_OUTPUT_TOOL}}

        kwargs: dict[str, Any] = {
            "modelId": self._profile.model_id,
            "system": CachingBuilder.build_system_blocks(system, self._profile.prompt_caching),
            "messages": _to_boto_messages(messages),
            "inferenceConfig": {
                "temperature": self._profile.temperature,
                "maxTokens": self._profile.max_tokens,
            },
        }
        if all_tools:
            kwargs["toolConfig"] = _build_tool_config(all_tools, tool_choice)
        if self._cfg.guardrails_id:
            kwargs["guardrailConfig"] = {
                "guardrailIdentifier": self._cfg.guardrails_id,
                "guardrailVersion": "DRAFT",
            }

        started = time.perf_counter()
        raw = self._call_converse(**kwargs)
        latency_s = time.perf_counter() - started
        return self._parse_response(raw, call_id, latency_s)

    @bedrock_retry
    def _call_converse(self, **kwargs: Any) -> dict[str, Any]:
        """boto3 를 직접 호출하는 유일한 지점 (NFR-B04)."""
        return self._boto.converse(**kwargs)  # type: ignore[no-any-return]

    def _parse_response(
        self, raw: dict[str, Any], call_id: str, latency_s: float
    ) -> ConverseResponse:
        blocks = raw.get("output", {}).get("message", {}).get("content", [])
        texts: list[str] = []
        tool_uses: list[ToolUseBlock] = []
        for block in blocks:
            if "text" in block:
                texts.append(str(block["text"]))
            elif "toolUse" in block:
                use = block["toolUse"]
                tool_uses.append(
                    ToolUseBlock(
                        id=str(use.get("toolUseId", "")),
                        name=str(use.get("name", "")),
                        input=dict(use.get("input", {})),
                    )
                )
        usage_raw = raw.get("usage", {})
        usage = TokenUsage(
            input=int(usage_raw.get("inputTokens", 0)),
            output=int(usage_raw.get("outputTokens", 0)),
            cache_read=int(usage_raw.get("cacheReadInputTokens", 0)),
            cache_write=int(usage_raw.get("cacheWriteInputTokens", 0)),
        )
        # structured_output tool 로 강제한 JSON 은 content 로 승격해 스키마 검증 대상이 되게 한다.
        content: str | None = "\n".join(texts) if texts else None
        structured = next((t for t in tool_uses if t.name == STRUCTURED_OUTPUT_TOOL), None)
        if structured is not None:
            content = json.dumps(structured.input, ensure_ascii=False)
        return ConverseResponse(
            content=content,
            tool_use_blocks=[t for t in tool_uses if t.name != STRUCTURED_OUTPUT_TOOL],
            stop_reason=str(raw.get("stopReason", "end_turn")),
            usage=usage,
            cost_usd=CostCalculator.calculate(self._profile.model_id, usage),
            latency_s=latency_s,
            call_id=call_id,
        )


def _to_boto_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message.content, str):
            content: list[dict[str, Any]] = [{"text": message.content}]
        else:
            content = [_to_boto_block(b) for b in message.content]
        out.append({"role": message.role, "content": content})
    return out


def _to_boto_block(block: Any) -> dict[str, Any]:
    if block.type == "tool_use":
        return {
            "toolUse": {
                "toolUseId": block.tool_use_id,
                "name": block.tool_use_name,
                "input": block.tool_input or {},
            }
        }
    if block.type == "tool_result":
        return {
            "toolResult": {
                "toolUseId": block.tool_use_id,
                "content": [{"text": block.tool_result_content or ""}],
            }
        }
    return {"text": block.text or ""}


def _build_tool_config(
    tools: list[ToolDefinition], tool_choice: dict[str, Any] | None
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "tools": [
            {
                "toolSpec": {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": {"json": t.input_schema},
                }
            }
            for t in tools
        ]
    }
    if tool_choice is not None:
        config["toolChoice"] = tool_choice
    return config
