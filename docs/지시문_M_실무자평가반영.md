# 지시문 M — 실무자 평가 반영: 기존 안전장치 전달 · 절차형 가이드워드 · 기준 공개 (2026-09-29)

## 배경 (사람이 읽는 부분 — Claude Code 에는 붙여넣지 않음)

`docs/실무자평가_20260929.md` 의 P-1~P-4 를 고친다. 핵심은 P-1: 판정 프롬프트가 "기존 안전장치는 노드 메타에 주어진
것 중에서만 고르라"고 지시하면서 **정작 안전장치 목록을 넘기지 않는다** → 염소 예시(P2) 64건 전부 Before 칸 공란.

### 사람이 먼저 결정할 것

1. **지금(제출일) 할지, 제출 후 본선으로 넘길지.** M-01·M-02 는 `core/` 와 프롬프트를 바꾼다 → 커밋된 재생 5파일과
   README §6 수치가 "옛 버전 결과"가 된다. 재캡처 없이 코드만 바꾸면 화면은 옛 결과를 계속 보여 준다(무해하지만 설명 필요).
2. **M-02 를 하려면 Kiro 에서 `.kiro/specs/hazop-generation/design.md` §4 를 먼저 고친다**(이 세션은 design.md 를 못 고친다):
   ```
   PROCEDURAL_KEYWORDS = {"절차", "운전", "조작", "순서", "작업", "procedure", "operation",
                          "출하", "하역", "충전", "로딩", "교체", "연결", "분리"}
   ```
   requirements.md R-04 "절차형 가이드워드" 문단은 문구상 그대로 둬도 된다("운전 절차·조작 순서를 나타내는 문자열").
   design.md 를 안 고치면 M-02 는 건너뛴다.
3. **재캡처 여부**(선택): P1·P2 재캡처 2회 ≈ $1.6. 하면 "고쳤더니 Before 칸이 채워졌다"를 숫자로 보일 수 있다.
   NH3 N1~N4 재캡처(≈$3.3)는 recall 표가 바뀌므로 이번 범위에서 뺀다.

---

## 붙여넣기 시작 (M 세션)

작업 디렉터리: `C:\Users\user\Desktop\공모전\AWS_AI_Innovators\hazop-copilot`

먼저 읽어라: `CLAUDE.md`, `docs/실무자평가_20260929.md` 전체, `docs/진행로그.md` 의 2026-09-29 항 전체(J 이후 3개 항 포함),
`.kiro/specs/hazop-generation/{requirements,design}.md` 의 R-01·R-04·§4, `core/agent/generate.py`,
`core/agent/prompts/deviation_generate.md`, `apps/web/{app,service}.py`, `tests/test_generate.py`, `tests/test_web_j.py`.

과제: 실무자 평가 P-1~P-4 대응(**M-01~M-04**). 대응 요구사항은 hazop-generation R-01(입력)·R-04(판정·절차형)이다 —
다른 R-xx 에 걸리면 코드를 쓰기 전에 보고하라. **실호출 예산: 0회.** 재캡처는 내가 따로 지시할 때만(M-05).

손대지 않는 것: `schemas/*`, `data/gold/*`, 기존 `data/replay/*.json`, `config/models.yaml`, `.kiro/specs/*`(읽기 전용),
`core/agent/prompts/matrix_enumerate.md`, `apps/web/prompts/node_parse.md`.

### 0단계 · 상태 검증
```
git log --oneline -3
git status --short
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m ruff check .
HAZOP_USE_MOCK=true PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -m "not live" -q
```
기대: 마지막 커밋 `900f974` 이후(실무자평가·지시문 M 문서 커밋이 있을 수 있음), ruff clean, **231 passed / 3 deselected**.
미추적 `.claude/`·`docs/지시문_J_공정확장.md` 는 정상. 다르면 멈추고 보고.
**`pytest ... | tail -1` 로 성패를 판단하지 마라** — 파이프가 종료코드를 삼킨다. 출력을 파일로 받고 `echo exit=$?` 로 확인한다.

### M-01 · 판정 단계에 노드 조건·기존 안전장치 전달 (P-1·P-6·P-9)

1. `core/agent/prompts/deviation_generate.md` **사용자 턴**(`<!-- USER -->` 아래)의 `## 노드` 절에 줄을 추가한다:
   상(phase)·압력(kPag)·온도(℃)·**기존 안전장치 목록**. 값이 없으면 "미상"/"없음". 시스템 지시(캐시 프리픽스)는 건드리지 않는다
   — 노드마다 바뀌는 값은 사용자 턴에만 둔다(R-08 캐싱 경계).
2. `generate.py::_generate_batch` 의 `_fill` 에 같은 키를 넣는다(`_fmt_number` 재사용).
3. `_assemble` 후처리: `safeguards_before` 의 각 항목을 **입력 `node_meta.safeguards` 의 정확한 문자열**로 정규화한다.
   규칙 — 괄호·공백·`·`·`/`·`,` 로 쪼갠 **2글자 이상 토큰**을 비교한다. 입력 항목과 토큰이 하나라도 겹치면 **입력 원문으로 치환**
   (예: 생성 "ESV" → 입력 "긴급차단밸브(ESV)", 생성 "ESV(긴급차단밸브)" → 같은 입력 — **부분문자열 비교로는 이 둘째 경우가 안 잡힌다**),
   어느 입력과도 안 겹치면 **버리고 WARNING 1줄**(노드·가이드워드·파라미터·버린 문자열). 중복 제거, 순서는 입력 순서.
   입력 safeguards 가 비어 있으면 결과도 항상 빈 배열(지금 규칙 그대로).
   한 항목이 입력 둘과 겹치면 **둘 다 채택**하고 시험으로 고정한다. "밸브" 같은 흔한 토큰 하나로 엉뚱한 입력에 붙는지
   (예: 생성 "체크밸브" ↔ 입력 "긴급차단밸브" — 토큰 "체크밸브"≠"긴급차단밸브" 이므로 안 붙어야 함) 시험에 넣어라.
4. 시험(오프라인 mock): (a) 판정 호출 사용자 메시지에 safeguards·P·T·phase 가 들어간다 (b) 정확 일치 유지
   (c) 토큰 겹침 → 원문 치환("ESV"·"ESV(긴급차단밸브)" → "긴급차단밸브(ESV)") (d) 무관 문자열("gas detector"·"체크밸브") → 버림 + WARNING
   (e) 입력 비면 빈 배열 (f) 시스템 프롬프트 바이트 불변(캐시 경계) — `_split_prompt` 결과 system 이 수정 전과 같음.
   결함 재삽입 최소 3건(정규화 제거 / 사용자 턴 누락 / 시스템 쪽에 넣기)으로 시험이 깨지는지 확인.

### M-02 · 절차형 가이드워드 키워드 (P-4) — **design.md §4 가 이미 고쳐졌을 때만**

`design.md §4` 의 `PROCEDURAL_KEYWORDS` 를 읽고, 그 집합과 `generate.py` 상수가 **같아지도록만** 고친다(값을 추측해 넣지 말 것).
design.md 가 옛 값 그대로면 M-02 는 건너뛰고 보고한다.
시험: 카탈로그 P1(설비 "로딩암" 은 안 걸리고 공정은 "출하" — **설비명 기준 판정**이므로 걸리는지 실제로 확인해 보고),
P2, N1(7종 유지), N4(10종 유지). P1·P2 가 설비명만으로는 안 걸리면 **그 사실을 보고**하고 로직을 바꾸지 마라(R-04 는 equipment 기준).

### M-03 · 평가기준 불일치 공개 (P-3) — UI 만

- 골드 없는 공정(`split == "none"`)과 직접 입력 결과 화면에, 워크시트 위에 한 줄 배지:
  "S·F 등급 정의는 NH3 선박 벙커링 기준(선내·항만 영향)입니다 — 이 공정에는 참고용."
- `summary_line` 에 S·F 분포 요약 1개 추가: `F=3 비율 85%` 처럼 **가장 많은 F 값과 그 비율**. 불리한 숫자도 그대로(NFR-03).
- 시험: 배지는 골드 공정에서 안 보이고 예시·직접 입력에서 보인다. 분포 문자열 값 검증.

### M-04 · 문서

- `README.md` §7 한계에 실무자 평가 요약 4줄(P-1 수정 여부·P-2·P-3·P-5) + `docs/실무자평가_20260929.md` 링크.
- `docs/실무자평가_20260929.md` 는 **고치지 않는다**(평가 시점 기록). 조치 결과는 진행로그에.
- `docs/backlog.md`: 노드 분할 제안(P-5), 사업장 위험성 매트릭스 업로드(P-3), 검토자 수정·서명 흐름(P-10) 각 1줄.

### M-05 · (내가 별도로 지시할 때만) P1·P2 재캡처

`tools/capture_replay.py --node P1 --out data/replay/p1_<날짜>_m.json --source live` → 로그 확인 후 P2. 실패 시 재실행 금지.
보고: 두 파일의 `safeguards_before` 채움률(레코드 중 비어 있지 않은 비율)·버려진 문자열 수(WARNING 수)·F 분포·지연·비용을
**수정 전(p1/p2_20260929.json) 대비 표**로. 키는 `.env` 에서 읽되 **파일에 BOM 이 있다**(9/29 11:30 재저장) —
`grep '^ANTHROPIC_API_KEY='` 는 BOM 때문에 빈 값을 준다. `utf-8-sig` 로 읽어라. 값은 출력하지 않는다.

### 완료 보고 (`docs/진행로그.md`)
변경 파일 / 시험 결과(종료코드 포함) / 재삽입 표 / M-02 수행·건너뜀 사유 / 시스템 프롬프트 바이트 불변 확인 /
**기존 재생 파일이 옛 프롬프트 결과라는 점을 README·화면 어디에 적었는지** / 남은 리스크 4줄.

커밋은 내가 지시할 때만, 태스크별로:
1. `fix(FR-03) M-01 — 판정 프롬프트에 기존 안전장치·운전조건 전달 + safeguards_before 입력 원문 정규화`
2. `fix(FR-03) M-02 — 절차형 가이드워드 키워드 design.md §4 동기화` (수행 시)
3. `feat(FR-10) M-03 — 예시 공정 평가기준 불일치 배지 + S·F 분포 요약`
4. `docs M-04 — 실무자 평가 요약·backlog`

각 커밋 직전에 그 커밋 상태로 전체 시험을 돌려 **종료코드 0** 을 확인한다. 한 태스크가 2시간을 넘기면 멈추고 분할안을 보고하라.

## 붙여넣기 끝 (M)

---

## 이후 (사람용)

| 시점 | 할 일 |
|---|---|
| M 커밋 후 | `git push` → Streamlit **Reboot 필수**(service.py·core 변경은 재부팅 전까지 옛 모듈이 돈다) |
| 재캡처를 원하면 | M-05 지시 + 크레딧 ≥ $3 확인 |
| API 키 | 콘솔에서 새 키 발급 → Secrets·`.env`(BOM 없이 저장) 둘 다 교체 — 현재 `.env` 키는 9/29 오후 401 |
