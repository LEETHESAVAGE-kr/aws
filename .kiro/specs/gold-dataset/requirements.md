# Requirements — gold-dataset

spec: `gold-dataset`  
대응 FR: PRD §5 FR-01  
버전: 1.0 · 작성 2026-09-04  
상위 문서: `PRD.md` §5 FR-01, §3.1

---

## 1. 목적

전문가 HAZOP 워크시트 xlsx를 기계 판독 가능한 JSON 레코드로 변환하고, 노드 단위 홀드아웃 분할 파일을 생성한다. 이 골드셋은 이탈 생성 루프(FR-03)의 프롬프트 튜닝 기준과 평가 하네스(FR-08)의 정답 레이블로 사용된다.

---

## 2. 요구사항 (EARS 형식)

### REQ-01 · xlsx 입력 경로와 시트 지정

**WHEN** `build_gold.py`가 CLI 인자 `--input <path>`, `--sheet <name>` 을 받으면,  
**THE SYSTEM SHALL** 해당 경로의 xlsx 파일에서 지정된 시트를 읽는다.

**수용 기준 (AC-01)**
- `--input` 인자 없이 실행하면 `argparse` 오류가 발생하고 종료 코드 2를 반환한다.
- 존재하지 않는 파일 경로를 지정하면 `FileNotFoundError` 메시지를 출력하고 종료 코드 1을 반환한다.
- 존재하지 않는 시트 이름을 지정하면 `ValueError: sheet '<name>' not found` 메시지를 출력하고 종료 코드 1을 반환한다.
- 기본값: `--input data/raw/D1_HAZOP_워크시트.xlsx`, `--sheet HAZOP워크시트`.

---

### REQ-02 · 12열 컬럼 매핑

**WHEN** 지정 시트를 읽으면,  
**THE SYSTEM SHALL** 아래 12열을 순서가 아닌 **헤더 이름**으로 매핑한다.

| 열 인덱스(0-based) | 헤더 | JSON 필드 |
|---|---|---|
| 0 | `No` | `row_no` (int) |
| 1 | `노드` | `node_raw` (str) |
| 2 | `가이드워드` | `guideword_raw` (str) |
| 3 | `이탈` | `deviation` (str) |
| 4 | `원인` | `causes_raw` (str) |
| 5 | `결과` | `consequences_raw` (str) |
| 6 | `기존 안전장치(Before)` | `safeguards_raw` (str) |
| 7 | `S(1-5)` | `severity` (int) |
| 8 | `F(1-5)` | `frequency` (int) |
| 9 | `위험도` | `risk_score_raw` (int\|str) |
| 10 | `권고` | `recommendations_raw` (str) |
| 11 | `시나리오 연계` | `scenario` (str\|null) |

**수용 기준 (AC-02)**
- 12개 헤더가 모두 존재하지 않으면 `ValueError: missing columns: [<names>]` 를 출력하고 종료 코드 1을 반환한다.
- 헤더 매핑은 `strip()` 후 비교하므로 선행·후행 공백은 무시된다.
- 열 순서가 달라도 정상 동작한다 (`pytest tests/test_gold.py::test_column_order_invariant` 통과).

---

### REQ-03 · 출력 JSON 레코드 스키마

**WHEN** xlsx 행을 처리하면,  
**THE SYSTEM SHALL** 각 유효 행을 아래 스키마를 만족하는 JSON 오브젝트로 변환하고 배열로 직렬화한다.

```jsonc
{
  "id": "nh3-001",              // str, "<prefix>-<row_no 3자리 zero-pad>"
  "node": "N1",                 // str, 노드 식별자 (REQ-05 참조)
  "node_meta": {                // 노드별 1회 계산, 같은 노드 행은 동일 객체 공유
    "substance": "NH3",         // str
    "phase": "liquid",          // str: "liquid" | "gas" | "liquid/gas" | "unknown"
    "P_kPag": null,             // float | null  (운전 압력, kPag)
    "T_degC": null,             // float | null  (운전 온도, °C)
    "equipment": [],            // list[str]
    "safeguards": []            // list[str]  (노드 수준 기존 안전장치)
  },
  "guideword": "More",          // str, REQ-04 분해 결과
  "parameter": "압력",           // str, REQ-04 분해 결과
  "deviation": "운전 압력 초과",  // str
  "causes": ["...", "..."],     // list[str], REQ-06 분해 결과
  "consequences": ["..."],      // list[str], REQ-06 분해 결과
  "safeguards_before": ["..."], // list[str], REQ-06 분해 결과
  "S": 4,                       // int 1-5
  "F": 3,                       // int 1-5
  "risk_score": 12,             // int = S × F  (REQ-07 검증)
  "recommendations": ["..."],   // list[str], REQ-06 분해 결과
  "scenario": "S1"              // str | null
}
```

**수용 기준 (AC-03)**
- 출력 파일은 `data/gold/hazop_nh3.json` 에 UTF-8 BOM 없이 저장된다.
- JSON 배열의 길이는 원본 시트의 유효 데이터 행 수(헤더 제외, 공백 행 제외)와 같다 (`pytest tests/test_gold.py::test_record_count` 통과).
- 모든 레코드가 `schemas/gold_record.schema.json`에 정의된 JSON Schema(draft-07)를 통과한다 (`pytest tests/test_gold.py::test_schema_valid` 통과).
- `id` 필드는 배열 내에서 유일하다.

---

### REQ-04 · 가이드워드 문자열 분해

**WHEN** `guideword_raw` 셀을 처리하면,  
**THE SYSTEM SHALL** 다음 규칙을 순서대로 적용하여 `guideword`와 `parameter`를 분리한다.

분해 규칙:
1. 셀 값을 `strip()` 한다.
2. 정규식 `^(?P<gw>[^(（]+)\s*[(\（](?P<param>[^)）]+)[)）]$` 로 매칭을 시도한다.
   - 매칭 성공: `guideword = gw.strip()`, `parameter = param.strip()`.
3. 매칭 실패 시, 구분자 없이 가이드워드만 있는 것으로 간주한다.
   - `guideword = strip된 값 전체`, `parameter = ""` (빈 문자열).
4. `guideword` 는 정규화 테이블(REQ-04-T)에 따라 표준 영문으로 변환한다.

**REQ-04-T · 가이드워드 정규화 테이블**

| 원본(한글/혼용 포함) | 표준 `guideword` 값 |
|---|---|
| `No`, `없음`, `없는` | `No` |
| `More`, `고`, `높은`, `증가`, `과다` | `More` |
| `Less`, `저`, `낮은`, `감소`, `부족` | `Less` |
| `Reverse`, `역`, `역방향`, `반대` | `Reverse` |
| `Other than`, `이외`, `다른` | `Other than` |
| `Part of`, `일부` | `Part of` |
| `As well as`, `추가`, `이외에도` | `As well as` |

정규화 테이블에 없는 값은 원본 문자열을 그대로 사용하고 표준 `guideword` 필드에 저장한다.

**수용 기준 (AC-04)**
- `"More (압력)"` → `{"guideword": "More", "parameter": "압력"}` (`pytest tests/test_gold.py::test_guideword_split` 통과).
- `"Less(유량)"` (공백 없음) → `{"guideword": "Less", "parameter": "유량"}`.
- `"Reverse"` (괄호 없음) → `{"guideword": "Reverse", "parameter": ""}`.
- `"고(온도)"` → `{"guideword": "More", "parameter": "온도"}` (정규화 적용).
- 전체 골드셋 변환 후 `guideword` 값이 빈 문자열인 레코드가 0개 이다.

---

### REQ-05 · 노드 식별자 추출

**WHEN** `node_raw` 셀을 처리하면,  
**THE SYSTEM SHALL** 노드 식별자와 노드 메타데이터를 추출한다.

추출 규칙:
1. `node_raw` 셀이 비어 있으면(병합 셀) 직전 유효 행의 값을 계승한다(forward-fill).
2. 정규식 `^(N\d+)` 로 노드 코드를 추출한다. 매칭 실패 시 `node = "UNKNOWN"` 으로 설정하고 경고를 로그로 출력한다.
3. `node_meta` 는 동일 `node` 코드의 첫 번째 행에서 1회 파싱한다. 이후 행은 같은 객체를 재사용한다.
4. `node_meta` 내 `substance`, `phase`, `P_kPag`, `T_degC`, `equipment`, `safeguards` 는 `node_raw` 셀 텍스트에서 패턴 매칭으로 파싱하거나, 파싱 불가 시 `null`/빈 배열로 남긴다.

**수용 기준 (AC-05)**
- 병합 셀로 인해 `node_raw` 가 비어 있는 행의 `node` 필드가 올바른 값으로 채워진다 (`pytest tests/test_gold.py::test_node_forwardfill` 통과).
- 전체 골드셋에서 `node = "UNKNOWN"` 레코드가 0개 이다(원본 데이터가 정상인 경우).
- `node_meta` 는 같은 노드의 모든 레코드에서 동일한 객체(값 일치)이다.

---

### REQ-06 · 다중값 셀 분해 (원인·결과·안전장치·권고)

**WHEN** `causes_raw`, `consequences_raw`, `safeguards_raw`, `recommendations_raw` 셀을 처리하면,  
**THE SYSTEM SHALL** 아래 구분자 우선순위로 문자열을 분해하여 문자열 배열로 변환한다.

구분자 우선순위:
1. 줄바꿈 문자 `\n` (엑셀 셀 내 줄바꿈)
2. 번호 패턴 `^\s*\d+[.)]\s*` (줄 선두의 `1.`, `2)` 등)
3. 세미콜론 `;`
4. 위 구분자 없으면 셀 전체를 요소 1개로 처리

각 분해 항목은 `strip()` 하고, 빈 문자열은 제거한다.

**수용 기준 (AC-06)**
- `"1. 압력 상승\n2. 배관 파열"` → `["압력 상승", "배관 파열"]` (번호 제거, 줄바꿈 분해).
- `"PSV 설치; 압력계"` → `["PSV 설치", "압력계"]`.
- 분해 후 배열이 비어 있는 필드는 `[]` (빈 배열)로 저장된다 (null 허용 안 함).
- `causes` 배열이 비어 있는 레코드 수는 경고 로그에 기록된다.

---

### REQ-07 · 결측 처리 및 데이터 정합성 검증

**WHEN** 행 변환이 완료되면,  
**THE SYSTEM SHALL** 아래 규칙으로 결측과 이상값을 처리한다.

| 필드 | 결측/이상 조건 | 처리 |
|---|---|---|
| `deviation` | 빈 문자열 | 해당 행을 건너뛰고 경고 로그 기록 |
| `S`, `F` | 1–5 범위 밖 정수 또는 비정수 | `null` 로 저장, 경고 로그 기록 |
| `risk_score` | 셀 값 ≠ `S × F` (둘 다 유효한 경우) | 셀 값 무시, `S × F` 로 재계산하고 경고 로그 기록 |
| `scenario` | 빈 셀 | `null` |
| `guideword_raw` | 빈 셀 | 해당 행을 건너뛰고 경고 로그 기록 |

**수용 기준 (AC-07)**
- 정상 원본 파일 변환 후 `deviation` 이 빈 레코드가 0개 이다.
- `S` 또는 `F` 가 `null` 인 레코드 수가 변환 종료 시 표준 출력에 출력된다.
- `risk_score = S × F` 조건이 모든 레코드(S, F 모두 유효)에서 성립한다 (`pytest tests/test_gold.py::test_risk_score` 통과).
- 의도적으로 S=6을 삽입한 fixture에서 해당 필드가 `null` 로 저장된다 (`pytest tests/test_gold.py::test_invalid_sf_to_null` 통과).

---

### REQ-08 · 노드 단위 홀드아웃 분할 파일 생성

**WHEN** `--split` 플래그가 `node` 이면,  
**THE SYSTEM SHALL** 노드 코드 기준으로 훈련/평가 세트를 분리한다.

분할 규칙:
1. `--tune-nodes <N1,N2,...>` 로 프롬프트 튜닝용 노드를 명시한다. 기본값: 원본 노드 목록 중 사전순 첫 번째 노드.
2. 튜닝용 노드 레코드 → `data/gold/hazop_nh3_tune.json`
3. 나머지 노드 레코드 → `data/gold/hazop_nh3_eval.json`
4. 전체 레코드는 `data/gold/hazop_nh3.json` (분할 전과 동일)

**WHEN** `--split` 플래그가 `stratified` 이면,  
**THE SYSTEM SHALL** 고유 노드 수가 홀드아웃에 충분하지 않다고 판단하여 이탈 단위 stratified 70/30 분할을 수행한다.

- Stratified 키: `guideword`.
- 난수 시드: `--seed` 인자, 기본값 42.
- 출력: `data/gold/hazop_nh3_tune.json` (70%) + `data/gold/hazop_nh3_eval.json` (30%).
- 분할 방식은 `data/gold/split_config.json` 에 기록한다.

**수용 기준 (AC-08)**
- `--split node --tune-nodes N1` 실행 후 `hazop_nh3_tune.json` 의 모든 레코드 `node` 가 `"N1"` 이다 (`pytest tests/test_gold.py::test_node_split` 통과).
- `hazop_nh3_tune.json` 과 `hazop_nh3_eval.json` 의 레코드 수 합이 `hazop_nh3.json` 의 레코드 수와 같다.
- `--split stratified --seed 42` 를 두 번 실행하면 동일한 분할 결과가 생성된다 (`pytest tests/test_gold.py::test_stratified_reproducible` 통과).
- `split_config.json` 에 `split_type`, `tune_nodes`(또는 `seed`), `tune_count`, `eval_count`, `timestamp` 필드가 포함된다.

---

### REQ-09 · CLI 실행 및 종료 코드

**WHEN** 모든 변환·분할이 정상 완료되면,  
**THE SYSTEM SHALL** 아래 요약을 표준 출력에 출력하고 종료 코드 0으로 종료한다.

```
[build_gold] 완료: 34 레코드 | 노드: N1, N2, N3 | null S/F: 0 | 건너뜀: 0
  → data/gold/hazop_nh3.json
  → data/gold/hazop_nh3_tune.json (N1, 24 레코드)
  → data/gold/hazop_nh3_eval.json (N2, N3, 10 레코드)
```

**수용 기준 (AC-09)**
- 정상 실행 시 종료 코드가 0이다.
- 요약 출력에 레코드 수·노드 목록·null 필드 수·건너뜀 행 수가 포함된다.
- `--dry-run` 플래그 시 파일을 쓰지 않고 요약만 출력하고 종료 코드 0으로 종료한다.

---

## 3. 비기능 요구사항 (이 spec 범위)

| ID | 내용 |
|---|---|
| NFR-G01 | `ruff check tools/build_gold.py` 경고 0개 |
| NFR-G02 | `mypy --strict tools/build_gold.py` 통과 (타입 힌트 완전) |
| NFR-G03 | 36행 xlsx 처리 시간 ≤ 5초 (로컬 실행 기준) |
| NFR-G04 | 출력 JSON은 UTF-8, 들여쓰기 2칸, 한글 non-ASCII 유지 (`ensure_ascii=False`) |
| NFR-G05 | 원본 xlsx 경로는 `data/raw/` 하위에만 허용, 외부 경로 사용 시 경고 출력 |

---

## 4. 용어 정의

| 용어 | 정의 |
|---|---|
| 유효 데이터 행 | 헤더 행과 완전 공백 행을 제외한 행 |
| 가이드워드 | HAZOP 방법론에서 공정 변수 이탈 방향을 나타내는 표준 단어 (No, More, Less, Reverse, Other than, Part of, As well as) |
| 파라미터 | 가이드워드가 적용되는 공정 변수 (압력, 유량, 온도, 조성, 준위 등) |
| 이탈 | 가이드워드 + 파라미터 조합으로 정의되는 정상 운전 조건에서의 벗어남 |
| 홀드아웃 | 프롬프트 튜닝에 사용하지 않고 평가에만 사용하는 데이터 세트 |
| 골드셋 | 전문가가 작성한 정답 HAZOP 레코드 모음 |
