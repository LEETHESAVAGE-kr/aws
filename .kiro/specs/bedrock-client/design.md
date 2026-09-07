# Design — bedrock-client

spec: `bedrock-client`  
버전: 1.0 · 작성 2026-09-04  
상위 문서: `requirements.md` (REQ-01~11), `PRD.md` §5 FR-02, steering `aws.md`, steering `engineering.md`

---

## 1. 전체 아키텍처

```
호출자 (core/agent/, eval/, services/api/)
        │
        │  get_bedrock_client()  ← HAZOP_USE_MOCK 환경변수로 분기
        ▼
┌─────────────────────────────────────────────────────────┐
│  AbstractBedrockClient  (core/llm/base.py)              │
│  converse(system, messages, tools, response_schema)     │
└─────────┬───────────────────────────┬───────────────────┘
          │                           │
          ▼                           ▼
┌──────────────────────┐   ┌──────────────────────────┐
│  BedrockClient       │   │  MockBedrockClient        │
│  (core/llm/client.py)│   │  (core/llm/mock.py)       │
│                      │   │                           │
│  ┌────────────────┐  │   │  responses: list[...]     │
│  │ _call_converse │  │   │  calls: list[dict]        │
│  │  (boto3 단일   │  │   │  response_factory         │
│  │   호출 지점)   │  │   └──────────────────────────┘
│  └────────────────┘  │
└──────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│  공유 믹스인 / 유틸리티                                  │
│  ├─ ConfigLoader      (core/llm/config.py)              │
│  ├─ CostCalculator    (core/llm/cost.py)                │
│  ├─ RetryHandler      (core/llm/retry.py)               │
│  ├─ CachingBuilder    (core/llm/caching.py)             │
│  └─ SchemaValidator   (core/llm/schema_validator.py)    │
└─────────────────────────────────────────────────────────┘
```

설계 원칙:
- `boto3` 직접 호출은 `BedrockClient._call_converse()` 단 한 곳에 격리 (NFR-B04).
- `MockBedrockClient` 는 `AbstractBedrockClient` 를 구현하며, 공유 유틸리티(비용·로깅·캐싱 검증)를 그대로 실행한다.
- `get_bedrock_client()` 팩토리가 `HAZOP_USE_MOCK` 환경변수를 읽어 인스턴스를 결정한다.

---

## 2. 모듈 구조

```
core/llm/
├─ __init__.py              # 공개 인터페이스 re-export
│                           #   AbstractBedrockClient, BedrockClient,
│                           #   MockBedrockClient, get_bedrock_client
├─ base.py                  # AbstractBedrockClient, 공유 pre/post 훅
├─ client.py                # BedrockClient (boto3 의존)
├─ mock.py                  # MockBedrockClient (boto3 의존 없음)
├─ config.py                # ConfigLoader, ModelConfig, load_model_config()
├─ cost.py                  # CostCalculator, PRICE_TABLE, calculate_cost()
├─ retry.py                 # RetryHandler, is_throttling_error()
├─ caching.py               # CachingBuilder — cachePoint 블록 생성
├─ schema_validator.py      # SchemaValidator — jsonschema 검증 + 재시도 조율
└─ types.py                 # Message, ToolDefinition, ConverseResponse,
                            # TokenUsage, ToolUseBlock, ContentBlock 등

config/
└─ models.yaml              # 단일 설정 소스 (REQ-01)

tests/
├─ test_bedrock_client.py   # 오프라인 테스트 (MockBedrockClient 사용)
│   └─ fixtures/llm/
│       ├─ mock_response_end_turn.json
│       ├─ mock_response_tool_use.json
│       └─ mock_response_schema_fail.json
└─ conftest.py              # monkeypatch HAZOP_USE_MOCK, shared fixtures
```

---

## 3. 타입 정의 (`core/llm/types.py`)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal

# ── 입력 타입 ──────────────────────────────────────────

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
    input_schema: dict[str, Any]   # JSON Schema draft-07

# ── 응답 타입 ──────────────────────────────────────────

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
    content: str | None                    # end_turn 시 텍스트 또는 structured JSON
    tool_use_blocks: list[ToolUseBlock]    # stop_reason="tool_use" 시 비어 있지 않음
    stop_reason: str                       # "end_turn" | "tool_use" | "max_tokens"
    usage: TokenUsage
    cost_usd: float
    latency_s: float
    call_id: str                           # UUID4
    confidence_override: str | None = None # "review" — 스키마 검증 2회 실패 시

# ── 설정 타입 ──────────────────────────────────────────

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
```

---

## 4. `ConfigLoader` (`core/llm/config.py`)

```python
from __future__ import annotations
from pathlib import Path
import yaml
from .types import ModelConfig, ModelProfile

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "models.yaml"

class ConfigValidationError(ValueError):
    """models.yaml 필수 필드 누락 또는 값 범위 오류."""

def load_model_config(path: Path = _CONFIG_PATH) -> ModelConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    _validate_raw(raw)
    return _parse(raw)

def _validate_raw(raw: dict) -> None:
    required_top = {"region", "generation", "verifier", "embedding"}
    missing = required_top - raw.keys()
    if missing:
        raise ConfigValidationError(f"missing fields: {sorted(missing)}")
    for profile_key in ("generation", "verifier"):
        p = raw[profile_key]
        if not (0.0 <= p.get("temperature", -1) <= 1.0):
            raise ConfigValidationError(
                f"{profile_key}.temperature must be 0.0–1.0"
            )
```

로드는 모듈 임포트 시 1회 수행하고 `functools.lru_cache` 로 캐시한다. 테스트에서 `monkeypatch` 로 경로를 교체하여 격리한다.

---

## 5. `AbstractBedrockClient` 와 공유 훅 (`core/llm/base.py`)

```python
from __future__ import annotations
import logging
import time
import uuid
from abc import ABC, abstractmethod
from .types import ConverseResponse, Message, ToolDefinition

logger = logging.getLogger(__name__)

class AbstractBedrockClient(ABC):
    """BedrockClient와 MockBedrockClient 공통 인터페이스 및 pre/post 훅."""

    def converse(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        response_schema: dict | None = None,
        context: dict[str, str] | None = None,
    ) -> ConverseResponse:
        # ── 입력 검증
        if not system:
            raise ValueError("system prompt must not be empty")
        if not messages:
            raise ValueError("messages must not be empty")

        call_id = str(uuid.uuid4())
        node_id = (context or {}).get("node", "unknown")
        t0 = time.monotonic()

        # ── 실제 호출 (하위 클래스 구현)
        response = self._do_converse(
            call_id=call_id,
            system=system,
            messages=messages,
            tools=tools or [],
            response_schema=response_schema,
        )

        # ── latency 보정 (하위 클래스가 이미 계산했을 수 있으므로 최솟값 보장)
        response.latency_s = max(response.latency_s, time.monotonic() - t0)
        response.call_id = call_id

        # ── 로깅 (REQ-06)
        self._log_call(response, node_id)

        # ── 누적 비용 상한 확인 (REQ-07)
        self._check_cost_limit(response.cost_usd, node_id)

        return response

    @abstractmethod
    def _do_converse(
        self,
        call_id: str,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition],
        response_schema: dict | None,
    ) -> ConverseResponse:
        ...

    def _log_call(self, r: ConverseResponse, node_id: str) -> None:
        model_short = r.__dict__.get("_model_short", "unknown")
        logger.info(
            "call_id=%s node=%s model=%s tokens_in=%d tokens_out=%d "
            "cache_read=%d cost_usd=%.4f latency_s=%.1f",
            r.call_id, node_id, model_short,
            r.usage.input, r.usage.output, r.usage.cache_read,
            r.cost_usd, r.latency_s,
        )

    def _check_cost_limit(self, cost: float, node_id: str) -> None:
        # 누적 비용 추적은 호출자(agent 루프)가 context에 주입
        # 여기서는 단일 호출이 0.30을 넘는 극단적 케이스만 경고
        from .config import load_model_config
        limit = load_model_config().cost_limit_usd
        if cost > limit:
            logger.warning(
                "node=%s cumulative_cost_usd=%.4f EXCEEDS LIMIT %.2f",
                node_id, cost, limit,
            )
```

---

## 6. `BedrockClient` (`core/llm/client.py`)

```
BedrockClient._do_converse() 실행 흐름
──────────────────────────────────────────────────────────
1. CachingBuilder.build_system_blocks(system, caching_on)
   → list[dict] (cachePoint 포함 여부 결정)

2. response_schema가 있으면:
   tools에 "structured_output" tool 추가
   tool_choice = {"type": "tool", "name": "structured_output"}

3. RetryHandler 데코레이터로 감싼 _call_converse() 호출
   → ThrottlingException / ServiceUnavailableException 시 지수 백오프

4. _call_converse():
   boto3_client.converse(
       modelId=model_id,
       system=system_blocks,
       messages=_to_boto_messages(messages),
       toolConfig=_build_tool_config(tools, tool_choice),
       inferenceConfig={"temperature": ..., "maxTokens": ...},
       guardrailConfig=... (guardrails_id가 있을 때만),
   )

5. _parse_response(boto_resp):
   → ConverseResponse 생성
   → TokenUsage 추출 (inputTokens, outputTokens,
                      cacheReadInputTokens, cacheWriteInputTokens)

6. CostCalculator.calculate(model_id, usage)
   → cost_usd 계산

7. response_schema가 있으면:
   SchemaValidator.validate_and_retry(response, schema, retry_fn)
   → 실패 시 confidence_override="review"
──────────────────────────────────────────────────────────
```

boto3 클라이언트 초기화:

```python
import boto3
from botocore.config import Config

class BedrockClient(AbstractBedrockClient):
    def __init__(self, config: ModelConfig | None = None) -> None:
        self._cfg = config or load_model_config()
        self._boto = boto3.client(
            "bedrock-runtime",
            region_name=self._cfg.region,
            config=Config(retries={"mode": "standard", "max_attempts": 1}),
            # tenacity가 재시도를 담당하므로 boto3 자체 재시도는 1회로 제한
        )
```

---

## 7. `RetryHandler` (`core/llm/retry.py`)

```python
from __future__ import annotations
import logging
from botocore.exceptions import ClientError
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception, before_sleep_log,
)

logger = logging.getLogger(__name__)

def is_throttling_error(exc: BaseException) -> bool:
    if isinstance(exc, ClientError):
        code = exc.response["Error"]["Code"]
        return code in ("ThrottlingException", "ServiceUnavailableException")
    return False

bedrock_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(is_throttling_error),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
```

`before_sleep_log` 가 `WARNING | 재시도 attempt=<n>/3 reason=ThrottlingException` 형태로 자동 출력한다. `tenacity` 버전: `==8.3.0`.

`ValidationException` (JSON 스키마 불일치) 는 `is_throttling_error` 에서 `False` 를 반환하므로 지수 백오프 재시도 대상이 아니다 (REQ-04 단일 재시도와 분리).

---

## 8. `CachingBuilder` (`core/llm/caching.py`)

```python
from __future__ import annotations

class CachingBuilder:
    @staticmethod
    def build_system_blocks(
        system: str,
        caching_on: bool,
    ) -> list[dict]:
        block: dict = {"text": system}
        if caching_on:
            block["cachePoint"] = {"type": "default"}
        return [block]
```

캐싱 활성화 조건: `ModelConfig.generation.prompt_caching` 또는 `verifier.prompt_caching` 이 `True` 이고, 호출 시 전달된 프로파일이 해당 설정을 따른다.

---

## 9. `SchemaValidator` (`core/llm/schema_validator.py`)

```
validate_and_retry 흐름:
─────────────────────────────────────────────────
1. response.content 를 JSON 파싱 시도
   → 파싱 실패 시 즉시 confidence_override="review"

2. jsonschema.validate(instance, schema)
   → 통과: content 그대로 반환

3. 실패: WARNING 로그 "schema validation failed, retry 1/1"
   retry_fn() 호출 (동일 인자로 _do_converse 재실행)

4. 재시도 응답 재검증
   → 통과: 재시도 content 반환
   → 실패: confidence_override="review", content=None 반환
─────────────────────────────────────────────────
```

구현 시 `response_schema` 를 `structured_output` tool 의 `input_schema` 로 변환하여 모델이 tool input 형태로 JSON 을 반환하게 강제한다. 이 방식이 Bedrock Converse API 에서 JSON 출력을 가장 안정적으로 강제하는 패턴이다.

---

## 10. `CostCalculator` (`core/llm/cost.py`)

가격표는 `config/prices.yaml` 에서 로드한다. 코드에 하드코딩하지 않으며, 모델 교체 시
`prices.yaml` 만 수정하면 된다 (steering `aws.md` §2).

```python
from __future__ import annotations
import logging
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)

_PRICES_PATH = Path(__file__).parent.parent.parent / "config" / "prices.yaml"

def _load_price_table(path: Path = _PRICES_PATH) -> dict[str, dict[str, float]]:
    """config/prices.yaml 을 로드하여 가격표 dict 반환. 모듈 임포트 시 1회 실행."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))

# 모듈 로드 시 1회 읽어 캐시 (테스트에서 monkeypatch로 경로 교체 가능)
PRICE_TABLE: dict[str, dict[str, float]] = _load_price_table()

def calculate_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """USD 단위 비용 반환. 미등록 모델은 0.0 반환 + WARNING 1회 로깅."""
    if model_id not in PRICE_TABLE:
        logger.warning("no price entry for model: %s — cost set to 0.0", model_id)
        return 0.0
    p = PRICE_TABLE[model_id]
    return (
        input_tokens       / 1000 * p["input"]
        + output_tokens    / 1000 * p["output"]
        + cache_read_tokens  / 1000 * p["cache_read"]
        + cache_write_tokens / 1000 * p["cache_write"]
    )
```

`config/prices.yaml` 형식 (업데이트 필요 시 이 파일만 수정):

```yaml
# USD per 1,000 tokens
us.anthropic.claude-3-5-sonnet-20241022-v2:0:
  input: 0.003
  output: 0.015
  cache_read: 0.0003
  cache_write: 0.00375

us.anthropic.claude-3-haiku-20240307-v1:0:
  input: 0.00025
  output: 0.00125
  cache_read: 0.000025
  cache_write: 0.0003

amazon.titan-embed-text-v2:0:
  input: 0.00002
  output: 0.0
  cache_read: 0.0
  cache_write: 0.0
```

---

## 11. `MockBedrockClient` (`core/llm/mock.py`)

```python
from __future__ import annotations
from collections.abc import Callable
from .base import AbstractBedrockClient
from .types import ConverseResponse, Message, ToolDefinition

class MockExhaustedError(RuntimeError):
    pass

class MockBedrockClient(AbstractBedrockClient):
    def __init__(
        self,
        responses: list[ConverseResponse] | None = None,
        response_factory: Callable[..., ConverseResponse] | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._factory = response_factory
        self.calls: list[dict] = []   # 호출 이력 — 테스트에서 검증 가능

    def _do_converse(
        self,
        call_id: str,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition],
        response_schema: dict | None,
    ) -> ConverseResponse:
        # 호출 이력 기록
        self.calls.append({
            "call_id": call_id,
            "system": system,
            "messages": messages,
            "tools": tools,
            "response_schema": response_schema,
        })
        # 응답 결정
        if self._factory:
            return self._factory(system=system, messages=messages)
        if self._responses:
            return self._responses.pop(0)
        raise MockExhaustedError("MockBedrockClient: no more responses")
```

`MockBedrockClient` 는 `AbstractBedrockClient` 를 상속하므로 `converse()` 의 공통 pre/post 훅(로깅, 비용 경고)이 동일하게 실행된다. 비용 계산은 `mock_response.cost_usd` 를 주입자가 설정한다.

---

## 12. 팩토리 함수 (`core/llm/__init__.py`)

```python
from __future__ import annotations
import os
from .client import BedrockClient
from .mock import MockBedrockClient
from .base import AbstractBedrockClient

def get_bedrock_client() -> AbstractBedrockClient:
    """
    HAZOP_USE_MOCK=true 이면 MockBedrockClient 반환.
    그 외에는 실제 BedrockClient 반환.
    테스트에서 monkeypatch로 환경변수를 주입하여 격리.
    """
    if os.environ.get("HAZOP_USE_MOCK", "false").lower() == "true":
        return MockBedrockClient()
    return BedrockClient()
```

---

## 13. `models.yaml` 전체 예시 (`config/models.yaml`)

```yaml
# config/models.yaml — 이 파일만 수정하면 전체 모델 교체 적용
region: us-east-1

generation:
  model_id: us.anthropic.claude-3-5-sonnet-20241022-v2:0
  temperature: 0.2
  max_tokens: 4096
  prompt_caching: true

verifier:
  model_id: us.anthropic.claude-3-haiku-20240307-v1:0
  temperature: 0.0
  max_tokens: 1024
  prompt_caching: false

embedding:
  model_id: amazon.titan-embed-text-v2:0

guardrails:
  id: null           # Bedrock Guardrails 생성 후 ID 입력 (REQ-07, NFR-05)

cost_limit_usd: 0.30  # 노드 1건 소프트 상한 (WARNING 로그 기준)
```

---

## 14. 의존성

| 패키지 | 용도 | 핀 버전 |
|---|---|---|
| `boto3` | Bedrock Runtime 호출 | `==1.35.0` |
| `botocore` | `ClientError` 타입 참조 | boto3 의존 해결 |
| `pyyaml` | `models.yaml` 로드 | `==6.0.2` |
| `jsonschema` | `response_schema` 검증 | `==4.23.0` |
| `tenacity` | 지수 백오프 재시도 | `==8.3.0` |
| `pydantic` | (상위 모듈 공유) | `==2.8.2` |

---

## 15. 요구사항 ↔ 설계 추적

| REQ | 구현 컴포넌트 | 핵심 메서드/상수 |
|---|---|---|
| REQ-01 | `ConfigLoader`, `config/models.yaml` | `load_model_config()`, `_validate_raw()` |
| REQ-02 | `AbstractBedrockClient.converse()`, `BedrockClient._do_converse()` | 입력 검증, `ConverseResponse` 생성 |
| REQ-03 | `BedrockClient._build_tool_config()`, `types.ToolUseBlock` | `stop_reason="tool_use"` 분기 |
| REQ-04 | `SchemaValidator.validate_and_retry()` | `structured_output` tool 패턴, `confidence_override` |
| REQ-05 | `RetryHandler`, `bedrock_retry` 데코레이터 | `is_throttling_error()`, `tenacity` |
| REQ-06 | `AbstractBedrockClient._log_call()` | `logger.info(...)` 형식 |
| REQ-07 | `AbstractBedrockClient._check_cost_limit()` | `cost_limit_usd` 비교, `logger.warning()` |
| REQ-08 | `CachingBuilder.build_system_blocks()` | `cachePoint` 블록 조건부 삽입 |
| REQ-09 | `CostCalculator`, `PRICE_TABLE`, `calculate_cost()` | 가격표 기반 USD 계산 |
| REQ-10 | `MockBedrockClient`, `get_bedrock_client()` | `HAZOP_USE_MOCK` 분기, `calls` 이력 |
| REQ-11 | `tests/test_bedrock_client.py::test_smoke_live_converse` | `@pytest.mark.live` |
