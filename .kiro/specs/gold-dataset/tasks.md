# Tasks — gold-dataset

spec: `gold-dataset`  
버전: 1.0 · 작성 2026-09-04  
상위 문서: `requirements.md`, `design.md`  
구현 담당: Claude Code (`CLAUDE.md` 및 steering 준수)  
커밋 접두어: `spec:gold-dataset T-xx`

완료 조건: 각 태스크의 "검증" 항목이 모두 통과되고 `ruff` · `mypy --strict` 경고 0개.

---

## T-01 · 프로젝트 스캐폴딩 및 의존성 등록

**목적**: 이후 태스크가 의존하는 파일 트리와 패키지 설정을 만든다.

작업:
1. `tools/_gold/__init__.py` 생성 (빈 파일).
2. `tools/_gold/models.py` 생성 — `NodeMeta`, `GoldRecord`, `SplitConfig` dataclass 정의 (`design.md §3` 기준).
3. `schemas/gold_record.schema.json` 생성 — `design.md §5` JSON Schema 그대로 작성.
4. `pyproject.toml` 의 `[project.dependencies]` 에 `openpyxl==3.1.5`, `jsonschema==4.23.0` 추가.
5. `[project.optional-dependencies]` 에 `gold = ["scikit-learn==1.5.2"]` 추가.
6. `data/raw/.gitkeep`, `data/gold/.gitkeep` 생성.
7. `data/README.md` 생성 — 원본 xlsx 취득 방법(공모전 내부 파일, git-ignored 이유) 한 문단 기재.
8. `.gitignore` 에 `data/raw/` 추가 (이미 있으면 확인만).

검증:
- `python -c "from tools._gold.models import GoldRecord"` 오류 없음.
- `schemas/gold_record.schema.json` 이 유효한 JSON임 (`python -m json.tool schemas/gold_record.schema.json`).

---

## T-02 · `XlsxLoader` 구현

**목적**: xlsx 파일을 읽어 raw 딕셔너리 리스트를 반환한다. (REQ-01)

파일: `tools/_gold/loader.py`

작업:
1. `XlsxLoader.load(path: Path, sheet: str) -> list[dict[str, Any]]` 구현.
   - `openpyxl.load_workbook(path, read_only=True, data_only=True)`.
   - 시트 부재 시 `ValueError: sheet '<name>' not found` raise.
   - 헤더 행(row 1)을 키로 사용.
   - 완전 공백 행 제거.
2. `build_gold.py` CLI 스캐폴딩 — argparse (`--input`, `--sheet`, `--output-dir`, `--split`, `--tune-nodes`, `--seed`, `--dry-run`, `--verbose`) 만 구현, 로직은 stub.

검증:
- `pytest tests/test_gold.py::test_loader_missing_file` — `FileNotFoundError`.
- `pytest tests/test_gold.py::test_loader_missing_sheet` — `ValueError`.
- `pytest tests/test_gold.py::test_loader_returns_rows` — `sample_valid.xlsx` 5행 반환.

필요 fixture: `tests/fixtures/gold/sample_valid.xlsx` (5행, 12열 정상 데이터 — T-06에서 작성).

---

## T-03 · `ColumnMapper` 구현

**목적**: 12열 헤더 검증 및 내부 필드명 매핑. (REQ-02)

파일: `tools/_gold/mapper.py`

작업:
1. `REQUIRED_COLUMNS` 상수 정의 (design.md §4.2).
2. `ColumnMapper.validate_and_rename(rows: list[dict]) -> list[dict]` 구현.
   - 헤더 `strip()` 후 `REQUIRED_COLUMNS` 존재 확인.
   - 누락 컬럼 있으면 `ValueError: missing columns: [<names>]` raise.
   - 내부 필드명(`node_raw`, `guideword_raw`, … `scenario`)으로 rename.

검증:
- `pytest tests/test_gold.py::test_column_order_invariant` — 열 순서 바꿔도 정상 매핑.
- `pytest tests/test_gold.py::test_column_missing_raises` — 누락 컬럼 시 `ValueError`.
- `pytest tests/test_gold.py::test_column_strip_whitespace` — 헤더에 공백 있어도 매핑 성공.

---

## T-04 · `GuidewordParser` 구현

**목적**: 가이드워드 문자열 분해 및 정규화. (REQ-04)

파일: `tools/_gold/parsers.py` (이 파일에 T-04·T-05·T-06 파서 모두 구현)

작업:
1. `_GW_PATTERN` 정규식 상수 정의 (design.md §4.3).
2. `_GW_NORMALIZE` 딕셔너리 상수 정의.
3. `GuidewordParser.parse(raw: str | None) -> tuple[str, str]` 구현.
   - 반환값: `(guideword, parameter)`.
   - `raw` 가 None 또는 빈 문자열이면 `("", "")` 반환 (REQ-07에서 행 건너뜀 처리).
   - 정규식 매칭 → 정규화 테이블 적용.
   - 매칭 실패 → 전체 문자열을 guideword로, parameter는 빈 문자열.

검증:
- `pytest tests/test_gold.py::test_guideword_split` — AC-04의 4가지 케이스 모두 통과:
  - `"More (압력)"` → `("More", "압력")`
  - `"Less(유량)"` → `("Less", "유량")`
  - `"Reverse"` → `("Reverse", "")`
  - `"고(온도)"` → `("More", "온도")`
- `pytest tests/test_gold.py::test_guideword_fullwidth_paren` — 전각 괄호 `（온도）` 도 분해 성공.

---

## T-05 · `MultiValueParser` 구현

**목적**: 원인·결과·안전장치·권고 셀의 다중값 분해. (REQ-06)

파일: `tools/_gold/parsers.py` (T-04와 동일 파일)

작업:
1. `_NUMBERED_LINE` 정규식 상수 정의.
2. `MultiValueParser.parse(raw: str | None) -> list[str]` 구현 (design.md §4.4 의사코드 그대로).

검증:
- `pytest tests/test_gold.py::test_multivalue_newline` — `"1. 압력 상승\n2. 배관 파열"` → `["압력 상승", "배관 파열"]`.
- `pytest tests/test_gold.py::test_multivalue_semicolon` — `"PSV 설치; 압력계"` → `["PSV 설치", "압력계"]`.
- `pytest tests/test_gold.py::test_multivalue_single` — 구분자 없는 단일 문자열 → 요소 1개 배열.
- `pytest tests/test_gold.py::test_multivalue_none` — `None` 입력 → `[]`.

---

## T-06 · `NodeParser` 구현 및 테스트 fixture 생성

**목적**: 노드 식별자 forward-fill 및 노드 메타 파싱. (REQ-05)

파일: `tools/_gold/parsers.py` (동일 파일에 추가)

작업:
1. `NodeParser` 클래스 구현 (design.md §4.5).
   - `parse_node(raw: str | None) -> tuple[str, NodeMeta]`.
   - forward-fill: raw가 빈 경우 직전 값 사용.
   - `_extract_code`: `N\d+` 패턴 추출, 실패 시 `"UNKNOWN"` + WARNING 로그.
   - `_parse_meta`: `node_raw` 텍스트에서 `substance`, `phase`, `P_kPag`, `T_degC` 파싱 시도. 파싱 불가 시 기본값.
2. 테스트 fixture 생성:
   - `tests/fixtures/gold/sample_valid.xlsx` — 5행 12열, 정상 데이터, 모든 노드 `N1`, guideword 혼용(한글·영문).
   - `tests/fixtures/gold/sample_merged.xlsx` — 3행, `노드` 열 row 2·3이 빈 셀(병합 시뮬레이션).
   - `tests/fixtures/gold/sample_bad_sf.xlsx` — 3행, row 2의 `S(1-5)` = 6.
   - `tests/fixtures/gold/expected_valid.json` — `sample_valid.xlsx` 의 기대 출력 JSON.

검증:
- `pytest tests/test_gold.py::test_node_forwardfill` — `sample_merged.xlsx` 변환 후 모든 `node` 필드가 `"N1"`.
- `pytest tests/test_gold.py::test_node_unknown_logged` — `N\d+` 미매칭 셀 시 `node="UNKNOWN"` 이고 WARNING 로그 발생.

---

## T-07 · `FieldValidator` 구현

**목적**: S·F 범위 검증, risk_score 재계산, 빈 deviation 건너뜀. (REQ-07)

파일: `tools/_gold/validator.py`

작업:
1. `validate_sf(value: Any) -> int | None` 함수 구현 (design.md §4.6).
2. `compute_risk(S: int | None, F: int | None) -> int | None` 구현.
3. `FieldValidator.validate_row(row: dict) -> dict | None` 구현:
   - `deviation` 빈 문자열 → `None` 반환 (호출자가 건너뜀).
   - `guideword_raw` 빈 문자열 → `None` 반환.
   - `S`, `F` 범위 밖 → `None` 으로 대체 + WARNING 로그.
   - `risk_score` 불일치 → 재계산 + WARNING 로그.

검증:
- `pytest tests/test_gold.py::test_risk_score` — 전체 골드셋(sample_valid) 변환 후 `risk_score == S * F` 성립.
- `pytest tests/test_gold.py::test_invalid_sf_to_null` — `sample_bad_sf.xlsx` 변환 후 S=6 행의 `S` 필드가 `null`.
- `pytest tests/test_gold.py::test_skip_empty_deviation` — deviation 빈 행이 출력에서 제외됨.

---

## T-08 · `DatasetValidator` 구현

**목적**: 전체 레코드 배열의 JSON Schema 검증 및 id 유일성 확인. (REQ-03)

파일: `tools/_gold/validator.py` (T-07과 동일 파일)

작업:
1. `DatasetValidator.validate(records: list[dict], schema_path: Path) -> list[str]` 구현:
   - `jsonschema.validate` 로 각 레코드 검증.
   - 검증 실패 레코드의 `id` 와 오류 메시지를 리스트로 반환.
   - `id` 중복 확인 — 중복 시 오류 리스트에 추가.
2. `id` 생성 로직: `f"nh3-{row_no:03d}"`.

검증:
- `pytest tests/test_gold.py::test_schema_valid` — `sample_valid.xlsx` 변환 결과가 Schema 검증 통과.
- `pytest tests/test_gold.py::test_record_count` — 변환 레코드 수 = 원본 유효 행 수 (5).
- `pytest tests/test_gold.py::test_id_unique` — `id` 중복 없음.

---

## T-09 · `NodeSplitter` / `StratifiedSplitter` 구현

**목적**: 노드 단위 및 stratified 홀드아웃 분할. (REQ-08)

파일: `tools/_gold/splitter.py`

작업:
1. `NodeSplitter.split(records, tune_nodes) -> tuple[list, list]` 구현 (design.md §4.7).
2. `StratifiedSplitter.split(records, seed, ratio) -> tuple[list, list]` 구현 (design.md §4.8).
   - `scikit-learn` 있으면 `train_test_split` 사용.
   - 없으면 fallback: guideword별 그룹 내 `random.Random(seed).shuffle` 후 비율 분할.
3. 분할 결정 트리 함수 `decide_splitter(records, split_mode, tune_nodes, seed) -> tuple[list, list]` 구현 (design.md §6):
   - `split_mode == "node"` 이고 고유 노드 수 ≥ 2 → `NodeSplitter`.
   - `split_mode == "node"` 이고 고유 노드 수 < 2 → WARNING + `StratifiedSplitter` fallback.
   - `split_mode == "stratified"` → `StratifiedSplitter`.
4. `SplitConfig` 인스턴스 생성 로직 포함.

검증:
- `pytest tests/test_gold.py::test_node_split` — `--split node --tune-nodes N1` 후 tune 파일의 모든 `node == "N1"`.
- `pytest tests/test_gold.py::test_split_count_sum` — tune + eval 레코드 수 합 = 전체.
- `pytest tests/test_gold.py::test_stratified_reproducible` — seed=42 두 번 실행 결과 동일.
- `pytest tests/test_gold.py::test_split_config_fields` — `split_config.json` 에 필수 필드 5개 포함.

---

## T-10 · `JsonWriter` 구현

**목적**: GoldRecord 배열을 JSON 파일로 직렬화. (REQ-03, REQ-08, REQ-09)

파일: `tools/_gold/writer.py`

작업:
1. `JsonWriter.write(records: list[dict], path: Path, dry_run: bool = False) -> None` 구현:
   - `dry_run=True` 시 파일 미생성, INFO 로그만 출력.
   - `json.dump(..., ensure_ascii=False, indent=2)`, UTF-8 BOM 없이 저장.
2. `SplitConfig` 를 `split_config.json` 으로 직렬화하는 `write_split_config` 함수 구현.

검증:
- `pytest tests/test_gold.py::test_writer_utf8` — 한글 포함 레코드 저장 후 재로딩 시 문자 동일.
- `pytest tests/test_gold.py::test_writer_dry_run` — `dry_run=True` 시 파일 미생성.
- `pytest tests/test_gold.py::test_writer_indent` — 저장 파일이 2칸 들여쓰기.

---

## T-11 · `build_gold.py` 통합 및 CLI 완성

**목적**: 모든 컴포넌트를 오케스트레이션하고 CLI 완성. (REQ-01, REQ-09)

파일: `tools/build_gold.py`

작업:
1. `main()` 함수: argparse → `XlsxLoader` → `ColumnMapper` → `RowTransformer(NodeParser+GuidewordParser+MultiValueParser+FieldValidator)` → `DatasetValidator` → `decide_splitter` → `JsonWriter` 순서로 호출.
2. 요약 출력 구현 (REQ-09 형식 그대로):
   ```
   [build_gold] 완료: N 레코드 | 노드: ... | null S/F: N | 건너뜀: N
     → data/gold/hazop_nh3.json
     → data/gold/hazop_nh3_tune.json (노드, N 레코드)
     → data/gold/hazop_nh3_eval.json (노드, N 레코드)
   ```
3. 종료 코드: 정상 0, argparse 오류 2, 런타임 오류 1.
4. `--verbose` 플래그 시 `logging.DEBUG` 활성화.
5. `data/raw/` 외부 경로 사용 시 WARNING 출력.

검증:
- `pytest tests/test_gold.py::test_cli_missing_input` — `--input` 없으면 종료 코드 2.
- `pytest tests/test_gold.py::test_cli_dry_run_no_files` — `--dry-run` 시 파일 미생성 + 종료 코드 0.
- `pytest tests/test_gold.py::test_cli_summary_output` — 표준 출력에 "완료:" 문자열 포함.
- `pytest tests/test_gold.py::test_golden_snapshot` — `sample_valid.xlsx` 전체 변환 결과가 `expected_valid.json` 과 일치 (snapshot 테스트).

---

## T-12 · `ruff` · `mypy` · 커버리지 통과

**목적**: NFR-G01, NFR-G02, PRD NFR-07 달성.

작업:
1. `ruff check tools/ tests/test_gold.py` 경고 0개가 될 때까지 수정.
2. `mypy --strict tools/build_gold.py tools/_gold/` 통과.
3. `pytest tests/test_gold.py --cov=tools/_gold --cov-report=term-missing` 실행:
   - `tools/_gold/` 핵심 모듈 커버리지 ≥ 70%.
4. `pyproject.toml` 에 `[tool.ruff]` 및 `[tool.mypy]` 설정 추가 (steering `engineering.md` 기준).

검증:
- `ruff check tools/ tests/test_gold.py` → 출력 없음(경고 0).
- `mypy --strict tools/build_gold.py tools/_gold/` → `Success: no issues found`.
- `pytest tests/test_gold.py --cov=tools/_gold` → 커버리지 ≥ 70%.

---

## T-13 · `Makefile` 타겟 및 G0 게이트 확인

**목적**: PRD §8 G0 킬체크 조건 중 골드셋 관련 항목 달성.

작업:
1. `Makefile` 에 아래 타겟 추가:
   ```makefile
   build-gold:
       PYTHONIOENCODING=utf-8 python tools/build_gold.py \
           --input data/raw/D1_HAZOP_워크시트.xlsx \
           --sheet HAZOP워크시트 \
           --split node --tune-nodes N1

   test-gold:
       pytest tests/test_gold.py -v

   check-gold: test-gold
       ruff check tools/_gold/ tools/build_gold.py
       mypy --strict tools/build_gold.py tools/_gold/
   ```
2. `README.md` (프로젝트 루트) 에 `## 골드셋 빌드` 절 추가:
   - 원본 xlsx 배치 방법, `make build-gold` 실행, 출력 파일 3종 설명, 분할 방식 명시 (노드 단위 / stratified fallback 조건).

검증:
- 원본 xlsx를 `data/raw/` 에 배치한 후 `make build-gold` 실행 → 종료 코드 0.
- `data/gold/hazop_nh3.json` 레코드 수 = 원본 유효 행 수.
- `make check-gold` → 모두 통과.
- G0 체크리스트: `골드셋 JSON ✓` 항목에 체크 가능.

---

## 태스크 의존 관계

```
T-01 (스캐폴딩)
  └─ T-02 (XlsxLoader)
       └─ T-03 (ColumnMapper)
            ├─ T-04 (GuidewordParser)
            ├─ T-05 (MultiValueParser)
            └─ T-06 (NodeParser + fixtures)
                 └─ T-07 (FieldValidator)
                      └─ T-08 (DatasetValidator)
                           ├─ T-09 (Splitter)
                           └─ T-10 (JsonWriter)
                                └─ T-11 (CLI 통합)
                                     └─ T-12 (lint/type/coverage)
                                          └─ T-13 (Makefile + G0 확인)
```

병렬 가능: T-04, T-05, T-06은 T-03 완료 후 동시 진행 가능.

---

## 요구사항 ↔ 태스크 추적

| REQ | 태스크 | 테스트 함수 |
|---|---|---|
| REQ-01 | T-02, T-11 | `test_loader_missing_file`, `test_loader_missing_sheet`, `test_cli_missing_input` |
| REQ-02 | T-03 | `test_column_order_invariant`, `test_column_missing_raises`, `test_column_strip_whitespace` |
| REQ-03 | T-08, T-10, T-11 | `test_schema_valid`, `test_record_count`, `test_id_unique`, `test_golden_snapshot` |
| REQ-04 | T-04 | `test_guideword_split`, `test_guideword_fullwidth_paren` |
| REQ-05 | T-06 | `test_node_forwardfill`, `test_node_unknown_logged` |
| REQ-06 | T-05 | `test_multivalue_newline`, `test_multivalue_semicolon`, `test_multivalue_single`, `test_multivalue_none` |
| REQ-07 | T-07 | `test_risk_score`, `test_invalid_sf_to_null`, `test_skip_empty_deviation` |
| REQ-08 | T-09 | `test_node_split`, `test_split_count_sum`, `test_stratified_reproducible`, `test_split_config_fields` |
| REQ-09 | T-10, T-11 | `test_cli_dry_run_no_files`, `test_cli_summary_output`, `test_writer_dry_run` |
| NFR-G01 | T-12 | `ruff check` |
| NFR-G02 | T-12 | `mypy --strict` |
| NFR-G03 | T-13 | `make build-gold` 실행 시간 측정 |
| NFR-G04 | T-10 | `test_writer_utf8`, `test_writer_indent` |
