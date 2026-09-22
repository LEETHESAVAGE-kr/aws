# design.md — export-formats
# spec: export-formats · 대응 FR: PRD §5 FR-07
# 생성: 2026-09-11 (손 작성)

## 1. 아키텍처 개요

```
list[DeviationRecord] | list[dict]      (골드셋 JSON 또는 FR-03 생성 결과)
        │
        ▼  normalize_rows()               core/export/rows.py
list[WorksheetRow]   ← 12열 + evidence + confidence 로 평탄화된 불변 행
        │
        ├─ export_xlsx(rows, path)        core/export/xlsx.py   → 시트 5개
        ├─ build_report(rows, …)          core/export/report.py → ConfidenceReport → JSON
        └─ render_lopa(rows, top_n)       core/export/lopa.py   → Markdown 문자열
        │
        ▼  export_all(records, out_dir, generated_at=None, coverage=None)
   out_dir/hazop.xlsx · confidence_report.json · lopa_draft.md
```

의존 방향: `core/export/` → `openpyxl`, 표준 라이브러리. **프로젝트 내부 임포트 없음**
(`core/llm`·`core/agent` 금지 — requirements 범위 절).

---

## 2. 신규 클래스 (3개 상한)

### 2.1 `WorksheetRow` (frozen dataclass) — `rows.py`

```python
@dataclass(frozen=True)
class WorksheetRow:
    no: int                      # 1부터 연번
    node_label: str              # "N1 벙커링선 매니폴드"
    guideword_label: str         # "No (유량)"
    deviation: str
    causes: str                  # "·" 연결
    consequences: str
    safeguards_before: str
    S: int
    F: int
    recommendations: str
    scenario: str
    # 워크시트 밖 정보
    node: str                    # "N1" — 리포트 nodes 집계용
    risk_score: int              # S × F — 리포트·LOPA 정렬용 (셀에는 쓰지 않음)
    evidence: tuple[dict, ...]   # 근거 시트용, FR-04 전에는 ()
    confidence: str | None       # None = 미부여(골드셋)
    causes_list: tuple[str, ...]           # LOPA IE 후보 (원문 리스트)
    safeguards_list: tuple[str, ...]       # LOPA IPL 후보(기존)
    recommendations_list: tuple[str, ...]  # LOPA IPL 후보(권고)
```

`normalize_rows(records) -> list[WorksheetRow]` 가 유일한 생성 지점. `model_dump()` 가 있으면
호출하고, 아니면 `Mapping` 으로 읽는다. `risk_score` 는 입력값이 있어도 `S*F` 로 다시 계산한다
(FR-03 R-05 와 같은 원칙 — 값이 어긋나 있으면 워크시트 수식과 리포트가 불일치하기 때문).

### 2.2 `ConfidenceReport` (pydantic BaseModel) — `report.py`

requirements R-06 의 필드를 그대로 가진다. `model_dump_json(indent=2)` 대신
`json.dumps(model_dump(), ensure_ascii=False, indent=2)` 로 쓴다(한글 키 보존, NFR-07).

### 2.3 (예비) — 사용하지 않음

LOPA 는 함수만으로 충분하다. 클래스 2개로 마감한다.

---

## 3. 파일 구조

```
core/export/
  __init__.py      ← export_all, normalize_rows, export_xlsx, build_report, write_report,
                     render_lopa, write_lopa, WorksheetRow, ConfidenceReport 재수출
  rows.py          ← WorksheetRow, normalize_rows, HEADERS(12), 라벨 조립 규칙
  xlsx.py          ← export_xlsx (시트 5개)
  report.py        ← ConfidenceReport, build_report, write_report
  lopa.py          ← render_lopa, write_lopa
tests/
  test_export.py
  golden/export_gold34.snapshot.json   ← R-09 스냅샷 기대값 (골드셋 34건)
```

---

## 4. xlsx 세부 (`xlsx.py`)

상수(모듈 최상위, 실측값 그대로):

```python
HEADERS = ("No","노드","가이드워드","이탈","원인","결과","기존 안전장치(Before)",
           "S(1-5)","F(1-5)","위험도","권고","시나리오 연계")
COLUMN_WIDTHS = {"A":4.5,"B":17,"C":15,"D":20,"E":22,"F":24,"G":17,"H":6,"J":7,"K":30,"L":10}  # I 없음
HEADER_FILL = "1F4E79"
SHEET_ORDER = ("HAZOP워크시트","평가기준","스크리닝","근거","신뢰도")
```

`HAZOP워크시트`: 행 r(2..N+1)에 12열. `J{r}` = `f"=H{r}*I{r}"`. N+2 빈 행, N+3 A열 범례.
틀 고정 `A2`. 헤더 서식과 본문 서식은 `openpyxl.styles` 로 재현.

`평가기준`: `rating_scale.json` 을 **`export_xlsx(…, rating_scale=…)` 인자로 주입**받는다.
기본값은 `data/gold/rating_scale.json` 을 `Path(__file__)` 체인으로 읽는다(steering §4).
레이아웃은 requirements 실측표.

`스크리닝`: A1 제목, A2 `S＼F`·B2..F2 `F1..F5`, A3..A7 `S5..S1`, 셀 = 
`=COUNTIFS(HAZOP워크시트!$H$2:$H${last},{s},HAZOP워크시트!$I$2:$I${last},{f})`.
N=0 이면 `last=2` 로 두어 수식이 깨지지 않게 한다.

`근거`: 헤더 5열. 각 row 의 `evidence` 원소마다 `[no, e.get("source_id"), e.get("doc_title"),
e.get("locator"), e.get("quote")]`. 총 0행이면 A2 안내 문구(R-04).

`신뢰도`: 헤더 3열. `CONFIDENCE_REASONS` 사전(R-05 표)으로 표기·사유 결정.

---

## 5. 리포트 세부 (`report.py`)

```python
def build_report(rows, *, generated_at=None, coverage=None) -> ConfidenceReport
```

- `risk_distribution` 구간 경계는 `rating_scale.json` 의 `risk_bands[].range` 를 파싱하지 않고
  **상수** `(15, 25)="높음", (8, 14)="중간(ALARP)", (1, 7)="낮음"` 로 둔다. 근거: 등급 구간은
  `domain.md` §4.3 이 정의한 방법론 값이며(가이드워드와 같은 성격) 데이터가 아니다.
  `rating_scale.json` 의 문자열과 다르면 시험이 잡는다(test_export 가 두 값을 대조).
- `evidence_attachment_rate`: `attached = sum(1 for r if r.evidence)`; `attached == 0` → `None`,
  아니면 `attached / len(rows)` (소수 4자리 반올림).
- `pending`: `None` 인 필드마다 담당 FR 을 적는다. 값이 채워지면 키가 사라진다.

---

## 6. LOPA 세부 (`lopa.py`)

```python
def render_lopa(rows, *, top_n=5, generated_at=None) -> str
```

정렬: `sorted(rows, key=lambda r: (-r.risk_score, r.no))[:top_n]`.

문서 골격(고정 문자열은 모듈 상수 `_DISCLAIMER`, `_TBD`):

```
# LOPA 초안 — 위험도 상위 {n}건
> 정성 스크리닝(S×F) 기반 초안. IEF·PFD·TMEL·RRF 등 정량값은 미산정이며 …
생성 시각: {generated_at or "미기록"} · 형식: NH3 QRA LOPA_S1_C1.md 준용(정량 절은 자리표시자)

## 시나리오 {k}: No.{no} {guideword_label} — {deviation}
| 항목 | 값 |            ← 노드·가이드워드·S·F·위험도·판정구간
### 시나리오 서술         ← "원인({causes}) → 이탈({deviation}) → 결과({consequences})"
### IE(개시사건) 후보      ← causes_list 각 항목 "- {c} — IEF: TBD (…)"
### IPL(독립방호계층) 후보 ← safeguards_list "[기존]" / recommendations_list "[권고]" 각 항목
                             "- [기존] {s} — PFD: TBD (…) · 3원칙(독립성·유효성·감사가능성): 미판정"
### 정량 산정              ← 6행 표, 값 전부 _TBD
```

`_TBD = "TBD (문헌 근거 필요 — FR-04/FR-05)"`. 판정 구간은 `report.py` 의 상수를 재사용한다
(순환 없음: `lopa.py` → `report.py` → `rows.py`).

---

## 7. `export_all` (`__init__.py`)

```python
def export_all(records, out_dir: Path, *, generated_at=None, coverage=None, top_n=5) -> dict[str, Path]
```

`out_dir` 를 만들고 `hazop.xlsx`·`confidence_report.json`·`lopa_draft.md` 를 쓴 뒤 경로 사전을
돌려준다. `results/` 아래를 쓰는 것은 호출자 책임(CLAUDE.md 불변규칙 2·6).

---

## 8. 골든 스냅샷 (`tests/golden/export_gold34.snapshot.json`)

xlsx 를 재로딩해 뽑은 **구조 요약**을 저장한다(바이너리 아님):

```json
{
  "sheets": ["HAZOP워크시트", "평가기준", "스크리닝", "근거", "신뢰도"],
  "worksheet": {"max_row": 37, "max_column": 12, "headers": [...12], "widths": {...11},
                "risk_formulas": ["=H2*I2", …, "=H35*I35"], "freeze": "A2",
                "row2": [...12 values], "row35": [...12 values]},
  "rating": {"max_row": 18, "max_column": 3},
  "screening": {"b3": "=COUNTIFS(HAZOP워크시트!$H$2:$H$35,5,HAZOP워크시트!$I$2:$I$35,1)"},
  "evidence": {"max_row": 2}, "confidence": {"max_row": 35, "values": ["미부여"]},
  "report": {...ConfidenceReport dict (generated_at null)}
}
```

시험은 같은 요약을 다시 만들어 `==` 비교한다. 스냅샷 갱신은 `UPDATE_SNAPSHOT=1` 환경변수로만.
