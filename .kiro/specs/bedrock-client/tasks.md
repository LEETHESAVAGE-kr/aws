# Tasks — bedrock-client

spec: `bedrock-client`  
버전: 1.0 · 작성 2026-09-04  
상위 문서: `requirements.md`, `design.md`  
구현 담당: Claude Code (`CLAUDE.md` 및 steering 준수)  
커밋 접두어: `spec:bedrock-client T-xx`  
G0 킬체크 마감: 2026-09-07

완료 조건: 각 태스크의 "검증" 항목 전부 통과 + `ruff check core/llm/` 경고 0 + `mypy --strict core/llm/` 통과.

---

## T-01 · 프로젝트 스캐폴딩 및 의존성 등록

**목적**: 이후 태스크가 의존하는 파일 트리와 패키지 설정을 만든다.

작업:
1. 디렉토리 생성: `core/llm/`, `core/__init__.py`, `core/llm/__init__.py` (빈 파일).
2. `core/llm/types.py` 생성 — `design.md §3` 타입 정의 전체 구현.
   - `ContentBlock`, `Message`, `ToolDefinition`, `TokenUsage`, `ToolUseBlock`, `ConverseResponse`, `ModelProfile`, `ModelConfig` dataclass.
3. `config/models.yaml` 생성 — `design.md §13` 전체 예시 그대로 작성.
4. `pyproject.toml` 에 의존성 추가 (`design.md §14`):
   - `boto3==1.35.0`, `pyyaml==6.0.2`, `jsonschema==4.23.0`, `tenacity==8.3.0`, `pydantic==2.8.2`.
5. `.env.example` 에 `HAZOP_USE_MOCK=false` 추가 (없으면 생성).
6. `tests/fixtures/llm/` 디렉토리 생성 + 픽스처 JSON 파일 3종 생성:
   - `mock_response_end_turn.json` — `stop_reason: "end_turn"`, content 있음.
   - `mock_response_tool_use.json` — `stop_reason: "tool_use"`, `tool_use_blocks` 1개.
   - `mock_response_schema_fail.json` — 스키마 검증 실패 시뮬레이션용.

검증:
- `python -c "from core.llm.types import ConverseResponse, ModelConfig"` 오류 없음.
- `python -m json.tool config/models.yaml` 대신 `python -c "import yaml; yaml.safe_load(open('config/models.yaml'))"` 오류 없음.

---

## T-02 · `ConfigLoader` 구현 (`core/llm/config.py`)

**목적**: `config/models.yaml` 로드, 유효성 검사, `ModelConfig` 반환. (REQ-01)

작업:
1. `core/llm/config.py` 생성.
2. `ConfigValidationError(ValueError)` 예외 클래스 정의.
3. `load_model_config(path: Path = _CONFIG_PATH) -> ModelConfig` 구현:
   - `_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "models.yaml"`.
   - `_validate_raw(raw)`: 필수 최상위 키 `{"region","generation","verifier","embedding"}` 확인, `temperature` 0.0~1.0 범위 검사.
   - `functools.lru_cache` 적용 (경로별 1회 로드).
4. `pyproject.toml` 의 `[tool.pytest.ini_options]` 에 `markers` 등록:
   ```toml
   markers = ["live: requires real AWS credentials and network access"]
   ```

검증:
- `pytest tests/test_bedrock_client.py::test_config_load_path_independent` — 작업 디렉토리와 무관하게 로드.
- `pytest tests/test_bedrock_client.py::test_config_missing_field` — 누락 필드 시 `ConfigValidationError`, 메시지에 필드명 포함.
- `pytest tests/test_bedrock_client.py::test_config_temperature_out_of_range` — `temperature=1.5` 시 `ConfigValidationError`.
- `pytest tests/test_bedrock_client.py::test_config_lru_cache` — 동일 경로 두 번 호출 시 같은 객체 반환.

---

## T-03 · `CostCalculator` 구현 (`core/llm/cost.py`)

**목적**: 모델 ID와 토큰 수로 USD 비용 산출. (REQ-09)

작업:
1. `core/llm/cost.py` 생성.
2. `PRICE_TABLE` 상수 정의 (`design.md §10`) — Claude 3.5 Sonnet, Haiku, Titan 임베딩.
3. `UnknownModelError(KeyError)` 예외 클래스 정의.
4. `calculate_cost(model_id, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens) -> float` 구현.

검증:
- `pytest tests/test_bedrock_client.py::test_cost_calculation` — `calculate_cost("us.anthropic.claude-3-5-sonnet-20241022-v2:0", 1000, 500)` == `0.0105`.
- `pytest tests/test_bedrock_client.py::test_cost_cache_discount` — `cache_read_tokens=500` 시 비용이 일반 입력 토큰보다 저렴.
- `pytest tests/test_bedrock_client.py::test_cost_unknown_model` — 미등록 모델 ID 시 `UnknownModelError`.
- `pytest tests/test_bedrock_client.py::test_cost_zero_tokens` — 모든 토큰 0 → 비용 0.0.

---

## T-04 · `CachingBuilder` 구현 (`core/llm/caching.py`)

**목적**: 프롬프트 캐싱 `cachePoint` 블록 조건부 삽입. (REQ-08)

작업:
1. `core/llm/caching.py` 생성.
2. `CachingBuilder.build_system_blocks(system: str, caching_on: bool) -> list[dict]` 구현 (`design.md §8`).
   - `caching_on=True`: `[{"text": system, "cachePoint": {"type": "default"}}]`.
   - `caching_on=False`: `[{"text": system}]`.

검증:
- `pytest tests/test_bedrock_client.py::test_caching_marker_present` — `caching_on=True` 시 결과에 `"cachePoint"` 키 포함.
- `pytest tests/test_bedrock_client.py::test_caching_marker_absent` — `caching_on=False` 시 `"cachePoint"` 키 없음.
- `pytest tests/test_bedrock_client.py::test_caching_system_text_preserved` — `cachePoint` 유무와 무관하게 `"text"` 값이 입력과 동일.

---

## T-05 · `RetryHandler` 구현 (`core/llm/retry.py`)

**목적**: ThrottlingException·ServiceUnavailableException 지수 백오프 재시도. (REQ-05)

작업:
1. `core/llm/retry.py` 생성.
2. `is_throttling_error(exc: BaseException) -> bool` 구현 (`design.md §7`).
3. `bedrock_retry` tenacity 데코레이터 정의:
   - `stop_after_attempt(3)`, `wait_exponential(multiplier=1, min=1, max=10)`.
   - `retry_if_exception(is_throttling_error)`.
   - `before_sleep=before_sleep_log(logger, logging.WARNING)`.
   - `reraise=True`.
4. `BedrockCallError(RuntimeError)` 예외 클래스 정의 — 3회 모두 실패 시 raise.

검증:
- `pytest tests/test_bedrock_client.py::test_retry_throttling_success` — 2회 실패 후 3회 성공 시나리오에서 정상 응답 반환.
- `pytest tests/test_bedrock_client.py::test_retry_throttling_exhausted` — 3회 모두 `ThrottlingException` 시 `BedrockCallError`.
- `pytest tests/test_bedrock_client.py::test_retry_warning_logged` — 재시도 시 `WARNING` 로그 발생 (`caplog` 사용).
- `pytest tests/test_bedrock_client.py::test_no_retry_for_validation_exception` — `ValidationException` 은 재시도 없이 즉시 전파.

---

## T-06 · `SchemaValidator` 구현 (`core/llm/schema_validator.py`)

**목적**: `response_schema` 기반 JSON 검증 및 단일 재시도. (REQ-04)

작업:
1. `core/llm/schema_validator.py` 생성.
2. `SchemaValidator.validate_and_retry(response, schema, retry_fn) -> ConverseResponse` 구현 (`design.md §9`):
   - `response.content` JSON 파싱 → `jsonschema.validate` → 통과 시 원본 반환.
   - 실패 → WARNING 로그 `"schema validation failed, retry 1/1"` → `retry_fn()` 호출.
   - 재시도 재실패 → `confidence_override="review"`, `content=None`.
3. `structured_output` tool 정의 헬퍼: `build_structured_output_tool(schema: dict) -> ToolDefinition`.

검증:
- `pytest tests/test_bedrock_client.py::test_schema_enforcement_pass` — 유효한 JSON 응답 시 `content` 정상 반환.
- `pytest tests/test_bedrock_client.py::test_schema_enforcement_fail_review` — 두 번 연속 스키마 실패 시 `confidence_override="review"`, `content=None`.
- `pytest tests/test_bedrock_client.py::test_schema_retry_warning` — 첫 번째 실패 시 `WARNING` 로그 포함 `"schema validation failed, retry 1/1"`.
- `pytest tests/test_bedrock_client.py::test_schema_retry_succeeds` — 재시도 성공 시 재시도 응답의 `content` 반환.

---

## T-07 · `AbstractBedrockClient` 구현 (`core/llm/base.py`)

**목적**: 공통 pre/post 훅 (입력 검증, 로깅, 비용 경고). (REQ-02, REQ-06, REQ-07)

작업:
1. `core/llm/base.py` 생성.
2. `AbstractBedrockClient(ABC)` 구현 (`design.md §5`):
   - `converse()`: 입력 검증 → `_do_converse()` 호출 → `_log_call()` → `_check_cost_limit()`.
   - `_log_call(response, node_id)`: `INFO` 레벨, `design.md §5` 형식.
   - `_check_cost_limit(cost, node_id)`: `cost_limit_usd` 초과 시 `WARNING`.
   - `@abstractmethod _do_converse(...)`.
3. `context: dict[str, str] | None` 파라미터 — `converse()` 에 추가, `node_id` 추출.

검증:
- `pytest tests/test_bedrock_client.py::test_converse_empty_system_raises` — `system=""` 시 `ValueError`.
- `pytest tests/test_bedrock_client.py::test_converse_empty_messages_raises` — `messages=[]` 시 `ValueError`.
- `pytest tests/test_bedrock_client.py::test_logging_format` — 로그 메시지에 `call_id`, `node`, `cost_usd`, `latency_s` 포함 (`caplog`).
- `pytest tests/test_bedrock_client.py::test_cost_limit_warning` — `cost_usd=0.31` 주입 시 `WARNING` 로그 포함 `"EXCEEDS LIMIT"`.
- `pytest tests/test_bedrock_client.py::test_node_unknown_default` — `context` 미제공 시 로그에 `node=unknown`.

---

## T-08 · `MockBedrockClient` 구현 (`core/llm/mock.py`)

**목적**: 오프라인 테스트용 모의 클라이언트. (REQ-10)

작업:
1. `core/llm/mock.py` 생성.
2. `MockExhaustedError(RuntimeError)` 예외 클래스 정의.
3. `MockBedrockClient(AbstractBedrockClient)` 구현 (`design.md §11`):
   - `responses: list[ConverseResponse] | None`, `response_factory: Callable | None` 생성자 인자.
   - `calls: list[dict]` — 호출 이력 기록.
   - `_do_converse()`: `responses.pop(0)` 또는 `response_factory()` 또는 `MockExhaustedError`.
4. `conftest.py` 에 공용 픽스처 추가:
   - `mock_end_turn_response()` — 픽스처 JSON 로드.
   - `mock_tool_use_response()`.
   - `mock_client_factory()` — `MockBedrockClient` 인스턴스 반환.

검증:
- `pytest tests/test_bedrock_client.py::test_mock_implements_interface` — `isinstance(MockBedrockClient(), AbstractBedrockClient)` 참.
- `pytest tests/test_bedrock_client.py::test_mock_records_calls` — `mock.calls[0]["system"]` 이 전달한 값과 일치.
- `pytest tests/test_bedrock_client.py::test_mock_exhausted` — 응답 소진 후 `MockExhaustedError`.
- `pytest tests/test_bedrock_client.py::test_mock_factory_callable` — `response_factory` 사용 시 매 호출마다 팩토리 반환값 사용.

---

## T-09 · 팩토리 및 `__init__.py` 공개 인터페이스 (`core/llm/__init__.py`)

**목적**: `get_bedrock_client()` 팩토리 + 공개 re-export. (REQ-10)

작업:
1. `core/llm/__init__.py` 에 `get_bedrock_client()` 구현 (`design.md §12`).
2. 공개 인터페이스 re-export:
   ```python
   from .base import AbstractBedrockClient
   from .client import BedrockClient
   from .mock import MockBedrockClient, MockExhaustedError
   from .config import load_model_config, ConfigValidationError
   from .cost import calculate_cost, UnknownModelError
   from .types import (
       Message, ToolDefinition, ConverseResponse,
       TokenUsage, ToolUseBlock, ModelConfig,
   )
   ```
3. `core/__init__.py` 빈 파일 확인 (순환 임포트 방지).

검증:
- `pytest tests/test_bedrock_client.py::test_factory_mock_env` — `HAZOP_USE_MOCK=true` 환경변수 시 `get_bedrock_client()` 가 `MockBedrockClient` 반환 (`monkeypatch` 사용).
- `pytest tests/test_bedrock_client.py::test_factory_real_env` — `HAZOP_USE_MOCK=false` 시 `BedrockClient` 반환.
- `python -c "from core.llm import get_bedrock_client, ConverseResponse"` 오류 없음.

---

## T-10 · `BedrockClient` 구현 (`core/llm/client.py`)

**목적**: 실제 boto3 Converse API 호출 구현. (REQ-02, REQ-03, REQ-04, REQ-05, REQ-08)

작업:
1. `core/llm/client.py` 생성.
2. `BedrockClient(AbstractBedrockClient)` 구현 (`design.md §6`):
   - `__init__`: `load_model_config()` → `boto3.client("bedrock-runtime", region_name=..., config=Config(retries={"mode":"standard","max_attempts":1}))`.
   - `_do_converse()` 흐름:
     1. `CachingBuilder.build_system_blocks(system, caching_on)`.
     2. `response_schema` 있으면 `build_structured_output_tool(schema)` → tools 에 추가, `tool_choice` 설정.
     3. `@bedrock_retry` 로 감싼 `_call_converse()` 호출.
     4. `_parse_response(boto_resp)` → `ConverseResponse`.
     5. `calculate_cost(model_id, ...)` → `cost_usd`.
     6. `response_schema` 있으면 `SchemaValidator.validate_and_retry(...)`.
   - `_call_converse(**kwargs) -> dict`: `self._boto.converse(...)` 단일 boto3 호출.
   - `_to_boto_messages(messages)`: `list[Message]` → boto3 형식.
   - `_build_tool_config(tools, tool_choice)`: tool 정의 → boto3 `toolConfig`.
   - `_parse_response(boto_resp) -> ConverseResponse`: boto3 응답 파싱, `tool_use_blocks` 추출.
3. Guardrails: `guardrails_id` 가 None이 아닌 경우에만 `guardrailConfig` 추가.

검증 (MockBedrockClient 로 불가한 boto3 경계 단위 테스트는 `unittest.mock.patch` 사용):
- `pytest tests/test_bedrock_client.py::test_converse_response_shape` — `ConverseResponse` 모든 필드 존재.
- `pytest tests/test_bedrock_client.py::test_no_tools_when_empty` — `tools=[]` 시 boto3 에 `toolConfig` 전달 안 함 (`patch` 검증).
- `pytest tests/test_bedrock_client.py::test_tool_use_blocks_populated` — `stop_reason="tool_use"` 모의 응답 시 `tool_use_blocks` 비어 있지 않음.
- `pytest tests/test_bedrock_client.py::test_guardrail_not_sent_when_none` — `guardrails_id=None` 시 boto3 호출에 `guardrailConfig` 없음 (`patch` 검증).
- `pytest tests/test_bedrock_client.py::test_caching_marker_in_boto_call` — `prompt_caching=True` 설정 시 boto3 `system` 인자에 `cachePoint` 포함 (`patch` 검증).

---

## T-11 · 오프라인 통합 테스트 — MockBedrockClient 전체 흐름

**목적**: `HAZOP_USE_MOCK=true` 환경에서 전체 호출 흐름 검증. (REQ-10, NFR-B05)

작업:
1. `tests/test_bedrock_client.py` 에 통합 시나리오 테스트 추가:
   - 정상 `end_turn` 흐름 (로깅, 비용, latency 포함).
   - `tool_use` 흐름 — `tool_use_blocks` 추출 및 후속 메시지 조립.
   - `response_schema` 통과 흐름.
   - `response_schema` 실패→재시도→성공 흐름.
   - `response_schema` 실패→재시도→실패 → `confidence_override="review"`.
   - 비용 상한 초과 경고 흐름.
2. `conftest.py` 에 `HAZOP_USE_MOCK=true` 자동 설정 픽스처 추가 (`autouse=False`, 필요한 테스트에서 명시 사용).

검증:
- `HAZOP_USE_MOCK=true pytest tests/test_bedrock_client.py -m "not live"` — AWS 자격증명 없이 전부 통과.
- `pytest tests/test_bedrock_client.py -m "not live" --cov=core/llm --cov-report=term-missing` — 커버리지 ≥ 70%.

---

## T-12 · 실호출 스모크 테스트 (`@pytest.mark.live`)

**목적**: G0 킬체크 — Bedrock 실호출 1회 성공 확인. (REQ-11)

작업:
1. `tests/test_bedrock_client.py` 에 `test_smoke_live_converse` 추가:
   ```python
   @pytest.mark.live
   def test_smoke_live_converse():
       """실제 Bedrock Converse API 1회 호출 — G0 킬체크."""
       import os
       if not os.environ.get("AWS_ACCESS_KEY_ID") and not _has_iam_role():
           pytest.skip("AWS credentials not set")
       client = BedrockClient()
       resp = client.converse(
           system="당신은 안전 전문가입니다.",
           messages=[Message(role="user", content="안녕하세요")],
       )
       assert resp.stop_reason == "end_turn"
       assert resp.cost_usd > 0
       assert resp.latency_s > 0
   ```
2. `_has_iam_role()` 헬퍼: `boto3.client("sts").get_caller_identity()` 성공 여부로 IAM 역할 확인.
3. G0 킬체크 체크리스트를 `tests/README.md` 에 기록:
   - `pytest -m live` 통과 스크린샷 또는 로그를 `results/g0/smoke_<date>.log` 로 저장 권장.

검증:
- `pytest -m "not live" tests/test_bedrock_client.py` — `test_smoke_live_converse` 건너뜀(skip).
- AWS 자격증명 설정 후 `pytest -m live tests/test_bedrock_client.py` — 통과 및 `cost_usd > 0` 확인.
- 통과 로그 `results/g0/smoke_<date>.log` 저장.

---

## T-13 · `ruff` · `mypy` · 커버리지 통과

**목적**: NFR-B01, NFR-B02, NFR-B03 달성.

작업:
1. `ruff check core/llm/ tests/test_bedrock_client.py` 경고 0개가 될 때까지 수정.
2. `mypy --strict core/llm/` 통과.
   - `boto3-stubs[bedrock-runtime]` 를 `[project.optional-dependencies]` `dev` 그룹에 추가 (mypy 타입 힌트용).
3. `pytest tests/test_bedrock_client.py -m "not live" --cov=core/llm --cov-report=term-missing` — 커버리지 ≥ 70%.
4. `pyproject.toml` 에 `[tool.mypy]` 설정 추가 (steering `engineering.md` 기준):
   ```toml
   [tool.mypy]
   strict = true
   ignore_missing_imports = true
   ```

검증:
- `ruff check core/llm/` → 출력 없음.
- `mypy --strict core/llm/` → `Success: no issues found`.
- 커버리지 ≥ 70%.

---

## T-14 · `Makefile` 타겟 및 G0 게이트 확인

**목적**: PRD §8 G0 킬체크 조건 달성 및 `make` 워크플로 통합.

작업:
1. `Makefile` 에 타겟 추가:
   ```makefile
   test-llm:
   	HAZOP_USE_MOCK=true pytest tests/test_bedrock_client.py -m "not live" -v

   smoke:
   	pytest tests/test_bedrock_client.py -m live -v 2>&1 | tee results/g0/smoke_$(shell date +%Y%m%d_%H%M%S).log

   check-llm: test-llm
   	ruff check core/llm/
   	mypy --strict core/llm/

   test:              # 기존 타겟에 test-llm 추가
   	HAZOP_USE_MOCK=true pytest -m "not live" -v
   ```
2. `results/g0/` 디렉토리 생성 + `.gitkeep`.
3. G0 체크리스트를 `PRD.md` §8 G0 항목 옆에 ✓ 로 표시 (이 태스크 완료 후 수동 갱신).

검증:
- `make check-llm` → 모두 통과.
- AWS 자격증명 설정 후 `make smoke` → `results/g0/smoke_*.log` 생성, 파일 내 `cost_usd > 0` 로그 확인.
- G0 체크리스트: `Bedrock 실호출 성공 ✓`, `spec bedrock-client 완성 ✓` 항목에 체크 가능.

---

## 태스크 의존 관계

```
T-01 (스캐폴딩 · types)
  ├─ T-02 (ConfigLoader)
  ├─ T-03 (CostCalculator)
  ├─ T-04 (CachingBuilder)
  ├─ T-05 (RetryHandler)
  └─ T-06 (SchemaValidator)
       └─ T-07 (AbstractBedrockClient)  ← T-02~T-06 모두 필요
            ├─ T-08 (MockBedrockClient)
            │    └─ T-09 (팩토리 · __init__)
            │         └─ T-11 (오프라인 통합 테스트)
            └─ T-10 (BedrockClient)     ← T-07 + T-02~T-06
                 └─ T-12 (live 스모크)
                      └─ T-13 (lint · type · coverage)
                           └─ T-14 (Makefile · G0 확인)
```

병렬 가능: T-02, T-03, T-04, T-05, T-06 은 T-01 완료 후 동시 진행 가능.  
T-08 과 T-10 은 T-07 완료 후 동시 진행 가능.

---

## 요구사항 ↔ 태스크 ↔ 테스트 추적 매트릭스

| REQ | 태스크 | 테스트 함수 |
|---|---|---|
| REQ-01 | T-02 | `test_config_load_path_independent`, `test_config_missing_field`, `test_config_temperature_out_of_range`, `test_config_lru_cache` |
| REQ-02 | T-07, T-10 | `test_converse_empty_system_raises`, `test_converse_empty_messages_raises`, `test_converse_response_shape` |
| REQ-03 | T-10 | `test_no_tools_when_empty`, `test_tool_use_blocks_populated` |
| REQ-04 | T-06, T-10 | `test_schema_enforcement_pass`, `test_schema_enforcement_fail_review`, `test_schema_retry_warning`, `test_schema_retry_succeeds` |
| REQ-05 | T-05 | `test_retry_throttling_success`, `test_retry_throttling_exhausted`, `test_retry_warning_logged`, `test_no_retry_for_validation_exception` |
| REQ-06 | T-07 | `test_logging_format`, `test_node_unknown_default` |
| REQ-07 | T-07 | `test_cost_limit_warning` |
| REQ-08 | T-04, T-10 | `test_caching_marker_present`, `test_caching_marker_absent`, `test_caching_marker_in_boto_call` |
| REQ-09 | T-03 | `test_cost_calculation`, `test_cost_cache_discount`, `test_cost_unknown_model`, `test_cost_zero_tokens` |
| REQ-10 | T-08, T-09, T-11 | `test_mock_implements_interface`, `test_mock_records_calls`, `test_mock_exhausted`, `test_factory_mock_env`, `test_factory_real_env` |
| REQ-11 | T-12 | `test_smoke_live_converse` |
| NFR-B01 | T-13 | `ruff check core/llm/` |
| NFR-B02 | T-13 | `mypy --strict core/llm/` |
| NFR-B03 | T-11, T-13 | `pytest --cov=core/llm` ≥ 70% |
| NFR-B04 | T-10 | `grep -r "boto3.client" core/` — `client.py` 1건만 |
| NFR-B05 | T-11 | `HAZOP_USE_MOCK=true pytest -m "not live"` 전부 통과 |
