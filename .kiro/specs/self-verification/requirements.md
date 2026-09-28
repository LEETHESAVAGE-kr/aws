# requirements.md — self-verification
# spec: self-verification · 대응 FR: PRD v2.0 §5 FR-06 (규칙 기반 verifier, P1)
# 생성: 2026-09-29 · 기준 문서: 지시문_I_홀드아웃-verifier.md
# 작성 방식: 손 작성(PRD v2.0 §6 — 신규 spec 3종은 손 작성). Kiro 크레딧 미사용.

## 범위

`core/agent/verify.py` 1개 파일과 `tests/test_verify.py`. 태스크 ≤ 4개(PRD §6 상한).

이 spec 은 **LLM 을 호출하지 않는다.** `core/llm` 을 임포트하지 않는다. 입력은 `DeviationRecord`
목록(또는 같은 필드를 가진 Mapping)이고 출력은 같은 길이의 목록 + 플래그 목록이다. 순수 함수.

**포함하지 않는 것**: 근거 검색·인용(FR-04′ — 예선 미착수, 따라서 `grounded` 는 이 spec 에서
절대 부여하지 않는다), LLM 2차 호출 verifier(v1.2 삭제), 매트릭스 재생성, 프롬프트 수정,
`schemas/deviation.schema.json` 수정(`confidence` enum 은 `inferred | review` 그대로).

---

## 배경 — 왜 규칙 기반인가

9/29 live 캡처 61건은 전부 `confidence=inferred`, `evidence=[]` 다(FR-04 미구현). 즉 모델이
본문에 적은 **규격 번호·문헌명·단위 붙은 수치는 전부 근거가 없는 주장**이다. 이를 사람이 검토
하도록 `review` 로 격하하는 것이 이 spec 의 전부다(CLAUDE.md 불변규칙 5 의 예선 축소판).

---

### R-01 근거 없는 규격·문헌 번호 플래그

WHEN 레코드의 텍스트 필드(`deviation`, `causes[]`, `consequences[]`, `safeguards_before[]`,
`recommendations[]`, `scenario`)에 규격·문헌 번호 패턴이 나타나고 THE SYSTEM SHALL 그 패턴이
`evidence[]` 의 어떤 항목에도 없으면 `Flag(rule="unverified_standard", field, matched)` 를 낸다.

패턴(대소문자 무시, 공백 유연): `KOSHA\s*(GUIDE)?\s*[A-Z]-\d+`, `KS\s*[A-Z]\s*(IEC|ISO)?\s*\d+`,
`API\s*(RP|STD|Std)?\s*\d+`, `NFPA\s*\d+`, `IEC\s*\d+`, `ISO\s*\d+`, `ASME\s*[A-Z]?\d*(\.\d+)?`,
`OSHA\s*\d+`, `산업안전보건기준에\s*관한\s*규칙\s*제?\s*\d+조`, `고압가스안전관리법\s*(시행규칙)?\s*제?\s*\d+조`.
패턴 목록은 모듈 상수 1개(`STANDARD_PATTERNS`)로 두고, 각 항목에 예시 문자열 주석을 단다.

- AC-01-1 예선에서는 `evidence[]` 가 항상 비어 있으므로 패턴이 잡히면 예외 없이 플래그.
- AC-01-2 같은 레코드에서 같은 매치 문자열은 1회만 센다.

### R-02 근거 없는 수치 주장 플래그

WHEN `causes[]`, `consequences[]`, `safeguards_before[]`, `recommendations[]` 에
단위가 붙은 수치(`\d+(\.\d+)?\s*(kPa|kPag|MPa|bar|barg|°C|℃|K|ppm|%|vol%|kg|t|톤|m³|m3|L|mm|m|m/s|초|분|시간|h|min|s)`)
가 나타나고 THE SYSTEM SHALL 그 수치가 `node_meta` 가 제공한 값(`P_kPag`, `T_degC`)과
같지 않으면 `Flag(rule="unsupported_number", field, matched)` 를 낸다.

- AC-02-1 `node_meta.P_kPag`·`T_degC` 와 같은 숫자(단위 무관)는 플래그하지 않는다.
- AC-02-2 `S`, `F`, `risk_score` 필드는 대상이 아니다(등급이지 주장 아님).
- AC-02-3 `deviation` 필드는 대상이 아니다("압력 10% 상승" 같은 이탈 정의는 수치를 포함하는 것이 정상).

### R-03 신뢰도 격하와 요약

WHEN 레코드에 플래그가 1개 이상이면 THE SYSTEM SHALL `confidence="review"` 로 바꾼 사본을 낸다.
플래그가 없으면 입력 값을 유지한다(`inferred`). `grounded` 는 어떤 경우에도 부여하지 않는다.

THE SYSTEM SHALL `VerifySummary(total, flagged, by_rule: dict[str,int], flags: list[Flag])` 를
함께 돌려준다. 입력 순서·개수는 보존한다(원본 객체는 변경하지 않는다 — `model_copy(update=...)`).

### R-04 매트릭스 누락 셀 보고 (보고만)

WHEN 호출자가 `expected_cells`·`judged_cells` 를 넘기면 THE SYSTEM SHALL 요약에
`missing_cells = expected - judged` 를 적는다. 계산·재생성은 하지 않는다(생성기 관측값의 전달).

---

## 완료 조건 (PRD §5 FR-06)

- 의도 삽입 결함 **10건 중 ≥ 9건 플래그**(규격 번호 5건 + 수치 5건, 서로 다른 필드에 분산).
- 9/29 live 재생 61건에 verifier 를 돌린 결과(플래그 수·규칙별)를 진행로그에 **숫자로** 적는다.
  낮든 높든 그대로.
- `AC-02-1` 위양성 시험: `node_meta.P_kPag=350` 인 레코드의 "350 kPag" 은 플래그되지 않는다.
- `pytest -m "not live"` 전부 통과, ruff clean, `core/llm` 임포트 0.
