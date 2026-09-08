# 지시문 D — `export-formats` spec 생성 요청 (Kiro) · 2026-09-08

FR-07(내보내기, PRD §5)의 spec 을 Kiro 에서 만든다.
**아래 "붙여넣기 시작" 이후 전체를 Kiro 에 그대로 붙여넣는다.**

---

## 새 창 진입점 (사람이 읽는 부분 — 붙여넣지 말 것)

| 항목 | 현재 상태 (2026-09-08) |
|---|---|
| 저장소 | `C:\Users\user\Desktop\공모전\AWS_AI_Innovators\hazop-copilot` (git `master`) |
| 완료 | FR-01 골드셋 34건 · FR-02 Bedrock 래퍼(mock) · **FR-03 이탈 생성 T-01~T-06**(`a3a9179`) |
| 미완 | **G0**: AWS 자격증명 없음 → 실호출 0회. FR-03 의 T-07·T-08(G1 킬체크)이 여기 걸려 있다 |
| 다음 게이트 | G1(9/10) recall — **측정 불가 상태** / G2(9/14) 핵심 루프 = FR-03·04·**07** |
| 테스트 | ruff clean · `pytest -m "not live"` 117 passed |

FR-07 은 LLM 무관이라 **G0 와 무관하게 지금 끝낼 수 있다.** G1 이 자격증명 때문에 막혀 있는
동안 G2 지분을 확보하는 것이 이 지시문의 목적이다.

### 사용자가 먼저 결정할 것 2가지

**① spec 개수 상한 충돌.** PRD §6 표는 spec 을 6개로 못 박았고 그 목록은
`gold-dataset · bedrock-client · hazop-generation · evidence-citation · self-verification ·
evaluation-harness` 다 — **`export-formats` 는 없다.** 반면 PRD §5 FR-07 은 "spec:
`export-formats`" 라고 적혀 있다. §6 표는 "export/api/ui 는 hazop-generation·evaluation 안에
requirement 로 흡수하거나 W3 에 spec 없이 구현" 이라는 예외를 함께 적어 두었다.

- 권고: **7번째 spec 으로 만든다.** 근거는 NFR-01(추적성) — 코드 10점·기술 30점의 일부가
  `.kiro/` 에서 나온다. `export-formats` 는 FR-03 과 결합도가 낮아 흡수하면 오히려 추적이 흐려진다.
- 이 선택을 하면 **PRD §6 표의 "spec 6개 상한"과 목록을 7개로 갱신**해야 한다(문서 정합).
  PRD 는 사용자 정본이므로 이 세션이 고치지 않는다.
- 크레딧이 빠듯하면 대안은 `.kiro/specs/export-formats/` 를 손으로 작성하는 것이다(R2 대응책).

**② LOPA 초안의 정량 수준** — 아래 붙여넣기 본문 §5 에 3안을 적어 두었다. Kiro 가 고르게 두지
말고 사용자가 먼저 정하는 편이 낫다. 권고는 **A안(정량 자리표시자)**.

---

## 붙여넣기 시작

`export-formats` spec 을 만들어라. 대응 FR 은 `PRD.md` §5 FR-07 이다.
`CLAUDE.md`, `.kiro/steering/domain.md`, `engineering.md`, `docs.md` 를 먼저 읽어라.
`.kiro/specs/hazop-generation/` 3파일도 읽어라 — 이 spec 의 입력이 그 출력이다.

### 범위 상한 (PRD §6 — 반드시 지킬 것)

- `tasks.md` 태스크 **6개 이하**. 신규 클래스 **3개 이하**.
- 파일은 `core/export/` 아래와 `tests/test_export.py` 로 제한한다.
- PRD 에 없는 도구·의존성을 넣지 마라: `mypy --strict`, `pandas`, `xlsxwriter`, `jinja2` 금지.
  **xlsx 는 `openpyxl` 로만 쓴다**(이미 의존성에 있다). 품질 게이트는 `ruff check` 와 `pytest` 뿐이다.
- 이 spec 은 **LLM 을 호출하지 않는다.** `core/llm` 을 임포트하지 마라. AWS 자격증명과 무관하게
  전 태스크가 오프라인으로 완료돼야 한다.

### 이미 존재하는 자산 (다시 만들지 마라)

| 자산 | 경로 | 비고 |
|---|---|---|
| 이탈 레코드 모델 | `core/agent/generate.py` 의 `DeviationRecord` | pydantic v2. `model_dump()` 로 dict |
| 산출물 스키마 | `schemas/deviation.schema.json` | 배열 최상위 draft-07 |
| 골드셋 34건 | `data/gold/hazop_nh3.json` | 같은 필드 구성(+`evidence`·`confidence` 없음) |
| S/F 등급 정의 | `data/gold/rating_scale.json` | `평가기준` 시트 원문 |
| 원본 워크시트 | `data/raw/D1_HAZOP_워크시트.xlsx` | **읽기 전용.** 양식의 정본 |

입력은 `list[DeviationRecord]` 또는 그와 동일한 필드의 dict 목록이다. 골드셋 JSON 도 같은
함수로 내보낼 수 있어야 한다(골드셋에는 `evidence`·`confidence` 가 없으므로 기본값 처리).

### 원본 xlsx 실측 구조 (2026-09-08 확인 — 이 값을 추측으로 바꾸지 마라)

`data/raw/D1_HAZOP_워크시트.xlsx` 를 openpyxl 로 읽은 결과다.

| 항목 | 실측값 |
|---|---|
| 시트 3개 | `HAZOP워크시트`(37행×12열) · `평가기준`(18행×3열) · `스크리닝`(24행×6열) |
| 병합 셀 | **0개** (세 시트 모두) |
| 데이터 행 구성 | 1행 헤더 + 2~35행 데이터 **34건** + 36행 **빈 행** + 37행 **범례 텍스트**(A열 1칸) |
| 헤더 12열 | `No · 노드 · 가이드워드 · 이탈 · 원인 · 결과 · 기존 안전장치(Before) · S(1-5) · F(1-5) · 위험도 · 권고 · 시나리오 연계` |
| 노드 열(B) | `"N1 벙커링선 매니폴드"` — 골드 JSON 의 `node` + `node_meta.equipment[0]` 이 **결합**된 형태 |
| 가이드워드 열(C) | `"No (유량)"` — `guideword` + `parameter` 가 **결합**된 형태 |
| 위험도 열(J) | 하드코딩이 아니라 **수식** `=H2*I2`, `=H3*I3` … (행마다) |
| 리스트 열(E·F·G·K) | 여러 항목을 `·` 로 이어 붙인 단일 문자열 |
| 열 너비 | A 4.5 · B 17 · C 15 · D 20 · E 22 · F 24 · G 17 · H 6 · **I 미지정(기본)** · J 7 · K 30 · L 10 |
| `평가기준` 시트 | 3열 `구분 / 등급 / 정의`, `S 강도` 5행 + `F 빈도` 5행 + 위험도 구간 |
| `스크리닝` 시트 | 5×5 매트릭스, 셀이 `COUNTIFS(HAZOP워크시트!…)` 수식 |

**PRD R10 해소**: "전략서 34 vs 원본 시트 36 데이터행" 불일치의 정체는 빈 행 1 + 범례 행 1이었다.
유효 이탈은 **34건**이 맞다. requirements 에 이 사실을 근거로 적고, 다른 숫자를 쓰지 마라.

주의: PRD §5 FR-07 과 `domain.md` §3 은 시트를 `HAZOP워크시트` + `근거` + `신뢰도` 로만 서술하고
**`평가기준`·`스크리닝` 시트를 언급하지 않는다.** 두 시트를 생성물에 포함할지 requirements 에서
명시적으로 결정하라. 포함하지 않으면 "원본과 동일한 양식"이라는 표현을 쓸 수 없다.

### requirements.md 에 반드시 들어갈 것

1. **xlsx 내보내기** (`core/export/xlsx.py`)
   - 위 12열을 **같은 순서·같은 헤더 문자열**로 쓴다.
   - 노드 열·가이드워드 열은 위 결합 규칙으로 재조립한다. 리스트 필드는 `·` 로 잇는다.
   - **위험도(J) 는 값이 아니라 수식** `=H{row}*I{row}` 로 쓴다(PRD FR-07 명시 요구).
     `DeviationRecord.risk_score` 값을 셀에 넣지 마라 — 그러면 원본 양식과 달라진다.
   - 열 너비를 위 실측표대로 설정한다.
   - `equipment` 가 비었거나 2개 이상일 때의 노드 열 표기 규칙을 정하라(실측 골드셋은 전부 1개다).

2. **`근거` 시트** — 이탈 No ↔ `{source_id, doc_title, locator, quote}`.
   **⚠ 현 시점에는 항상 비어 있다.** FR-03 이 산출하는 `evidence[]` 는 빈 배열 고정이고
   근거 인용은 FR-04(`evidence-citation`) 소관이다. 시트는 헤더까지 만들되, 데이터가 0행일 때
   "FR-04 미완료로 비어 있음"을 시트 안에 표기할지 requirements 에서 정하라.

3. **`신뢰도` 시트** — 이탈 No ↔ `confidence` + 사유.
   **⚠ 현 시점에는 전 행이 `inferred` 한 값뿐이다.** 등급 판정은 FR-06 소관이다.
   빈 시트가 아니라 단일값 시트라는 점을 수용 기준에 적어라.

4. **신뢰도 리포트 json** (`core/export/report.py`) — PRD FR-07 세 번째 산출물.
   `confidence` 분포·근거 첨부율·매트릭스 커버리지를 담는다. 지금 산출 가능한 값만 넣고,
   FR-04·FR-06 이 채울 자리는 `null` 로 남겨라(0 으로 채우지 마라 — 0 은 측정 결과처럼 읽힌다).

5. **LOPA 초안 md** (`core/export/lopa.py`) — **여기가 이 spec 의 함정이다. 아래를 반드시 읽어라.**

   형식 준용 대상인 `LOPA_S1_C1.md`(NH3 QRA 프로젝트, 75줄)의 실제 구성은
   `IE 빈도(/yr) → 조건수정자 → TMEL → IPL별 PFD → 요구 RRF·SIL 산정 → 감도` 이며,
   **문헌 인용(L-01·L-19, Purple Book, IEC 61511)이 각 숫자마다 붙는 정량 문서**다.

   그런데 이 프로젝트가 지금 가진 것은 **정성 등급 S·F(1~5)뿐**이다. 그리고
   `.kiro/steering/domain.md` §4.3 주석은 이렇게 못 박고 있다:

   > "스크리닝용 정성 등급이다. 정량 빈도·확률은 Phase 2 FTA·ETA에서 문헌치로 산정하며
   >  스크리닝 F등급과 혼용하지 않는다."

   따라서 **S×F 위험도에서 IE 빈도(/yr)나 PFD 를 유도하는 요구사항을 쓰면 안 된다.**
   그것은 steering 이 명시적으로 금지한 혼용이며, 만들어 낸 숫자가 곧 환각이다(PRD NFR-03).

   세 가지 안 중 하나를 requirements 에서 **명시적으로 선택**하고 그 이유를 적어라:

   - **A안(권고) — 정량 자리표시자**: 위험도 상위 N개 이탈에 대해 시나리오·IE 후보·IPL 후보를
     **서술만** 생성하고, `IEF`·`PFD`·`TMEL`·`RRF` 는 `TBD (문헌 근거 필요 — FR-04/FR-05)` 로
     명시적으로 비운다. 문서 머리에 "정성 스크리닝 기반 초안이며 정량값은 미산정"을 박는다.
   - **B안 — LOPA 를 FR-07 에서 제외**하고 FR-05(고장률 tool) 완료 후로 미룬다.
     PRD FR-07 문면과 어긋나므로 PRD 개정이 필요하다.
   - **C안 — S·F 에서 정량값을 유도한다. 금지. 선택지로 적어 두었을 뿐이다.**

   IPL 후보는 **레코드의 `safeguards_before` 와 `recommendations` 에 실제로 적힌 것만** 나열한다.
   IPL 3원칙(독립성·유효성·감사가능성) 충족 여부는 판정하지 말고 "미판정"으로 둔다.

6. **골든 파일 스냅샷 시험** — PRD FR-07 완료 조건.
   생성 xlsx 를 openpyxl 로 재로딩해 헤더 12열·시트 이름·수식 문자열·행 수를 대조한다.
   바이너리 비교는 하지 마라(openpyxl 버전에 따라 바이트가 달라진다).

7. **오프라인·재현성**: 시각(timestamp)·UUID 처럼 실행마다 바뀌는 값을 산출물에 넣으려면
   주입 가능한 인자로 두어라. 그러지 않으면 스냅샷 시험이 매번 깨진다.

### 완료 조건 (PRD FR-07 그대로)

- 생성 xlsx 를 openpyxl 로 재로딩 시 스키마 일치, 골든 파일 스냅샷 테스트 통과.
- 골드셋 34건을 입력해도, FR-03 생성 결과를 입력해도 같은 함수로 내보내진다.
- `pytest -m "not live"` 가 자격증명 없이 통과.

### 이 spec 에 넣지 말 것 (다른 spec 소관)

- 근거 검색·인용 생성 → FR-04 `evidence-citation`
- 신뢰도 **판정** → FR-06 `self-verification` (이 spec 은 판정 결과를 **표시**만 한다)
- recall·지표 계산 → FR-08 `evaluation-harness`
- API 응답·다운로드 엔드포인트 → FR-09 / UI → FR-10
- 원본 xlsx 수정 — `data/raw/` 는 읽기 전용이다(CLAUDE.md 불변규칙 2)

## 붙여넣기 끝

---

## Kiro 산출 후 확인할 것

1. `tasks.md` 태스크가 6개 이하인가.
2. 위험도 열이 **수식** `=H*I` 로 쓰이는가(값 하드코딩이 아닌가).
3. LOPA 정량값 처리가 A/B/C 중 무엇으로 결정됐는가. **C안이면 반려**한다.
4. `근거`·`신뢰도` 시트가 "현 시점에는 비었거나 단일값"이라는 사실을 수용 기준에 적었는가.
5. `core/llm` 을 임포트하는 태스크가 섞이지 않았는가(이 spec 은 LLM 무관).
6. 34 를 정본으로 썼는가(36 이 남아 있으면 실측과 어긋난다).

## 부수 작업 (spec 과 별개, 사용자 확인 필요)

- `LOPA_S1_C1.md` 는 이 저장소에 **없다**. 실제 경로는
  `C:\Users\user\Desktop\공모전\위험성평가경진대회\NH3-STS-QRA\08_bowtie_lopa\LOPA_S1_C1.md` 다.
  형식 참조용으로 `data/` 에 복사한다면 `data/README.md` 에 출처를 기재해야 한다
  (CLAUDE.md 불변규칙 1 — 출처·라이선스가 적힌 데이터만 사용).
  본인 저작물이지만 별개 프로젝트 산출물이므로 출처 표기가 필요하다.
- PRD §6 의 spec 목록·상한(6개)을 갱신할지 결정(위 "먼저 결정할 것 ①").
- PRD §9 R10(골드셋 34 vs 36)은 이번 실측으로 해소됐다 — 닫아도 된다.
