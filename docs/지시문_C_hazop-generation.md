# 지시문 C — `hazop-generation` spec 생성 요청 (Kiro) · 2026-09-06

FR-03(이탈 생성 루프, PRD §5 ★핵심)의 spec 을 Kiro 에서 만든다.
**아래 "붙여넣기 시작" 이후 전체를 Kiro 에 그대로 붙여넣는다.**

---

## 새 창 진입점 (사람이 읽는 부분 — 붙여넣지 말 것)

| 항목 | 현재 상태 (2026-09-06) |
|---|---|
| 저장소 | `C:\Users\user\Desktop\공모전\AWS_AI_Innovators\hazop-copilot` (git `master`) |
| 완료 | FR-01 골드셋 34 레코드(`spec:gold-dataset` T-01~T-11, 커밋 `291f7ea`) |
| 완료 | FR-02 Bedrock 래퍼 **mock 경로만** — `core/llm/`, 101 tests 통과 |
| 미완 | **G0(9/7)**: AWS 자격증명 없음 → 실호출 0회. `config/models.yaml` 의 model_id 3개가 `null` |
| 다음 게이트 | **G1(9/10)**: 프롬프트만으로 N1 recall ≥ 0.5 |
| 진행 중 | `docs/지시문_K_spec수정.md` 4건을 Kiro 가 반영 중 (K-2 는 사용자 선택 필요) |

개발은 `HAZOP_USE_MOCK=true` 로 진행 가능하다. 실측 지표는 G0 통과 후에만 낸다.

---

## 붙여넣기 시작

`hazop-generation` spec 을 만들어라. 대응 FR 은 `PRD.md` §5 FR-03 이다.
`CLAUDE.md`, `.kiro/steering/domain.md`, `engineering.md`, `aws.md` 를 먼저 읽어라.

### 범위 상한 (PRD §6, 2026-09-04 추가 — 반드시 지킬 것)

- `tasks.md` 태스크 **8개 이하**. 신규 클래스 **3개 이하**.
- 파일은 `core/agent/generate.py` 와 `core/agent/prompts/` 아래 프롬프트 텍스트로 제한한다.
- PRD 에 없는 도구·의존성을 넣지 마라: `mypy --strict`, `scikit-learn`, `tenacity`, 새 LLM SDK 금지.
  품질 게이트는 `ruff check` 와 `pytest` 뿐이다.
- 기존 spec(gold-dataset 13태스크, bedrock-client 14태스크)이 과잉 분해되어 압축 구현해야 했다.
  같은 실수를 반복하지 마라.

### 이미 존재하는 자산 (다시 만들지 마라)

| 자산 | 경로 | 비고 |
|---|---|---|
| 골드셋 34 레코드 | `data/gold/hazop_nh3.json` | 노드 N1 8 / N2 9 / N3 7 / N4 10 |
| 튜닝/홀드아웃 분할 | `hazop_nh3_tune.json`(N1 8건), `hazop_nh3_eval.json`(26건) | `split_node.json` 에 id 목록 |
| S/F 등급 정의 | `data/gold/rating_scale.json` | `평가기준` 시트 원문 (S 5단·F 5단·위험도 구간 3단) |
| 레코드 스키마 | `schemas/gold_record.schema.json` | draft-07 |
| Bedrock 래퍼 | `core/llm/` | `get_bedrock_client()`, `converse(system, messages, tools, response_schema, context)` |
| 모의 클라이언트 | `core/llm/mock.py` | `MockBedrockClient(responses=[...])` — 오프라인 테스트용 |

LLM 호출은 반드시 `core/llm` 래퍼를 경유한다. `boto3` 를 `core/agent/` 에서 직접 부르지 않는다.

### requirements.md 에 반드시 들어갈 것

1. **입력**: 노드 메타 JSON — `{node, substance, phase, P_kPag, T_degC, equipment[], safeguards[]}`.
   골드셋 `node_meta` 와 같은 형태여야 한다.
2. **출력**: 이탈 레코드 배열. `schemas/gold_record.schema.json` 필드 + `evidence[]`, `confidence`
   두 필드를 더한 형태. 출력 스키마 파일은 `schemas/deviation.schema.json` 로 새로 정의한다.
   (이 spec 에서는 `evidence[]` 를 **빈 배열로 두고** `confidence` 는 `inferred` 고정으로 시작한다.
   근거 인용은 FR-04, 신뢰도 채점은 FR-06 의 몫이다.)
3. **매트릭스 선열거 (핵심 요구)**: 가이드워드 7종 × 파라미터를 **먼저 열거한 뒤** 각 셀에 대해
   적용 여부와 이탈을 생성한다. 자유 생성 금지 — 누락 방지가 이 구조의 목적이다.
   - 가이드워드: No / More / Less / Reverse / Other than / Part of / As well as (`domain.md` §1)
   - 파라미터: 노드 특성에 따라 선택 (`domain.md` §2, 유량·압력·온도·조성·준위·상·시간 등)
   - **주의**: 골드셋 원본에는 표준 7종 밖의 절차형 가이드워드가 9건 있다
     (`Too early` 3 · `Too late` 3 · `Wrong action` 3, 전부 N4 절차 노드). 이것을 매트릭스에
     포함할지 여부를 requirements 에서 명시적으로 결정하라. 포함하지 않으면 N4 recall 상한이 구조적으로
     낮아진다는 점을 수용 기준에 적어라.
4. **S·F 산출**: `data/gold/rating_scale.json` 을 컨텍스트로 주고 정수 1~5 로 산출.
   위험도 = S × F 는 코드에서 계산한다(모델에게 곱셈을 시키지 않는다).
5. **스키마 강제**: `converse(response_schema=...)` 로 JSON 을 강제하고, 검증 실패 시
   `core/llm` 의 기존 규칙(1회 재시도 → `confidence=review` 격하)을 그대로 쓴다. 새로 만들지 마라.
6. **오프라인 테스트**: `MockBedrockClient` 로 전 흐름이 자격증명 없이 통과해야 한다
   (`pytest -m "not live"`). 실호출 테스트는 `@pytest.mark.live`.
7. **프롬프트 파일 분리**: 시스템 프롬프트는 `core/agent/prompts/*.md` 로 두고 코드에 문자열로
   박지 않는다. 프롬프트 캐싱(`prompt_caching`) 적용 지점을 명시하라.

### 완료 조건 (PRD FR-03 그대로)

- N1 노드 입력 시 **60초 내** 결과, 스키마 검증 100%.
- 골드셋 N1(8건) 대비 **recall ≥ 0.5** — G1 킬체크 9/10.
- 최종 목표 recall ≥ 0.7 (홀드아웃 노드 N2·N3·N4 26건).

### 이 spec 에 넣지 말 것 (다른 spec 소관)

- KB 검색·근거 인용 → FR-04 `evidence-citation`
- 물질/고장률 tool → FR-05 (`evidence-citation` 에 포함)
- verifier·신뢰도 배지 → FR-06 `self-verification`
- xlsx/LOPA 내보내기 → FR-07, 평가 지표 계산 → FR-08, API/UI → FR-09/10

### 제약 사항 (2026-09-06 현재)

`config/models.yaml` 의 `generation.model_id` 가 `null` 이다(G0 미완료 — 자격증명 없음).
따라서 tasks.md 는 **모의 클라이언트만으로 완료 가능한 태스크**와 **실호출이 필요한 태스크**를
분리하고, 후자에 "G0 통과 후"를 명시하라. recall 측정은 실호출 태스크에 속한다.

## 붙여넣기 끝

---

## Kiro 산출 후 확인할 것

1. `tasks.md` 태스크가 8개 이하인가 (넘으면 재요청 대신 압축 구현으로 처리)
2. 절차형 가이드워드(`Too early` 등) 포함 여부가 requirements 에 명시됐는가
3. `core/llm` 래퍼를 재구현하는 태스크가 섞이지 않았는가
4. 실호출 필요 태스크가 "G0 통과 후"로 분리됐는가
