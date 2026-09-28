# design.md — self-verification
# spec: self-verification · 대응 FR: PRD v2.0 §5 FR-06
# 생성: 2026-09-29 · 손 작성

## 1. 배치

```
core/agent/verify.py          ← 이 spec 의 전부 (순수 함수, core/llm 임포트 금지)
apps/web/service.py           ← 호출부 1곳: 재생·실호출 결과를 표시·내보내기 전에 verify() 통과
tests/test_verify.py          ← 결함 삽입 10건 + 위양성 + 순서 보존
```

`core/agent/generate.py` 는 **고치지 않는다.** verifier 는 생성기 밖에서 사후에 돈다(PRD §4 그림의
`verify.py  규칙 기반 플래그 → confidence`). `core/export` 는 `confidence` 값을 그대로 표시하므로
변경 없음.

## 2. 타입

```python
@dataclass(frozen=True)
class Flag:
    record_id: str
    rule: Literal["unverified_standard", "unsupported_number"]
    field: str          # "causes[1]" 처럼 인덱스 포함
    matched: str        # 매치된 원문 조각

@dataclass(frozen=True)
class VerifySummary:
    total: int
    flagged: int
    by_rule: dict[str, int]
    missing_cells: int | None
    flags: tuple[Flag, ...]

def verify(records, *, expected_cells=None, judged_cells=None) -> tuple[list[DeviationRecord], VerifySummary]
```

## 3. 규칙 구현

- `STANDARD_PATTERNS: tuple[re.Pattern, ...]`, `NUMBER_PATTERN: re.Pattern` — 모듈 상수. R-01·R-02 문면.
- `_iter_text_fields(record) -> Iterator[tuple[str, str]]` — `(field_label, text)`. R-01 대상 6필드,
  R-02 대상 4필드를 각각 상수 튜플로.
- `_allowed_numbers(node_meta) -> set[str]` — `P_kPag`·`T_degC` 를 문자열 정규화(`350`, `350.0` 둘 다).
- 격하는 `record.model_copy(update={"confidence": "review"})`. 원본 불변.

## 4. 호출부 (`apps/web/service.py`)

- `_display_records(result)` 와 `export_files(result)` 가 같은 `verify()` 결과를 쓰도록
  `Result` 에 `verified: tuple[list[DeviationRecord], VerifySummary] | None` 캐시 1개 추가
  (재생 파일은 바꾸지 않는다 — 파일은 생성 원본, 검증은 표시 시점).
- 결과표에 열 1개 추가: `검증 플래그` — `rule: matched` 를 `; ` 로 이어 붙인 문자열(없으면 빈칸).
- 요약 줄에 `review N건 (규격 a·수치 b)` 추가.
- `BADGES` 는 그대로(`review` 🔴 이미 있음).

## 5. 시험 설계

- 결함 삽입: 9/29 live 재생에서 레코드 10건을 골라 각각 1개 필드에 결함 1개 삽입
  (규격 5: `KOSHA GUIDE P-140`, `API 520`, `NFPA 55`, `KS B 6750`, `산업안전보건기준에 관한 규칙 제261조` /
  수치 5: `10 kPag`, `-33 ℃`, `25 ppm`, `15 %`, `30 분`). 기대: ≥ 9건 `review`.
- 위양성: 삽입 전 61건의 플래그 수를 **기록만** 한다(단언 없음 — 그 숫자가 진행로그의 실측값).
  `P_kPag=350` 을 가진 합성 레코드의 "350 kPag" 은 플래그 0.
- 순서·개수 보존, 원본 객체 `confidence` 불변.
