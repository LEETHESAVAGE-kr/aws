# 지시문 H — FR-10 Streamlit 재생 데모 + 배포 준비 (2026-09-28 밤)

## 배경 (사람이 읽는 부분 — Claude Code 에는 붙여넣지 않음)

`docs/수상가능성_보고서_20260928.md` §5-1 의 실행분이다. 제출물 3종 중 **배포 주소**가 0% 이고,
그 뼈대가 이 세션이다. 목표는 "심사위원이 URL 을 열어 프리셋 1클릭 → 결과표 → xlsx 다운로드"
까지 **10초 안에** 보는 것. 실호출은 노드당 10분·$0.75 라 기본 모드로 쓸 수 없다(9/28 실측).
그래서 **기본 = 재생(replay)**, 실호출은 키가 있을 때만 켜지는 선택 모드다.

### 정본 문제 — 이 지시문이 근거다

FR-10 은 Kiro spec 이 없다. PRD v2.0 §5 는 "FR-10 Streamlit UI — spec 없음(steering `docs.md`·
PRD 가 정본) · P0" 로 못 박았고, CLAUDE.md 의 "G2(9/14) 전 `apps/web/` 금지" 는 날짜가 지났다.
Claude Code 가 "spec 에 없다" 며 멈추면 **PRD v2.0 §5 FR-10 항과 이 지시문을 근거로 진행**하라고
답하면 된다. 태스크 번호는 `FR-10 H-01~H-05` 로 부여한다(손 작성 spec 선례와 동일).

### 사람이 먼저 할 일 (H 세션 전, 15분)

1. **미커밋분 커밋.** 9/28 작업 7개 파일 + `docs/지시문_G_병렬매트릭스.md` +
   `docs/수상가능성_보고서_20260928.md` + 이 파일.
   ```
   git add -A
   git commit -m "docs: E-2 실측(G1 미달·원인 max_tokens 절단) + 지시문 G·H + D-1 수상가능성 보고서"
   ```
2. **키 유출 확인.** `git log --all --oneline -- .env` 가 **비어 있어야** 한다. 비어 있지 않으면
   H 세션을 시작하지 말고 먼저 이력에서 제거한다(공개 리포로 갈 것이므로 실격급 위험).
3. **재생 데이터 소스 결정** — 둘 중 하나를 고른다. 9/28 run1 결과는 파일로 남아 있지 않다
   (`results/` 없음). 그래서 다시 만들어야 한다.
   - **A안(권고)**: 실호출 1회로 N1 결과를 캡처한다. 절단을 막기 위해 `config/models.yaml` 의
     `generation.max_tokens` 를 **4096 → 16384** 로 올린다(E-2 가 지목한 갈래 ①). 주석에
     "예선 데모용 — 지연은 못 줄임, 본선 지시문 G 에서 재검토" 를 적는다. 예상 비용 ≈ $0.8,
     지연 ≈ 10분. 이 1회가 이번 세션 실호출 예산의 전부다.
   - **B안(A 실패 시 자동)**: 골드셋 `data/gold/hazop_nh3_tune.json` 의 N1 8건을 그대로 재생한다.
     화면·소개서에 **"전문가 골드셋 재생 — 생성 결과 아님"** 을 명시한다(PRD §9 Plan B 문면).
4. `.env` 에 `ANTHROPIC_API_KEY` 가 BOM 없이 들어 있는지 확인(9/27·9/28 두 번 재발한 함정).
   PowerShell 이면 `[IO.File]::WriteAllText` 로 쓴다.

---

## 붙여넣기 시작 (H 세션)

작업 디렉터리: `C:\Users\user\Desktop\공모전\AWS_AI_Innovators\hazop-copilot`

`CLAUDE.md`, `PRD.md` **§0·§4·§5 FR-10·§9**, `.kiro/steering/{engineering,docs}.md`,
`docs/진행로그.md` 의 **2026-09-28 항 전체**, `core/agent/generate.py` (`NodeMeta`·`DeviationRecord`·
`HazopGenerator`), `core/export/__init__.py` (`export_all`), `core/llm/__init__.py`
(`get_bedrock_client`), `tests/test_generate.py` 의 `N1_META`·`_live_generator`·`_recall_n1`
를 먼저 읽어라.

이 세션의 과제는 **PRD v2.0 §5 FR-10 (P0, spec 없음 — PRD 가 정본)** 이다. 태스크 ID 는
`FR-10 H-01~H-05`. `.kiro/specs/` 에 없다는 이유로 멈추지 마라 — PRD §5 가 그렇게 정했다.

**이 세션에서 손대지 않는 것**: `core/agent/*`, `core/llm/*`, `core/export/*`, `schemas/*`,
`core/agent/prompts/*`, `data/gold/*`. UI 는 `core/` 를 **호출만** 한다(PRD §4). `core/` 에 고치고
싶은 것이 보이면 `docs/backlog.md` 에 한 줄 적고 넘어가라.

### 0단계 · 상태 검증 (먼저 이것만)

```bash
git log --oneline -3
git status --short
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m ruff check .
HAZOP_USE_MOCK=true PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -m "not live" -q
.venv/Scripts/python.exe -c "import streamlit; print(streamlit.__version__)"
```

기대: 작업 트리 clean(사람이 방금 커밋함), ruff clean, **162 passed / 3 deselected**.
`streamlit` 이 없으면 `pyproject.toml` `dependencies` 에 `"streamlit>=1.38"` 을 이유 한 줄과 함께
추가하고 `pip install -e ".[dev]"` (CLAUDE.md 불변규칙 9).
`git log --all -- .env` 가 비어 있지 않으면 **멈추고 보고**.

### H-01 · 재생 캡처 도구 — `tools/capture_replay.py`

`tools/build_gold.py` 와 같은 스타일의 CLI 스크립트 1개.

```
python tools/capture_replay.py --node N1 --out data/replay/n1_20260928.json [--source live|gold]
```

- `--source live`(기본): `HazopGenerator(get_bedrock_client(), load_generator_config())` 로
  `N1_META`(tests 의 것과 **동일 값** — 복사하되 출처 주석) 를 1회 생성. 저장 내용:
  ```json
  {
    "schema_version": 1,
    "source": "live",
    "captured_at": "<ISO8601>",
    "provider": "<models.yaml provider>", "model_id": "<generation.model_id>",
    "node": "N1", "node_meta": {...},
    "latency_s": 0.0, "cost_usd": 0.0,
    "expected_cells": 0, "judged_cells": 0, "review_guidewords": [],
    "recall_n1": {"recall": 0.0, "matched": 0, "total": 8},
    "records": [ ...DeviationRecord.model_dump()... ]
  }
  ```
  `recall_n1` 은 `tests/test_generate.py::_recall_n1` 과 **같은 규칙**이어야 한다. 시험 코드를
  import 하지 말고(테스트 모듈은 배포에 없다) 함수를 `tools/_replay.py` 로 옮겨 **양쪽이 같은 것을
  쓰게** 하라. 기존 시험이 깨지지 않아야 한다.
- `--source gold`: `data/gold/hazop_nh3_tune.json` 의 `node == "N1"` 8건을 records 로 넣고
  `source: "gold"`, `latency_s`·`cost_usd` 는 `null`, `recall_n1` 은 `null`.
- 저장 전 `schemas/deviation.schema.json` 으로 records 를 검증한다. 실패 시 저장하지 않는다.
- 실호출은 **이 세션에서 정확히 1회**. 실패(예외·절단·타임아웃)하면 재실행하지 말고 `--source gold`
  로 만든 뒤 실패 로그를 보고에 붙여라. 실행은 백그라운드로 파일에 흘리고(`> log 2>&1`),
  `; echo "EXIT=$?"` 를 붙이지 마라(9/28 함정 4). 판정은 로그로.

### H-02 · UI — `apps/web/app.py` (+ `apps/web/replay.py`)

한 화면. Streamlit 위젯 외 프런트 라이브러리 금지. 구성은 PRD §5 FR-10 그대로:

1. **상단**: 제목 + "HAZOP 60초 설명" 3~4문장(steering `domain.md` 용어 준수) + 데이터 출처 한 줄
   (NH3 QRA 전문가 HAZOP 34건 골드셋, 실데이터 없음).
2. **좌측**: 모드 라디오 `재생 (9/28 실측 결과)` / `실호출` + "NH3 벙커링 매니폴드 프리셋" 버튼
   + `NodeMeta` JSON 편집창(프리셋 값이 기본으로 들어감; 재생 모드에서는 읽기 전용 표시).
3. **우측**: 결과표 — 열 순서는 `core/export/rows.py` 의 워크시트 12열 그대로, `confidence` 는
   배지 색(grounded 초록 / inferred 노랑 / review 빨강; `export/xlsx.py::confidence_label` 의 문구
   재사용). 표 위에 요약 줄: 레코드 수 · 판정 셀 `judged/expected` · review 가이드워드 · 지연 ·
   비용 · (live 캡처면) recall 0.xx. **불리한 숫자도 그대로 표시**(NFR-03).
4. **다운로드 3개**: `export_all(records, tmp_dir, generated_at=captured_at, coverage=(expected, judged))`
   → xlsx · `lopa_draft.md` · `confidence_report.json`. `st.download_button` 에 파일 바이트를 넘긴다.
   임시 디렉터리는 `tempfile.mkdtemp()` — `results/` 에 쓰지 마라(재현성 규칙과 섞이지 않게).
5. **재생 모드**(기본): `apps/web/replay.py::load_replay(path)` 가 `data/replay/*.json` 중
   `source == "live"` 를 우선, 없으면 `gold` 를 고른다. `gold` 재생이면 화면 상단에 경고 배너
   "전문가 골드셋 재생 — LLM 생성 결과 아님". 로드 시 `DeviationRecord.model_validate` 로 복원.
6. **실호출 모드**: 다음이 **모두** 참일 때만 라디오가 활성화된다 — `HAZOP_ALLOW_LIVE=true`
   환경변수(또는 `st.secrets`), 그리고 `ANTHROPIC_API_KEY` 가 env 또는 `st.secrets` 에 존재.
   `st.secrets` 값은 **`os.environ` 으로 복사한 뒤** `get_bedrock_client()` 를 부른다(`core/llm` 은
   환경변수만 본다, AC-12-3). 버튼 옆에 "약 10분 · 약 $0.8 소요(9/28 실측)" 고정 문구.
   **상한**: 프로세스 전역 카운터로 **하루 5회**, `st.session_state` 로 **세션 1회**. 초과 시 버튼
   비활성 + 사유 표시. 실행 중 `st.spinner`, 예외는 `st.error(사유)` 로 보이고 앱은 죽지 않는다.
7. `HAZOP_USE_MOCK=true` 면 실호출 모드는 mock 으로 돈다(오프라인 시험용, 화면에 "mock" 표시).

구현 규칙:
- `apps/web/app.py` 첫 줄에서 리포 루트를 `sys.path` 에 넣어라. `pyproject.toml` 이
  `packages = []` 라 배포 환경에서 `core` 가 설치되지 않는다. `pathlib` 로 계산(불변규칙 8).
- 비즈니스 로직은 `apps/web/replay.py` 와 `apps/web/service.py`(모드 판정·상한·export 호출)에
  두고 `app.py` 는 위젯 배선만. **시험 가능한 코드는 `app.py` 밖에** 있어야 한다.
- 타입힌트·docstring·ruff clean(steering `engineering.md`).

### H-03 · 배포 파일 — `requirements.txt` · `Makefile` · `.streamlit/config.toml`

- 리포 루트 `requirements.txt`: `pyproject.toml` `dependencies` 와 **같은 버전 제약**으로 생성
  (streamlit 포함, `anthropic==1.7.0` 고정 유지). 상단 주석: "Streamlit Community Cloud 용 —
  정본은 pyproject.toml, 둘을 같이 고친다". `pytest`·`ruff` 는 넣지 않는다.
- `Makefile` 에 `demo` 타깃 추가(CLAUDE.md 환경 절에 이미 약속된 이름):
  `demo: ; $(VENV_PY) -m streamlit run apps/web/app.py`
  `capture-replay` 타깃도 추가(H-01 명령 그대로).
- `.streamlit/config.toml`: `[server] headless = true`, `[browser] gatherUsageStats = false`.
  `.streamlit/secrets.toml` 은 **만들지 말고** `.gitignore` 에 추가만.
- `.env.example` 에 `HAZOP_ALLOW_LIVE=false` 항목과 설명 한 줄 추가.

### H-04 · 오프라인 시험 — `tests/test_web.py` (네트워크 0회)

≥ 6건. `streamlit` 의 `AppTest`(`streamlit.testing.v1`) 를 쓰되, 없으면 `service.py`·`replay.py`
단위 시험으로 대체.

- (a) `load_replay` 가 `live` 파일을 `gold` 보다 우선한다(둘 다 있는 tmp 디렉터리로).
- (b) 재생 records 가 `deviation.schema.json` 을 100% 통과하고 `risk_score == S*F` 다.
- (c) 재생 → `export_all` 이 3개 파일을 만들고 xlsx 의 워크시트 행 수 == records 수.
- (d) 실호출 활성 판정: `HAZOP_ALLOW_LIVE` 없음 → 비활성 / 키 없음 → 비활성 / 둘 다 있음 → 활성.
- (e) 상한: 세션 1회 초과·일 5회 초과 시 거부 사유 문자열이 반환된다.
- (f) `HAZOP_USE_MOCK=true` + `HAZOP_ALLOW_LIVE=true` 로 실호출 경로가 mock 으로 끝까지 돈다
  (`MockBedrockClient` 에 `tests/test_generate.py` 의 `response_factory` 방식 재사용).
- (g) AppTest 가 되면: 앱 기동 → 프리셋 버튼 → 결과표 존재 → 예외 0건.

**결함 재삽입 3건**: (a) 우선순위 반전, (d) 키 검사 제거, (e) 상한 제거 — 시험이 실제로 깨지는지
확인하고 원복, 결과를 보고에 적어라.

### H-05 · 로컬 완주 확인 + 새 venv 리허설

1. `make demo` → 브라우저에서 프리셋 클릭 → 결과표 → xlsx 다운로드 → Excel 로 열림 확인.
   **첫 화면까지 걸린 시간을 재라**(목표 10초 이내).
2. **새 venv 리허설**(PRD §8 9/28 항 "제3자 실행 확인"): 임시 폴더에 `git clone` → 
   `python -m venv .venv && .venv/Scripts/pip install -r requirements.txt` →
   `streamlit run apps/web/app.py` 가 뜨는지. `-e .` 없이 되어야 Streamlit Cloud 에서도 된다.
   실패하면 그 원인을 고친다(대개 `sys.path` 또는 `data/replay` 경로).
3. 세션 1회 실호출은 H-01 캡처로 이미 썼다. **UI 의 실호출 버튼은 mock 으로만 확인**하고 실제로
   누르지 마라.

### 완료 보고 (`docs/진행로그.md` 에 추가)

변경·신규 파일 / `pytest` 결과(신규 시험 수 + 결함 재삽입 3건) / H-01 캡처 결과 표:
`source` · 지연 · 비용 · 절단 호출 수(4,096 대신 16,384 에 닿은 호출 수) · `judged/expected` ·
review 가이드워드 · recall(8건 대조표 포함, 9/28 run1 0.875 옆에 나란히) / 첫 화면 시간 /
새 venv 리허설 성공 여부 / 남은 리스크 4줄.

커밋은 사용자가 지시할 때만. 두 개로 나눈다:
1. `feat(FR-10) H-01 — 재생 캡처 도구 + data/replay/n1_20260928.json (source=<live|gold>)`
2. `feat(FR-10) H-02~H-05 — Streamlit 재생 데모·배포 파일·오프라인 시험`

## 붙여넣기 끝 (H)

---

## 이후 (참고 — 사람용)

| 시점 | 할 일 |
|---|---|
| H 완료 직후 (9/29 08:00~) | GitHub public 리포 생성 → push → Streamlit Community Cloud 연결(메인 파일 `apps/web/app.py`). secrets 에는 **아무것도 넣지 않는다**(재생 모드만 공개). 시크릿 창에서 프리셋 → xlsx 다운로드 확인. 실패 시 Hugging Face Spaces 1회 → 그래도 안 되면 리포 주소 + 실행 영상 + ZIP 을 배포 주소로(Q&A A1) |
| 9/29 11:30 | 제출 사이트 로그인만 먼저 테스트 |
| 9/29 오후 | **지시문 I**(README 9절 + 추적 매트릭스, 실호출 0회) — H 보고의 표를 §6 에 그대로 옮긴다. 소개서 10장은 Claude(이 대화)에서 PDF 로 만든다 |
| 본선 | 지시문 G(청크 병렬), 지시문 F(하네스), FR-05·06 |
