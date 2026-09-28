# 지시문 G — 매트릭스 청크 분할 + 병렬 호출 (2026-09-28)

## 배경 (사람이 읽는 부분 — Claude Code 에는 붙여넣지 않음)

9/28 E-2 실측 결과(`docs/진행로그.md` 2026-09-28 항):

- **G1 미달 — N1 recall 평균 0.417.** 단 파이프라인이 완주한 run1 은 **0.875** 였다.
- 원인은 모델 능력이 아니라 **`max_tokens: 4096` 절단**이다. 출력이 정확히 4,096 에 닿은 호출
  11 회가 11 회 모두 `content=None` 으로 끝났고, 4,096 미만은 한 번도 아니었다. 파라미터 축이
  10 → 11 → 12 로 늘수록 붕괴 가이드워드가 0 → 5 → 6 종으로 단조 증가했다.
- 지연도 실패다: 노드 612~832 초 (R-09 기준 60 초의 10~14 배). 노드당 $0.713~$0.790
  (소프트 상한 $0.30 의 2.4~2.6 배).

갈래 3 개(① max_tokens 상향 ② 파라미터 단위 분할 + 병렬 ③ maxItems 하향) 중 **②를 선택**했다.
①·③은 절단은 막아도 **지연 60 초를 못 푼다** — 총 출력 토큰량(약 26,000)이 내용에서 오는 값이라
순차로는 줄지 않기 때문이다. ②만이 절단과 지연을 동시에 푼다.

### R-04 와의 충돌 — 사람이 먼저 해결해야 한다

R-04 는 두 가지를 못 박고 있다:

1. "가이드워드 단위로 LLM 호출하여 열거된 파라미터 **전부**와의 조합을 빠짐없이 판정한다"
2. "가이드워드 행을 **순차 호출**한다. 병렬 호출 여부는 지연 실측(G0 완료) 후 결정한다"

②는 (1) 과 정면충돌한다. (2) 는 **실측 후 결정하라고 유보해 둔 항목**이고 그 실측이 끝났으므로
지금이 결정 시점이다. Claude Code 는 `requirements.md` 를 수정하지 못하므로(CLAUDE.md), 아래
R-10 을 **손으로 추가**해야 한다. 없으면 G 세션은 "requirements 에 없다"며 멈춘다.

### 사람이 먼저 할 일 (G 세션 전)

1. `.kiro/specs/hazop-generation/requirements.md` 끝에 아래 R-10 을 손으로 추가
   (REQ-12/T-15 선례와 동일한 방식).

```
### R-10 매트릭스 청크 분할 및 병렬 호출 (2026-09-28 추가 — R-04 의 유보 항목 결정)

WHEN 노드의 가이드워드 × 파라미터 매트릭스를 판정할 때 THE SYSTEM SHALL 한 번의
`deviation_generate` 호출이 담당하는 파라미터 수를 `max_parameters_per_call` 이하로 제한하고,
그렇게 쪼갠 (가이드워드 × 파라미터청크) 단위를 최대 `max_concurrency` 개까지 동시에 호출한다.

R-04 의 "파라미터 전부를 한 호출로" 와 "가이드워드 행을 순차 호출한다" 는 이 요구사항으로
대체된다. R-04 의 나머지(가이드워드 7종 고정, 절차형 3종 조건부, applicable=false 반환,
열거≠판정 시 WARNING 후 계속)는 그대로 유효하다.

AC-10-1: 동일 입력에 대해 생성 레코드의 순서와 `id` 가 **호출 완료 순서와 무관하게** 결정적이다
         (가이드워드 축 순서 → 파라미터 열거 순서로 정렬 후 부여).
AC-10-2: `max_parameters_per_call`·`max_concurrency` 는 `config/models.yaml` 에서만 읽는다
         (코드 하드코딩 금지 — CLAUDE.md 정본 사슬).
AC-10-3: 비용·판정셀 수·review 집계가 병렬 실행에서 유실되지 않는다(경합 없음).
AC-10-4: 오프라인 테스트(`pytest -m "not live"`)가 자격증명·네트워크 없이 통과한다.
AC-10-5: `max_concurrency: 1` 로 두면 기존 순차 동작과 동등한 결과를 낸다(동일 레코드 집합).

근거: 9/28 실측에서 출력 절단 11/11 이 content=None 으로 끝났고 노드 지연이 기준의 10~14배였다
(docs/진행로그.md 2026-09-28). 총 출력 토큰량은 내용에서 오는 값이라 순차로는 줄지 않는다.
```

2. 같은 spec 의 `tasks.md` 체크리스트 표에 한 줄 추가:
   `| T-09 | 매트릭스 청크 분할 + 병렬 호출 (R-10) | 일부 | ☐ |`

3. `config/models.yaml` 은 **G 세션이 고친다** — 사람이 미리 건드리지 말 것.

---

## 붙여넣기 시작 (G 세션)

작업 디렉터리: `C:\Users\user\Desktop\공모전\AWS_AI_Innovators\hazop-copilot`

`CLAUDE.md`, `docs/진행로그.md` 의 **2026-09-28 항 전체**,
`.kiro/specs/hazop-generation/requirements.md` 의 **R-04·R-09·R-10**,
`core/agent/generate.py`, `core/llm/{client,anthropic_client,mock}.py`, `tests/test_generate.py`
를 먼저 읽어라.

### 0단계 · 상태 검증 (먼저 이것만)

```bash
git log --oneline -3
git status --short
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m ruff check .
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -m "not live" -q
```

기대: ruff clean, **162 passed / 3 deselected / xfail 0건**.
`requirements.md` 에 **R-10 이 없으면 코드를 쓰지 말고 멈춰라.**
`config/models.yaml` 의 `generation.model_id` 는 `claude-opus-4-8`, `verifier.model_id` 는
`claude-haiku-4-5` 여야 한다(9/28 확정). 다르면 멈추고 보고.

### 1단계 · 구현 — spec:hazop-generation T-09 (R-10)

수정 파일은 **3개로 제한**한다: `core/agent/generate.py`, `config/models.yaml`,
`tests/test_generate.py`. `core/llm/*` 과 프롬프트 파일(`core/agent/prompts/*`)과
`schemas/*` 는 **한 줄도 고치지 마라** — 이번 변경은 호출 단위 문제이지 프롬프트·스키마 문제가
아니다(9/28 실측이 그렇게 말한다).

1. **`config/models.yaml`** — `generation` 아래 두 키 추가. 값의 근거를 주석으로 남길 것.
   ```yaml
   max_parameters_per_call: 3   # 9/28 실측: 셀당 출력 ≈ 372 tokens → 3셀 ≈ 1,100 < 4,096
   max_concurrency: 8           # 총 출력 ≈ 26,000 tokens ÷ 60초 목표 ÷ 약 65 tok/s ≈ 7
   ```
   **`max_tokens` 는 4096 그대로 둔다.** 한 번에 두 변수를 바꾸면 ②의 효과를 분리해 잴 수 없다.
   절단이 그래도 나면 그게 결과다.

2. **`core/llm/config.py` 는 고치지 않는다.** 이 두 값은 `ModelProfile` 이 아니라
   `core/agent/generate.py` 의 `GeneratorConfig`·`load_generator_config()` 가 읽는다
   (이미 `models.yaml` 을 읽고 있다). `core/llm` 은 Bedrock/Anthropic 계약만 책임진다.

3. **`core/agent/generate.py`** — `generate()` 의 가이드워드 루프를 교체한다.
   - `_chunk_parameters(parameters, size)` → 파라미터를 순서 보존하며 size 단위로 분할.
   - 작업 단위는 `(gw_index, chunk_index, guideword, chunk)`. `_enumerate_parameters` 는
     **순차 유지**(결과가 있어야 작업 목록이 나온다). 이 첫 호출이 `AnthropicClient._sdk()` 의
     지연 생성도 끝내주므로 풀 시작 시점에 SDK 클라이언트 경합이 없다 — 이 순서를 바꾸지 마라.
   - `concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency)` 로 팬아웃.
     `asyncio` 를 쓰지 마라(동기 SDK 이고 호출부 전체가 동기다).
   - **워커는 순수 함수로 두고 `self` 를 쓰지 마라.** `self.total_cost_usd += ...` 는 원자적이지
     않다(AC-10-3). 워커는 `(key, batch_or_None, cost, review_flag)` 를 반환하고,
     **메인 스레드가 모아서 합산**한다.
   - **결정성(AC-10-1)**: 모은 결과를 `(gw_index, chunk_index)` 로 **정렬한 뒤** `_assemble` 에
     넘긴다. 완료 순서로 조립하면 `id` 가 실행마다 달라져 재현성(CLAUDE.md 불변규칙 6)이 깨진다.
     **이게 이번 태스크 1순위 함정이다.**
   - `max_concurrency: 1` 이면 풀을 만들지 말고 그대로 순차 실행(AC-10-5).

4. **`review_guidewords` 의 의미가 바뀐다.** 지금은 "행 전체가 죽었다" 이지만 청크 분할 후에는
   한 청크만 죽을 수 있다. `review_cells: list[tuple[str, str]]`(가이드워드, 파라미터)로 바꾸고,
   기존 이름은 **호환 property 로 남겨라** — `.kiro/specs/evaluation-harness` 가
   `review_guideword_rate` 를 지표로 쓰기로 돼 있다(9/23 로그). 그 spec 을 깨지 마라.
   호환 property 는 "청크가 하나라도 죽은 가이드워드" 의 중복 제거 목록으로 정의한다.

5. **비용 상한 검사.** `_check_node_cost` 는 여전히 사후 1회다. 호출 수가 8 → 최대 1+7×ceil(N/3)
   (N=12 면 29)로 늘어 폭주 시 감지 전 지출이 커진다. **이번 태스크에서는 고치지 말고**
   완료 보고에 "사후 검사 한계" 로 적어라(범위 확대 금지).

### 2단계 · 오프라인 시험 (`tests/test_generate.py`)

기존 시험 중 **호출 수를 세는 2곳이 반드시 깨진다.** 고치되, 의미를 유지하라:

- `test_...:171` `len(client.calls) == 1 + len(STANDARD_GUIDEWORDS)` → `1 + 7*ceil(N/K)`.
- `test_...:202` `== 1 + 10` → 절차형 10종 기준으로 같은 식.
- `client.calls[1:]` 를 쓰는 곳(:286)은 **집합 비교라 병렬에서도 안전**하다 — 확인만 하고 두라.
- `MockBedrockClient._responses.pop(0)` 는 순서 의존이라 병렬에서 매핑이 흔들린다.
  `tests/test_generate.py` 는 `response_factory`(내용 기반 분기)를 쓰므로 안전하지만,
  **factory 가 시스템 프롬프트로만 분기하면 청크를 구분하지 못한다.** 사용자 턴에서
  가이드워드·파라미터를 읽어 분기하도록 고쳐라.

추가할 시험 ≥ 5건 (전부 오프라인, 네트워크 0회):
- (a) **결정성**: 같은 입력으로 2회 생성 시 `[r.id for r in records]` 와 `(가이드워드, 파라미터)`
  순서가 완전히 같다. mock 에 **의도적으로 들쭉날쭉한 지연**을 넣어 완료 순서를 뒤섞어라
  (지연 없이 통과하는 시험은 이 결함을 못 잡는다).
- (b) **동등성(AC-10-5)**: `max_concurrency: 1` 과 `8` 의 레코드 집합이 동일하다.
- (c) **청크 경계**: N=7, K=3 일 때 청크가 3/3/1 로 쪼개지고 호출당 파라미터 수가 K 를 넘지 않는다.
- (d) **부분 실패**: 한 청크만 `content=None` 일 때 같은 가이드워드의 다른 청크는 살아남고,
  `review_cells` 에 그 청크의 파라미터만 들어간다.
- (e) **집계 무결(AC-10-3)**: 병렬 실행 후 `total_cost_usd` 가 주입한 비용의 정확한 합이고
  `judged_cells` 가 유실 없이 맞는다.

**결함 재삽입 검증 필수** — (a) 정렬 제거, (d) 부분실패 처리 제거, (e) 락/리듀스 제거 3곳에
일부러 결함을 넣어 시험이 실제로 깨지는지 확인하고 원복하라. 결과를 보고에 적어라.
(통과만 확인하는 건 검증이 아니다.)

### 3단계 · 실측 — **게이트 방식, 단계마다 멈춘다**

실호출 예산 **총 4회**(노드 생성 4건). 프롬프트·`max_tokens` 를 고치지 마라.

- **게이트 1 (1회)**: `test_generate_live_n1` 실행. 확인 항목 3개를 표로 보고하고 **멈춘다**:
  ① 출력이 4,096 에 닿은 호출 수(목표 0) ② 노드 지연(목표 ≤ 60초) ③ 노드 비용.
  - 지연이 60초를 넘으면 **재실행하지 말고** `max_concurrency` 를 올렸을 때의 예상치를
    실측 기반으로 계산해 보고하라(총 출력 토큰 ÷ 실측 tok/s ÷ 동시성).
  - 절단이 그래도 나면 K 를 더 줄여야 한다는 뜻이다. **그 판단은 사람이 한다.**
- **게이트 2 (3회)**: 게이트 1 통과 시에만 `test_recall_live_n1_x3` 실행 → G1 재판정.

백그라운드 실행 시 **출력을 파일로 흘려라**(`> log 2>&1`). `tail` 파이프는 프로세스가 죽을 때
로그를 통째로 잃는다. 그리고 `; echo "EXIT=$?"` 를 붙이지 마라 — 셸 종료코드가 `echo` 것이 돼
**실패한 pytest 가 "exit code 0" 으로 보고된다**(9/28 실제로 당함). 판정은 로그로 하라.

### 완료 보고 (`docs/진행로그.md` 에 추가)

변경 파일 / `pytest` 결과(신규 시험 수 + 결함 재삽입 3건 결과) / AC-10-1~5 충족 여부 /
**실측 표**: 절단 호출 수·노드 지연·노드 비용·recall(회차별·평균·최소·최대)·실호출 총 횟수.
9/28 수치와 **같은 표에 나란히** 놓아 개선폭을 보이게 하라. 불리해도 그대로 쓴다(PRD NFR-03).

커밋은 사용자가 지시할 때만: `spec:hazop-generation T-09 — 매트릭스 청크 분할 + 병렬 호출 (R-10)`.

## 붙여넣기 끝 (G)

---

## 이후 (참고 — 사람용)

| 시점 | 할 일 |
|---|---|
| G 완료 후 | G1 재판정. 통과 시 지시문 F(FR-08 하네스, 실호출 0회)와 합류 → 홀드아웃 26건 실측 |
| 미통과 시 | 남은 갈래는 ①(max_tokens 상향)·③(maxItems 하향)과 **프롬프트 1회 수정**(PRD §8) |
| 제출 전 | `provider: bedrock` 전환 + 개인 계정 모델 액세스 + `prices.yaml` Bedrock 항목 갱신 |

**열어둔 질문 2개** (G 세션에서 답이 나오면 진행로그에 적을 것):

1. **청크 분할이 HAZOP 품질을 떨어뜨리는가?** 파라미터 전부를 한 맥락에서 보던 모델이 3개씩만
   보게 된다. 셀 간 일관성(같은 원인·방호가 중복 서술되는지)이 나빠질 수 있다. recall 로는
   안 잡히는 축이므로, 게이트 2 산출물에서 **중복 서술 여부를 눈으로** 확인하고 적어라.
2. **동시성이 재현성에 주는 영향.** 레코드 순서는 정렬로 결정적이게 만들지만 모델 출력 자체는
   여전히 비결정적이다(temperature 미전송·시드 없음). 9/23 로그의
   `model_output_deterministic: false` 는 유효하며, 3회 반복 분산이 그 지표다.
