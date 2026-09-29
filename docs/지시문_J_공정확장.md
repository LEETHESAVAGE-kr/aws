# 지시문 J — 공정 카탈로그 확장 + 직접 입력 빠른 실호출 + 화면 재배치 (2026-09-29 오전)

## 배경 (사람이 읽는 부분 — Claude Code 에는 붙여넣지 않음)

배포 URL(`nwgll5tx3b2deizwqckhcc.streamlit.app`)을 본 소감: "N1 이 뭔지 모르겠고 LLM 이 왜 연결돼 있는지
안 보인다. 공정을 선택하면 그 공정의 위험성 평가가 나와야 하는 것 아닌가. 암모니아 말고 다른 공정에도
적용되게 하고 싶다." 심사위원도 같은 반응일 것이다.

코드 실사: `core/agent/generate.py`·프롬프트 2종은 NH3 를 한 번도 언급하지 않는다(범용 노드 입력). NH3 에
묶인 것은 `apps/web/service.py::PRESETS` 와 골드셋뿐. 따라서 확장은 `apps/web`·`tools/capture_replay.py`·
`data/presets.json` 만으로 된다. `core/` 무수정.

### 사람이 먼저 결정할 것

1. **추가 공정 2개** (기본안 — 바꾸려면 아래 JSON 값만 바꾼다):
   - P1 「LPG 저장탱크 출하」 — 프로판, 액상, 700 kPag, 25 ℃, 설비 `["LPG 저장탱크", "출하 펌프", "로딩암"]`, 안전장치 `["안전밸브", "긴급차단밸브(ESV)", "가스누출감지기"]`
   - P2 「염소 톤컨테이너 하역·기화」 — 염소, 액상→기상, 500 kPag, 20 ℃, 설비 `["톤컨테이너", "액염소 배관", "기화기"]`, 안전장치 `["염소 누출감지기", "긴급차단밸브", "중화(가성소다) 스크러버"]`
2. **직접 입력 빠른 실호출을 공개 배포에 켤지.** 켜면 Streamlit Cloud → App settings → Secrets 에
   ```
   HAZOP_ALLOW_LIVE = "true"
   HAZOP_LIVE_SCOPE = "quick"
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```
   상한은 세션 1회·일 5회(기존) + 빠른 모드는 호출 2회로 고정 → 노출 비용 하루 ≤ $1. 안 켜면 재생만.
3. 크레딧 잔액 ≥ $5 확인(캡처 2회 ≈ $1.7).

---

## 붙여넣기 시작 (J 세션)

작업 디렉터리: `C:\Users\user\Desktop\공모전\AWS_AI_Innovators\hazop-copilot`

먼저 읽어라: `CLAUDE.md`, `docs/아침브리핑_20260929.md`, `docs/진행로그.md` 의 2026-09-29 항 전체,
`apps/web/{app,service,replay}.py`, `tests/test_web.py`, `tools/capture_replay.py`, `core/agent/generate.py`
(`HazopGenerator` 의 `generate`·`_enumerate_parameters`·`_generate_batch`·`_assemble`·`_select_guidewords`),
`README.md` §4·§8.

과제: **FR-10 J-01~J-04** (PRD v2.0 §5 FR-10 — spec 없음, PRD 가 정본). 배포 화면을 "공정 선택 → 입력 →
생성 과정 → 워크시트" 로 바꾸고, NH3 외 공정 프리셋 2개를 실호출 캡처로 추가하고, 직접 입력 빠른 실호출을
넣는다. **실호출 예산: 캡처 2회(J-02) + 빠른 모드 검증 1회(J-03, 2 API 호출) = 노드 실행 3회.**

손대지 않는 것: `core/*`, `schemas/*`, `data/gold/*`, 기존 `data/replay/*.json`, `config/models.yaml`, 프롬프트.
`HazopGenerator` 의 비공개 메서드를 `apps/web/service.py` 에서 호출하는 것은 **이번에 한해 허용**한다 —
`core` 를 고치지 않기 위한 선택이며, 완료 보고에 "비공개 메서드 의존 3곳" 으로 적고 `docs/backlog.md` 에
"본선: `HazopGenerator.generate_quick()` 공개 API 로 승격" 한 줄을 남겨라.

### 0단계 · 상태 검증
```
git log --oneline -3
git status --short
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m ruff check .
HAZOP_USE_MOCK=true PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -m "not live" -q
```
기대: 마지막 커밋 `88758ea`, clean, ruff clean, 195 passed / 3 deselected. 다르면 멈추고 보고.

### J-01 · 공정 카탈로그 `data/presets.json` + 로더

하드코딩 `PRESETS` 를 파일로 뺀다. 구조:
```json
{
  "processes": [
    {
      "id": "nh3_sts", "name": "암모니아 선박 간(STS) 벙커링", "gold": true,
      "description": "공급선 → 이송 호스 → 수급선으로 액체 암모니아를 이송하는 공정. 전문가 HAZOP 골드셋 34건 보유.",
      "nodes": [
        {"id": "N1", "label": "① 공급선(벙커링선) 매니폴드", "node_meta": {…기존 N1…}},
        {"id": "N2", "label": "② 이송 호스", …}, {"id": "N3", "label": "③ 수급선 매니폴드", …},
        {"id": "N4", "label": "④ 이송 운전 절차", …}
      ]
    },
    {
      "id": "lpg_loading", "name": "LPG 저장탱크 출하", "gold": false,
      "description": "저장탱크의 액상 프로판을 출하 펌프로 로딩암까지 보내는 공정. 골드셋 없음 — 정성 검토용 예시.",
      "nodes": [{"id": "P1", "label": "저장탱크 → 출하 펌프 → 로딩암",
                 "node_meta": {"node": "P1", "substance": "프로판", "phase": "액상", "P_kPag": 700, "T_degC": 25,
                               "equipment": ["LPG 저장탱크", "출하 펌프", "로딩암"],
                               "safeguards": ["안전밸브", "긴급차단밸브(ESV)", "가스누출감지기"]}}]
    },
    {
      "id": "cl2_unloading", "name": "염소 톤컨테이너 하역·기화", "gold": false,
      "description": "톤컨테이너의 액염소를 배관으로 기화기까지 보내 기상 염소로 공급하는 공정. 골드셋 없음 — 정성 검토용 예시.",
      "nodes": [{"id": "P2", "label": "톤컨테이너 → 액염소 배관 → 기화기",
                 "node_meta": {"node": "P2", "substance": "염소", "phase": "액상→기상", "P_kPag": 500, "T_degC": 20,
                               "equipment": ["톤컨테이너", "액염소 배관", "기화기"],
                               "safeguards": ["염소 누출감지기", "긴급차단밸브", "중화(가성소다) 스크러버"]}}]
    }
  ]
}
```
NH3 4노드의 `node_meta` 는 `tools/capture_replay.py::NODE_METAS` 값을 그대로 옮긴다(추측 금지). `NodeMeta.phase`
가 문자열이므로 "액상→기상" 은 그대로 허용된다 — 스키마 `node_meta.phase` 제약을 확인하고, enum 이면 허용값
중 하나로 바꾸고 보고하라.
- `apps/web/catalog.py::load_catalog()` → 검증(`NodeMeta.model_validate`) 후 반환. `service.PRESETS` 는
  카탈로그에서 파생해 호환 유지. `tools/capture_replay.py` 의 `NODE_METAS`·`--node` choices 도 카탈로그에서
  읽게 바꾼다(NH3 는 골드 recall 계산, `gold: false` 노드는 recall `null` + `"split": "none"`).
- 시험: 카탈로그 로드·검증, 노드 id 유일성, `gold:false` 노드 캡처 시 recall null(mock).

### J-02 · 새 공정 2개 실호출 캡처 (2회, 순차)
```
python tools/capture_replay.py --node P1 --out data/replay/p1_20260929.json --source live > results/capture_p1.log 2>&1
```
로그 확인·1줄 보고 후 P2. 실패 시 재실행 금지, 그 프리셋은 "미캡처(비활성)" 로 남기고 다음 단계. 절단·지연·비용·
파라미터 목록·레코드 수를 보고.

### J-03 · 직접 입력 "빠른 실호출" (`apps/web/service.py::run_quick`)
입력: NodeMeta JSON + 가이드워드 1개(선택 상자, 기본 More). 실행: `HazopGenerator` 를 만들어
`_enumerate_parameters(node_meta)` → `_generate_batch(node_meta, parameters, guideword)` → `_assemble` 로
레코드 조립(API 호출 정확히 2회). `Result` 로 감싸되 `meta` 에 `source="quick"`, `guidewords=[gw]`,
`parameters=[...]`, 지연·비용·`expected_cells=len(parameters)`·`judged_cells`. verifier 통과 후 표·다운로드는
기존 경로 그대로. 실패 시 `st.error` 사유, 앱 생존.
- 활성 조건: 기존 `live_block_reason` + `HAZOP_LIVE_SCOPE` 환경변수(`quick` | `full`, 기본 `quick`). `full` 일
  때만 기존 노드 전체 실호출 버튼이 보인다. 상한(세션 1·일 5)은 공용.
- 시험(오프라인 mock): 호출 수 == 2, 레코드가 선택 가이드워드만 포함, 상한 공용 동작, `HAZOP_LIVE_SCOPE` 분기.
- **실호출 검증 1회**: `HAZOP_ALLOW_LIVE=true` 로 로컬에서 "프로판 저장탱크" 류 임의 입력 + More 를 실제로 눌러
  1분 안에 결과가 나오는지, 비용을 로그로. (이 1회가 J-03 예산.)

### J-04 · 화면 재배치 (`apps/web/app.py`)
위→아래 순서:
1. 제목 + 한 문단: "공정 노드 설명을 넣으면 LLM 이 HAZOP 매트릭스를 판정해 워크시트 초안을 만든다. 아래 결과는
   전부 LLM 이 **왼쪽 입력만 보고** 생성한 것이다(캡처 일시·모델·비용 표기)."
2. **공정 선택**: `st.selectbox` 공정(카탈로그 name) → 그 공정의 `description` 한 줄 + 노드 버튼(label). 골드셋
   있는 공정은 "골드셋 34건 · recall 실측" 배지, 없는 공정은 "예시 공정 · 골드셋 없음(정성 검토)" 배지.
   맨 아래 옵션 **"직접 입력"** → NodeMeta JSON 편집 + 가이드워드 선택 + "빠른 실호출(약 1분)" 버튼(J-03).
3. **LLM 에 보낸 입력** (좌) / **생성 과정** (우): 파라미터 열거 결과(레코드의 distinct parameter 순서대로), 가이드워드
   호출 수, 판정 셀, 지연, 비용, 절단 0, review 건수. 재생이어도 "2026-09-29 실호출 캡처" 라고 명시.
4. **HAZOP 워크시트** 표 + 다운로드 3개(기존).
5. `st.expander("평가 결과 — 골드셋 대비 recall (n=1)")` 안에 기존 평가 표 + README §6 링크. **기본 접힘.**
- 기존 `MODE_REPLAY/MODE_LIVE` 라디오는 제거하고 위 흐름으로 대체. 노드 전체 실호출은 `HAZOP_LIVE_SCOPE=full`
  일 때만 직접 입력 아래에 보조 버튼으로.
- AppTest: 공정 3개 × 노드 전환 예외 0, 직접 입력 mock 경로 완주, 첫 화면 시간 측정(목표 10초).
- `README.md` §8 사용법 문단을 새 화면에 맞게 갱신(공정 카탈로그·직접 입력·`HAZOP_LIVE_SCOPE`), §3 에
  예시 공정 2개는 골드셋 없음을 한 줄. `data/README.md` 에 `data/presets.json` 행.

### 완료 보고 (`docs/진행로그.md`)
변경·신규 파일 / pytest 결과 / J-02 캡처 표(P1·P2: 파라미터 목록·레코드·절단·지연·비용) / J-03 실호출 1회 결과
(호출 2회 확인·지연·비용) / 첫 화면 시간 / 비공개 메서드 의존 3곳 명시 / 남은 리스크 4줄.

커밋은 내가 지시할 때만, 셋으로:
1. `feat(FR-10) J-01·J-02 — 공정 카탈로그 data/presets.json + LPG·염소 예시 프리셋 실호출 캡처`
2. `feat(FR-10) J-03 — 직접 입력 빠른 실호출(열거 + 가이드워드 1개, 호출 2회)`
3. `feat(FR-10) J-04 — 화면 재배치(공정 선택 → 입력 → 생성 과정 → 워크시트) + README §8 갱신`

한 태스크가 2시간을 넘기면 멈추고 분할안을 보고하라.

## 붙여넣기 끝 (J)

---

## 이후 (사람용)

| 시점 | 할 일 |
|---|---|
| J 커밋 후 | `git push` → 자동 재배포 → 시크릿 창 확인. 빠른 실호출을 켜기로 했으면 Secrets 3줄 입력 → 앱 재시작 → 직접 입력으로 1회 눌러 확인(그 1회가 일 상한 5 중 1) |
| 정오 | 제출 사이트 로그인 테스트 |
| 오후 | 소개서 10장(이 대화) — 스크린샷: 공정 선택 화면 / 워크시트 / 직접 입력 결과 / xlsx |
| README 빈칸 | §1 사고 사례 · §8 배포 URL · §9 잔량·도구 비용 |
