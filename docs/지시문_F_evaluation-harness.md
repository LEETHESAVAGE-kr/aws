# 지시문 F — FR-08 평가 하네스 구현 (T-01~T-05, 전부 오프라인) (2026-09-23)

## 배경 (사람이 읽는 부분 — Claude Code에는 붙여넣지 않음)

- `evaluation-harness` spec 은 2026-09-23 손 작성 완료(커밋 `cad4438`). 이 지시문은 그 spec 의
  **T-01~T-05 를 구현**한다. **T-06(홀드아웃 실측)은 이 지시문에 없다** — G1 판정(지시문 E-2)과
  API 키가 먼저다.
- **이 세션은 실호출 0회다.** API 키가 없어도 끝까지 돌아간다. 그래서 키를 기다리는 동안
  무인 세션으로 돌릴 수 있다. 9/24 일정을 당겨 쓰는 것이며 PRD §8 9/24 행의 두 번째 항목이다.
- 새 의존성을 추가하지 않는다. 필요한 것은 전부 표준 라이브러리(`difflib` 는 쓰지 않는다 —
  design D2 가 2-gram Jaccard 를 택했다)와 이미 설치된 `pyyaml` 이다.

### 사람이 먼저 할 일

없다. 이 지시문은 현재 저장소 상태 그대로 시작한다.

---

## 붙여넣기 시작 (F 세션)

작업 디렉터리: `C:\Users\user\Desktop\공모전\AWS_AI_Innovators\hazop-copilot`

먼저 읽어라: `CLAUDE.md`, `PRD.md` §5 FR-08·§8·§10 R4·§11 OQ-7,
`.kiro/specs/evaluation-harness/{requirements,design,tasks}.md` **전체**,
`core/agent/generate.py`, `core/llm/{client,types,mock,__init__}.py`,
`data/gold/split_node.json`.

spec 3종이 이 세션의 계약이다. **spec 과 이 지시문이 어긋나면 spec 이 이긴다.** 어긋난 자리를
발견하면 고치지 말고 보고하라.

### 0단계 · 상태 검증 (먼저 이것만)

```bash
git log --oneline -3
git status --short
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m ruff check .
PYTHONIOENCODING=utf-8 HAZOP_USE_MOCK=true .venv/Scripts/python.exe -m pytest -m "not live" -q
```

기대:
- 최신 커밋이 `cad4438 spec:evaluation-harness — FR-08 평가 하네스 spec 손 작성`.
  그 아래가 `a95884d docs: 지시문 E-2 날짜 정합화…` / `0c9298f spec:bedrock-client T-15…`.
- 작업 트리 깨끗, ruff clean.
- 테스트는 **둘 중 하나**이며 **어느 쪽이든 정상이다**:
  - `161 passed, 1 deselected, 1 xfailed` — `models.yaml` 의 `model_id` 가 아직 `null`
    (이 지시문 작성 시점 상태)
  - `162 passed, 1 deselected` 또는 `161 passed, 1 deselected, 1 xpassed` —
    그 사이에 사람이 키를 넣고 모델을 골라 `model_id` 를 채웠다
  **xfail 이 사라졌다는 이유로 멈추지 마라.** 그건 진행이지 이상이 아니다.
- `.kiro/specs/evaluation-harness/` 에 파일 3개가 있어야 한다. 없으면 코드를 쓰지 말고 멈춰라.

위와 다르면(커밋이 다르거나 트리가 더럽거나 ruff 가 깨지면) **멈추고 차이를 보고하라.**

### 1단계 · 구현 — spec:evaluation-harness T-01~T-05

새로 만드는 파일은 아래 8개뿐이다. **`core/` 아래 파일은 한 줄도 수정하지 마라**
(spec 범위 §, R-04 수용 기준). `tests/test_llm.py`·`tests/test_generate.py`·
`tests/test_export.py` 도 건드리지 않는다.

```
eval/__init__.py   eval/data.py   eval/matching.py   eval/metrics.py
eval/recording.py  eval/report.py  eval/run.py       tests/test_eval.py
```

구현 순서는 **T-01 → T-02 → T-03 → T-04 → T-05**. 각 태스크의 작업·검증 항목은
`tasks.md` 에 그대로 있다. 여기서는 그 문서가 말하지 않는 것, 그리고 빠지기 쉬운 곳만 적는다.

1. **`_do_converse` 는 `@abstractmethod` 다** (`core/llm/client.py:277`). `converse` 만
   재정의한 `RecordingClient` 는 `TypeError: Can't instantiate abstract class` 로 죽는다.
   2026-09-22 에 실제로 재현해 확인했다. `_do_converse` 를 정의하되 본문은
   `raise AssertionError(...)` 로 둬라(design §2 함정 블록). `pass` 나 `...` 금지 — 상속
   구조가 바뀌면 조용히 빈 응답이 나와 지표가 0 으로 채워진다.

2. **`RecordingClient` 는 `converse` 를 감싼다**(`_do_converse` 가 아니라). 재시도·비용 상한
   훅 바깥에서 봐야 실제로 일어난 호출이 잡힌다. 응답 객체는 **그대로 반환**하고 복사·변형하지
   마라.

3. **`--provider mock` 은 `HAZOP_USE_MOCK` 환경변수에 의존하지 마라.** `MockBedrockClient` 를
   직접 만들어 주입하라. 환경변수는 기존 테스트의 것이고, 하네스가 그걸 읽으면 CLI 인자와
   환경이 어긋났을 때 무엇으로 돈 건지 사후에 알 수 없다.

4. **지표 계산 시험과 종단 시험을 분리하라.** `tasks.md` T-03 의 네 시나리오
   (완전일치·공백차이·생성0건·과생성)는 **생성기를 거치지 않고** 레코드 리스트를 직접
   `matching`/`metrics` 함수에 넣어 검증한다. `MockBedrockClient` 로 `PARAMETER_LIST_SCHEMA`
   와 `DEVIATION_BATCH_SCHEMA` 를 만족하는 가짜 배치를 조립하는 것은 `--provider mock` 종단
   경로(T-05) 1건에서만 하라. 지표 검증을 위해 정교한 mock 을 짜기 시작하면 이 세션은 끝나지
   않는다.

5. **τ 를 고르지 마라.** 기본값 0.5 로 두고 `--tau` 를 받는다. 0.4/0.5/0.6 스윕과 선택은
   T-06(다음 지시문) 소관이다(OQ-7). 이 세션에서 "0.45 가 좋아 보인다" 같은 판단을 하지 마라.

6. **`null` 규율을 지켜라.** 매칭쌍 0 → `S_mae`/`F_mae` 는 `None`, 생성 0건 → `precision` 은
   `None`. `0.0` 으로 채우지 마라. JSON 에는 `null` 로 나가야 한다.

7. **동의어 사전 금지.** 규칙 B 의 파라미터 정규화는 NFKC·공백·괄호·말미 조사까지다.
   `액위`↔`준위` 같은 매핑을 넣지 마라 — 골드를 봐야 알 수 있는 것이고 그게 홀드아웃 누출이다.

8. `--max-calls` 기본 120, `--dry-run` 은 예상 호출 수만 출력하고 종료. 이 세션에서는 어차피
   실호출이 없지만 T-06 이 이 가드를 쓴다.

9. `results/` 를 `.gitignore` 에 넣지 마라(R-05). 대신 이 세션이 만든 mock 산출물은
   커밋하지 말고 지워라 — 실측이 아니다.

10. 새 의존성 추가 금지. `difflib` 도 쓰지 마라(design D2 가 기각했다).

### 2단계 · 결함 재삽입 검증 (프로젝트 관례 — 생략 금지)

`tasks.md` 의 각 태스크 검증 절에 결함 재삽입 항목이 있다. **전부 수행하고 원복하라.**
최소한 아래 다섯은 반드시 한다.

| # | 넣을 결함 | 깨져야 하는 시험 |
|---|---|---|
| 1 | 매칭 탐욕 배정에서 `used_gold` 검사 제거 | 과생성 시나리오 precision |
| 2 | `S_mae` 의 `None` 을 `0.0` 으로 | 생성 0건 시나리오 |
| 3 | `_do_converse` 본문을 `pass` 로 | 도달불가 시험 |
| 4 | `report.py` 재현성 한계 상수 삭제 | 리포트 문구 시험 |
| 5 | `data.py` 의 노드 메타 1종 검사 제거 | `test_node_meta_conflict_raises` |

**깨지지 않는 결함이 하나라도 있으면 그 시험은 아무것도 검증하지 않는 것이다.** 시험을 고쳐서
깨지게 만든 뒤 다시 원복하고, 그 사실을 보고에 적어라. 원복 후 `grep -rn DEFECT eval/ tests/`
가 0건이어야 한다.

### 3단계 · 마무리 검증

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m ruff check .
PYTHONIOENCODING=utf-8 HAZOP_USE_MOCK=true .venv/Scripts/python.exe -m pytest -m "not live" -q

# core 무수정 확인 — 건수를 직접 센다(grep 의 종료코드를 세지 마라, 0/1 은 개수가 아니다)
git status --porcelain -- core schemas data | wc -l

PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m eval.run --split holdout --dry-run
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m eval.run --split holdout --repeats 2 --seed 42 --provider mock --out .tmp_eval_check
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m eval.run --split holdout --repeats 2 --seed 42 --provider mock --out .tmp_eval_check2
```

- 위 `wc -l` 이 **`0`** 이어야 한다 — 이것이 R-04 의 핵심 수용 기준이다.
  (`git status --porcelain -- <경로>` 는 해당 경로만 본다. 파이프로 `grep` 하고 `$?` 를 찍는
  방식은 "개수" 가 아니라 "매치 여부" 라서 0건과 1건을 구별하지 못한다.)
- mock 종단 실행을 **같은 인자로 두 번**(출력 경로만 다르게) 돌려 `metrics.json` 이 바이트
  동일한지 확인하라(하네스 결정성, R-06 수용 기준). 다르면 어디가 비결정적인지 찾아 보고하라 —
  흔한 원인은 `dict` 순회 순서가 아니라 **타임스탬프가 `metrics.json` 본문에 섞인 것**이다.
  `run_id` 는 경로에만 쓰고 지표 본문의 동일성 비교에서는 제외하라.
- 확인 후 `.tmp_eval_check*` 를 지워라. 커밋 대상이 아니다.
  (Windows 경로다 — `/tmp` 를 쓰지 마라. PowerShell 에서는 존재하지 않는다.)

### 완료 보고 (4줄 + 표, `docs/진행로그.md` 에 추가)

변경 파일 / `pytest` 결과(신규 테스트 수 포함) / T-01~T-05 완료 조건 충족 여부 /
결함 재삽입 5건 각각의 결과(깨졌는가·원복했는가).

표 1개: 각 태스크 × 대응 R × 신규 테스트 이름(추적 매트릭스 `tasks.md` 와 대조).

**하지 말 것**: T-06 실행(실호출) · `models.yaml` 수정 · τ 결정 · 프롬프트 수정 ·
`core/` 수정 · 커밋. 커밋은 사용자가 지시할 때만:
`spec:evaluation-harness T-01~T-05 — 평가 하네스 구현 (오프라인)`.

## 붙여넣기 끝 (F)

---

## 이후 (참고 — 사람용)

| 시점 | 할 일 |
|---|---|
| 키 발급 후 | 지시문 E-2 — T-07 스모크 + T-08 N1 recall → **G1 판정** |
| G1 이후 | 지시문 G(가칭) — T-06 τ 스윕(mock) → 홀드아웃 26건 × 3회 실측 → README §평가 |
| 9/25 | FR-05 데이터 + evidence-citation·self-verification spec 손 작성 → FR-06 규칙 verifier |
| 9/27 | 개인 AWS 계정 Bedrock → `provider: bedrock` 전환 → 하네스 3회 재실측 |

**미결(주저자 판단 대기)**: 매칭 규칙 A/B 병기는 PRD FR-08 문면을 넘어서는 결정이다
(근거는 §10 R4 "보조 지표 병기"). 승인 전이면 F 세션은 그대로 진행해도 된다 —
규칙 B 를 빼는 것은 나중에 한 줄 삭제이고, 나중에 넣으려면 매칭 전체를 다시 짜야 한다.
