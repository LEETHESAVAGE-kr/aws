# tasks.md — export-formats
# spec: export-formats · 대응 FR: PRD §5 FR-07
# 생성: 2026-09-11 · 태스크 6개 이하 (지시문 D 상한) · 전부 오프라인

## 범례

- **오프라인 완료**: `pytest -m "not live"` 만으로 통과. AWS 자격증명 불필요. 이 spec 은 전 태스크가 여기 해당한다.
- 커밋 메시지 형식: `spec:export-formats T-xx — 요약`

---

## T-01 `WorksheetRow` 정규화 【오프라인 완료】

**목표**: `core/export/rows.py` — 두 입력 형태(dict·`DeviationRecord`)를 `WorksheetRow` 로 평탄화.

**작업**:
1. `HEADERS` 12개 상수, `WorksheetRow` frozen dataclass(design §2.1).
2. `normalize_rows(records)` — `model_dump()` 우선, 아니면 Mapping. `confidence` 기본 `None`,
   `evidence` 기본 `()`. `risk_score = S*F` 재계산. 노드·가이드워드 라벨 조립(R-01).
3. `core/export/__init__.py` 재수출.

**완료 조건**: 골드셋 34건 정규화 결과 1번 행의 `node_label == "N1 벙커링선 매니폴드"`,
`guideword_label == "No (유량)"`, 전 행 `confidence is None`.

**대응 요구사항**: R-01

---

## T-02 `HAZOP워크시트` 시트 【오프라인 완료】

**목표**: `core/export/xlsx.py` 의 `export_xlsx(rows, path, *, rating_scale=None)` 중 첫 시트.

**작업**:
1. 헤더 12열, 열 너비 11개(I 제외), 헤더 서식·틀 고정 `A2`·본문 서식.
2. 행마다 12열, `J{r}` 수식 `=H{r}*I{r}`.
3. 데이터 다음 빈 행 + 범례 행.

**완료 조건**: 골드셋 34건 → 재로딩 시 37행×12열, J2..J35 수식 문자열 일치, 너비 일치.

**대응 요구사항**: R-02

---

## T-03 `평가기준` · `스크리닝` · `근거` · `신뢰도` 시트 【오프라인 완료】

**목표**: 같은 파일에 나머지 4개 시트.

**작업**:
1. `평가기준`: `rating_scale.json` 주입(기본 경로는 `data/gold/`), 원본 레이아웃(18행×3열).
2. `스크리닝`: 제목 + 5×5 COUNTIFS 수식 매트릭스(마지막 데이터 행 반영). 선정표는 제외(R-03).
3. `근거`: 헤더 5열 + evidence 행. 0행이면 안내 문구 1행.
4. `신뢰도`: 헤더 3열 + 레코드마다 표기·사유(R-05 표).

**완료 조건**: 시트 순서 5개 일치. 골드셋 입력 시 `근거` 2행, `신뢰도` B 열 전부 `미부여`.

**대응 요구사항**: R-03, R-04, R-05

---

## T-04 신뢰도 리포트 JSON 【오프라인 완료】

**목표**: `core/export/report.py` — `ConfidenceReport`, `build_report`, `write_report`.

**작업**:
1. R-06 필드 전부. `evidence_attachment_rate`·`matrix_coverage` 는 근거가 없으면 `null`(0 금지).
2. `risk_distribution` 구간 상수 + `sf_matrix` 5×5.
3. `pending` 사전에 `null` 필드의 담당 FR 기록.

**완료 조건**: 골드셋 → `record_count 34`, `unassigned 34`, `evidence_attachment_rate null`,
`risk_distribution` 합 34, `sf_matrix` 합 34. 두 번 써도 바이트 동일.

**대응 요구사항**: R-06, R-08

---

## T-05 LOPA 초안 Markdown — A안 【오프라인 완료】

**목표**: `core/export/lopa.py` — `render_lopa`, `write_lopa`.

**작업**:
1. 위험도 상위 N(기본 5, 동률 No 오름차순) 선정.
2. 머리 고정 문구 + 시나리오별 절(design §6). IE 후보 = `causes`, IPL 후보 = `safeguards_before`[기존]
   + `recommendations`[권고], 정량 표 6행 전부 `TBD (문헌 근거 필요 — FR-04/FR-05)`, 3원칙 미판정.
3. 정량 표기(`/yr`, `PFD=`, `1E-`)를 생성하는 코드 경로가 없음을 확인.

**완료 조건**: 골드셋 → 상위 5건 순서 일치, 정량 정규식 매칭 0줄, `TBD (문헌 근거 필요` ≥ 30회.

**대응 요구사항**: R-07, R-08

---

## T-06 오프라인 테스트 + 골든 스냅샷 【오프라인 완료】

**목표**: `tests/test_export.py` 와 `tests/golden/export_gold34.snapshot.json`.

**작업 (시험 항목)**:
1. 정규화 양방향(골드셋 dict / `DeviationRecord`) — 같은 함수, 같은 결과 형태.
2. 워크시트 구조(헤더·수식·너비·행 수·틀 고정), `risk_score` 값이 J 열에 들어가지 않음.
3. 시트 5개 순서, `평가기준` 값이 `rating_scale.json` 과 일치, `스크리닝` 수식 범위.
4. `근거` 안내 행 ↔ evidence 1건 주입 시 데이터 행. `신뢰도` inferred / 미부여.
5. 리포트 필드(R-06 수용 기준), 구간 상수가 `rating_scale.json` 문자열과 일치.
6. LOPA 순서·고정 문구·정량 표기 부재·TBD 횟수.
7. 재현성: 2회 내보내기 동일(R-08). 골든 스냅샷 `==` (R-09), `UPDATE_SNAPSHOT=1` 로 갱신.
8. FR-03 mock 경로 결과(`HazopGenerator` + `MockBedrockClient`)를 `export_all` 로 내보내기 —
   양방향 입력 완료 조건. 이 시험만 `core.agent` 를 임포트한다(`core/export` 는 아님).
9. `core/export/*.py` 소스에 `core.llm`·`core.agent`·`boto3` 문자열 없음(임포트 금지 검증).

**완료 조건**: `pytest -m "not live" tests/test_export.py` 통과, `ruff check .` 경고 0.

**대응 요구사항**: R-01~R-09

---

## 체크리스트 요약

| 태스크 | 설명 | 오프라인 | 상태 |
|---|---|---|---|
| T-01 | `WorksheetRow` 정규화 | ✅ | ☐ |
| T-02 | `HAZOP워크시트` 시트(수식·너비·서식) | ✅ | ☐ |
| T-03 | `평가기준`·`스크리닝`·`근거`·`신뢰도` 시트 | ✅ | ☐ |
| T-04 | 신뢰도 리포트 JSON | ✅ | ☐ |
| T-05 | LOPA 초안 md (A안) | ✅ | ☐ |
| T-06 | 오프라인 테스트 + 골든 스냅샷 | ✅ | ☐ |
