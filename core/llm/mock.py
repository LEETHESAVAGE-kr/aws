"""오프라인 테스트용 모의 클라이언트 — REQ-10 (design.md §11).

`AbstractBedrockClient` 를 상속하므로 로깅·비용 경고·스키마 재시도 훅이 실 클라이언트와
동일하게 실행된다. AWS 자격증명·네트워크·`config/models.yaml` 없이 동작한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .client import DEFAULT_COST_LIMIT_USD, AbstractBedrockClient

if TYPE_CHECKING:
    from collections.abc import Callable

    from .types import ConverseResponse, Message, ToolDefinition


class MockExhaustedError(RuntimeError):
    """주입한 응답을 모두 소진했다."""


class MockBedrockClient(AbstractBedrockClient):
    def __init__(
        self,
        responses: list[ConverseResponse] | None = None,
        response_factory: Callable[..., ConverseResponse] | None = None,
        cost_limit_usd: float = DEFAULT_COST_LIMIT_USD,
        model_short: str = "mock",
    ) -> None:
        self._responses = list(responses or [])
        self._factory = response_factory
        self.calls: list[dict[str, Any]] = []  # 호출 이력 — 테스트에서 검증
        self.cost_limit_usd = cost_limit_usd
        self.model_short = model_short

    def _do_converse(
        self,
        call_id: str,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition],
        response_schema: dict[str, Any] | None,
    ) -> ConverseResponse:
        self.calls.append(
            {
                "call_id": call_id,
                "system": system,
                "messages": messages,
                "tools": tools,
                "response_schema": response_schema,
            }
        )
        if self._factory is not None:
            # Y-2: 기준별 S·F 상한이 스키마에 실려 온다 — 공장이 필요하면 읽는다(받지 않는 공장은 **_ 로 무시)
            return self._factory(system=system, messages=messages, response_schema=response_schema)
        if self._responses:
            return self._responses.pop(0)
        raise MockExhaustedError("MockBedrockClient: no more responses")
