# Requirements — bedrock-client

spec: `bedrock-client`  
대응 FR: PRD §5 FR-02  
버전: 1.0 · 작성 2026-09-04  
상위 문서: `PRD.md` §5 FR-02, steering `aws.md`, steering `engineering.md`  
G0 킬체크 대상: 2026-09-07

---

## 1. 목적

Amazon Bedrock Converse API의 단일 진입 래퍼를 제공한다. 모든 Bedrock 호출은 이 래퍼를 경유하며, 재시도·토큰/지연/비용 로깅·JSON 스키마 강제 출력을 일관되게 처리한다. 오프라인 테스트를 위한 모의 클라이언트와 실호출 스모크 테스트를 함께 제공한다.

---

## 2. 요구사항 (EARS 형식)

### REQ-01 · `config/models.yaml` 스키마 및 로드

**WHEN** `core/llm/` 내 임의 모듈이 초기화되면,  
**THE SYSTEM SHALL** `config/models.yaml` 을 단일 소스로 삼아 리전·모델 ID·생성 파라미터를 로드한다.

`config/models.yaml` 필수 필드:

```yaml
region: <str>                    # AWS 리전 (크로스리전 추론 프로파일 허용)
generation:
  model_id: <str>                # 생성용 모델 ID
  temperature: <float 0.0–1.0>
  max_tokens: <int>
  prompt_caching: <bool>
verifier:
  model_id: <str>                # 검증용 (하위) 모델 ID
  temperature: <float>
  max_tokens: <int>
  prompt_caching: <bool>
embedding:
  model_id: <str>                # 임베딩 모델 ID
guardrails:
  id: <str | null>               # Bedrock Guardrails ID (null 허용)
```

**수용 기준 (AC-01)**
- `config/models.yaml` 에 필수 필드가 없으면 `ConfigValidationError` 를 raise하고 누락 필드명을 메시지에 포함한다.
- 코드 어디서도 모델 ID·리전을 문자열 리터럴로 하드코딩하면 `ruff` 규칙이 아닌 `grep -r "us\.anthropic\|us-east-1" core/` 검사로 확인하고 PR에서 차단한다.
- `load_model_config()` 는 `Path(__file__)` 기준 상대 경로로 파일을 찾으므로 작업 디렉토리에 무관하게 동작한다 (`pytest tests/test_bedrock_client.py::test_config_load_path_independent` 통과).
- `temperature` 가 0.0~1.0 범위를 벗어나면 `ConfigValidationError` 를 raise한다.

---

### REQ-02 · `BedrockClient.converse` — 기본 호출

**WHEN** 호출자가 `BedrockClient.converse(system, messages)` 를 호출하면,  
**THE SYSTEM SHALL** Bedrock Converse API 를 통해 응답을 반환한다.

인터페이스 (steering `aws.md` §1 그대로):

```python
class BedrockClient:
    def converse(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        response_schema: dict | None = None,
    ) -> ConverseResponse:
        ...
```

타입 정의:
- `Message`: `{"role": "user"|"assistant", "content": str | list[ContentBlock]}`
- `ToolDefinition`: `{"name": str, "description": str, "input_schema": dict}`  
- `ConverseResponse`: `{"content": str, "tool_use_blocks": list[ToolUseBlock], "stop_reason": str, "usage": TokenUsage, "cost_usd": float, "latency_s": float, "call_id": str}`
- `TokenUsage`: `{"input": int, "output": int, "cache_read": int, "cache_write": int}`

**수용 기준 (AC-02)**
- `system` 이 빈 문자열이면 `ValueError` 를 raise한다.
- `messages` 가 빈 리스트이면 `ValueError` 를 raise한다.
- 정상 호출 시 `ConverseResponse.stop_reason` 이 `"end_turn"` 또는 `"tool_use"` 중 하나다.
- `ConverseResponse.cost_usd` 는 항상 0 이상의 float 이다.
- `ConverseResponse.call_id` 는 UUID4 문자열이다 (`pytest tests/test_bedrock_client.py::test_converse_response_shape` — MockBedrockClient 사용).

---

### REQ-03 · tool use 지원

**WHEN** `tools` 인자가 제공되고 모델이 `stop_reason="tool_use"` 로 응답하면,  
**THE SYSTEM SHALL** `ConverseResponse.tool_use_blocks` 에 모든 tool 호출 블록을 담아 반환하고, tool 실행 및 후속 호출은 **호출자**(agent 루프)가 수행한다.

**수용 기준 (AC-03)**
- `tools` 가 빈 리스트 `[]` 이면 API 호출 시 tool 정의를 전달하지 않는다 (`pytest tests/test_bedrock_client.py::test_no_tools_when_empty` — MockBedrockClient 사용).
- `stop_reason="tool_use"` 응답 시 `tool_use_blocks` 가 비어 있지 않다 (mock fixture 사용).
- `ToolUseBlock` 에는 `{"id": str, "name": str, "input": dict}` 필드가 있다.

---

### REQ-04 · JSON 스키마 강제 출력 (`response_schema`)

**WHEN** `response_schema` 가 제공되면,  
**THE SYSTEM SHALL** 모델 출력을 해당 JSON Schema(draft-07)로 검증하고, 검증 실패 시 1회 재시도한다. 재시도 후에도 실패하면 `confidence` 를 `"review"` 로 격하한 채 결과를 반환한다.

강제 구현 방식: `tool_choice={"type": "tool", "name": "structured_output"}` 패턴으로 모델이 JSON 오브젝트를 tool input으로 반환하도록 강제한다.

**수용 기준 (AC-04)**
- `response_schema` 가 주어지면 응답 JSON 이 스키마를 통과해야 `ConverseResponse.content` 에 정상 반환된다 (`pytest tests/test_bedrock_client.py::test_schema_enforcement_pass` — MockBedrockClient 사용).
- 스키마 검증 실패 → 재시도 → 재실패 시 `ConverseResponse.content` 가 `None` 이고 `confidence_override="review"` 필드가 설정된다 (`pytest tests/test_bedrock_client.py::test_schema_enforcement_fail_review` — MockBedrockClient 사용).
- 재시도 시 `WARNING` 레벨 로그가 발생한다: `schema validation failed, retry 1/1`.

---

### REQ-05 · 재시도 — Throttling / 서비스 불가

**WHEN** Bedrock API 가 `ThrottlingException` 또는 `ServiceUnavailableException` 을 반환하면,  
**THE SYSTEM SHALL** 지수 백오프(초기 1초, 배수 2, 최대 10초)로 최대 3회 재시도한다.

**수용 기준 (AC-05)**
- `ThrottlingException` 모의 주입 시 3회 재시도 후 성공하면 정상 `ConverseResponse` 를 반환한다 (`pytest tests/test_bedrock_client.py::test_retry_throttling_success`).
- 3회 모두 실패하면 `BedrockCallError` 를 raise한다 (`pytest tests/test_bedrock_client.py::test_retry_throttling_exhausted`).
- 각 재시도 전 `WARNING` 로그: `재시도 attempt=<n>/3 reason=ThrottlingException`.
- `ValidationException` (스키마 불일치)에는 지수 백오프 재시도를 적용하지 않는다(REQ-04의 단일 재시도만 적용).

---

### REQ-06 · 토큰·지연·비용 로깅

**WHEN** Bedrock API 호출이 완료되면 (성공 또는 최종 실패 전),  
**THE SYSTEM SHALL** 매 호출마다 다음 정보를 `INFO` 레벨로 로깅한다.

로그 형식 (steering `aws.md` §5):
```
INFO | core.llm.client | call_id=<uuid> node=<node_id> model=<model_short_name> \
  tokens_in=<int> tokens_out=<int> cache_read=<int> cost_usd=<float:.4f> latency_s=<float:.1f>
```

**수용 기준 (AC-06)**
- `node_id` 컨텍스트는 `BedrockClient` 인스턴스 생성 시 또는 `converse()` 호출 시 `context={"node": "N1"}` 로 전달하여 로그에 포함된다.
- `node_id` 미제공 시 `node=unknown` 으로 로깅된다.
- `MockBedrockClient` 사용 시에도 동일한 형식의 로그가 발생한다 (`pytest tests/test_bedrock_client.py::test_logging_format` — `caplog` 픽스처 사용).
- 로그에 `cost_usd` 값이 포함되어 있으며 소수점 4자리 형식이다.

---

### REQ-07 · 노드 누적 비용 상한 경고

**WHEN** 단일 노드 처리 중 누적 비용이 USD 0.30 을 초과하면,  
**THE SYSTEM SHALL** `WARNING` 레벨로 아래 로그를 출력한다. 호출을 중단하지 않는다.

```
WARNING | core.llm.client | node=<node_id> cumulative_cost_usd=<float:.4f> EXCEEDS LIMIT 0.30
```

**수용 기준 (AC-07)**
- MockBedrockClient 에 `cost_usd=0.31` 응답을 주입하면 `WARNING` 로그가 발생한다 (`pytest tests/test_bedrock_client.py::test_cost_limit_warning`).
- 경고 후에도 호출 흐름이 계속된다 (예외 raise 없음).
- 비용 상한값(0.30)은 `config/models.yaml` 의 `cost_limit_usd` 필드로 오버라이드 가능하다.

---

### REQ-08 · 프롬프트 캐싱

**WHEN** `models.yaml` 의 해당 모델 설정에서 `prompt_caching: true` 이면,  
**THE SYSTEM SHALL** 시스템 프롬프트 블록에 `cachePoint` 마커를 추가하여 Bedrock 프롬프트 캐싱을 활성화한다.

**수용 기준 (AC-08)**
- `prompt_caching: true` 설정 시 `boto3` 에 전달되는 `system` 파라미터에 `"cachePoint": {"type": "default"}` 블록이 포함된다 (`pytest tests/test_bedrock_client.py::test_caching_marker_present`).
- `prompt_caching: false` 설정 시 `cachePoint` 블록이 없다 (`pytest tests/test_bedrock_client.py::test_caching_marker_absent`).
- `cache_read` 토큰이 0보다 크면 `ConverseResponse.usage.cache_read` 에 반영되어 비용 계산에 사용된다.

---

### REQ-09 · 비용 계산 (`core/llm/cost.py`)

**WHEN** API 응답에서 `usage` 정보를 받으면,  
**THE SYSTEM SHALL** `core/llm/cost.py` 의 `calculate_cost()` 를 호출하여 USD 비용을 산출한다.

```python
def calculate_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """USD 단위 비용 반환. 가격표는 cost.py 내 PRICE_TABLE 상수로 관리."""
    ...
```

가격표 초기값 (Claude 3.5 Sonnet on Bedrock, 업데이트 필요 시 `cost.py` 만 수정):

| 항목 | USD / 1K tokens |
|---|---|
| 입력 (input) | 0.003 |
| 출력 (output) | 0.015 |
| 캐시 읽기 (cache_read) | 0.0003 |
| 캐시 쓰기 (cache_write) | 0.00375 |

**수용 기준 (AC-09)**
- `calculate_cost("us.anthropic.claude-3-5-sonnet-20241022-v2:0", 1000, 500)` == `0.003 * 1 + 0.015 * 0.5` = `0.0105` (`pytest tests/test_bedrock_client.py::test_cost_calculation`).
- 가격표에 없는 모델 ID 입력 시 `UnknownModelError` 를 raise한다.
- `cache_read_tokens > 0` 이면 비용 절감이 반영된다 (`pytest tests/test_bedrock_client.py::test_cost_cache_discount`).

---

### REQ-10 · `MockBedrockClient` — 오프라인 테스트

**WHEN** 환경변수 `HAZOP_USE_MOCK=true` 이거나 `MockBedrockClient` 를 직접 인스턴스화하면,  
**THE SYSTEM SHALL** `BedrockClient` 와 동일한 인터페이스로 응답을 반환하되, AWS 자격증명·네트워크 없이 동작한다.

`MockBedrockClient` 동작:
- 생성 시 `responses: list[ConverseResponse]` 또는 `response_factory: Callable` 를 주입하여 시나리오별 응답을 설정한다.
- 호출 이력을 `mock.calls: list[dict]` 에 기록하여 테스트에서 검증 가능하다.
- `responses` 가 소진되면 `MockExhaustedError` 를 raise한다.
- 비용 로깅, 캐싱 마커 확인, 재시도 로직은 `BedrockClient` 와 동일하게 동작한다(공유 기반 클래스로 구현).

**수용 기준 (AC-10)**
- `MockBedrockClient` 가 `BedrockClient` 와 동일한 추상 기반 클래스(`AbstractBedrockClient`)를 구현한다 (`pytest tests/test_bedrock_client.py::test_mock_implements_interface`).
- `HAZOP_USE_MOCK=true` 환경변수 설정 시 `get_bedrock_client()` 팩토리 함수가 `MockBedrockClient` 인스턴스를 반환한다 (`pytest tests/test_bedrock_client.py::test_factory_mock_env`).
- `mock.calls[0]["system"]` 으로 전달된 시스템 프롬프트를 검증할 수 있다.
- `pytest -m "not live"` 실행 시 모든 `core/llm/` 테스트가 AWS 자격증명 없이 통과한다.

---

### REQ-11 · 실호출 스모크 테스트 (`@pytest.mark.live`)

**WHEN** `pytest -m live` 를 실행하면,  
**THE SYSTEM SHALL** 실제 Bedrock Converse API 를 1회 호출하여 응답이 반환됨을 검증한다.

**수용 기준 (AC-11)**
- `@pytest.mark.live` 테스트가 `tests/test_bedrock_client.py::test_smoke_live_converse` 에 존재한다.
- 테스트는 `config/models.yaml` 의 `generation.model_id` 로 "안녕하세요" 단문을 전송하고 `stop_reason="end_turn"` 응답을 받는다.
- 응답 `cost_usd > 0` 이고 `latency_s > 0` 이다.
- AWS 자격증명 환경변수(`AWS_ACCESS_KEY_ID` 등) 또는 IAM 역할이 없으면 `pytest.skip("AWS credentials not set")` 으로 건너뛴다.
- `pytest -m "not live"` 실행 시 이 테스트는 실행되지 않는다.

---

## 3. 비기능 요구사항 (이 spec 범위)

| ID | 내용 |
|---|---|
| NFR-B01 | `ruff check core/llm/` 경고 0개 |
| NFR-B02 | `mypy --strict core/llm/` 통과 |
| NFR-B03 | `pytest -m "not live" --cov=core/llm` 커버리지 ≥ 70% |
| NFR-B04 | `boto3` 직접 호출은 `core/llm/client.py` 의 `_call_converse()` 단 한 곳에서만 발생 |
| NFR-B05 | `HAZOP_USE_MOCK=true` 환경에서 `make test` 가 네트워크 없이 완전 통과 |
| NFR-B06 | 노드 1건 생성+검증 합산 비용 ≤ USD 0.30 (소프트 상한, WARNING 로그로 감시) |

---

## 4. 용어 정의

| 용어 | 정의 |
|---|---|
| Converse API | Amazon Bedrock의 통합 텍스트 생성 API. 단일 인터페이스로 다중 모델을 지원 |
| 프롬프트 캐싱 | 반복 호출 시 입력 토큰 비용을 줄이는 Bedrock 기능. `cachePoint` 마커로 경계 지정 |
| 크로스리전 추론 프로파일 | `us.` 접두어를 가진 모델 ID. 다중 리전에서 추론하여 가용성·처리량 향상 |
| `stop_reason` | Converse API 응답이 종료된 이유. `end_turn`, `tool_use`, `max_tokens` 등 |
| 모의 클라이언트 | 실제 API 호출 없이 동일 인터페이스를 구현하는 테스트용 객체 |
| G0 킬체크 | PRD §8 첫 번째 마일스톤(9/7). Bedrock 실호출 성공이 통과 조건 |
