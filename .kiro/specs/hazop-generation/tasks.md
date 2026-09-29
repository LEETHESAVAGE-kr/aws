# tasks.md — hazop-generation
# spec: hazop-generation · 대응 FR: PRD §5 FR-03
# 생성: 2026-09-08 · 태스크 8개 이하 (PRD §6 상한)

## 범례

- **오프라인 완료**: `pytest -m "not live"` 만으로 통과. AWS 자격증명 불필요.
- **G0 통과 후**: `config/models.yaml` `generation.model_id` 가 채워진 뒤 실행.
- 커밋 메시지 형식: `spec:hazop-generation T-xx — 요약`

---

## T-01 출력 스키마 파일 정의 【오프라인 완료】

**목표**: `schemas/deviation.schema.json` 을 새로 작성한다.

**작업**:
1. `design.md §6` 의 `DeviationBatchSchema` JSON 을 `schemas/deviation.schema.json` 에 저장한다.
2. `schemas/gold_record.schema.json` 과 필드 호환성을 확인하는 메모를 파일 상단 `$comment` 에 추가한다.

**완료 조건**:
- `schemas/deviation.schema.json` 이 Draft-07 유효한 JSON 스키마다.
- `jsonschema` 로 올바른 샘플 객체를 검증하면 통과한다.

**대응 요구사항**: R-02

---

## T-02 `NodeMeta` · `DeviationRecord` 모델 및 `generate.py` 뼈대 【오프라인 완료】

**목표**: `core/agent/generate.py` 에 두 Pydantic 모델과 `HazopGenerator` 클래스 뼈대를 만든다.

**작업**:
1. `NodeMeta` 모델 — `design.md §2.1` 참고. `gold_record.schema.json` 의 `node_meta` 와 1:1 대응.
2. `DeviationRecord` 모델 — `design.md §2.2` 참고. `risk_score = S × F` 는 `model_validator` 로 계산.
3. `HazopGenerator.__init__` 뼈대 (`client`, `config` 주입).
4. `core/agent/__init__.py` 에 `HazopGenerator`, `NodeMeta`, `DeviationRecord` re-export.

**완료 조건**:
- `NodeMeta.model_validate(gold_record["node_meta"])` 가 `data/gold/hazop_nh3.json` 34건 모두 성공.
- `ruff check core/agent/generate.py` 경고 0.

**대응 요구사항**: R-01, R-02

---

## T-03 프롬프트 파일 작성 및 로딩 함수 【오프라인 완료】

**목표**: `core/agent/prompts/matrix_enumerate.md` · `deviation_generate.md` 를 작성하고,
코드에서 파일로 읽는 `_load_prompt` 함수를 구현한다.

**작업**:
1. `core/agent/prompts/matrix_enumerate.md` — `프롬프트초안_FR-03_20260908.md §4.1` 본문을 그대로 옮긴다.
2. `core/agent/prompts/deviation_generate.md` — `프롬프트초안_FR-03_20260908.md §4.2` 본문을 그대로 옮긴다.
   S·F 등급표 플레이스홀더 `{rating_scale}` 을 런타임에 `data/gold/rating_scale.json` 내용으로 채운다.
3. `generate.py` 에 `_load_prompt(name: str) -> str` 구현 (`design.md §5`).
4. `generate.py` 에 한글 프롬프트 리터럴 문자열 없음을 확인.

**완료 조건**:
- `core/agent/prompts/` 아래 두 파일이 존재한다.
- `_load_prompt("matrix_enumerate.md")` 가 빈 문자열이 아닌 내용을 반환한다.
- `generate.py` 에 5줄 이상 한글 리터럴 없음(`grep` 검증).

**대응 요구사항**: R-03, R-08 (프롬프트 외부화)

---

## T-04 `HazopGenerator.generate` 핵심 흐름 구현 【오프라인 완료】

**목표**: `generate(node_meta)` 가 매트릭스 열거 → 가이드워드 행 판정 → 결과 조립의 전체 루프를 돈다.

**작업**:
1. `_enumerate_parameters`: `matrix_enumerate.md` 시스템 프롬프트 + 노드 메타 사용자 턴으로
   `converse` 호출. `ParameterListSchema` 로 JSON 강제.
2. `_select_guidewords(node_meta)`: 표준 7종 + 절차형 조건부 3종 (`design.md §4`).
3. `_generate_batch`: 가이드워드 1종 + 파라미터 목록으로 `deviation_generate.md` 호출.
   `DeviationBatchSchema` 로 JSON 강제.
4. `_assemble`: `content=None` 행은 `confidence="review"` 로 처리, 예외 없이 계속.
   `risk_score = S × F` 코드 계산. `id`, `node`, `node_meta`, `scenario` 조립.
5. 노드 누적 비용 집계 및 경고 (`design.md §8`).

**완료 조건**:
- `MockBedrockClient` 로 N1 노드 메타를 입력하면 `DeviationRecord` 목록이 반환된다.
- 반환된 모든 레코드의 `risk_score == record.S * record.F` 를 단언(assert).
- `content=None` 을 2회 주입해도 예외 없이 나머지 결과가 반환된다.

**대응 요구사항**: R-03, R-04, R-05, R-06

---

## T-05 캐싱 블록 적용 【오프라인 완료】

**목표**: `deviation_generate` 호출의 시스템 프롬프트 블록에 `cachePoint` 를 추가한다.

**작업**:
1. `generate.py` 의 `_generate_batch` 에서 시스템 프롬프트를 `CachingBuilder.build_system_blocks`
   로 조립한다. `config.prompt_caching` 이 `true` 이면 `cachePoint` 가 포함된다.
2. `matrix_enumerate` 호출에는 캐싱을 적용하지 않는다(노드당 1회).

**완료 조건**:
- `mock` 에서 캡처한 시스템 블록에 `cachePoint` 가 포함된다(캐싱 on 설정).
- 캐싱 off 설정에서는 `cachePoint` 가 없다.

**대응 요구사항**: R-08

---

## T-06 오프라인 테스트 스위트 작성 【오프라인 완료】

**목표**: `tests/test_generate.py` 에 `프롬프트초안_FR-03_20260908.md §8` 의 시험 전부를 구현한다.

**작업 (테스트 6종)**:
1. **매트릭스 완전성**: 열거 파라미터 N개 × GW k종 = N×k 셀이 전부 판정됐는가.
2. **`risk_score` 코드 계산**: mock 이 `risk_score` 를 틀린 값으로 반환해도 결과가 옳은가.
3. **스키마 강제**: `converse` 호출 시 `response_schema` 가 `None` 이 아닌가.
4. **`content=None` 격하**: 스키마 위반 응답 2회 주입 시 `review` 기록, 예외 없음.
5. **절차형 가이드워드 조건부**: N1 메타 → 7종, 절차 노드 메타 → 10종.
6. **프롬프트 외부화**: `generate.py` 에 5줄 이상 한글 프롬프트 리터럴 없음.

모든 테스트는 `@pytest.mark.not live` (기본 마커 없음 = 오프라인).

**완료 조건**: `pytest -m "not live" tests/test_generate.py` 통과.

**대응 요구사항**: R-03, R-04, R-05, R-06, R-07

---

## T-07 실호출 스모크 테스트 【G0 통과 후】

**목표**: 실제 Bedrock 호출로 N1 노드 메타를 처리하고 기본 품질을 확인한다.

**작업**:
1. `tests/test_generate.py` 에 `@pytest.mark.live` 테스트 추가.
2. N1 노드 메타(`data/gold/hazop_nh3.json` 의 N1 `node_meta`)를 입력.
3. 지연 ≤ 60초, 반환 레코드 ≥ 1건, 스키마 검증 100% 를 단언.
4. 토큰·비용·지연을 로그로 출력(실측 기록).

**완료 조건**: `pytest -m live tests/test_generate.py::test_generate_live_n1` 통과.
비용·지연 실측값을 `docs/진행로그.md` 에 4줄 완료 보고로 추가.

**대응 요구사항**: R-09 (지연 60초, 스키마 100%)

---

## T-08 G1 킬체크 — N1 recall ≥ 0.5 【G0 통과 후 · 9/10 마감】

**목표**: 골드셋 N1 8건 대비 recall 을 측정하고 G1 통과 여부를 판정한다.

**작업**:
1. `eval/` 하위에 간단한 매칭 스크립트 작성(또는 `tests/test_generate.py` 내 함수):
   - 가이드워드 정확 일치 + 파라미터 정규화(공백·조사 제거) 일치 기준으로 매칭.
   - recall = 매칭된 골드 레코드 수 / 전체 골드 레코드 수(N1 8건).
2. recall ≥ 0.5 이면 G1 통과. 미달 시 `docs/진행로그.md` 에 분석 내용과 다음 조치를 기록.

**완료 조건**:
- N1 recall 수치가 `docs/진행로그.md` 에 기록돼 있다.
- recall ≥ 0.5 이면 G1 통과 선언. 미달이면 매트릭스 열거 방식 강화 후 9/12 재판정.

**대응 요구사항**: R-09 (G1 킬체크)

---

## 체크리스트 요약

| 태스크 | 설명 | 오프라인 | 상태 |
|---|---|---|---|
| T-01 | `schemas/deviation.schema.json` 작성 | ✅ | ☑ |
| T-02 | `NodeMeta` · `DeviationRecord` · `HazopGenerator` 뼈대 | ✅ | ☑ |
| T-03 | 프롬프트 파일 작성 및 로딩 함수 | ✅ | ☑ |
| T-04 | `generate` 핵심 흐름 구현 | ✅ | ☑ |
| T-05 | 캐싱 블록 적용 | ✅ | ☑ |
| T-06 | 오프라인 테스트 스위트 | ✅ | ☑ |
| T-07 | 실호출 스모크 테스트 | G0 후 | ☑ |
| T-08 | G1 킬체크 N1 recall ≥ 0.5 | G0 후 | ☑ |
| T-09 | 가이드워드 판정 병렬 호출 (R-10, 지시문 O-1) | ✅ | ☑ |
