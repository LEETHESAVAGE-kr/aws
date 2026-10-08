# CLAUDE.md — hazop-copilot 작업 규칙

이 저장소는 고려대 × AWS AI Innovators Challenge 2026 출품작 「위험성평가 코파일럿」이다. **작업 전 `PRD.md`를 반드시 읽을 것** — 요구사항(FR)·수용 기준·마일스톤·비목표가 거기 있다. 전략 배경은 `AI_Innovators_수상전략서_v1.md`.

## 정본 사슬

| 무엇 | 정본 |
|---|---|
| 무엇을 만들고 언제까지 | `PRD.md` |
| 기능별 요구사항·설계·태스크 | `.kiro/specs/<spec>/{requirements,design,tasks}.md` — **Kiro가 생성한 파일. 여기 없는 기능은 만들지 않는다** |
| 코드·도메인·AWS·문서 규칙 | `.kiro/steering/*.md` |
| 모델 ID·리전·온도 | `config/models.yaml` (코드에 하드코딩 금지) |
| 출력 스키마 | `schemas/deviation.schema.json` |

## Kiro와의 분담 — 이 세션(Claude Code)의 역할

- 이 세션은 **구현 엔진**이다. 작업 지시는 항상 "`.kiro/specs/<spec>/tasks.md`의 T-xx" 형태로 온다. 지시에 spec/task 번호가 없으면 먼저 어느 task에 해당하는지 확인하고, 해당 task가 없으면 **코드를 쓰지 말고** "requirements.md에 추가가 필요하다"고 알린다.
- `.kiro/specs/*/requirements.md`·`design.md`는 **읽기 전용**. 요구사항 변경이 필요하면 변경안을 텍스트로 제안하고 사용자가 Kiro에서 반영한다. `tasks.md`의 체크박스는 사용자가 Kiro에서 표시한다(이 세션은 완료 보고만).
- steering 파일의 규칙은 이 문서보다 우선한다. 충돌 시 steering을 따르고 충돌 사실을 보고.
- 커밋 메시지: `spec:<name> T-xx — <요약>`. 하나의 커밋은 하나의 task.
- 커밋 메시지에 `Co-Authored-By:`·`Claude-Session:` 같은 트레일러를 넣지 않는다(저자는 사람 1인). 도구 언급은 README §5 로 충분하다.

## 불변 규칙

1. **KECC 고객사 실데이터·개인정보 절대 사용 금지.** 데이터는 `data/README.md`에 출처·라이선스가 적힌 것만.
2. `data/gold/`, `data/kb/` 원본은 읽기 전용. 파생물은 `results/`·`data/processed/`.
3. LLM 호출은 `core/llm/` 래퍼로만. 리전·모델 ID는 `config/models.yaml`에서만 읽는다. 시크릿은 환경변수, `.env.example`만 커밋.
4. 모든 LLM 출력은 `schemas/`로 검증. 검증 실패 시 1회 재시도 후 `confidence="review"`로 격하 — 절대 조용히 통과시키지 않는다.
5. 인용(`evidence[]`)은 tool이 반환한 텍스트에서만 생성. 모델이 지어낸 규격 번호·문서명은 verifier가 제거하도록 구현한다.
6. 실험·평가는 config(yaml) + 고정 시드 + 단일 명령으로 재현. 결과는 `results/{run_id}/`에 config 사본과 함께.
7. 실 LLM 호출 테스트는 `@pytest.mark.live`. 기본 `pytest`는 모의 클라이언트로 오프라인 통과해야 한다.
8. 한글 출력 스크립트는 `PYTHONIOENCODING=utf-8` 가정. Windows에서 실행되므로 경로는 `pathlib`, 인코딩 명시.
9. 새 의존성 추가 시 `pyproject.toml`에 버전 고정 + 이유 한 줄.
10. 평가 결과가 나쁘게 나와도 숨기지 않는다. README 평가표에는 불리한 지표도 그대로 쓴다(PRD NFR-03).

## 범위 규율 (솔로 프로젝트)

- **압축 구현 원칙**: 이미 생성된 spec(gold-dataset 13태스크, bedrock-client 14태스크)은 과잉 분해 상태다. 지시가 "T-01~T-11 한 번에"처럼 묶여 오면 태스크별 파일을 만들지 말고 파일 1~2개로 압축한다. design.md의 클래스명은 함수/얇은 클래스 이름으로 유지해 추적성만 보존한다.
- `mypy --strict`는 요구하지 않는다(spec에 있어도 무시). 품질 게이트는 `ruff check` + `pytest`만. `scikit-learn`은 설치하지 않고 fallback 분할 구현을 쓴다.
- `CostCalculator`류에서 미등록 모델 ID는 예외를 던지지 말고 비용 0 + WARNING 로그. 모델 ID는 대회 계정 확인 후 바뀔 예정이다.

- G2(9/14) 전에는 `apps/web/` 작업 금지. 핵심 루프(FR-03·04·07)가 먼저다.
- "있으면 좋을" 기능 제안은 `docs/backlog.md`에 한 줄 적고 끝. 구현하지 않는다.
- 한 task가 2시간을 넘기면 멈추고 분할안을 보고.

## 환경

```
Python 3.12 · boto3 · pydantic v2 · fastapi · streamlit · openpyxl · pytest · ruff
AWS: Bedrock(Converse API, Knowledge Bases, Guardrails) · S3 · (본선) App Runner/Lambda
make setup   # venv + 의존성
make test    # 오프라인 테스트
make demo    # Streamlit 실행
python -m eval.run --split holdout --repeats 5 --seed 42
```

## 세션 시작 체크리스트

1. `PRD.md` §5 FR 상태와 §8 게이트 날짜 확인 — 오늘 어느 게이트 앞인가.
2. 지시된 `tasks.md`의 T-xx와 그 requirement(R-xx)를 읽는다.
3. 관련 steering 파일을 읽는다(`domain.md`는 항상).
4. 구현 → `make test` → 완료 보고(변경 파일·테스트 결과·R-xx 충족 여부·남은 리스크 4줄).

## 도메인 최소 지식 (steering `domain.md`가 정본, 여기는 요약)

- HAZOP 가이드워드: No / More / Less / Reverse / Other than / Part of / As well as. 파라미터: 유량·압력·온도·준위·조성·상(phase)·시간 등.
- 워크시트 12열: `No, 노드, 가이드워드, 이탈, 원인, 결과, 기존 안전장치(Before), S(1-5), F(1-5), 위험도(=S×F), 권고, 시나리오 연계`.
- S·F 등급 정의: 골드셋 노드(NH3 N1~N4)는 골드셋 `평가기준` 시트를 그대로 사용. 그 밖의 공정은 `data/kb/criteria/` 의 공식 기준(출처·쪽 확인된 것만) — 10/9 사용자 결정(지시문 Y Q5). steering `domain.md` §4 개정은 사용자가 Kiro 에서.
- LOPA 용어: IE(개시사건), IPL(독립방호계층), PFD, SIL. 형식은 NH3 `LOPA_S1_C1.md` 준용.
