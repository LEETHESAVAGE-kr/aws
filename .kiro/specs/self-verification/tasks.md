# tasks.md — self-verification
# spec: self-verification · 대응 FR: PRD v2.0 §5 FR-06
# 생성: 2026-09-29 · 태스크 4개 이하(PRD §6 상한) · 전부 오프라인 · 실호출 0회

## 범례

- **오프라인 완료**: `pytest -m "not live"` 만으로 통과. 이 spec 은 전 태스크가 여기 해당한다.
- 커밋 메시지 형식: `spec:self-verification T-xx — 요약`

---

## T-01 규칙·타입 (`core/agent/verify.py`) 【오프라인】 ☑

`Flag`·`VerifySummary`·`STANDARD_PATTERNS`·`NUMBER_PATTERN`·`_iter_text_fields`·`_allowed_numbers`.
`verify()` 가 R-01·R-02·R-03·R-04 를 수행. `core/llm` 임포트 0.

## T-02 시험 (`tests/test_verify.py`) 【오프라인】 ☑

결함 삽입 10건(≥ 9 플래그), 위양성(AC-02-1), 순서·개수 보존, 원본 불변, 같은 매치 1회 계수(AC-01-2),
`deviation` 필드 수치 비대상(AC-02-3). 61건 baseline 플래그 수를 로그로 출력.

## T-03 UI·내보내기 결선 (`apps/web/service.py`, `tests/test_web.py`) 【오프라인】 ☑

`Result.verified` 캐시, `검증 플래그` 열, 요약 줄 `review N건`. `export_files` 가 격하된 confidence 로
xlsx 신뢰도 시트를 쓴다. `tests/test_web.py` 에 결함 1건 삽입 → 표·xlsx 모두 `review` 인 시험 1건.

## T-04 완료 보고 (`docs/진행로그.md`) 【오프라인】 ☑

61건 실측 플래그 수(규칙별), 결함 삽입 결과(10건 중 n), 결함 재삽입 검증 결과, AC 충족 표.

---

## 추적 매트릭스 (NFR-01)

| 요구사항 | 코드 | 테스트 | 지표 |
|---|---|---|---|
| R-01 규격 번호 | `core/agent/verify.py::STANDARD_PATTERNS` | T-02 | 삽입 5건 중 ≥ 4 플래그 |
| R-02 수치 주장 | `core/agent/verify.py::NUMBER_PATTERN` | T-02 | 삽입 5건 중 ≥ 4, 위양성(AC-02-1) 0 |
| R-03 격하·요약 | `core/agent/verify.py::verify` | T-02·T-03 | 10건 중 ≥ 9 `review` |
| R-04 누락 셀 | `VerifySummary.missing_cells` | T-02 | expected−judged 전달 |
