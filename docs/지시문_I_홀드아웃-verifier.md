# 지시문 I — I-1 홀드아웃 3노드 실측 + 프리셋 4개 · I-2 규칙 verifier (2026-09-29 새벽)

## 배경 (사람이 읽는 부분 — Claude Code 에는 붙여넣지 않음)

지시문 H 완료 상태(커밋 `0bee197`): Streamlit 재생 데모, N1 live 캡처 recall 0.875 · 절단 0 · 511초 · $0.79.
남은 하루에 점수를 올리는 두 가지를 **두 세션으로 나눠** 한다. 순서는 I-1 → I-2. I-1 은 실호출 3회
(약 30분·$3), I-2 는 실호출 0회.

| 세션 | 무엇 | 왜 점수인가 | 실호출 |
|---|---|---|---|
| I-1 | 골드셋 홀드아웃 N2·N3·N4(26건) 캡처 + UI 프리셋 4개 | tune 1노드 recall 은 "본 문제" 숫자. **미학습 노드 recall** 이 교수 심사위원이 보는 숫자이고 PRD 성공 정의 그 자체 | 3회 |
| I-2 | 규칙 기반 verifier(FR-06) | 61건 전부 🟡 inferred·evidence 0 → 배지가 한 색. 근거 없는 규격번호·수치를 🔴 review 로 격하하면 "환각을 시스템이 잡는 장면"(전략서 R7)이 데모·소개서에 생긴다 | 0회 |

### 사람이 먼저 할 일

1. **크레딧 확인** — console.anthropic.com 잔액 ≥ $5. 부족하면 충전 후 시작(00:53 에 잔액 부족으로 거부된 전례).
2. **spec 저장(I-2 용)** — `.kiro/specs/self-verification/{requirements,design,tasks}.md` 세 파일이 이미
   저장돼 있다(손 작성, 이 지시문과 같이 생성). `git status` 로 보이면 된다. CLAUDE.md 상 Claude Code 는
   requirements.md 를 못 만들기 때문에 사람이 넣어 둔 것이다.
3. I-1 은 낮에 돌린다고 했지만 지금 하겠다면: 세 노드를 **한 번에 하나씩**, 하나가 끝나고 로그를 본 뒤
   다음을 돌린다. 새벽 DNS 단절 전례가 있다.
4. 커밋 순서: I-1 끝나면 커밋 → I-2 끝나면 커밋 → push(재배포 자동).

---

## 붙여넣기 시작 (I-1 세션)

작업 디렉터리: `C:\Users\user\Desktop\공모전\AWS_AI_Innovators\hazop-copilot`

먼저 읽어라: `CLAUDE.md`, `docs/진행로그.md` 의 **2026-09-29 항 전체**, `tools/capture_replay.py`,
`tools/_replay.py`, `apps/web/{replay,service,app}.py`, `tests/test_web.py`, `data/gold/split_node.json`,
`.kiro/specs/evaluation-harness/requirements.md` 의 **R-02(매칭)·R-03(지표)** 만.

과제: **FR-10 H-06 (프리셋 확장) + FR-08 T-06 의 축소 실행(홀드아웃 실측 — 하네스 없이 캡처 도구로)**.
근거는 PRD v2.0 §5 FR-08 완료 조건("holdout 26건 ... 표가 README §평가에")과 FR-10 프리셋. spec
evaluation-harness 의 T-01~T-05(하네스 구현)는 **이 세션 범위가 아니다** — `eval/` 을 만들지 마라.
캡처 도구가 이미 같은 recall 규칙(`tools/_replay.recall_n1`)을 쓰므로 그것으로 잰다. 이 축소를
완료 보고에 명시한다("하네스 미구현, 캡처 도구로 노드별 1회 실측").

손대지 않는 것: `core/*`, `schemas/*`, `data/gold/*`, 프롬프트, `config/models.yaml`.

### 0단계 · 상태 검증
```
git log --oneline -3
git status --short
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m ruff check .
HAZOP_USE_MOCK=true PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -m "not live" -q
```
기대: 마지막 커밋 `0bee197`, 미추적은 `.kiro/specs/self-verification/` 만(I-2 용, 손대지 마라), ruff clean,
**174 passed / 3 deselected**. 다르면 멈추고 보고.

### 1단계 · 캡처 도구 확장 (`tools/capture_replay.py`, `tools/_replay.py`)

1. `NODE_METAS` 에 N2·N3·N4 추가. 값은 **`data/gold/hazop_nh3_eval.json` 의 각 노드 첫 레코드
   `node_meta` 를 그대로**(손으로 옮기되 출처 주석; 추측 기입 금지). 현재 골드 기준:
   N2 `equipment=["이송 호스"]`, N3 `["수급선 매니폴드"]`, N4 `["이송 운전 절차"]`, 나머지 필드는 N1 과 동일.
2. `--split {tune,holdout}` 인자 추가(기본: `node == "N1"` 이면 tune, 아니면 holdout). 골드 파일을
   `hazop_nh3_tune.json` / `hazop_nh3_eval.json` 으로 분기. 저장 JSON 에 `"split"` 키 추가.
3. `tools/_replay.recall_n1` 은 이름만 N1 일 뿐 노드 무관이다 — **`recall_for_node` 로 이름을 바꾸고
   `recall_n1 = recall_for_node` 별칭을 남겨** 기존 시험을 깨지 마라. 저장 키는 `recall_n1` → `recall`
   로 바꾸되 `load_replay` 가 두 키를 모두 읽게 한다(9/29 파일 호환).
4. 원시 호출 로그(출력 토큰·stop_reason)는 H-01 그대로.

### 2단계 · 실측 — 3회, 순차, 게이트

```
python tools/capture_replay.py --node N2 --out data/replay/n2_20260929.json --source live > results/capture_n2.log 2>&1
```
끝나면 **로그를 읽고** 결과 1줄 보고(지연·비용·절단·recall) 후 N3, 다시 확인 후 N4. `; echo "EXIT=$?"`
금지, `tail` 파이프 금지(9/28 함정 4). 한 노드가 실패(네트워크·크레딧·예외)하면 **그 노드는 재실행하지
않고** 다음 노드로 넘어간다. 총 실호출 상한 3회.

### 3단계 · UI 프리셋 4개 (`apps/web/replay.py`, `service.py`, `app.py`, `tests/test_web.py`)

1. `load_replays(directory) -> dict[str, Result]` — 노드별로 `live > gold`, 같은 source 는 최신.
   기존 `load_replay()` 는 `load_replays()["N1"]` 로 유지(호환).
2. 프리셋 버튼 1개 → **`st.radio` 또는 버튼 4개**(N1 벙커링선 매니폴드 / N2 이송 호스 / N3 수급선
   매니폴드 / N4 이송 운전 절차). 캡처가 없는 노드는 비활성 + "미캡처". 기본 N1.
3. 요약 줄에 노드별 `split`·recall 표시. 사이드바 또는 표 아래에 **평가 요약 표** 1개:
   노드 · split · 레코드 · judged/expected · 절단 · 지연(s) · 비용($) · recall(m/n). 마지막 행
   **홀드아웃 합계 recall = Σmatched / 26**(캡처된 노드만 합산했으면 분모를 실제 골드 수로 쓰고 그렇게
   표기). 이 표는 `service.py::evaluation_table(results)` 가 만들고 README §6 에 그대로 쓸 수 있게
   마크다운 문자열도 내는 함수(`evaluation_markdown`)를 같이 둔다.
4. 시험 ≥ 4건: (a) 노드별 우선순위 (b) 미캡처 노드 처리 (c) 합계 recall 계산(가짜 파일 3개로, 분모 검증)
   (d) `recall_n1`/`recall` 두 키 호환. 결함 재삽입 2건(합계 분모·우선순위).

### 완료 보고 (`docs/진행로그.md`)

노드별 표(N1 9/29 값 포함) + 홀드아웃 합계 recall + 골드 26건 대조표(일치/불일치 사유: 가이드워드
미생성 / 파라미터 어휘 불일치 / 조합 없음) + 실호출 총 횟수·총 비용 + 절단 호출 수 + "하네스 미구현"
명시 + 남은 리스크 4줄. 불리해도 그대로(NFR-03).

커밋은 내가 지시할 때만, 둘로:
1. `feat(FR-08) 홀드아웃 N2·N3·N4 캡처 — recall <합계> (하네스 없이 capture_replay 로 노드별 1회)`
2. `feat(FR-10) H-06 — 프리셋 4개 + 평가 요약 표`

## 붙여넣기 끝 (I-1)

---

## 붙여넣기 시작 (I-2 세션)

작업 디렉터리: `C:\Users\user\Desktop\공모전\AWS_AI_Innovators\hazop-copilot`

먼저 읽어라: `CLAUDE.md`, `.kiro/specs/self-verification/{requirements,design,tasks}.md` **전체**,
`core/agent/generate.py` 의 `DeviationRecord`·`NodeMeta`, `apps/web/service.py`, `apps/web/replay.py`,
`tests/test_web.py`, `data/replay/n1_20260929.json` 의 records 앞 5건.

과제: **spec:self-verification T-01~T-04** (PRD v2.0 §5 FR-06, P1). 실호출 0회. `core/llm` 임포트 0.

손대지 않는 것: `core/agent/generate.py`, `core/llm/*`, `core/export/*`, `schemas/*`, 프롬프트,
`data/replay/*.json`(검증은 표시 시점에 한다 — design §4).

### 0단계 · 상태 검증
```
git log --oneline -3
git status --short
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m ruff check .
HAZOP_USE_MOCK=true PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -m "not live" -q
```
기대: 작업 트리 clean(I-1 커밋 완료), ruff clean, 전부 통과. `.kiro/specs/self-verification/` 이 없으면
멈추고 보고.

### T-01 · `core/agent/verify.py`
requirements R-01~R-04, design §2·§3 그대로. 순수 함수, 원본 불변(`model_copy`). 패턴 상수마다 예시 주석.
`core/agent/__init__.py` 에 `verify`, `Flag`, `VerifySummary` 재수출.

### T-02 · `tests/test_verify.py`
design §5. 결함 삽입 10건(규격 5·수치 5, 서로 다른 필드·다른 레코드) → `review` ≥ 9 단언.
위양성 AC-02-1(`P_kPag=350` → "350 kPag" 무플래그), AC-01-2(같은 매치 1회), AC-02-3(`deviation` 의 수치
비대상), 순서·개수 보존, 원본 `confidence` 불변. **61건 baseline 플래그 수는 단언하지 말고 `logging` 으로
출력** — 그 숫자를 보고에 적는다.
결함 재삽입 3건: (a) `STANDARD_PATTERNS` 를 빈 튜플로 (b) `_allowed_numbers` 가 빈 set 반환 (c) 격하
로직 제거 — 각각 어느 시험이 깨지는지 확인 후 원복.

### T-03 · `apps/web/service.py` + `tests/test_web.py`
design §4. `Result.verified` 캐시, 표에 `검증 플래그` 열, 요약 줄 `review N건 (규격 a·수치 b)`,
`export_files` 가 격하된 confidence 로 xlsx 를 쓴다. `tests/test_web.py` 에 결함 1건 삽입 → 표와 xlsx
신뢰도 시트 모두 `review` 인 시험 1건. AppTest 로 화면 예외 0 확인.

### T-04 · 완료 보고 (`docs/진행로그.md`)
61건(+I-1 홀드아웃 캡처분) 실측 플래그 수 규칙별 / 결함 삽입 10건 중 n / 재삽입 3건 결과 / AC 표 /
남은 리스크 4줄. 플래그가 0건이면 0건이라고 쓴다.

커밋은 내가 지시할 때만: `spec:self-verification T-01~T-04 — 규칙 기반 verifier (FR-06, 실호출 0회)`.

## 붙여넣기 끝 (I-2)

---

## 이후 (사람용)

| 시점 | 할 일 |
|---|---|
| I-1·I-2 커밋 후 | `git push` → Streamlit Cloud 자동 재배포 → 시크릿 창에서 프리셋 4개·🔴 배지 확인 |
| 그다음 | 지시문 J(README 9절, 실호출 0회) — I-1 의 `evaluation_markdown` 출력을 §6 에 그대로. 소개서 10장은 이 대화에서 |
| 15:00 기준 | I-2 가 안 끝났으면 중단하고 README·소개서로. verifier 는 "본선 로드맵" 한 줄 |
