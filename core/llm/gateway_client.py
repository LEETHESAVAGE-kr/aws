"""대회 AI 모델 게이트웨이(OpenAI Chat Completions 호환) 공급자 어댑터 — PRD 추론경계·Kiro K-2 B.

근거: 「AI 모델 API 사용 가이드」(고려대 AI Innovators Challenge, 넥스트클라우드 테크니컬 트레이닝 팀) —
base_url `https://52.79.201.46/v1`, `Authorization: Bearer <키>`, 모델은 별칭(`bedrock-haiku` 등),
허용 별칭 목록은 `GET /v1/models`. 주소·별칭은 `config/models.yaml` 의 `gateway:` 절에만 둔다.

`AnthropicClient` 와 같은 `converse()` 계약을 지킨다 — JSON 스키마 강제는 function tool 1개 +
`tool_choice` 로, 결과 tool 인자를 content JSON 으로 승격한다. 재시도는 기존 `bedrock_retry`(429·5xx).
새 의존성 없이 표준 라이브러리 `urllib` 로 부른다. TLS 는 **certifi 인증서 묶음**으로 검증한다 —
10/9 이 PC 의 파이썬 기본 저장소로는 Let's Encrypt 체인이 'certificate has expired' 로 실패했고
(Windows curl·certifi 는 통과), 검증을 끄지는 않는다. 키는 환경변수 `HAZOP_GATEWAY_KEY`
(없으면 `KIRO_API_KEY`)에서만 읽고 로그·예외 메시지에 남기지 않는다.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any, Final

from .anthropic_client import short_model_id
from .client import STRUCTURED_OUTPUT_TOOL, AbstractBedrockClient, CostCalculator, bedrock_retry
from .config import load_model_config
from .types import ConverseResponse, TokenUsage, ToolUseBlock

if TYPE_CHECKING:
    from .types import Message, ModelConfig, ToolDefinition

KEY_ENV_NAMES: Final[tuple[str, ...]] = ("HAZOP_GATEWAY_KEY", "KIRO_API_KEY")
#: finish_reason → 기존 stop_reason 어휘(절단 집계가 "max_tokens" 를 본다).
_STOP: Final[dict[str, str]] = {"length": "max_tokens", "tool_calls": "tool_use", "stop": "end_turn"}


class APIStatusError(RuntimeError):
    """HTTP 오류. 이름이 `client._ANTHROPIC_HTTP_ERROR_NAMES` 에 있어 429·5xx 가 재시도된다. 본문은 300자까지만."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"gateway HTTP {status_code}: {message[:300]}")
        self.status_code = status_code


def gateway_key(environ: Any = os.environ) -> str:
    return next((environ.get(n, "").strip() for n in KEY_ENV_NAMES if environ.get(n, "").strip()), "")


def _ssl_context() -> ssl.SSLContext:
    import certifi

    return ssl.create_default_context(cafile=certifi.where())


class GatewayClient(AbstractBedrockClient):
    def __init__(self, config: ModelConfig | None = None, profile: str = "generation") -> None:
        self._cfg = config or load_model_config()
        self._profile = getattr(self._cfg, profile)
        gateway = self._cfg.gateway
        self.base_url = str(gateway.get("base_url", "")).rstrip("/")
        self.model_id = str(gateway.get(f"{profile}_model_id", ""))
        if not self.base_url or not self.model_id:
            from .config import ConfigValidationError

            raise ConfigValidationError(f"models.yaml gateway.base_url·{profile}_model_id 필요")
        self.model_short = short_model_id(self.model_id)
        self.cost_limit_usd = self._cfg.cost_limit_usd

    @bedrock_retry
    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """게이트웨이를 직접 호출하는 유일한 지점."""
        key = gateway_key()
        if not key:
            raise APIStatusError(401, "게이트웨이 키 환경변수(HAZOP_GATEWAY_KEY 또는 KIRO_API_KEY)가 비어 있다")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=300, context=_ssl_context()) as response:  # noqa: S310
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise APIStatusError(exc.code, exc.read().decode("utf-8", "replace")) from None

    def _do_converse(
        self,
        call_id: str,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition],
        response_schema: dict[str, Any] | None,
    ) -> ConverseResponse:
        functions = [{"type": "function", "function": {
            "name": t.name, "description": t.description, "parameters": t.input_schema}} for t in tools]
        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": [{"role": "system", "content": system}, *[_to_openai(m) for m in messages]],
            "max_tokens": self._profile.max_tokens,
        }
        if response_schema is not None:
            functions.append({"type": "function", "function": {
                "name": STRUCTURED_OUTPUT_TOOL, "description": "응답을 이 스키마의 JSON 으로 반환한다.",
                "parameters": response_schema}})
            payload["tool_choice"] = {"type": "function", "function": {"name": STRUCTURED_OUTPUT_TOOL}}
        if functions:
            payload["tools"] = functions
        started = time.perf_counter()
        raw = self._post(payload)
        return self._parse(raw, call_id, time.perf_counter() - started)

    def _parse(self, raw: dict[str, Any], call_id: str, latency_s: float) -> ConverseResponse:
        choice = (raw.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls = [
            ToolUseBlock(id=str(c.get("id", "")), name=str(c["function"]["name"]),
                         input=_json_or_empty(c["function"].get("arguments")))
            for c in message.get("tool_calls") or [] if c.get("function")
        ]
        content: str | None = message.get("content") or None
        structured = next((c for c in calls if c.name == STRUCTURED_OUTPUT_TOOL), None)
        if structured is not None:
            content = json.dumps(structured.input, ensure_ascii=False)
        u = raw.get("usage") or {}
        cached = int(((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
        usage = TokenUsage(input=int(u.get("prompt_tokens") or 0) - cached,
                           output=int(u.get("completion_tokens") or 0), cache_read=cached, cache_write=0)
        return ConverseResponse(
            content=content,
            tool_use_blocks=[c for c in calls if c.name != STRUCTURED_OUTPUT_TOOL],
            stop_reason=_STOP.get(str(choice.get("finish_reason")), str(choice.get("finish_reason") or "end_turn")),
            usage=usage,
            cost_usd=CostCalculator.calculate(self.model_id, usage),
            latency_s=latency_s,
            call_id=call_id,
        )

    def list_models(self) -> list[str]:
        """`GET /v1/models` — 이 키로 부를 수 있는 별칭(가이드 3번)."""
        request = urllib.request.Request(f"{self.base_url}/models", headers={"Authorization": f"Bearer {gateway_key()}"})
        with urllib.request.urlopen(request, timeout=30, context=_ssl_context()) as response:  # noqa: S310
            return [str(m["id"]) for m in json.loads(response.read()).get("data", [])]


def _json_or_empty(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    try:
        value = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {}  # 스키마 검증이 실패로 잡아 1회 재시도 → review(조용히 통과 금지)
    return value if isinstance(value, dict) else {}


def _to_openai(message: Message) -> dict[str, Any]:
    if isinstance(message.content, str):
        return {"role": message.role, "content": message.content}
    return {"role": message.role, "content": "\n".join(b.text or b.tool_result_content or "" for b in message.content)}


__all__ = ["APIStatusError", "GatewayClient", "gateway_key"]
