# 지시문 O — 제출 D-0 최종 스프린트: 코드 변경 허용, 점수 최대화 (2026-09-29 14:00 → 코드 동결 19:00 → 제출 21:00)

## 배경 (사람이 읽는 부분 — Claude Code 에는 붙여넣지 않음)

최종평가(`docs/최종평가_20260929.md`)의 결론은 "코드를 안 바꾸면 49 → 53". 이 지시문은 **코드를 바꿔서** 그 위를 노린다.
남은 7시간에 점수를 실제로 움직이는 코드 변경은 세 개뿐이고, 나머지는 문서다.

| 단계 | 무엇 | 올라가는 항목 | 예상 | 위험 | 킬 시각 |
|---|---|---|---|---|---|
| O-1 | 가이드워드 판정 **병렬화** (지시문 G 초안 실현) — 노드 7~9분 → 1.5~2.5분 | 기술 30 (NFR-06 "성능"), 완성도 30 (실호출 체감) | +2~3 | 중 — `core/agent/generate.py` 변경, 스레드 안전 | 15:45 미완이면 revert |
| O-2 | **재캡처 P2·P1(·N1)** — M-01 + 병렬 적용 결과로 재생 교체 | 실무자(P-1 Before 채움, "M-01 이전" 배지 소멸), 기술(지연 실측) | +1~2 | 저 — 도구 그대로, 비용 ≈ $2.4 | 크레딧 부족·실패 2회면 중단 |
| O-3 | **verifier 시연 토글** — 결함 1건 삽입 → 🔴 review 행이 화면에 보임 | 완성도(심사위원이 정직 장치를 눈으로 봄) | +1 | 저 — `apps/web` 만 | 16:30 |
| O-4 | (삭제 — 9/29 14:10 사용자 결정: Bedrock 은 README·소개서·화면 문구에서 빼고 §4 표 1행만 남긴다. 개인 계정 실호출도 하지 않는다) | — | — | — | — |
| O-5 | 문서 정합: README 빈칸·docx 표기·§6 갱신·**Bedrock 문구 제거**·tasks ☑·models.yaml 주석·`.gitignore` | 코드 10, 접근 10 | +2 | 없음 | — |

전부 되면 49 → **55~57** 범위를 본다(근거는 최종평가 §4 채점표에서 항목별로 더한 것 — 추정).

**사람이 결정·확인한 것 (14:10 확정)**
1. Anthropic 크레딧 잔량 **$14** → O-2 실행(상한 $3, 재캡처 3노드 ≈ $2.4).
2. Bedrock: 개인 계정 실호출 **하지 않음**. README·소개서·화면 문구에서 "Bedrock" 서술 제거, §4 표 1행만 유지. 코드·spec·steering 의 식별자(`BedrockClient`, `bedrock-client`, `aws.md`, `provider: bedrock`)는 **그대로**.
3. 미커밋 `.streamlit/config.toml`(웹폰트)·`apps/web/app.py`(캡션): ⟨커밋 / 되돌리기 — 사람이 채움⟩.
4. README 빈칸 값 — 아래 O-5 에 기재 완료(사고 사례 구미 불산 / 배포 URL / 잔량 $14 / 도구 비용).

소개서 10장은 사람이 15:00 부터 병행한다. 화면 캡처는 **O-2·O-3 뒤(18:30 이후) 배포 화면**으로 찍는다.

---

## 붙여넣기 시작 (O 세션)

작업 디렉터리: `C:\Users\user\Desktop\공모전\AWS_AI_Innovators\hazop-copilot`

제출 D-0 다. 이 세션은 **코드 변경을 허용**하되 **19:00 에 코드를 동결**한다. 각 단계는 킬 시각을 가지며, 킬 시각까지 시험이 초록이 아니면 그 단계의 변경을 `git revert`(커밋했으면) 또는 `git checkout --`(안 했으면)로 되돌리고 다음 단계로 간다. **단계마다 커밋 1개**, 메시지 형식은 기존 이력과 같다(`feat(FR-xx) O-n — 요약`). 커밋 후 즉시 `git push`.

실호출은 **지시문에 적힌 횟수만**(O-2 최대 3노드 + 실패 재시도 1회, O-4 최대 3회). 그 밖의 모든 실행은 `HAZOP_USE_MOCK=true`. 키는 `.env` 값을 **명령 1개의 환경에만** 주입하고 출력하지 않는다(9/29 I·J 방식).

시험 명령(변경 없음):
```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m ruff check .
HAZOP_USE_MOCK=true PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -m "not live" -q
```
기대 시작점: HEAD `a7ed2ab`, ruff clean, **252 passed, 3 deselected**.

**손대지 않는 것(전 단계 공통)**: 프롬프트 3종(`deviation_generate.md`·`matrix_enumerate.md`·`node_parse.md` — 시스템 프롬프트 sha256 시험 고정), `schemas/*`, `data/gold/*`, `core/export/*`, `core/llm/*`(O-4 에서 버그가 나오면 예외 — 아래), `config/models.yaml` 의 모델 ID·max_tokens, 기존 재생 파일 `n2·n3·n4_20260929.json`(홀드아웃은 재캡처하지 않는다).

---

### 0단계 · 정리 (14:00–14:20)

1. `git status --short`·`git log --oneline -3` 로 시작점 확인. 미커밋 `.streamlit/config.toml`·`apps/web/app.py` 는 사람의 답대로: **⟨커밋 / 되돌리기 — 사람이 채움⟩**. 커밋이면 `style(FR-10) 에스코어 드림 웹폰트 + 출처 캡션`.
2. `.gitignore` 에 `.claude/` 한 줄 추가. `docs/지시문_J·M·N`, `docs/최종평가_20260929.md`, 이 지시문을 커밋(`docs: 지시문 J·M·N·O + 최종평가`).
3. ruff·pytest 실행, 252 확인. 결과를 `docs/진행로그.md` 새 항 "2026-09-29 — 지시문 O 최종 스프린트" 의 0단계 줄로 기록.

---

### O-1 · 가이드워드 판정 병렬화 (14:20–15:45, 킬 15:45) — `core/agent/generate.py`

근거: `docs/지시문_G_병렬매트릭스.md` 초안, README §7 로드맵 1번, hazop-generation R-10(requirements.md 미반영). 가이드워드별 판정 호출은 서로 독립이다(진행로그 I-1·J: 열거 1회 뒤 GW 7~10회 순차).

**구현**
1. `HazopGenerator.generate` 의 가이드워드 루프를 `concurrent.futures.ThreadPoolExecutor(max_workers=N)` 로 바꾼다. **결과 순서는 가이드워드 목록 순서를 보존**한다(`executor.map` 또는 future 를 목록 순서로 수집). 레코드 `id` 부여·`_assemble` 은 수집 **뒤** 단일 스레드에서 하던 대로 한다.
2. `N` 은 `config/models.yaml` `generation.parallel_calls`(신규, 기본 4, 1 이면 기존 순차와 동일 경로). `core/llm/config.py` 로더에 필드 추가(기본값 있어 기존 yaml 호환). 모델 ID·max_tokens 는 건드리지 않는다.
3. **스레드 안전 점검(반드시 코드로 확인하고 진행로그에 적는다)**: `_generate_batch` 가 `self` 의 가변 상태(누적 비용·호출 수·로그 리스트·`review_guidewords`)를 쓰는지 grep. 쓰면 각 future 가 자기 결과(레코드·비용·토큰·재시도 여부·review 여부)를 **반환**하게 바꾸고 합산은 수집 뒤에 한다. `apps/web/service.py::_observe_calls` 와 `tools/capture_replay.py` 의 `_do_converse` 훅이 리스트에 append 하는 것은 GIL 로 안전하지만 **순서가 뒤섞인다** — `raw_calls` 저장 시 `guideword` 키로 정렬하거나 호출 순서에 의존하는 코드가 없는지 확인.
4. 스키마 실패 → 1회 재시도 → `review` 격하 흐름은 future 안에서 그대로. 한 future 의 예외는 그 가이드워드만 `review` 격하하고 나머지는 살린다(기존 규칙과 같음). 429/529 재시도는 `core/llm` 에 이미 있다 — 병렬로 429 가 늘 수 있으므로 기본 `parallel_calls: 4`.
5. `latency_s` 는 벽시계(열거 + 병렬 판정 전체). 재생 메타에 `parallel_calls` 를 저장(`tools/capture_replay.py`)해 순차 캡처와 구별한다. `apps/web/service.py::provenance_line` 에 `parallel_calls > 1` 이면 " · 병렬 N" 표기.

**시험(`tests/test_generate.py` 추가)**
- 순서 보존: mock 으로 가이드워드 7종 실행 → 레코드의 가이드워드 순서가 `STANDARD_GUIDEWORDS` 순서, `id` 연속.
- `parallel_calls=1` 과 `=4` 의 결과가 mock 에서 **바이트 동일**(records·expected/judged·cost).
- 한 가이드워드에서 mock 이 스키마 위반 2회 → 그 GW 만 `review`, 나머지 6종 정상, 호출 수 = 열거 1 + 7 + 재시도 1.
- 비용·토큰 합계가 호출별 합과 일치(공유 상태 경쟁 없음).
- 기존 골든 스냅샷·AppTest 전부 통과.

**결함 재삽입 3건**(각각 깨진 뒤 원복·`cmp`): 순서 보존 제거(`as_completed` 로 수집) / 합산을 공유 변수 `+=` 로 되돌림 / `parallel_calls` 무시하고 항상 순차.

커밋: `feat(FR-03) O-1 — 가이드워드 판정 병렬화(parallel_calls, 순서 보존) — R-10`. `.kiro/specs/hazop-generation/requirements.md` 에 R-10 한 줄(EARS 형식, 지시문 G 문면)과 `tasks.md` T-09 추가·☑. README §4 아키텍처 한 줄("가이드워드 판정은 `parallel_calls`(기본 4) 병렬")·§7 로드맵 1번을 "예선 반영(O-1)"으로.

**킬**: 15:45 에 252+신규 시험이 초록이 아니면 `git checkout -- core/ tests/ config/` 로 전부 되돌리고 O-2 를 **순차 그대로** 진행한다(재캡처 가치는 남는다 — M-01 효과).

---

### O-3 · verifier 시연 토글 (15:45–16:30, 킬 16:30) — `apps/web/` 만

근거: PRD FR-11 데모 "verifier 플래그 장면", 진행로그 self-verification "실측 플래그 0 이라 결함 1건 삽입 화면이어야 한다", 아침브리핑 ⑤-2. 지금 화면의 신뢰도 열은 413건 전부 🟡 라 심사위원은 🔴 를 볼 수 없다.

**구현**(`apps/web/service.py`·`app.py`)
1. 워크시트 위에 체크박스 `verifier 시연 — 결함 1건 삽입(근거 없는 규격 번호)` (기본 꺼짐). 켜면 **표시용 사본**의 첫 레코드 `recommendations[0]` 끝에 ` (KOSHA GUIDE P-999 참조)` 를 붙여 `verify()` 를 다시 돌린다 → 그 행이 🔴 review, `검증 플래그` 열에 `unverified_standard: KOSHA GUIDE P-999`, 요약 줄 `review 1건 (규격 1·수치 0)`.
2. 켜져 있는 동안 표 위에 `:red-background[시연] 아래 1행의 규격 번호는 시연용으로 삽입한 것입니다 — 원본 재생 데이터에는 없습니다.` 를 띄운다. **다운로드 3개는 삽입 없는 원본**으로 유지(내보내기에 시연 데이터가 섞이면 정직성 위반). 재생 파일·`Result` 원본은 불변.
3. 골드 재생(`is_gold`)에는 토글을 숨긴다(사람 작성 레코드는 검증 대상이 아님 — 기존 판단 유지).

**시험(`tests/test_web_j.py`)**: 토글 on → 표에 🔴 1행·플래그 문자열·요약 줄 1건, 다운로드 xlsx 신뢰도 시트에는 review 0 / off → 원래대로 / `Result.records` 객체 불변(id 비교) / AppTest 로 체크박스 클릭 예외 0. 재삽입 2건: 다운로드에 삽입 반영 / 배너 미표시.

커밋: `feat(FR-10) O-3 — verifier 시연 토글(표시 전용, 내보내기 원본 유지)`. README §8 화면 흐름에 한 줄.

---

### O-4 · (삭제) — 사용자 결정 14:10

Bedrock 실호출은 하지 않는다. 이 단계에 배정했던 16:30–17:30 은 O-2 재캡처를 앞당기는 데 쓴다(O-2 를 16:30 시작, 킬 18:00). 진행로그에 "O-4 삭제 — 사용자 결정(Bedrock 서술 제거, §4 표 1행만 유지)" 한 줄.

---

### O-2 · 재캡처 P2 → P1 → (N1) (16:30–18:00, 킬 18:00) — Anthropic 경로, 병렬 적용

전제: 크레딧 ≥ $3(사람 확인). **홀드아웃 N2·N3·N4 는 재캡처하지 않는다**(README §6 홀드아웃 표·26건 대조표·recall 0.154 서술이 그 파일에 묶여 있다).

1. `tools/capture_replay.py --node P2 --source live --out data/replay/p2_20260929b.json`. 확인: `safeguards_before` 채움 수(기대 > 0 — M-01 효과의 첫 실측), F 분포, 지연(병렬이면 ≤ 150초 기대), 비용, 절단 0, review 0. `load_replays` 는 같은 노드에서 **captured_at 최신**을 고르므로 화면이 자동으로 새 파일을 쓴다(시험 `test_load_replays_priority_is_per_node` 가 보장). 옛 `p2_20260929.json` 은 지우지 않는다(비교 근거).
2. 같은 방식으로 P1. 확인: `safeguards_before` 가 입력 3개 **원문**(`안전밸브`·`긴급차단밸브(ESV)`·`가스누출감지기`)으로만 나오는지(M-01 정규화), `ESV`·`gas detector` 0회.
3. **N1 은 시간·크레딧이 남을 때만**(18:00 이전 시작). N1 재캡처는 recall 이 바뀔 수 있다(temperature 0.2, n=1) — 바뀌면 **바뀐 값을 그대로 README §6 에 적는다**(NFR-03). 0.875 를 지키려고 재캡처를 미루는 판단은 사람이 한다: ⟨N1 재캡처 — 예 / 아니오 — 사람이 채움⟩.
4. 실패(네트워크·429) 시 재시도 1회, 두 번째도 실패면 그 노드는 옛 파일 유지.

문서 갱신(같은 커밋): README §6 에 "M-01·병렬 적용 후 재캡처(P1·P2)" 표 — 지연 이전/이후, `safeguards_before` 채움 이전/이후, F=3 비율 이전/이후, 비용. §7 한계 P-1 항 "코드는 고쳤으나 재캡처 전" → 실측 결과로. P-2 항에 F 분포 변화(풀렸으면 풀렸다고, 안 풀렸으면 안 풀렸다고). `service.M01_APPLIED_AT` 이후 캡처라 화면의 "M-01 이전 프롬프트" 표기는 자동 소멸 — AppTest 로 확인. `docs/실무자평가_20260929.md` 는 수정하지 않고(1차 평가 원본) 진행로그에 대조표.

커밋: `feat(FR-10) O-2 — P1·P2(·N1) 재캡처: M-01 + 병렬 실측`. 비용 상한 $3.

---

### O-5 · 문서 정합 + 동결 (18:00–19:00)

1. README 빈칸 4곳 — 아래 값을 **그대로** 넣는다(`⟨` 0개가 되어야 한다).
   - §1 L23 사고 사례 → `**사고 사례**: 2012년 9월 27일 경북 구미 휴브글로벌 공장에서 탱크로리의 불화수소(불산)를 하역하던 중 밸브 오조작으로 약 8톤이 누출돼 작업자 5명이 사망하고 주민·소방관 등 1만 2천여 명이 진료를 받았다. 하역 작업의 밸브 조작 순서·긴급차단·개인보호구는 전형적인 HAZOP 절차 노드의 이탈 항목이다. 이 사고를 계기로 화학물질관리법·화학물질등록평가법이 제정됐다([환경부 설명자료](https://mcee.go.kr/home/web/board/read.do?boardCategoryId=39&boardId=185469&boardMasterId=1), [위키백과](https://ko.wikipedia.org/wiki/%EA%B5%AC%EB%AF%B8_%EA%B0%80%EC%8A%A4_%EB%88%84%EC%B6%9C_%EC%82%AC%EA%B3%A0)).` — 넣기 전에 위키백과 항목의 누출량·진료 인원 숫자를 한 번 대조하고, 다르면 위키백과 숫자로.
   - §8 L341 → `- 배포 URL: https://nwgll5tx3b2deizwqckhcc.streamlit.app — 재생 모드(키 불필요, 실호출 0회). 직접 입력 실호출은 배포 Secrets 의 키로 세션 1회·일 5회.`
   - §9 L375 Anthropic API 크레딧 행 → `9/29 00:53 잔액 부족으로 거부 → 충전 후 재개. 9/29 14:00 잔량 $14`
   - §9 L376 기타 개발 도구 비용 행 → `Kiro: 대회 계정 크레딧 사용 · Claude Code: 개인 Claude 구독 안에서 사용, 별도 과금 없음 · Streamlit Community Cloud·GitHub: 무료 플랜`
   - §9 "크레딧·개발 도구" 표의 **`AWS(대회 계정) Bedrock 사용액` 행은 삭제**한다(아래 3항).
2. README 불일치: §0·§4·§8 "LOPA 초안(md)" → "LOPA 초안(Word .docx — 정본은 Markdown)", §5 시험 수를 최종 pytest 출력값으로, §8 화면 흐름에 verifier 시연·병렬 표기. 추적 매트릭스에 R-10(병렬) 행 추가.
3. **Bedrock 서술 제거(사용자 결정 14:10)** — 대상은 README·화면 문구·소개서 소재다. 규칙: **문장·표 셀의 서술은 지우고, 식별자(클래스명·spec 이름·파일 경로·`provider:` 값)는 남긴다.** 시험이 문자열을 고정한 곳은 시험도 같이 고친다.
   - README 머리말 인용문(`> **현재 상태를 먼저 밝힌다.** … Bedrock 실호출은 0회다`) → 삭제. 첫 단락 "LLM 이 …" 는 그대로.
   - §4 "AWS 요건" 표(6행) → 표 제목을 "LLM 호출 계층" 으로, **1행만** 남긴다: `| LLM 호출 계층 | 공급자 추상화(\`AbstractBedrockClient\`) — Converse 어댑터·Anthropic Messages 어댑터·mock 3종 같은 계약. 모든 실측은 Anthropic 경로(\`claude-opus-4-8\`), \`config/models.yaml\` \`provider\` 한 줄로 전환 |`. 그 아래 문장 "PRD v1.2 그림에서 FastAPI 와 Bedrock Knowledge Base 는 삭제됐다" → "FastAPI 와 Knowledge Base 는 삭제됐다".
   - §4 아키텍처 그림의 `client.py BedrockClient (provider: bedrock — Converse API, tool use)` 줄은 **식별자라 유지**.
   - §5 추적 매트릭스: `bedrock-client REQ-xx` 행 ID 는 유지(spec 폴더 이름). 지표 셀 "mock 통과, Bedrock 실호출 미실시" → "mock 통과(Converse 어댑터)".
   - §6 주석 "`claude-opus-4-8`(Anthropic 경로)" 유지. §7 한계 "**Bedrock 미실측**" 항 삭제. §7 로드맵 5 "Bedrock 전환 실측"·6 "Guardrails" 삭제(번호 재정렬). §7 삭제 표의 "Bedrock Knowledge Base (S3·벡터스토어)" → "Knowledge Base(RAG)", "Guardrails 설정" 행 삭제.
   - §9 표 "AWS(대회 계정) Bedrock 사용액" 행 삭제(1항).
   - `apps/web/*.py`·`data/presets.json` 에 "Bedrock" 문자열이 있는지 `grep -rn Bedrock apps/ data/presets.json` 으로 확인 — 사용자에게 보이는 문구(제목·캡션·배지·안내)에 있으면 제거, docstring·주석은 그대로. `config/models.yaml` 주석 "제출 전 bedrock 으로 되돌린다 — docs/backlog.md" → "provider 는 REQ-12 공급자 교체용. 실측은 anthropic". `docs/backlog.md` 첫 줄(bedrock 전환)은 삭제.
   - 제거 뒤 `grep -n -i bedrock README.md` 결과를 진행로그에 붙인다 — 남는 것은 §4 그림 1줄·§4 표 1행의 `AbstractBedrockClient`·§5 `bedrock-client` ID 여야 한다.
4. `.kiro/specs/*/tasks.md`: 구현·검증 완료 T-xx 를 ☑(hazop-generation T-01~T-08(+T-09), export-formats T-01~T-06, self-verification T-01~T-04, bedrock-client 1개). **evaluation-harness T-01~T-05 는 ☐ 유지**(미구현이 사실), T-06 은 "축소 실행" 주석. spec 파일 안의 Bedrock 서술은 **건드리지 않는다**(spec 은 그 시점의 요구사항 기록).
5. `docs/진행로그.md` 지시문 O 항 완성: 단계별 커밋·시험 수·실호출 횟수·비용·되돌린 것과 사유·Bedrock 제거 grep 결과·남은 리스크.
6. 최종 `ruff` + `pytest` → 커밋 `docs(FR-11) O-5 — README 빈칸·정합·Bedrock 서술 제거·tasks ☑·진행로그` → push → **19:00 코드 동결**. 이후 이 세션은 `git` 읽기 명령만 실행한다.
7. 동결 후 사람에게 보고: 최종 커밋 해시, 시험 수, 실호출 횟수·총비용, README `⟨` 개수(0)·`Bedrock` 서술 잔존 줄, 배포에서 확인할 항목 5개(공정 3개 전환 / 다운로드 3개 / verifier 토글 / 직접 입력 1회 또는 401 문구 / 출처 줄에 "병렬 4"·"M-01 이전" 소멸).

---

### 세션 규칙

- 킬 시각은 **시계 기준**이다. "10분만 더"는 없다. 되돌린 단계는 진행로그에 "되돌림 — 사유" 로 남긴다.
- 실호출 합계 상한 **$3**(O-2 만). 초과 직전에 멈추고 사람에게 묻는다.
- 재생 파일·골드·프롬프트를 사람 손으로 고치는 일은 없다. 새 실측만 새 파일로 추가한다.
- 커밋마다 push. 19:00 이후 push 금지(배포 Reboot 는 사람이 한다).
- 보고는 숫자로: 시험 수, 호출 수, 비용, 지연, 채움 비율. "개선됐다"는 문장은 앞뒤 숫자가 있을 때만.

## 붙여넣기 끝 (O)
