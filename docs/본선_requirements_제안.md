# 본선 requirements 변경 제안 (F-01 · F-02 · F-04 · F-05)

작성 2026-10-08 · 상위 `docs/PRD_본선_고도화.md` · **이 문서는 제안이다.** `.kiro/specs/*/requirements.md` 는 이 세션에서 읽기 전용이므로(CLAUDE.md) 사용자가 Kiro(또는 손 작성)로 반영한 뒤 T-xx 지시가 오면 구현한다.

---

## 0. 먼저 — PRD F-02 의 전제가 데모 경로와 맞지 않는다

PRD F-02 는 `HazopGenerator.generate()` 에 `on_batch` 를 달아 **가이드워드 묶음이 끝날 때마다** 행을 늘리고, G2 로 "**15초 안에 첫 레코드**"를 요구한다. 그런데:

1. 발표·부스에서 누르는 **직접 입력 빠른 실호출은 `generate()` 를 거치지 않는다.** `apps/web/service.py:373` `run_quick` 이 `_enumerate_parameters` → `_generate_batch`(가이드워드 **1개**) → `_assemble` 을 직접 부른다. 가이드워드가 하나라 "묶음마다 갱신"할 묶음이 하나뿐이다 — on_batch 를 달아도 첫 행은 지금과 같은 시각에 뜬다.
2. 실측(J-03, `docs/진행로그.md:682`): **열거 22초 + 판정 41초 = 63.6초**, 해석 약 3초가 앞에 붙는다. 열거 호출 하나가 이미 15초를 넘으므로 **어떤 조립 방식으로도 첫 레코드 ≤15초는 현재 모델 구성에서 불가능**하다.
3. on_batch 가 실제로 효과를 내는 곳은 **노드 전체 실호출**(`run_live`, 가이드워드 7~10종, 약 150초)뿐이다. 이 버튼은 `HAZOP_LIVE_SCOPE=full` 일 때만 보이고 PRD 도 "발표 중 실행 불가, 재생으로"라고 적었다.

→ 제안: G2 를 **단계 표시**로 바꾼다(아래 R-11). 발표는 대본이 64초를 설명 시간으로 덮도록 짰으므로(`docs/본선_F03_발표패키지.md`) F-02 없이도 G3 에 지장이 없다. F-02 의 실익은 부스 대기 화면 쪽이다.

**PRD G2 수정안**: "실행 버튼 후 **5초 안에 해석된 노드 정보**, **30초 안에 파라미터 축 목록**이 화면에 뜨고, 판정이 끝나면 표가 채워진다(빠른 실호출). 노드 전체 실호출은 가이드워드 판정이 끝날 때마다 행이 늘어난다."

---

## 1. bedrock-client REQ-13 · 대회 제공 게이트웨이 (F-01)

> REQ-12 는 `provider ∈ {anthropic, bedrock}` 만 정의한다. 게이트웨이 키가 오면 어느 쪽에도 정확히 맞지 않을 수 있어 별도 항목으로 둔다.

**코드 확인 결과 — Anthropic 형식이면 공급자를 새로 만들 필요가 없다.** `core/llm/anthropic_client.py:87` 은 `anthropic.Anthropic()` 을 인자 없이 만든다. SDK 는 `ANTHROPIC_BASE_URL`·`ANTHROPIC_API_KEY`(헤더 `x-api-key`)·`ANTHROPIC_AUTH_TOKEN`(헤더 `Authorization: Bearer`)을 환경변수에서 읽으므로, 게이트웨이가 Anthropic 형식이면 **환경변수 + `models.yaml` 의 `model_id` 두 줄 + `prices.yaml` 키 추가**로 끝난다. 그래서 REQ-13 은 `provider: anthropic` 의 확장으로 쓴다:

**WHEN** `provider` 가 `anthropic` 이고 환경변수 `ANTHROPIC_BASE_URL` 이 있으면,
**THE SYSTEM SHALL** 그 엔드포인트로 REQ-12 의 `converse()` 계약을 그대로 수행하고, 화면 출처 줄에 "대회 제공 API" 를 표시한다.

이때 필요한 코드 변경은 두 곳뿐이다:
- `apps/web/service.py:61` `SECRET_KEYS` 에 `ANTHROPIC_BASE_URL`·`ANTHROPIC_AUTH_TOKEN` 추가 — 빠지면 Secrets 값의 앞뒤 공백 정리(9/29 배포 401 원인)가 안 된다.
- `live_block_reason`(`service.py:157`)이 `ANTHROPIC_API_KEY` 만 본다 — Bearer 형식이면 `ANTHROPIC_AUTH_TOKEN` 도 키로 인정해야 실호출 버튼이 열린다. `key_hint` 의 접두사 진단도 게이트웨이 키엔 오경보를 낼 수 있다.

**WHEN** 게이트웨이가 OpenAI 형식이면,
**THE SYSTEM SHALL** `core/llm/` 의 어댑터 1개로 같은 계약을 수행하고, JSON 스키마 강제는 function calling 의 `parameters` 로 옮기며 응답은 기존 `jsonschema` 검증을 그대로 거친다.

- AC-13-1: 직결 Anthropic 경로는 지우지 않는다 — 환경변수·`model_id` 만으로 9/29 상태 복귀.
- AC-13-2: 게이트웨이 모델 ID(`bedrock-claude-opus-4-8` 등)를 `config/prices.yaml` 에 등재한다. 단가는 운영사 고지값, 없으면 대응 Anthropic 모델 단가를 쓰고 주석에 "추정"을 적는다.
- AC-13-3: sampling 파라미터는 싣지 않는다(REQ-12 판단 유지).
- AC-13-4: 화면 출처 줄은 운영사가 Bedrock 경유를 **확인해 준 뒤에만** "Amazon Bedrock 경유(대회 제공)"로, 그 전엔 "대회 제공 API"로 표시한다.
- AC-13-5: `@pytest.mark.live` 스모크 1건 — 키 환경변수가 없으면 skip.
- AC-13-6: 키는 환경변수로만 읽고 코드·yaml·로그에 나타나지 않는다.

**키 수령 직후 탐침 절차(코드 변경 전, 사람 또는 이 세션):**
1. 운영사 안내문에서 엔드포인트 URL·인증 헤더 형식을 먼저 읽는다(문서가 있으면 탐침 불필요).
2. 없으면 `POST {base}/v1/messages`(Anthropic 형식, 헤더 `x-api-key`)와 `POST {base}/v1/chat/completions`(OpenAI 형식, `Authorization: Bearer`)에 "안녕하세요" 1회씩. 200 이 나온 쪽이 형식이다.
3. Anthropic 형식이면 core/llm 코드 변경 0, `apps/web/service.py` 두 곳 + config 뿐이다 — 이틀이 아니라 반나절 작업. 되돌리기는 `ANTHROPIC_BASE_URL` 을 지우고 `model_id` 를 되돌리는 것(AC-13-1).
4. tool use(`tool_choice` 강제)가 통과하는지 같은 날 1회 확인 — 게이트웨이가 tool 필드를 떨어뜨리면 R1 리스크 현실화.

## 2. hazop-generation R-11 · 생성 진행 단계 표시 (F-02 수정안)

**WHEN** 직접 입력 빠른 실호출을 실행하면,
**THE SYSTEM SHALL** ① 입력 해석 결과(NodeMeta) ② 열거된 파라미터 축 목록 ③ 판정 결과 표를 각 단계가 끝나는 즉시 화면에 표시한다.

**WHEN** 노드 전체 실호출을 실행하면,
**THE SYSTEM SHALL** `HazopGenerator.generate(node_meta, on_batch=None)` 의 선택 콜백으로 가이드워드 판정이 끝날 때마다 `(완료 가이드워드 수, 전체 수, 지금까지의 레코드)` 를 알리고, 화면은 "가이드워드 k/n 판정 완료"와 부분 표를 갱신한다.

- AC-11-1: 최종 레코드 순서·`id` 는 콜백 유무와 무관하게 같다(R-10 AC-10-1, 골든 스냅샷 유지).
- AC-11-2: 콜백은 메인 스레드에서만 호출되고, 비용·review 합산도 메인 스레드에 남는다(AC-10-3, O-1 AST 구조 시험 유지).
- AC-11-3: 콜백 예외는 생성을 중단시키지 않는다(로그 후 계속).
- AC-11-4: 빠른 실호출 경로는 이 기회에 `HazopGenerator.generate_quick(node_meta, guideword, on_stage=None)` 공개 API 로 승격해 `service.run_quick` 의 비공개 메서드 의존 3곳을 없앤다(`docs/backlog.md` 기존 항목).
- 비목표: 판정 호출 스트리밍, 파라미터 청크 분할(`max_parameters_per_call`) — 판정 41초를 줄이려면 청크 분할이 유일한 길이지만 호출 수·비용이 늘고 순서 불변식을 다시 증명해야 한다. 10/14 G1·G2 통과 뒤 여력이 있을 때만 별도 R 로.

T 분할안: T-10 `generate(on_batch)` + `as_completed` 전환 + 시험 / T-11 `generate_quick(on_stage)` 승격 + `run_quick` 교체 / T-12 화면 단계 표시(apps/web).

## 3. FR-10 부스 모드 (F-04) — apps/web 범위

> UI(FR-10)는 spec 이 따로 없고 PRD·지시문으로 관리돼 왔다(지시문 H·J·M·U). 같은 방식이면 `docs/지시문_V_부스모드.md` 한 장으로 충분하다.

- `?booth=1` 일 때만: 큰 글씨, 예시 칩 3개를 일반 관람객 문장으로 교체, 생성 진행 중 버튼 잠금(쿨다운), 대기 중 사고 사례 카드 순환.
- 상한: 부스 모드에서 세션 상한 미적용, 일 상한은 Secrets `HAZOP_DAILY_LIMIT` 로 당일만 상향(예: 60).
- **알려진 한계(PRD R4 그대로)**: 일 상한은 프로세스 메모리 카운터라 재시작하면 0 — 부스 당일 Streamlit 재부팅이 나면 상한이 풀린다. 키 한도(Q3)가 작으면 이게 예산 초과 경로다.
- 수용: AppTest 로 `?booth=1` 유무에 따라 칩 문구가 바뀌고, 기본 화면 스냅샷은 무변경.

## 4. export-formats R-10 · 검토 열 (F-05)

**WHEN** 사용자가 결과 표에서 행의 `검토` 를 `채택`·`기각`·`수정` 중 하나로 정하면,
**THE SYSTEM SHALL** xlsx 의 HAZOP워크시트 시트에 `검토` 열을 추가하고, `기각` 행은 별도 시트 `기각` 으로 옮기며, LOPA 초안은 `기각` 이 아닌 행만으로 만든다.

- AC-10-1: 검토값이 하나도 없으면 xlsx 의 **시트·열 구조가 지금과 같다**(골든 스냅샷 유지 — 검토 열은 값이 있을 때만).
- AC-10-2: `수정` 행은 편집된 셀 값으로 내보내고 `수정됨` 표시를 남긴다. 위험도는 편집된 S·F 로 코드가 다시 계산한다(R-05 원칙).
- AC-10-3: AppTest 로 1행 기각 → `기각` 시트 1행, 본 시트에서 빠짐.
- 비목표: 서명·이력·다중 사용자.

> AC-10-1 은 판단이 필요하다: 검토 열을 항상 넣으면 골든 스냅샷이 바뀌고, 값이 있을 때만 넣으면 시트 구조가 입력에 따라 달라진다. 제안은 후자(기존 스냅샷 보존).

---

## 5. 지금(10/8) 이 세션이 한 것 / 막힌 것

| 항목 | 상태 |
|---|---|
| F-01 | 키 미수령. **키 없이 할 수 있는 건 끝냄**(아래 §6) — 남은 건 키를 Secrets 에 넣고 실호출 3회 |
| F-02 | **requirements 미반영으로 코드 착수 불가**(CLAUDE.md). R-11 수정안 작성, PRD G2 전제 오류 보고 |
| F-03 | `docs/본선_F03_발표패키지.md` 초안 — 대본·대체 경로·Q&A 10문 |
| F-04·F-05 | P0 완료 전 착수 금지(PRD §6). 제안 문안만 |
| F-06 | 착수 안 함(P2) |

---

## 6. 키 없이 끝낸 F-01 준비 (10/8 오후, 미커밋)

| 항목 | 내용 | 확인 |
|---|---|---|
| `tools/fake_gateway.py` | 127.0.0.1 에서 Anthropic Messages 형식으로 답하는 가짜 게이트웨이(응답은 재생 레코드). `--latency real`(해석 3·열거 22·판정 41초), `--fail 529:3` | 실 SDK·`AnthropicClient`·`run_quick` 를 그대로 탐 |
| `apps/web/service.py` | `SECRET_KEYS` 에 `ANTHROPIC_BASE_URL`·`ANTHROPIC_AUTH_TOKEN`·`HAZOP_ENDPOINT_LABEL` · `live_block_reason` 이 Bearer 키도 인정 · `key_hint` 가 게이트웨이 키엔 `sk-ant-` 오경보 안 냄 · 출처 줄에 "· 대회 제공 API 경유"(라벨은 Secrets 로 교체 — Bedrock 확인 뒤 `HAZOP_ENDPOINT_LABEL`) | — |
| `config/prices.yaml` | 신청 모델명 3개 선등재(단가는 대응 Anthropic 모델 **추정**) | `load_price_table` 로드 확인 |
| `tests/test_gateway.py` | 4건 — x-api-key·Bearer 양 형식, `tool_choice` 전달, temperature 미전송, 모델 ID 전달, Secrets 공백 정리, 기본 엔드포인트 명시는 직결 취급 | 결함 재삽입 4종 전부 잡힘 · 전체 272 passed · ruff clean |
| 화면 리허설 | Streamlit(1440×900) → 가짜 게이트웨이(실측 지연) → 직접 입력 생성 | **70초**, 출처 줄 "대회 제공 API 경유" 표시, 레코드 10·판정 12/12 |

**키 수령 당일 할 일**(코드 변경 없음): Secrets 에 `ANTHROPIC_BASE_URL` + 키(형식에 따라 `ANTHROPIC_API_KEY` 또는 `ANTHROPIC_AUTH_TOKEN`) → `config/models.yaml` 의 `generation.model_id`·`verifier.model_id` 두 줄 → 배포 실호출 3회(G1). OpenAI 형식일 때만 어댑터 작업이 생긴다.

**새로 찾은 것**
1. **실패 1회 = HTTP 요청 9회.** SDK 기본 재시도 2회가 `bedrock_retry` 3회 안에 중첩된다(529 상시 실패로 실측: 9요청·9.1초 후 `BedrockCallError`). 실패 상자까지 9초라 발표엔 문제없지만, 대회 키가 **요청 수로 한도를 세면 장애 때 3배로 깎인다.** 고치려면 `anthropic.Anthropic(max_retries=0)` — `core/llm` 변경이라 bedrock-client REQ-12 AC-12-5 개정이 필요.
2. **화면 단계 표시는 가짜다.** `app.py:263` "1/3 문장을 노드 입력으로 해석"이 생성 내내(약 66초) 떠 있고, "2/3 열거"·"3/3 판정"은 **전부 끝난 뒤에** 한꺼번에 찍힌다(`app.py:286-287`). R-11 의 단계 표시가 이 자리를 진짜로 바꾸는 것이다.
3. 빈 결과 칸 문구 "1분 안에 여기에 워크시트가 나타납니다"는 실측(64~70초)과 맞지 않는다 — 버튼 라벨의 "약 1분"은 맞다. 한 단어 수정(FR-10 문구).
4. 이 PC 의 셸에 `ANTHROPIC_BASE_URL=https://api.anthropic.com` 이 이미 설정돼 있다. 기본 엔드포인트 명시는 직결로 보도록 처리했다(안 하면 기존 시험 1건이 깨졌다).