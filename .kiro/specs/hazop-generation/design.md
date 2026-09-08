# design.md — hazop-generation
# spec: hazop-generation · 대응 FR: PRD §5 FR-03
# 생성: 2026-09-08

## 1. 아키텍처 개요

```
NodeMeta (Pydantic)
    │
    ▼
HazopGenerator.generate(node_meta)   ← core/agent/generate.py
    │
    ├─[호출 1] converse(system=matrix_enumerate.md, user=노드 메타)
    │           response_schema=ParameterListSchema
    │           → parameters: list[ParameterEntry]
    │
    ├─[호출 2..n] for gw in guidewords:
    │           converse(system=deviation_generate.md + rating_scale, user=gw+params)
    │           response_schema=DeviationBatchSchema
    │           → DeviationBatch(guideword, cells[])
    │
    └─[코드] _assemble(node_meta, batches) → list[DeviationRecord]
              · risk_score = S × F
              · id, node, node_meta, scenario 조립
              · content=None 행 → confidence="review", cells=[]
```

의존 방향: `core/agent/` → `core/llm/` → boto3 (외부 호출은 `core/llm` 에만)

---

## 2. 신규 클래스 (3개 상한, PRD §6)

### 2.1 `NodeMeta` (Pydantic BaseModel)

```python
class NodeMeta(BaseModel):
    node: str
    substance: str
    phase: str
    P_kPag: float | None = None
    T_degC: float | None = None
    equipment: list[str] = Field(default_factory=list)
    safeguards: list[str] = Field(default_factory=list)
```

- `gold_record.schema.json` 의 `node_meta` 와 1:1 대응.
- `model_validate(gold_record["node_meta"])` 로 34건 일괄 검증.

### 2.2 `DeviationRecord` (Pydantic BaseModel)

```python
class DeviationRecord(BaseModel):
    id: str                        # 코드 조립: "{node}-{seq:03d}"
    node: str
    node_meta: NodeMeta
    guideword: str
    parameter: str
    deviation: str
    causes: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    safeguards_before: list[str] = Field(default_factory=list)
    S: int = Field(ge=1, le=5)
    F: int = Field(ge=1, le=5)
    risk_score: int                # S × F — 코드 계산
    recommendations: list[str] = Field(default_factory=list)
    scenario: str = ""
    evidence: list = Field(default_factory=list)   # 항상 [] — FR-04 소관
    confidence: str = "inferred"                    # "inferred" | "review"
```

- `risk_score` 는 생성자에서 `S * F` 로 고정 계산 (`model_validator` 또는 별도 조립 함수).

### 2.3 `HazopGenerator`

```python
class HazopGenerator:
    def __init__(self, client: AbstractBedrockClient, config: GeneratorConfig) -> None: ...
    def generate(self, node_meta: NodeMeta) -> list[DeviationRecord]: ...

    def _enumerate_parameters(self, node_meta: NodeMeta) -> list[ParameterEntry]: ...
    def _generate_batch(
        self, node_meta: NodeMeta, parameters: list[ParameterEntry], guideword: str
    ) -> list[DeviationRecord]: ...
    def _assemble(
        self, node_meta: NodeMeta, batches: list[DeviationBatch]
    ) -> list[DeviationRecord]: ...
```

`GeneratorConfig` 는 `config/models.yaml` 에서 로드하는 설정값 묶음(dataclass 또는 간단한
Pydantic 모델). 클래스 카운트에 포함하지 않는다(기존 `ModelConfig` 패턴 재사용).

---

## 3. 파일 구조

```
core/
  agent/
    __init__.py
    generate.py          ← HazopGenerator, NodeMeta, DeviationRecord
    prompts/
      matrix_enumerate.md
      deviation_generate.md
schemas/
  deviation.schema.json  ← 이 spec 에서 새로 정의
tests/
  test_generate.py
```

**파일은 `core/agent/generate.py` 와 `core/agent/prompts/` 로 한정** (지시문 C 범위 상한).

---

## 4. 가이드워드 축 결정 로직

```python
STANDARD_GUIDEWORDS = ["No", "More", "Less", "Reverse", "Other than", "Part of", "As well as"]
PROCEDURAL_GUIDEWORDS = ["Too early", "Too late", "Wrong action"]
PROCEDURAL_KEYWORDS = {"절차", "운전", "조작", "순서", "작업", "procedure", "operation"}

def _select_guidewords(node_meta: NodeMeta) -> list[str]:
    gws = list(STANDARD_GUIDEWORDS)
    equip_text = " ".join(node_meta.equipment).lower()
    if any(kw in equip_text for kw in PROCEDURAL_KEYWORDS):
        gws.extend(PROCEDURAL_GUIDEWORDS)
    return gws
```

---

## 5. 프롬프트 파일 분리 및 캐싱

- 프롬프트는 `core/agent/prompts/*.md` 로 외부화한다. `generate.py` 에 프롬프트 리터럴 문자열 없음.
- `deviation_generate.md` 의 시스템 프롬프트 + S·F 등급표가 캐싱 경계(`cachePoint`).
  `deviation_generate` 는 노드 1건에서 7~10회 반복 호출되므로 캐시 적중 효과가 크다.
- `matrix_enumerate.md` 는 노드당 1회뿐이므로 캐싱 대상 제외.

프롬프트 로딩 함수:

```python
_PROMPT_DIR = Path(__file__).parent / "prompts"

def _load_prompt(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8")
```

---

## 6. 스키마 (`schemas/deviation.schema.json`)

호출 단위 스키마 `DeviationBatchSchema` (Bedrock `inputSchema` 제약 — 최상위는 객체):

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DeviationBatch",
  "type": "object",
  "required": ["guideword", "cells"],
  "properties": {
    "guideword": { "type": "string" },
    "cells": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["parameter", "applicable"],
        "properties": {
          "parameter":         { "type": "string", "minLength": 1 },
          "applicable":        { "type": "boolean" },
          "skip_reason":       { "type": "string" },
          "deviation":         { "type": "string" },
          "causes":            { "type": "array", "items": { "type": "string" } },
          "consequences":      { "type": "array", "items": { "type": "string" } },
          "safeguards_before": { "type": "array", "items": { "type": "string" } },
          "S": { "type": "integer", "minimum": 1, "maximum": 5 },
          "F": { "type": "integer", "minimum": 1, "maximum": 5 },
          "recommendations":   { "type": "array", "items": { "type": "string" } },
          "evidence":          { "type": "array", "items": {}, "maxItems": 0 },
          "confidence":        { "type": "string", "enum": ["inferred"] }
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

- `risk_score` 는 스키마에 없음 — 코드가 계산한다.
- `id`, `node`, `node_meta`, `scenario` 도 스키마에 없음 — 코드가 조립한다.
- 최종 출력 레코드 배열의 스키마는 `deviation.schema.json` 으로 별도 정의한다.

---

## 7. `content=None` 처리 흐름

```python
response = client.converse(system=..., messages=..., response_schema=schema)
if response.content is None:
    # 1회 재시도를 core/llm 이 이미 소진한 상태 → review 격하
    logger.warning("gw=%s content=None, recording as review", guideword)
    # 해당 행: 빈 레코드 목록으로 남기고, 노드 전체를 중단하지 않는다
    continue
batch = DeviationBatch.model_validate_json(response.content)
```

---

## 8. 노드 누적 비용 검사

`AbstractBedrockClient._check_cost_limit` 는 호출 1건씩 검사한다.
노드 전체 누적은 `HazopGenerator.generate` 에서 별도 집계:

```python
total_cost = sum(resp.cost_usd for resp in all_responses)
if total_cost > config.cost_limit_usd:
    logger.warning("node=%s total_cost_usd=%.4f EXCEEDS LIMIT %.2f",
                   node_meta.node, total_cost, config.cost_limit_usd)
```

---

## 9. `get_bedrock_client` 팩토리 사용

`core/llm/__init__.py` 에 이미 있는 `get_bedrock_client()` 를 그대로 사용한다.
`HAZOP_USE_MOCK=true` 이면 자동으로 `MockBedrockClient` 가 주입된다.

```python
from core.llm import get_bedrock_client

client = get_bedrock_client()  # 환경변수로 real/mock 자동 선택
generator = HazopGenerator(client=client, config=load_generator_config())
```
