# Design — gold-dataset

spec: `gold-dataset`  
버전: 1.0 · 작성 2026-09-04  
상위 문서: `requirements.md` (REQ-01~09), `PRD.md` §3.1, §5 FR-01

---

## 1. 전체 데이터 흐름

```
┌─────────────────────────────────────────────────────────────────┐
│  CLI: tools/build_gold.py                                       │
│                                                                 │
│  --input <xlsx>  --sheet <name>                                 │
│  --split {node|stratified}  --tune-nodes N1  --seed 42          │
│  --output-dir data/gold/  --dry-run                             │
└───────────────────────────┬─────────────────────────────────────┘
                            │ 1. 경로 검증 & 파일 로드
                            ▼
┌───────────────────────────────────────┐
│  XlsxLoader                           │
│  openpyxl read_only=True              │
│  → raw DataFrame (12열)               │
└───────────────┬───────────────────────┘
                │ 2. 컬럼 매핑 검증
                ▼
┌───────────────────────────────────────┐
│  ColumnMapper                         │
│  헤더 strip → 12열 존재 확인           │
│  → 표준 필드명으로 rename              │
└───────────────┬───────────────────────┘
                │ 3. 행 단위 변환
                ▼
┌───────────────────────────────────────┐
│  RowTransformer                       │
│  ├─ NodeParser      (REQ-05)          │
│  │   forward-fill, N\d+ 추출          │
│  ├─ GuidewordParser (REQ-04)          │
│  │   정규식 분해 → 정규화 테이블       │
│  ├─ MultiValueParser (REQ-06)         │
│  │   \n / 번호패턴 / ; 분해           │
│  └─ FieldValidator  (REQ-07)          │
│      결측·범위 검증, risk_score 재계산 │
│  → list[GoldRecord]                   │
└───────────────┬───────────────────────┘
                │ 4. 전체 검증
                ▼
┌───────────────────────────────────────┐
│  DatasetValidator                     │
│  JSON Schema 검증 (draft-07)          │
│  id 유일성, guideword 공백 0건 확인   │
└───────────────┬───────────────────────┘
                │ 5. 분할
                ▼
┌───────────────────────────────────────┐
│  Splitter                             │
│  NodeSplitter   (--split node)        │
│  StratifiedSplitter (--split strat.)  │
│  → tune/eval 인덱스 결정              │
└───────────────┬───────────────────────┘
                │ 6. 직렬화
                ▼
┌───────────────────────────────────────┐
│  JsonWriter                           │
│  hazop_nh3.json                       │
│  hazop_nh3_tune.json                  │
│  hazop_nh3_eval.json                  │
│  split_config.json                    │
└───────────────────────────────────────┘
```

---

## 2. 모듈 구조

```
tools/
└─ build_gold.py          # CLI 진입점, argparse, 오케스트레이션

tools/_gold/              # 내부 패키지 (build_gold.py 에서만 import)
├─ __init__.py
├─ loader.py              # XlsxLoader
├─ mapper.py              # ColumnMapper
├─ parsers.py             # NodeParser, GuidewordParser, MultiValueParser
├─ validator.py           # FieldValidator, DatasetValidator
├─ splitter.py            # NodeSplitter, StratifiedSplitter
├─ writer.py              # JsonWriter
└─ models.py              # GoldRecord, NodeMeta, SplitConfig (dataclass / TypedDict)

schemas/
└─ gold_record.schema.json   # JSON Schema draft-07

data/
├─ raw/                      # 원본 xlsx (git-ignored, README에 취득 방법 기재)
└─ gold/                     # 변환 산출물 (git-tracked)
    ├─ hazop_nh3.json
    ├─ hazop_nh3_tune.json
    ├─ hazop_nh3_eval.json
    └─ split_config.json

tests/
└─ test_gold.py              # pytest 테스트 (fixtures: tests/fixtures/gold/)
    └─ fixtures/gold/
        ├─ sample_valid.xlsx      # 정상 5행 fixture
        ├─ sample_merged.xlsx     # 병합 셀 fixture (노드 forward-fill 검증)
        ├─ sample_bad_sf.xlsx     # S=6 삽입 fixture (이상값 검증)
        └─ expected_valid.json    # sample_valid.xlsx 기대 출력
```

---

## 3. 핵심 데이터 모델

### 3.1 `NodeMeta`

```python
@dataclass
class NodeMeta:
    substance: str                  # 물질명 또는 CAS
    phase: str                      # "liquid" | "gas" | "liquid/gas" | "unknown"
    P_kPag: float | None            # 운전 압력 (kPag)
    T_degC: float | None            # 운전 온도 (°C)
    equipment: list[str]            # 설비 목록
    safeguards: list[str]           # 노드 수준 기존 안전장치
```

`node_raw` 셀에서 파싱되는 필드는 원본 워크시트 표현 방식에 따라 파싱 불가일 수 있으므로 모두 Optional 처리. 파싱 불가 시 기본값 사용 (`"unknown"`, `None`, `[]`).

### 3.2 `GoldRecord`

```python
@dataclass
class GoldRecord:
    id: str                         # "nh3-001"
    node: str                       # "N1"
    node_meta: NodeMeta
    guideword: str                  # 정규화된 영문 가이드워드
    parameter: str                  # 파라미터 (빈 문자열 허용)
    deviation: str
    causes: list[str]
    consequences: list[str]
    safeguards_before: list[str]
    S: int | None                   # 1-5, 이상값은 None
    F: int | None                   # 1-5, 이상값은 None
    risk_score: int | None          # S*F, 어느 하나 None이면 None
    recommendations: list[str]
    scenario: str | None
```

### 3.3 `SplitConfig`

```python
@dataclass
class SplitConfig:
    split_type: str                 # "node" | "stratified"
    tune_nodes: list[str] | None    # node 분할 시
    seed: int | None                # stratified 분할 시
    tune_count: int
    eval_count: int
    timestamp: str                  # ISO 8601
```

---

## 4. 컴포넌트 상세 설계

### 4.1 `XlsxLoader`

```python
class XlsxLoader:
    def load(self, path: Path, sheet: str) -> list[dict[str, Any]]:
        ...
```

- `openpyxl.load_workbook(path, read_only=True, data_only=True)` 사용.
- `data_only=True`: 수식 셀을 값으로 읽는다 (`risk_score` 셀이 `=H*I` 수식인 경우).
- 헤더 행(row 1)을 키로 사용하여 딕셔너리 리스트 반환.
- 완전 공백 행(모든 셀이 None 또는 빈 문자열) 제거.

### 4.2 `ColumnMapper`

```python
REQUIRED_COLUMNS: Final = [
    "No", "노드", "가이드워드", "이탈",
    "원인", "결과", "기존 안전장치(Before)",
    "S(1-5)", "F(1-5)", "위험도", "권고", "시나리오 연계",
]

class ColumnMapper:
    def validate_and_rename(self, rows: list[dict]) -> list[dict]:
        # 헤더 strip 후 REQUIRED_COLUMNS 존재 확인
        # 표준 내부 필드명으로 rename
        ...
```

누락 컬럼이 있으면 즉시 `ValueError` 를 raise하고 누락된 컬럼 이름을 메시지에 포함한다.

### 4.3 `GuidewordParser`

분해 정규식:

```python
_GW_PATTERN = re.compile(
    r"^(?P<gw>[^(（]+)\s*[(\（](?P<param>[^)）]+)[)）]\s*$"
)
```

정규화 테이블은 `dict[str, str]` 로 모듈 상수로 정의한다. 매칭 순서는 정확 일치 우선, 부분 포함 순.

```python
_GW_NORMALIZE: dict[str, str] = {
    "No": "No", "없음": "No", "없는": "No",
    "More": "More", "고": "More", "높은": "More", "증가": "More", "과다": "More",
    "Less": "Less", "저": "Less", "낮은": "Less", "감소": "Less", "부족": "Less",
    "Reverse": "Reverse", "역": "Reverse", "역방향": "Reverse", "반대": "Reverse",
    "Other than": "Other than", "이외": "Other than", "다른": "Other than",
    "Part of": "Part of", "일부": "Part of",
    "As well as": "As well as", "추가": "As well as", "이외에도": "As well as",
}
```

정규화 순서: 정확 일치 → strip 후 정확 일치. 미등록 값은 원본 유지.

### 4.4 `MultiValueParser`

```python
_NUMBERED_LINE = re.compile(r"^\s*\d+[.)]\s*")

class MultiValueParser:
    def parse(self, raw: str | None) -> list[str]:
        if not raw:
            return []
        # 1순위: 줄바꿈 분해
        if "\n" in raw:
            items = raw.split("\n")
        # 2순위: 번호 패턴 (줄 선두)
        elif _NUMBERED_LINE.search(raw):
            items = _NUMBERED_LINE.split(raw)
        # 3순위: 세미콜론
        elif ";" in raw:
            items = raw.split(";")
        else:
            items = [raw]
        # 번호 패턴 제거 + strip + 빈 문자열 제거
        return [_NUMBERED_LINE.sub("", i).strip() for i in items if i.strip()]
```

### 4.5 `NodeParser`

forward-fill 구현:

```python
class NodeParser:
    _current_node: str = "UNKNOWN"
    _node_meta_cache: dict[str, NodeMeta] = {}

    def parse_node(self, raw: str | None) -> tuple[str, NodeMeta]:
        if raw and raw.strip():
            self._current_node = self._extract_code(raw.strip())
            if self._current_node not in self._node_meta_cache:
                self._node_meta_cache[self._current_node] = self._parse_meta(raw)
        return self._current_node, self._node_meta_cache[self._current_node]

    def _extract_code(self, text: str) -> str:
        m = re.match(r"^(N\d+)", text)
        return m.group(1) if m else "UNKNOWN"
```

`NodeMeta` 파싱: `node_raw` 셀의 텍스트 패턴에서 물질명, 상태, 압력·온도 숫자를 추출한다. 패턴이 없으면 기본값을 사용하고 파싱 실패를 DEBUG 레벨로 로깅한다.

### 4.6 `FieldValidator`

```python
def validate_sf(value: Any) -> int | None:
    try:
        v = int(value)
        return v if 1 <= v <= 5 else None
    except (TypeError, ValueError):
        return None

def compute_risk(S: int | None, F: int | None) -> int | None:
    return S * F if S is not None and F is not None else None
```

셀 `risk_score_raw` 와 `S * F` 가 모두 유효하고 불일치하면 `WARNING` 로그를 기록하고 `S * F` 를 채택한다.

### 4.7 `NodeSplitter`

```python
class NodeSplitter:
    def split(
        self,
        records: list[GoldRecord],
        tune_nodes: list[str],
    ) -> tuple[list[GoldRecord], list[GoldRecord]]:
        tune = [r for r in records if r.node in tune_nodes]
        eval_ = [r for r in records if r.node not in tune_nodes]
        return tune, eval_
```

### 4.8 `StratifiedSplitter`

```python
class StratifiedSplitter:
    def split(
        self,
        records: list[GoldRecord],
        seed: int = 42,
        ratio: float = 0.7,
    ) -> tuple[list[GoldRecord], list[GoldRecord]]:
        # guideword 기준 stratified split
        # sklearn.model_selection.train_test_split 사용
        # stratify=[r.guideword for r in records]
        ...
```

`sklearn` 이 없는 환경을 고려하여 fallback 구현(guideword별 그룹 내 무작위 분할)을 제공한다.

---

## 5. JSON Schema (`schemas/gold_record.schema.json`)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "GoldRecord",
  "type": "object",
  "required": [
    "id", "node", "node_meta",
    "guideword", "parameter", "deviation",
    "causes", "consequences", "safeguards_before",
    "S", "F", "risk_score",
    "recommendations", "scenario"
  ],
  "properties": {
    "id":              { "type": "string", "pattern": "^[a-z0-9]+-\\d{3}$" },
    "node":            { "type": "string", "minLength": 1 },
    "node_meta": {
      "type": "object",
      "required": ["substance", "phase", "P_kPag", "T_degC", "equipment", "safeguards"],
      "properties": {
        "substance":  { "type": "string" },
        "phase":      { "type": "string", "enum": ["liquid", "gas", "liquid/gas", "unknown"] },
        "P_kPag":     { "type": ["number", "null"] },
        "T_degC":     { "type": ["number", "null"] },
        "equipment":  { "type": "array", "items": { "type": "string" } },
        "safeguards": { "type": "array", "items": { "type": "string" } }
      },
      "additionalProperties": false
    },
    "guideword":       { "type": "string", "minLength": 1 },
    "parameter":       { "type": "string" },
    "deviation":       { "type": "string", "minLength": 1 },
    "causes":          { "type": "array", "items": { "type": "string" } },
    "consequences":    { "type": "array", "items": { "type": "string" } },
    "safeguards_before": { "type": "array", "items": { "type": "string" } },
    "S":               { "type": ["integer", "null"], "minimum": 1, "maximum": 5 },
    "F":               { "type": ["integer", "null"], "minimum": 1, "maximum": 5 },
    "risk_score":      { "type": ["integer", "null"], "minimum": 1, "maximum": 25 },
    "recommendations": { "type": "array", "items": { "type": "string" } },
    "scenario":        { "type": ["string", "null"] }
  },
  "additionalProperties": false
}
```

---

## 6. 분할 결정 로직

```
build_gold.py 실행
        │
        ├─ --split node (기본)
        │      │
        │      └─ 노드 수 ≥ 2?
        │             ├─ YES → NodeSplitter (tune_nodes 인자 사용)
        │             └─ NO  → 경고 출력, stratified 로 자동 전환
        │                      split_config.json 에 fallback 사유 기록
        │
        └─ --split stratified
               └─ StratifiedSplitter (seed, ratio=0.7)
```

PRD §3.1 원문: "노드 수가 적으면 이탈 단위 stratified 70/30으로 대체하고 README에 명시." 이 로직은 위 결정 트리로 구현된다.

---

## 7. 로깅 설계

```python
import logging
logger = logging.getLogger("build_gold")
```

| 레벨 | 이벤트 |
|---|---|
| `INFO` | 파일 로드 시작/완료, 레코드 수, 분할 결과 |
| `WARNING` | S/F 범위 이상, risk_score 불일치, `node=UNKNOWN`, `causes` 빈 배열, 건너뜀 행 |
| `DEBUG` | 노드 메타 파싱 실패 세부, 각 행 변환 결과 |
| `ERROR` | 파일 없음, 시트 없음, 컬럼 누락 (raise 직전) |

CLI에서 `--verbose` 플래그 시 DEBUG 레벨 활성화.

---

## 8. 의존성

| 패키지 | 용도 | 핀 버전 |
|---|---|---|
| `openpyxl` | xlsx 로드 | `==3.1.5` |
| `jsonschema` | JSON Schema 검증 | `==4.23.0` |
| `scikit-learn` | stratified split (optional) | `==1.5.2` |

`scikit-learn` 은 optional dependency. `pyproject.toml` 의 `[project.optional-dependencies]` `gold` 그룹에 포함. 없을 경우 fallback 구현 사용.

---

## 9. 요구사항 ↔ 설계 추적

| REQ | 구현 컴포넌트 | 비고 |
|---|---|---|
| REQ-01 | `build_gold.py` argparse, `XlsxLoader` | 경로·시트 검증 |
| REQ-02 | `ColumnMapper` | 헤더 strip 매핑 |
| REQ-03 | `GoldRecord`, `JsonWriter`, `gold_record.schema.json` | 스키마 강제 |
| REQ-04 | `GuidewordParser`, `_GW_NORMALIZE` | 정규식 + 정규화 테이블 |
| REQ-05 | `NodeParser` | forward-fill, N\d+ 추출 |
| REQ-06 | `MultiValueParser` | 3단계 구분자 우선순위 |
| REQ-07 | `FieldValidator` | None 처리, risk 재계산 |
| REQ-08 | `NodeSplitter`, `StratifiedSplitter`, `SplitConfig` | 결정 트리 §6 |
| REQ-09 | `build_gold.py` main, `--dry-run` | 요약 출력, 종료 코드 |
