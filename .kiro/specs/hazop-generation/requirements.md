# requirements.md — hazop-generation
# spec: hazop-generation · 대응 FR: PRD §5 FR-03
# 생성: 2026-09-08 · 기준 문서: 지시문_C_hazop-generation.md, 프롬프트초안_FR-03_20260908.md

## 범위

`core/agent/generate.py` 와 `core/agent/prompts/` 아래의 프롬프트 파일.
신규 클래스 ≤ 3개, 태스크 ≤ 8개(PRD §6 범위 상한).

이 spec 이 **포함하지 않는 것**: KB 검색·근거 인용(FR-04), 물질/고장률 tool(FR-05),
verifier·신뢰도 배지(FR-06), xlsx 내보내기(FR-07), 평가 하네스(FR-08), API/UI(FR-09/10).

---

## 이미 존재하는 자산 (재구현 금지)

| 자산 | 경로 |
|---|---|
| 골드셋 34 레코드 | `data/gold/hazop_nh3.json` |
| 튜닝(N1 8건) / 홀드아웃(N2·N3·N4 26건) 분할 | `hazop_nh3_tune.json` / `hazop_nh3_eval.json` |
| S/F 등급 정의 | `data/gold/rating_scale.json` |
| 레코드 스키마(골드) | `schemas/gold_record.schema.json` (draft-07) |
| Bedrock 래퍼 | `core/llm/` — `get_bedrock_client()`, `converse(system, messages, tools, response_schema, context)` |
| 모의 클라이언트 | `core/llm/mock.py` — `MockBedrockClient(responses=[...])` |

LLM 호출은 반드시 `core/llm` 래퍼만 경유한다. `core/agent/` 에서 `boto3` 직접 호출 금지.

---

## 요구사항 (EARS 형식)

### R-01 입력 스키마

**The system shall** `NodeMeta` Pydantic 모델로 입력을 받는다.
필드: `node: str`, `substance: str`, `phase: str`, `P_kPag: float | None`,
`T_degC: float | None`, `equipment: list[str]`, `safeguards: list[str]`.
골드셋 `node_meta` 와 동일 형태여야 한다(`schemas/gold_record.schema.json` 의 `node_meta`).

**수용 기준**: `NodeMeta.model_validate(gold_record["node_meta"])` 가 34건 모두 성공한다.

---

### R-02 출력 스키마 (`schemas/deviation.schema.json`)

**The system shall** 이탈 레코드 배열을 반환한다.
스키마: `gold_record.schema.json` 필드 전체 + `evidence: list = []` + `confidence: "inferred"`.

- `risk_score` = S × F 는 **코드**가 계산한다(모델에게 곱셈을 시키지 않는다).
- `id`, `node`, `node_meta`, `scenario` 는 코드가 조립한다(모델 반환값 아님).
- 이 spec 에서 `evidence` 는 항상 빈 배열, `confidence` 는 `"inferred"` 고정이다.
  근거 인용은 FR-04, 신뢰도 채점은 FR-06 소관.

**수용 기준**: 생성 결과 전 레코드가 `deviation.schema.json` Draft-07 검증을 통과한다.

---

### R-03 파라미터 축 도출 (매트릭스 1단계)

**The system shall** 이탈 생성 전에 해당 노드에 적용 가능한 파라미터 목록을 LLM 호출
(`matrix_enumerate` 프롬프트)로 도출한다.

- 표준 12종 파라미터(`domain.md §2`) 중 이 노드에 실재하는 것을 우선 선택한다.
- 그 다음 설비 고유 파라미터(물리적 완결성·연결부·계장·구조 지지·운전 절차 관점)를 추가한다.
- 파라미터는 6개 이상 12개 이하. 이름은 한국어 명사구 4어절 이내.

**결정 근거 (프롬프트초안 §2.3)**:
표준 12종만 고정 열거하면 홀드아웃(N2·N3·N4) recall 상한이 **0.192**다.
N4 절차 노드는 상한 0.000이다. 파라미터를 노드 메타에서 도출해야 이 구조적 천장을 벗어날 수 있다.
수용 기준에 이 한계를 함께 기록한다.

**수용 기준**:
- `MockBedrockClient` 로 호출 시 파라미터 목록 JSON 이 반환되고, 결과가 6~12개 범위에 있다.
- 프롬프트 파일 `core/agent/prompts/matrix_enumerate.md` 가 존재하고, `generate.py` 에
  프롬프트 리터럴 문자열이 없다(외부화 검증).

---

### R-04 가이드워드 × 파라미터 매트릭스 판정 (매트릭스 2단계)

**The system shall** 가이드워드 단위로 LLM 호출(`deviation_generate` 프롬프트)하여
열거된 파라미터 전부와의 조합을 빠짐없이 판정한다.

- 가이드워드 고정 7종: No / More / Less / Reverse / Other than / Part of / As well as
  (`domain.md §1`).
- `applicable=false` 셀도 반환하게 한다(누락 방지). 열거 셀 수 ≠ 판정 셀 수 이면
  `WARNING` 로그를 남기고 계속 진행한다(예외를 던지지 않는다).
- 가이드워드 행을 순차 호출한다. 병렬 호출 여부는 지연 실측(G0 완료) 후 결정한다.

#### 절차형 가이드워드 (결정: 조건부 포함)

`Too early` / `Too late` / `Wrong action` 3종은 `equipment` 목록 중 하나라도 운전 절차·
조작 순서를 나타내는 문자열을 포함할 때 가이드워드 축에 추가한다(IEC 61882 확장 가이드워드).

미포함 시 N4 recall 상한 = 0.000, 홀드아웃 상한 = 0.192. 이 수치를 README 평가표 각주에 기재한다.

**수용 기준**:
- 표준 장치 노드 메타(N1 매니폴드) 입력 시 가이드워드 7종으로만 호출된다.
- 운전 절차 노드 메타 입력 시 가이드워드 10종으로 호출된다.

---

### R-05 S·F 산출 및 위험도 계산

**The system shall** `data/gold/rating_scale.json` 을 `deviation_generate` 프롬프트의
S·F 등급표 컨텍스트로 전달하고, LLM 으로부터 정수 1~5 의 S·F 값을 받는다.
`risk_score = S × F` 는 코드가 계산하며, 모델이 반환한 위험도 값이 있어도 무시한다.

**수용 기준**: `mock` 이 틀린 `risk_score` 값을 반환해도 코드 계산 결과가 옳다.
S=4, F=3 이면 `risk_score=12` (ALARP 구간).

---

### R-06 스키마 강제 및 검증 실패 처리

**The system shall** `converse(response_schema=deviation_batch_schema)` 로 JSON 출력을 강제한다.
스키마 검증 실패 시 `core/llm` 의 기존 규칙(1회 재시도 → `confidence_override="review"`)을
그대로 쓴다. 새로운 재시도 로직을 만들지 않는다.

`content=None` 으로 돌아온 가이드워드 행은 `confidence="review"` 로 기록하고 빈 셀로 남긴다.
예외를 던져 노드 전체를 중단시키지 않는다.

**수용 기준**: 스키마 위반 응답 2회 주입 시 해당 행이 `review` 로 기록되고 나머지 행은 계속 진행된다.

---

### R-07 오프라인 테스트

**The system shall** `MockBedrockClient` 로 전 흐름이 AWS 자격증명 없이 통과한다
(`pytest -m "not live"`).
실호출 테스트는 `@pytest.mark.live` 마커를 붙이고 G0 완료 후 실행한다.

**수용 기준**: `pytest -m "not live" tests/test_generate.py` 가 오프라인으로 통과.

---

### R-08 프롬프트 캐싱 적용 지점

**The system shall** `deviation_generate` 시스템 프롬프트와 S·F 등급표를 프롬프트 캐싱
적용 블록으로 구성한다(`aws.md §4`, `models.yaml` 의 `generation.prompt_caching`).
`matrix_enumerate` 는 노드당 1회뿐이므로 캐싱 대상에서 제외한다.

**수용 기준**: `generation.prompt_caching: true` 환경에서 `cachePoint` 블록이 시스템 프롬프트에 포함된다.

---

### R-09 완료 조건 (PRD FR-03 그대로)

| 조건 | 기준 | 시점 |
|---|---|---|
| 지연 | N1 노드 입력 시 **60초 이내** 결과 반환 | G0 완료 후 |
| 스키마 | 전 레코드 `deviation.schema.json` 검증 100% | 오프라인 mock 포함 |
| G1 킬체크 | 골드셋 N1(8건) 대비 **recall ≥ 0.5** | 9/10 |
| 최종 목표 | 홀드아웃(N2·N3·N4 26건) **recall ≥ 0.7** | 9/14 |

**FR-08 매칭 규칙 결정 (프롬프트초안 §7-②)**:
- 가이드워드: 정확 일치.
- 파라미터: 정규화(공백·조사 제거) 후 의미 유사도(임베딩 코사인 ≥ τ, τ는 README에 명시).
- 이탈 텍스트: 의미 유사도(기존 PRD §5 FR-08 그대로).

파라미터 정확 일치를 고집하면 §R-03 에서 도출된 파라미터 어휘가 지표에 반영되지 않는다.
이 완화는 README 평가표에 명시한다(NFR-03).

---

### 제약사항 (2026-09-06 현재)

`config/models.yaml` 의 `generation.model_id` 가 `null` (G0 미완료 — 자격증명 없음).
따라서:
- **mock 만으로 완료 가능한 태스크**: R-01~R-08 (T-01~T-06).
- **실호출이 필요한 태스크**: G1 킬체크, 지연·비용 실측 (T-07~T-08). "G0 통과 후" 실행.

---

### R-10 가이드워드 판정 병렬 호출 (2026-09-29 추가 — 지시문 O-1, 지시문 G 초안 중 병렬 부분만)

WHEN 노드의 가이드워드 행들을 판정할 때 THE SYSTEM SHALL 가이드워드별 `deviation_generate` 호출을
최대 `generation.parallel_calls` 개까지 동시에 실행하고, 결과는 호출 완료 순서와 무관하게 가이드워드 축 순서로 조립한다.

AC-10-1: 레코드 순서와 `id` 가 결정적이다(가이드워드 축 순서 → 셀 순서). AC-10-2: `parallel_calls` 는 `config/models.yaml` 에서만 읽는다(누락 시 4).
AC-10-3: 비용·review 집계가 유실되지 않는다(각 호출이 결과를 반환, 합산은 수집 뒤 단일 스레드). AC-10-4: `parallel_calls: 1` 이면 순차 경로와 결과가 같다.
파라미터 청크 분할(`max_parameters_per_call`)은 이번 범위가 아니다.

---

### R-11 생성 진행 단계 표시 (2026-10-08 추가, 손 작성 — 본선 PRD F-02 수정안)

배경: 데모의 직접 입력 빠른 실호출은 `generate()` 를 거치지 않고(가이드워드 1종), 열거 호출만 약 22초다(J-03 실측).
그래서 PRD 원안의 "가이드워드 묶음마다 행 추가·첫 레코드 ≤15초"는 데모 경로에서 효과가 없다. 대신 **각 단계가
끝나는 즉시** 그 산출물을 알린다. 화면의 기존 "1/3·2/3·3/3" 은 생성이 다 끝난 뒤 한꺼번에 찍혔다.

WHEN `HazopGenerator.generate()` 또는 `generate_quick()` 이 선택 인자 `on_progress` 를 받으면
THE SYSTEM SHALL 파라미터 열거가 끝난 즉시 `("parameters", {...})` 를, 가이드워드 판정이 하나 끝날 때마다
`("guideword", {guideword, done, total, records})` 를 호출 완료 순서대로 알린다.

AC-11-1: 최종 반환 레코드의 순서·`id` 는 `on_progress` 유무·`parallel_calls` 와 무관하게 같다(R-10 AC-10-1, 골든 스냅샷 유지).
AC-11-2: `on_progress` 는 `generate()` 를 부른 스레드에서만 호출된다. 비용·review 합산도 그 스레드에 남는다(AC-10-3).
AC-11-3: `on_progress` 가 예외를 던져도 생성은 계속된다(WARNING 로그).
AC-11-4: 진행 알림의 `records` 는 표시용 중간 결과다 — `judged_cells` 등 생성기 집계를 바꾸지 않는다.
AC-11-5: 빠른 실호출은 공개 API `generate_quick(node_meta, guideword, on_progress=None)` 를 쓴다. 웹 서비스의
비공개 메서드 의존(`_enumerate_parameters`·`_generate_batch`·`_assemble`)을 없앤다.
비목표: 판정 호출 스트리밍, 파라미터 청크 분할(`max_parameters_per_call`).