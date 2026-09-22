# 지시문 E — LLM 공급자 추상화(Anthropic API 어댑터) + T-07/T-08 실호출 (2026-09-15)

## 배경 (사람이 읽는 부분 — Claude Code에는 붙여넣지 않음)

- 9/15 확인: 대회 IAM Identity Center 포털(`d-9267fcca7f`)에는 **AWS 계정이 없고 Kiro 앱만** 있다. 대회 경로로는 Bedrock 자격증명이 나오지 않는다.
- 결정(9/15): **절충안**. 지금은 Anthropic API로 개발·측정(G1 판정)하고, 제출 전 개인 AWS Bedrock 계정으로 `models.yaml`만 바꿔 최종 지표를 다시 찍는다. 사무국 문의는 하지 않는다.
- 이 지시문은 두 세션으로 나눠 실행한다. **E-1**(어댑터, 오프라인 테스트) → 사람이 API 키 설정 → **E-2**(T-07 스모크 + T-08 recall). 한 세션에 하나만.

### 사람이 먼저 할 일 (E-1 세션 전)

1. `hazop-copilot/.git/index.lock` 삭제(9/11 세션에서 남은 0바이트 파일). 그다음 로컬 `.venv`(3.12)에서 `make test` → 142 passed 확인 → 9/11 export-formats 작업 커밋:
   `git add -A && git commit -m "spec:export-formats T-01~T-06 — xlsx·LOPA·신뢰도 리포트 내보내기 (손 작성 spec)"`
2. `.kiro/specs/bedrock-client/requirements.md` 끝에 아래 REQ-12를 **손으로 추가**(Kiro 크레딧 없이, 9/11 export-formats 선례). Claude Code는 requirements를 수정하지 못하므로 이게 없으면 "requirements에 없다"고 멈춘다.

```
### REQ-12 LLM 공급자 교체 (2026-09-15 추가)
WHEN `config/models.yaml` 의 `provider` 가 `anthropic` 이면 THE SYSTEM SHALL Anthropic Messages API 로
동일한 `converse()` 계약(시스템 프롬프트·메시지·tool·JSON 스키마 강제·재시도·토큰/비용/지연 로깅)을 수행한다.
WHEN `provider` 가 `bedrock` 이면 기존 `BedrockClient` 경로를 그대로 쓴다.
AC-12-1: `core/agent`·`core/export`·`tests` 의 기존 코드는 한 줄도 바뀌지 않는다(호출부는 `AbstractBedrockClient` 만 본다).
AC-12-2: 오프라인 테스트(`pytest -m "not live"`)는 `anthropic` 패키지의 네트워크 호출 없이 통과한다.
AC-12-3: API 키는 환경변수 `ANTHROPIC_API_KEY` 로만 읽고, 코드·yaml·로그에 나타나지 않는다.
AC-12-4: 프롬프트 캐싱은 `prompt_caching: true` 일 때 시스템 블록에 `cache_control: {"type": "ephemeral"}` 을 붙이는 것으로 대응한다.
AC-12-5: 429(rate limit)·529(overloaded)·5xx 는 기존 재시도 규칙(3회, 1→2→4s, 최대 10s)과 같은 로그 형식으로 재시도한다.
근거: 대회 제공 계정에 Bedrock 권한이 없어(docs/G0_bedrock_access_20260905.md, 9/15 포털 확인) 개발 기간 중
Anthropic API 로 측정하고 제출 전 Bedrock 으로 전환한다. README 비용 절에 공개한다.
```

3. 같은 spec의 `tasks.md` 표에 `T-15 | Anthropic 공급자 어댑터 (REQ-12) | ☐` 한 줄 추가.
4. Anthropic 콘솔에서 API 키 발급 → `hazop-copilot/.env`에 `ANTHROPIC_API_KEY=...` 기입(`.env`는 gitignore 대상인지 확인). 크레딧은 $5~10이면 이번 주 실측에 충분하다.

---

## 붙여넣기 시작 (E-1 세션)

작업 디렉터리: `C:\Users\user\Desktop\공모전\AWS_AI_Innovators\hazop-copilot`

`CLAUDE.md`, `PRD.md` §5 FR-02·§8, `.kiro/steering/aws.md`·`engineering.md`, `.kiro/specs/bedrock-client/requirements.md` **REQ-12**, `core/llm/*.py`, `tests/test_llm.py` 를 먼저 읽어라.

### 0단계 · 상태 검증 (먼저 이것만)

```bash
git log --oneline -3
git status --short
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m ruff check .
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -m "not live" -q
```

기대(**2026-09-22 갱신** — 9/22 정리 세션에서 커밋이 2개가 됐다):
최신 2개 커밋이 `0da8139 docs: PRD v2.0 … REQ-12·T-15 손 추가` / `bc02f1d spec:export-formats T-01~T-06`,
작업 트리 깨끗, ruff clean, **142 passed, 1 deselected**. 다르면 멈추고 차이를 보고하라.
`requirements.md` 에 REQ-12 가 없으면 코드를 쓰지 말고 멈춰라(9/22 추가 완료 — 있어야 정상).

`anthropic` 패키지는 아직 설치돼 있지 않다(9/22 확인). PyPI 접근은 가능하며 최신은 1.7.0.
`.env` 는 존재하지 않는다 — **2단계(모델 목록 조회)는 "미실행(키 없음)" 으로 건너뛰고 보고에 적어라.**

### 1단계 · 구현 — spec:bedrock-client T-15 (REQ-12)

파일은 아래 4개로 제한한다(압축 구현 원칙). 기존 `core/agent`·`core/export`·`tests/test_generate.py`·`tests/test_export.py` 는 수정하지 않는다.

1. **`core/llm/anthropic_client.py`** (신규) — `class AnthropicClient(AbstractBedrockClient)`.
   - `_do_converse()` 만 구현. `anthropic` SDK 의 `messages.create` 를 호출하는 지점은 `_call_messages()` 한 곳뿐(NFR-B04 와 같은 원칙).
   - 매핑: `system` → `[{"type":"text","text":system, ("cache_control":{"type":"ephemeral"} if prompt_caching)}]`; `Message`/`ContentBlock` → Anthropic 형식(`tool_use`·`tool_result` 블록 포함); `ToolDefinition` → `{"name","description","input_schema"}`; `response_schema` 가 있으면 `structured_output` tool 추가 + `tool_choice={"type":"tool","name":STRUCTURED_OUTPUT_TOOL}` (BedrockClient 와 동일한 승격 규칙 — tool input 을 `content` JSON 으로).
   - 사용량: `usage.input_tokens`·`output_tokens`·`cache_read_input_tokens`·`cache_creation_input_tokens` → `TokenUsage(input, output, cache_read, cache_write)`.
   - `stop_reason` 은 Anthropic 값을 그대로 둔다(`end_turn`·`tool_use`·`max_tokens`). 기존 테스트가 `end_turn` 을 기대하므로 매핑 불필요.
   - 비용: `CostCalculator.calculate(model_id, usage)` 재사용. 가격표는 `config/prices.yaml` 에 사용 모델 항목을 추가(값은 Anthropic 공식 가격 페이지 기준, 출처 주석 필수).
   - 재시도: `client.py` 의 `is_throttling_error()` 를 확장해 `anthropic.RateLimitError`·`anthropic.InternalServerError`·`APIStatusError(status 529)` 를 재시도 대상으로 포함. 로그 형식 `재시도 attempt=<n>/3 reason=<code>` 유지(reason 은 HTTP 상태코드 문자열). `anthropic` 미설치 환경에서도 `client.py` 가 import 되도록 `anthropic` import 는 `anthropic_client.py` 안에서만, 예외 클래스 판정은 클래스 이름 문자열 또는 지연 import 로 처리.
   - `model_short` 는 model_id 의 마지막 `-` 뒤 토큰 대신 전체 id 를 짧게 자른 값 — 로그 가독성만 목적.
2. **`core/llm/config.py`** — `provider: Literal["bedrock","anthropic"]` 필드 추가(`ModelConfig` 에도). 기본값 `bedrock`. `provider: anthropic` 이면 `region`·`embedding.model_id`·`guardrails` 는 **비어 있어도 통과**(Bedrock 전용 필드). `provider: bedrock` 검증 규칙은 현행 유지.
3. **`core/llm/__init__.py`** — `get_bedrock_client()`: `HAZOP_USE_MOCK=true` → Mock; 아니면 `load_model_config().provider` 로 분기. `AnthropicClient` export 추가.
4. **`tests/test_llm.py`** — 다음을 추가·수정:
   - `test_repo_config_is_pending_g0` 는 **삭제하고** `test_repo_config_provider_declared` 로 교체: 저장소 `models.yaml` 이 로드되고 `provider in {"bedrock","anthropic"}` 이며 `generation.model_id`·`verifier.model_id` 가 비어 있지 않음을 단언. 삭제 사유를 docstring 에 적는다("G0 대체 경로 확정, 2026-09-15").
   - `AnthropicClient` 오프라인 테스트 ≥ 6건: `_call_messages` 를 monkeypatch 한 가짜 응답으로 (a) 텍스트 응답 파싱, (b) structured_output tool → content 승격 + 스키마 통과, (c) tool_use 블록 파싱, (d) usage 4필드 매핑, (e) `prompt_caching` 에 따른 `cache_control` 유무, (f) 429 재시도 후 성공 / 3회 소진 시 `BedrockCallError`. **네트워크 호출 0회**.
   - 결함 재삽입 검증: (e)·(f)·structured 승격 3곳에 일부러 결함을 넣어 시험이 깨지는지 확인하고 원복. 결과를 보고에 적는다.
5. **`config/models.yaml`** — 상단 G0 경고 블록을 "2026-09-15: 대회 계정에 Bedrock 권한 없음 확인 → provider=anthropic 으로 개발, 제출 전 bedrock 전환" 3줄로 교체. `provider: anthropic` 추가. **모델 ID 는 추측해 넣지 마라** — 2단계에서 목록을 받아 사람이 고른다. 이 세션에서는 `null` 유지.
6. **`pyproject.toml`** — `anthropic` 의존성 추가, 버전 고정 + 이유 한 줄(CLAUDE.md 규칙 9). `.env.example` 에 `ANTHROPIC_API_KEY=<your-key>` 와 `# provider=anthropic 일 때만 필요` 주석 추가. `.gitignore` 에 `.env` 가 있는지 확인.
7. `docs/backlog.md` 가 없으면 만들고 한 줄: "제출 전 provider=bedrock 전환 + 개인 계정 Bedrock 모델 액세스 + prices.yaml Bedrock 항목 갱신 (9/24 목표)".

`models.yaml` 의 `generation.model_id` 가 `null` 인 동안 `test_repo_config_provider_declared` 는 실패한다. 이 세션에서는 그 테스트를 `pytest.mark.skipif(model_id is None)` 로 두지 말고, **2단계 완료까지 xfail(strict=False) 로 표시**하고 보고에 명시하라.

### 2단계 · 모델 목록 확인 (실호출 1회, 비용 0)

`.env` 에 `ANTHROPIC_API_KEY` 가 있을 때만: `anthropic.Anthropic().models.list()` 를 **1회** 호출해 사용 가능한 모델 ID 목록을 표로 출력하고 멈춰라. 사람이 생성용(상위)·verifier용(하위) 모델을 고른 뒤 `models.yaml` 에 기입한다. 키가 없으면 이 단계를 건너뛰고 보고에 "2단계 미실행(키 없음)" 이라고 적는다.

### 완료 보고 (4줄, `docs/진행로그.md` 에 추가)

변경 파일 / `pytest` 결과(신규 테스트 수 포함) / REQ-12 AC-12-1~5 충족 여부 / 실측 숫자(모델 목록 호출 1회 여부, 네트워크 호출 0회 확인 방법). 커밋은 사용자가 지시할 때만: `spec:bedrock-client T-15 — Anthropic 공급자 어댑터 (REQ-12)`.

## 붙여넣기 끝 (E-1)

---

## 붙여넣기 시작 (E-2 세션 — 사람이 `models.yaml` 모델 ID 기입 후)

작업 디렉터리: `C:\Users\user\Desktop\공모전\AWS_AI_Innovators\hazop-copilot`

`CLAUDE.md`, `.kiro/specs/hazop-generation/tasks.md` **T-07·T-08**, `core/agent/generate.py`, `data/gold/hazop_nh3_tune.json`, `data/gold/split_node.json` 을 읽어라.

### 0단계 · 검증

`git log --oneline -2` 가 `spec:bedrock-client T-15` 로 시작하고, `pytest -m "not live"` 전부 통과(xfail 0건 — `models.yaml` 이 채워졌으므로 `test_repo_config_provider_declared` 는 pass 여야 한다). `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -m live tests/test_llm_live.py -q` 를 **1회** 실행 — `test_smoke_live_converse` 는 `_has_credentials()` 가 AWS 만 보므로 skip 될 것이다. 이 함수를 `provider=anthropic` 이면 `ANTHROPIC_API_KEY` 유무로 판정하도록 고친 뒤 **다시 1회** 실행해 통과를 확인한다. 총 실호출 2회 이내.

### 1단계 · T-07 실호출 스모크

`tests/test_generate.py` 에 `@pytest.mark.live` `test_generate_live_n1` 추가. N1 `node_meta` 입력, 지연 ≤ 60초·레코드 ≥ 1·스키마 검증 100% 단언, 토큰·비용·지연을 로그로. **실행은 1회.** 60초를 넘기면 실패로 기록하되 재실행하지 말고 원인(호출 수·max_tokens)을 보고.

### 2단계 · T-08 G1 킬체크

`eval/` 은 아직 spec 이 없으므로 `tests/test_generate.py` 안에 `_recall_n1(generated, gold)` 함수로 둔다(T-08 문면 허용). 매칭: 가이드워드 정확 일치 + 파라미터 정규화(공백·조사 제거) 일치. recall = 매칭 골드 / 8. **실호출은 N1 생성 최대 3회**(프롬프트 수정 없이 3회 반복해 분산 확인 — 각 회 recall·비용·지연을 표로). 프롬프트를 고치지 마라 — 미달이면 어디가 안 맞는지(가이드워드 vs 파라미터 어휘) 골드 8건 × 생성 결과 대조표를 만들어 보고하고 멈춘다. 프롬프트 수정은 다음 지시문이다.

### 완료 보고 (4줄 + 표)

변경 파일 / pytest 결과 / T-07·T-08 완료 조건 충족 여부 / **실측 숫자**: 실호출 총 횟수, N1 3회 recall 평균·최소·최대, 노드당 비용(USD)·지연(초)·토큰. recall ≥ 0.5 이면 "G1 통과(9/23, Anthropic API 경로)" 라고 `docs/진행로그.md` 에 적고, 미달이면 대조표와 함께 "G1 미달 — 대조표 보고 후 정지. 프롬프트 수정 1회는 같은 날 별도 지시문(PRD v2.0 §8 9/23 행·R4)" 로 적는다. **이 세션에서 프롬프트를 고치지 마라**(2단계와 동일 — PRD 의 "미달 시 프롬프트 1회 수정·재측정"은 9/23 안에 하라는 뜻이지 E-2 세션 안에서 하라는 뜻이 아니다). 커밋: `spec:hazop-generation T-07~T-08 — 실호출 스모크 + N1 recall 실측`.

## 붙여넣기 끝 (E-2)

---

## 이후 (참고 — 사람용)

> **일정은 PRD v2.0 §8 이 정본이다.** 아래 표는 9/15 작성 당시 계획(9/16 실행 전제)을
> PRD v2.0 기준으로 옮긴 것. 9/15~9/22 공백(R11)으로 전체가 1주일 밀렸다.

| 시점 | 할 일 |
|---|---|
| 9/22 | E-1(어댑터·오프라인) — **완료**, 커밋 `0c9298f` |
| 9/23 | 키 설정 → E-2. G1 판정. 미달 시 프롬프트 1회 수정·같은 날 재측정 |
| 9/24 | evaluation-harness spec 손 작성 → 지시문 F(FR-08 하네스) → 홀드아웃 26건 실측 |
| 9/27 | 개인 AWS 계정 Bedrock 모델 액세스(us-east-1 또는 us-west-2, Claude 계열) → `check_bedrock_access.py` → `models.yaml` `provider: bedrock` 전환 → 하네스 3회 반복 최종 지표 |
| README 비용 절 | "개발 기간(9/22~9/27) Anthropic API 사용 $X, 최종 평가·데모 Bedrock $Y" 로 공개 |
