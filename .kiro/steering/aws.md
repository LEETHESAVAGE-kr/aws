---
inclusion: fileMatch
fileMatchPattern: "core/**,infra/**"
---

# AWS / Bedrock 규칙 — HAZOP 위험성평가 코파일럿

이 파일은 `core/` 및 `infra/` 파일을 편집할 때 항상 적용된다.
AWS 서비스 호출·설정·비용·보안에 관한 모든 결정은 이 규칙을 따른다.

---

## 1. Bedrock 호출 래퍼

- **모든 Amazon Bedrock 호출은 `core/llm/` 래퍼를 경유해야 한다.**
- `boto3.client("bedrock-runtime")` 를 직접 호출하는 코드를 `core/llm/` 외부에 두지 않는다.
- 래퍼 인터페이스 (`core/llm/client.py`):

```python
class BedrockClient:
    def converse(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        response_schema: dict | None = None,  # JSON Schema 강제
    ) -> ConverseResponse:
        """Converse API 단일 진입점. 재시도·로깅·비용 집계 포함."""
        ...
```

- 오프라인 테스트용 `MockBedrockClient`도 동일 인터페이스 구현 (`core/llm/mock.py`).
- 환경변수 `HAZOP_USE_MOCK=true` 시 자동으로 mock 교체.

---

## 2. 모델 ID · 리전 설정

- **모델 ID와 리전은 `config/models.yaml` 한 곳에서만 정의한다.** 코드에 하드코딩 금지.
- `config/models.yaml` 구조:

```yaml
# config/models.yaml
region: us-east-1          # 크로스리전 추론 프로파일 허용
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
```

- 모델 교체(리전 제한 등)는 `models.yaml`만 수정하면 전체 적용된다. 코드 변경 불필요.
- 로드 방법:

```python
from pathlib import Path
import yaml

def load_model_config() -> dict:
    config_path = Path(__file__).parent.parent.parent / "config" / "models.yaml"
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))
```

---

## 3. Converse API 사용

- Bedrock 텍스트 생성 호출은 반드시 **Converse API** (`converse`, `converse_stream`) 사용.
- `InvokeModel` / `InvokeModelWithResponseStream` 직접 호출 금지.
- tool use 루프 구현 시 `stopReason == "tool_use"` 패턴 준수:

```python
while True:
    response = client.converse(system=system, messages=messages, tools=tools)
    if response.stop_reason == "end_turn":
        break
    elif response.stop_reason == "tool_use":
        tool_results = execute_tools(response.tool_use_blocks)
        messages.extend([response.assistant_message, tool_results_message])
    else:
        raise UnexpectedStopReason(response.stop_reason)
```

- 구조화 출력 강제: `tool_choice={"type": "tool", "name": "structured_output"}` 패턴 또는 tool 결과를 JSON Schema로 검증. 스키마 검증 실패 시 1회 재시도 후 `confidence=review`로 격하.

---

## 4. 프롬프트 캐싱 적용 지점

캐싱은 Bedrock의 프롬프트 캐싱 기능을 사용한다. 적용 위치:

| 캐싱 대상 | 적용 위치 | 효과 |
|-----------|-----------|------|
| 시스템 프롬프트 (HAZOP 역할·지시) | `core/agent/generate.py` system block | 노드별 반복 호출 비용 절감 |
| 평가기준 시트 (S/F 등급 정의) | system block 또는 첫 user turn | 동일 세션 내 재사용 |
| 가이드워드 정의 7종 | system block | |

캐싱 설정 방법 (`models.yaml`의 `prompt_caching: true` 시 활성화):

```python
# 캐싱 마커 추가 예시 (Anthropic Claude on Bedrock)
system_content = [
    {
        "text": SYSTEM_PROMPT,
        "cachePoint": {"type": "default"},  # 캐싱 경계 마커
    }
]
```

- verifier·요약 호출처럼 반복 패턴이 적은 경우 캐싱 off (`models.yaml`에서 개별 설정).

---

## 5. 비용 로깅 (필수)

- **모든 Bedrock 호출 후 비용을 계산하고 로깅한다.** 미기록 호출 금지.
- 비용 계산 로직은 `core/llm/cost.py`에 집중:

```python
def calculate_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """USD 단위 비용 반환. 가격표는 cost.py 내 상수로 관리."""
    ...
```

- 로그 형식 (INFO 레벨, `core.llm.client` 로거):
  ```
  INFO | core.llm.client | call_id=<uuid> node=N1 model=claude-3-5-sonnet \
    tokens_in=1234 tokens_out=567 cache_read=890 cost_usd=0.042 latency_s=18.3
  ```

- 노드 1건(생성 + 검증 전체) 누적 비용이 **USD 0.30 상한**을 초과하면 `WARNING` 로그 발생:
  ```
  WARNING | core.llm.client | node=N1 cumulative_cost_usd=0.32 EXCEEDS LIMIT 0.30
  ```

- `eval/` 실행 결과 `results/{run_id}/metrics.json`에 평균 비용·토큰 포함.

---

## 6. 노드 1건 비용 상한

- **생성 + 검증 합산 ≤ USD 0.30 (목표, 소프트 상한).**
- 초과 시 즉각 중단하지 않고 경고 로그만 남긴다(사용자 알림은 UI에서 처리).
- 비용 절감 우선순위:
  1. 프롬프트 캐싱으로 입력 토큰 절감
  2. verifier에 하위 모델(haiku 계열) 사용
  3. 가이드워드 매트릭스 필터링으로 불필요한 셀 제거

---

## 7. 리소스 태그

- Bedrock Knowledge Base·S3 버킷·기타 생성 리소스 모두에 태그 필수:

```python
RESOURCE_TAGS = {
    "project": "hazop-copilot",
    "env": "dev",          # dev | prod
    "owner": "team",
}
```

- `infra/kb_setup.py`에서 KB 생성 시 태그 포함:

```python
bedrock_agent.create_knowledge_base(
    name="hazop-copilot-kb",
    tags=RESOURCE_TAGS,
    ...
)
```

- S3 버킷 생성 시도 `boto3` `put_bucket_tagging` 호출로 태그 추가.

---

## 8. Guardrails

- Bedrock Guardrails에서 **PII 차단** 활성화 필수 (NFR-05).
- Guardrails ID는 `config/models.yaml`의 `guardrails.id` 필드에서 읽는다.
- 규칙: 근거 tool 결과에 없는 KOSHA 코드를 모델이 인용하면 verifier가 플래그.
  - 이는 Guardrails + verifier 이중 방어로 처리.

---

## 9. 오류 처리 및 재시도

- `botocore.exceptions.ClientError`의 `ThrottlingException`·`ServiceUnavailableException`에는 **지수 백오프 재시도** (최대 3회, 초기 딜레이 1초).
- `ValidationException` (스키마 불일치)은 재시도 1회 후 `confidence=review`로 격하.
- 모든 재시도는 로그에 기록: `WARNING | 재시도 attempt=2/3 reason=ThrottlingException`.

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(is_throttling_error),
)
def _call_converse(self, **kwargs) -> dict:
    ...
```
