# 위험성평가 코파일럿 (HAZOP Copilot)

고려대 × AWS AI Innovators Challenge 2026 출품작. 공정 노드 설명(물질·상태·운전조건·설비)을 넣으면
LLM 이 HAZOP 가이드워드×파라미터 매트릭스를 판정해 워크시트 초안(xlsx)과 LOPA 초안(Word .docx — 정본은 Markdown)을 만들고,
전문가 HAZOP 골드셋 대비 성능을 이 문서에 숫자로 공개한다(불리한 지표 포함 — [PRD.md](PRD.md) NFR-03).

---

## § 1 문제

**HAZOP 60초 설명.** HAZOP(위험과 운전성 분석)은 공정을 노드(배관·설비 구간이나 운전 절차)로 나누고,
노드마다 파라미터(유량·압력·온도·준위·조성·상 등)에 가이드워드 7종(No·More·Less·Reverse·Other than·
Part of·As well as)을 붙여 설계 의도에서 벗어난 **이탈**을 빠짐없이 찾는 방법이다. 운전 절차 노드에는
Too early·Too late·Wrong action 같은 절차형 가이드워드를 쓴다. 이탈마다 원인·결과·기존 안전장치를 적고
심각도(S, 1~5)×빈도(F, 1~5)로 위험도를 매긴 뒤 권고를 낸다. 결과물은 12열 워크시트
(`No, 노드, 가이드워드, 이탈, 원인, 결과, 기존 안전장치(Before), S, F, 위험도(=S×F), 권고, 시나리오 연계`)다
(정의 정본: [.kiro/steering/domain.md](.kiro/steering/domain.md)).

**사고 사례**: 2012년 9월 27일 경북 구미 제4국가산업단지 휴브글로벌 공장에서 탱크로리의 플루오린화수소(불산)를 공장 설비에 주입하던 중 근로자의 실수로 탱크로리 밸브가 열려 가스가 누출됐다. 공장 근로자 5명이 사망하고 18명이 다쳤으며, 가스가 인근 지역까지 퍼져 농작물·가축 피해가 이어졌고 특별재난지역으로 선포됐다. 하역 작업의 밸브 조작 순서·긴급차단·개인보호구는 전형적인 HAZOP 절차 노드의 이탈 항목이다([위키백과](https://ko.wikipedia.org/wiki/%EA%B5%AC%EB%AF%B8_%EA%B0%80%EC%8A%A4_%EB%88%84%EC%B6%9C_%EC%82%AC%EA%B3%A0)).

**실무 페인포인트.** HAZOP 은 공정안전관리(PSM) 위험성평가의 핵심 산출물이고, 컨설팅 현장에서는
워크시트 초안 작성에 가장 많은 인력과 시간이 든다(작성자가 KECC 에서 이 업무를 직접 수행한 경험에 근거한
서술이며 정량 측정값은 아니다). 기존 HAZOP 소프트웨어는 양식 관리 도구이고 이탈을 생성하지 않는다.
범용 챗봇은 근거 없이 그럴듯한 이탈·규격 번호를 만들 수 있고, 안전 문서에서 그런 출력은 곧 위험이다.
그래서 이 서비스는 (1) 매트릭스를 빠짐없이 돌게 강제하고 (2) 출력을 스키마로 검증하며 (3) 근거 없는
주장을 `review` 로 격하해 사람 검토 대상으로 표시한다.

## § 2 왜 LLM인가

- **매트릭스 판정은 텍스트 추론이다.** 가이드워드×파라미터 셀 하나를 채우려면 "이 노드의 이 설비에서
  이 조합이 물리적으로 의미가 있는가"를 판단하고, 원인·결과·안전장치를 공정 맥락에 맞춰 문장으로 써야
  한다. 노드마다 설비 구성이 달라 고정 규칙표로는 셀 판정과 서술을 대신할 수 없다.
- **단일 프롬프트가 아니라 2단 구조다** ([core/agent/generate.py](core/agent/generate.py)).
  1. 파라미터 축 열거 — 노드 설명에서 파라미터를 6~12개 뽑는다
     ([core/agent/prompts/matrix_enumerate.md](core/agent/prompts/matrix_enumerate.md)).
  2. 가이드워드별 판정 — 가이드워드 1개마다 호출 1회로 모든 파라미터 셀을 `applicable` 판정·서술한다
     ([core/agent/prompts/deviation_generate.md](core/agent/prompts/deviation_generate.md)).
     셀 수(expected)와 판정 수(judged)를 세어 누락을 관측한다.
- **스키마 강제**: 출력은 tool use(`structured_output`)의 `input_schema` 로 JSON 스키마를 강제하고
  [schemas/deviation.schema.json](schemas/deviation.schema.json) 으로 다시 검증한다.
- **재시도·격하**: 스키마 검증 실패 시 1회 재시도, 그래도 실패하면 그 가이드워드 행을 `confidence="review"`
  로 격하한다(조용히 통과시키지 않는다). 429·529·5xx 는 1→2→4초 간격 3회 재시도(REQ-12 AC-12-5).
- **캐싱**: 시스템 블록에 `cache_control: ephemeral` — 실측에서 3번째 호출부터 매 호출 `cache_read=2186`
  토큰이 찍혔다(tool 정의 포함 프리픽스).
- **규칙 기반 자기 검증**: 생성 후 [core/agent/verify.py](core/agent/verify.py) 가 근거(`evidence[]`) 없는
  규격·법령 번호와 단위 붙은 수치를 정규식으로 잡아 `review` 로 격하한다. LLM 2차 호출은 쓰지 않는다.

## § 3 데이터 · 라이선스

출처·라이선스·재현 방법 정본: [data/README.md](data/README.md).

- **골드셋 34건**: 저장소 소유자 본인이 제12회 위험성평가 경진대회에 출품한 암모니아(NH3) 벙커링
  위험성평가의 HAZOP 워크시트(본인 저작물). 원본 xlsx 는 `.gitignore` 로 제외하고 파생 JSON 만 커밋한다.
- **노드 홀드아웃 분할**: 튜닝 = N1(8건), 홀드아웃 = N2·N3·N4(26건 = 9·7·10). 같은 노드의 이탈이 튜닝과
  평가에 섞이지 않도록 레코드가 아니라 **노드 단위**로 나눴다
  ([data/gold/split_node.json](data/gold/split_node.json)).
- **재생 데이터**: [data/replay/](data/replay/) — `tools/capture_replay.py` 가 실호출 결과를 저장한 JSON.
  데모의 기본 화면과 §6 표가 이 파일을 읽는다.
- **공정 카탈로그**: [data/presets.json](data/presets.json) — NH3 벙커링 4노드 + 예시 공정 2개(LPG 저장탱크 출하,
  염소 톤컨테이너 하역·기화). **예시 공정 2개는 골드셋이 없다** — recall 을 재지 않는 정성 검토용이다.
- **실데이터 금지**: KECC 고객사 실데이터·개인정보는 쓰지 않는다([CLAUDE.md](CLAUDE.md) 불변규칙 1).
- **글꼴**: 데모 화면에 S-Core 에스코어 드림을 쓴다 — S-Core 무료 배포 글꼴(개인·기업 무료, 수정·판매 금지, 출처 표기 권장).
  웹폰트는 눈누가 jsDelivr 에 올린 파일(`projectnoonnu/noonfonts_six@1.2`)을 `.streamlit/config.toml` 에서 불러온다.
- 예선에서 KOSHA Guide 발췌·물질 DB·고장률 대장(`data/kb/`)은 만들지 않았다(§7).

## § 4 아키텍처

```text
apps/web/app.py (Streamlit)         위젯 배선만 (공정 선택 → 입력·생성 과정 → 워크시트 → 평가)
  └─ apps/web/service.py            실호출 판정·상한·빠른 실호출·결과표·평가 요약 표·내보내기
  └─ apps/web/catalog.py            data/presets.json 공정 카탈로그 로더 (NodeMeta·스키마 검증)
  └─ apps/web/prompts/node_parse.md 직접 입력 문장 → NodeMeta 해석 프롬프트 (verifier 프로필)
  └─ apps/web/replay.py             data/replay/*.json 로더 (노드별 live > gold)
        │
        ▼
core/agent/generate.py   HazopGenerator: ① 파라미터 열거 → ② 가이드워드별 셀 판정 (스키마 강제·재시도·격하)
                         가이드워드 판정은 `parallel_calls`(기본 4) 병렬 — 결과는 가이드워드 순서 보존 (R-10)
core/agent/verify.py     규칙 verifier: 근거 없는 규격 번호·수치 → confidence="review" (LLM 호출 없음)
        │
        ▼
core/llm/                AbstractBedrockClient  ← config/models.yaml 의 provider 로 선택
  ├─ client.py           BedrockClient    (provider: bedrock — Converse API, tool use)
  ├─ anthropic_client.py AnthropicClient  (provider: anthropic — 개발·실측 경로)
  └─ mock.py             MockBedrockClient (HAZOP_USE_MOCK=true — 오프라인 시험)
        │
        ▼
core/export/             xlsx 5시트(HAZOP워크시트·평가기준·스크리닝·근거·신뢰도) · lopa_draft.md(화면 다운로드는 Word .docx) · confidence_report.json

tools/capture_replay.py  노드 1건 실호출 → data/replay/<node>_<date>.json (recall·지연·비용·절단 기록)
tools/build_gold.py      data/raw/*.xlsx → data/gold/*.json
```

- **FastAPI 와 Knowledge Base 는 삭제**됐다(PRD v2.0 §4). Streamlit 이 `core/` 를
  직접 호출한다.
- 모델 ID·리전·`max_tokens` 는 [config/models.yaml](config/models.yaml) 한 곳에서만 읽는다. 현재
  `generation.model_id: claude-opus-4-8`, `max_tokens: 16384`.
- 카탈로그 공정은 **재생**(키 불필요, 실호출 0회)이다. 직접 입력의 실호출은 `HAZOP_ALLOW_LIVE=true` 와
  `ANTHROPIC_API_KEY` 가 모두 있을 때만 켜지고 세션 1회·일 5회로 제한된다(§8).

### LLM 호출 계층

| 항목 | 상태 |
|---|---|
| LLM 호출 계층 | 공급자 추상화(`AbstractBedrockClient`) — Converse 어댑터·Anthropic Messages 어댑터·mock 3종 같은 계약. 모든 실측은 Anthropic 경로(`claude-opus-4-8`), `config/models.yaml` `provider` 한 줄로 전환 |

## § 5 Kiro 개발 방식 · 추적 매트릭스

- **정본 사슬**: [PRD.md](PRD.md)(무엇을 언제까지) → `.kiro/specs/<spec>/{requirements,design,tasks}.md`
  (기능별 요구사항·설계·태스크) → 코드 → 테스트 → 지표. 구현은 Claude Code 가 "tasks.md 의 T-xx" 단위로
  받아 수행하고, 커밋 메시지는 `spec:<name> T-xx — 요약` 형식이다.
- **steering 4종**: [domain.md](.kiro/steering/domain.md)(HAZOP·LOPA 용어·S/F 등급) ·
  [engineering.md](.kiro/steering/engineering.md) · [aws.md](.kiro/steering/aws.md) ·
  [docs.md](.kiro/steering/docs.md)(README 9절·추적 매트릭스·평가표 규칙).
- **spec 6종**: Kiro 생성 3종 — [gold-dataset](.kiro/specs/gold-dataset/requirements.md) ·
  [bedrock-client](.kiro/specs/bedrock-client/requirements.md) ·
  [hazop-generation](.kiro/specs/hazop-generation/requirements.md).
  손 작성 3종 — [export-formats](.kiro/specs/export-formats/requirements.md) ·
  [evaluation-harness](.kiro/specs/evaluation-harness/requirements.md) ·
  [self-verification](.kiro/specs/self-verification/requirements.md).
  **Kiro 크레딧 소진 후(9/11 export-formats 부터) spec 3종과 bedrock-client 의 REQ-12·T-15 는 Kiro 와 같은
  형식(EARS requirements + design + tasks)으로 손으로 작성·유지했다.**
- 시험: `pytest -m "not live"` **266 passed, 3 deselected**(live 마커), `ruff check .` clean.

### 추적 매트릭스

ID 는 각 spec 의 requirements.md·tasks.md 원문 그대로다(gold-dataset·bedrock-client 는 `REQ-xx`, 나머지는 `R-xx`).

| 요구사항 ID | 코드 모듈 | 테스트 ID | 측정 지표 |
|------------|----------|----------|----------|
| gold-dataset REQ-01·02 xlsx 입력·12열 매핑 | `tools/build_gold.py` (`XlsxLoader`·`ColumnMapper`) | T-02·T-03·T-11 | 지표: 통합 테스트 통과 |
| gold-dataset REQ-03 출력 스키마 | `tools/_gold/models.py`, `tools/build_gold.py` | T-08·T-10·T-11 | 34 레코드 스키마 검증 통과 |
| gold-dataset REQ-04~06 가이드워드·노드·다중값 분해 | `tools/build_gold.py` (`GuidewordParser`·`NodeParser`·`MultiValueParser`) | T-04·T-05·T-06 | 지표: 통합 테스트 통과 |
| gold-dataset REQ-07 결측·정합성 | `tools/build_gold.py` (`FieldValidator`·`DatasetValidator`) | T-07·T-08 | 지표: 통합 테스트 통과 |
| gold-dataset REQ-08 노드 홀드아웃 분할 | `tools/build_gold.py` (`NodeSplitter`) | T-09 | tune 8 / holdout 26 |
| gold-dataset REQ-09 CLI·종료 코드 | `tools/build_gold.py::main` | T-10·T-11·T-13 | 지표: 통합 테스트 통과 |
| bedrock-client REQ-01 설정 로드 | `core/llm/config.py` | T-02 | 지표: 통합 테스트 통과 |
| bedrock-client REQ-02·03 Converse 호출·tool use | `core/llm/client.py` (`AbstractBedrockClient`·`BedrockClient`) | T-07·T-10 | mock 통과(Converse 어댑터) |
| bedrock-client REQ-04 JSON 스키마 강제 | `core/llm/client.py` (`SchemaValidator`) | T-06·T-10 | 실측 스키마 통과 100%(재시도 포함) |
| bedrock-client REQ-05 재시도 | `core/llm/client.py` (`bedrock_retry`) | T-05 | 지표: 통합 테스트 통과 |
| bedrock-client REQ-06·07 로깅·비용 상한 경고 | `core/llm/client.py` | T-07 | 소프트 상한 $0.30 WARNING 발동(실측) |
| bedrock-client REQ-08 프롬프트 캐싱 | `core/llm/client.py` (`CachingBuilder`), `core/llm/anthropic_client.py` | T-04·T-10 | `cache_read=2186` 실측 |
| bedrock-client REQ-09 비용 계산 | `core/llm/client.py` (`CostCalculator`) | T-03 | 지표: 통합 테스트 통과 |
| bedrock-client REQ-10 모의 클라이언트 | `core/llm/mock.py` | T-08·T-09·T-11 | 오프라인 시험 네트워크 0회 |
| bedrock-client REQ-11 스모크 | `tests/test_llm_live.py` | T-12 | 9/28 스모크 1회 성공($0.0098) |
| bedrock-client REQ-12 공급자 교체 | `core/llm/anthropic_client.py`, `core/llm/__init__.py` | T-15 | 호출부 무변경, 실측 경로 |
| hazop-generation R-01·02 입출력 스키마 | `core/agent/generate.py` (`NodeMeta`·`DeviationRecord`), `schemas/deviation.schema.json` | T-01·T-02 | 스키마 검증 100% |
| hazop-generation R-03 파라미터 축 도출 | `core/agent/prompts/matrix_enumerate.md`, `generate.py` | T-03·T-04 | 노드당 10~11축 |
| hazop-generation R-04 매트릭스 판정 | `core/agent/prompts/deviation_generate.md`, `generate.py` | T-04·T-06 | judged/expected 317/317 |
| hazop-generation R-05 S·F·위험도 | `generate.py` (`DeviationRecord._compute_risk_score`) | T-04·T-06 | risk_score = S×F |
| hazop-generation R-06 스키마 실패 처리 | `generate.py` | T-04·T-06 | review 가이드워드 0(9/29) |
| hazop-generation R-07 오프라인 시험 | `tests/test_generate.py` | T-06 | 지표: 통합 테스트 통과 |
| hazop-generation R-08 캐싱 적용 지점 | `generate.py` | T-05 | `cache_read=2186` 실측 |
| hazop-generation R-10 가이드워드 판정 병렬화 | `generate.py` (`parallel_calls`), `config/models.yaml` | T-09 | 순차=병렬 레코드 바이트 동일(mock) |
| hazop-generation R-09 완료 조건 | `generate.py`, `tools/capture_replay.py` | T-07·T-08 | 지연 ≤ 60초 ⚠️ / N1 recall ≥ 0.5 ✅ / holdout ≥ 0.7 ⚠️ |
| export-formats R-01 입력 정규화 | `core/export/rows.py` | T-01 | 지표: 통합 테스트 통과 |
| export-formats R-02~05 xlsx 5시트 | `core/export/xlsx.py` | T-02·T-03 | 헤더 12열·시트 5개·`=H*I` 수식 |
| export-formats R-06 신뢰도 리포트 JSON | `core/export/report.py` | T-04 | 지표: 통합 테스트 통과 |
| export-formats R-07 LOPA 초안 md(화면은 .docx) | `core/export/lopa.py` | T-05 | 지표: 통합 테스트 통과 |
| export-formats R-08·09 재현성·완료 조건 | `tests/test_export.py`, `tests/golden/export_gold34.snapshot.json` | T-06 | 골든 스냅샷 일치 |
| evaluation-harness R-01~06 하네스 | `eval/` — **미구현** | T-01~T-05 ☐ | 미측정 — 본선 |
| evaluation-harness 완료 조건(축소 실행) | `tools/capture_replay.py`, `tools/_replay.py::recall_for_node` | T-06(축소) | holdout recall 0.154, n=1 |
| self-verification R-01 규격 번호 | `core/agent/verify.py::STANDARD_PATTERNS` | T-02 | 삽입 5건 중 5 플래그 |
| self-verification R-02 수치 주장 | `core/agent/verify.py::NUMBER_PATTERN` | T-02 | 삽입 5건 중 5, 위양성(AC-02-1) 0 |
| self-verification R-03 격하·요약 | `core/agent/verify.py::verify`, `apps/web/service.py` | T-02·T-03 | 10건 중 10 `review` |
| self-verification R-04 누락 셀 | `VerifySummary.missing_cells` | T-02 | 4노드 실측 0 |

### 커밋 이력과 spec 순서

커밋 이력은 spec 순서(골드셋 → LLM 클라이언트 → 이탈 생성 → 내보내기 → 공급자 교체 → 평가 하네스 spec →
자기 검증)와 대응한다. `git log --oneline --grep=spec` 발췌 10줄(최신이 위):

```text
315a99d spec:self-verification T-01~T-04 — 규칙 기반 verifier (FR-06, 실호출 0회)
cad4438 spec:evaluation-harness — FR-08 평가 하네스 spec 손 작성 (9/24 당김)
0c9298f spec:bedrock-client T-15 — Anthropic 공급자 어댑터 (REQ-12)
0da8139 docs: PRD v2.0 (D-7 범위 재정의) + spec:bedrock-client REQ-12·T-15 손 추가
bc02f1d spec:export-formats T-01~T-06 — xlsx·LOPA·신뢰도 리포트 내보내기 (손 작성 spec)
a3a9179 spec:hazop-generation T-01~T-06 — 2단 매트릭스 이탈 생성 (mock 경로)
8cbb418 chore: Kiro spec hazop-generation 추가 (requirements/design/tasks)
c39d86d spec:bedrock-client T-01~T-11 — Converse 래퍼 mock 경로(실호출 미검증)
291f7ea spec:gold-dataset T-01~T-11 — xlsx→JSON 변환·노드 홀드아웃 분할
f9c14c0 chore: PRD v1.2, CLAUDE.md, Kiro steering 4종, spec gold-dataset/bedrock-client
```

## § 6 평가 결과

### 노드별 실측 (앱의 `evaluation_markdown` 출력 원문)

| 노드 | split | 레코드 | judged/expected | 절단 | 지연(s) | 비용($) | recall(m/n) |
|---|---|---|---|---|---|---|---|
| N1 벙커링선 매니폴드 | tune | 73 | 84/84 | 0 | 150.1 | 0.812 | 0.875 (7/8) |
| N2 이송 호스 | holdout | 61 | 70/70 | 0 | 422.7 | 0.745 | 0.222 (2/9) |
| N3 수급선 매니폴드 | holdout | 61 | 70/70 | 0 | 444.5 | 0.767 | 0.286 (2/7) |
| N4 이송 운전 절차 | holdout | 97 | 100/100 | 0 | 553.5 | 1.008 | 0.000 (0/10) |
| 홀드아웃 합계 | holdout | 219 | 240/240 | 0 | 1420.7 | 2.519 | 0.154 (4/26) |

> 2026-09-29 `claude-opus-4-8`(Anthropic 경로), `max_tokens=16384`, **노드당 1회(n=1)**. 합계 행은 holdout
> 3노드만(N1 은 tune 이라 섞지 않음). **N1 은 M-01·병렬(`parallel_calls: 4`) 적용 후 재캡처(9/29 14:32 KST)**,
> 홀드아웃 N2~N4 는 01:35~01:52 KST 순차 캡처 그대로다(재캡처하지 않음 — 아래 26건 대조표가 그 파일에 묶여 있다).
> 지연 합계는 순차 실행 벽시계의 합.

### M-01·병렬 적용 후 재캡처 (O-2 — P1·P2·N1, 각 n=1)

| 노드 | 지연(s) 이전 → 이후 | `safeguards_before` 채움 이전 → 이후 | F=3 비율 이전 → 이후 | 비용($) 이전 → 이후 | 레코드 | 판정 셀 | recall |
|---|---|---|---|---|---|---|---|
| P2 염소 톤컨테이너 | 417.1 → **145.9** | 0/64 → **65/70** | 84% (54/64) → **64%** (45/70) | 0.752 → 0.812 | 64 → 70 | 77/77 → 77/77 | — |
| P1 LPG 출하 | 440.8 → **138.1** | 35/69 → **60/72** | 87% (60/69) → 85% (61/72) | 0.793 → 0.778 | 69 → 72 | 84/84 → 84/84 | — |
| N1 NH3 매니폴드 | 511.5 → **150.1** | 0/61 → 0/73 (입력 안전장치 없음 — 해당 없음) | 85% (52/61) → **93%** (68/73) | 0.787 → 0.812 | 61 → 73 | 77/77 → 84/84 | 0.875 → 0.875 (7/8) |

> 이전 = 9/29 00:11~00:18 KST(P1·P2)·01:06 KST(N1) 순차 캡처, 이후 = 14:26~14:32 KST `parallel_calls: 4`. 세 노드 모두 절단 0·review 가이드워드 0·스키마 재시도 0, 호출 8회.
> **지연**은 약 3배 줄었으나 NFR-06(60초)은 여전히 미달이다. **비용**은 줄지 않는다 — 병렬 첫 묶음 4호출은 캐시가 비어 있으면
> 같은 시스템 블록을 동시에 써서 캐시 읽기를 못 한다(P2: 열거 포함 5호출 `cache_read=0`; P1·N1 은 P2 직후라 캐시가 살아 있어 0건).
> **P1 기존 안전장치**는 입력 원문 3개로만 나온다(가스누출감지기 50·긴급차단밸브(ESV) 37·안전밸브 18회, 이전의 `ESV`·`gas detector` 0회, 버린 항목 0).
> **F 분포**는 P2 만 풀렸다. P1 은 거의 그대로, N1 은 오히려 더 뭉쳤다(93%). F=1 은 세 노드 모두 0건. N1 파라미터 축은 11 → 12개(판정 셀 77 → 84).
>
> **매칭 규칙**: 가이드워드 정확 일치 **AND** 파라미터 정규화(공백·조사 제거) 일치. 이탈 텍스트 유사도
> 조건 없음(`tools/_replay.py::recall_for_node`). evaluation-harness R-02 의 정본 규칙(유사도 τ 포함)이
> 아니며, 정본으로 재면 같거나 더 낮다(유사도 조건이 추가되므로).

### 필수 지표 ([.kiro/steering/docs.md](.kiro/steering/docs.md) §3)

| 지표 | 값 | 목표 | 달성 여부 |
|------|----|------|----------|
| 이탈 recall (holdout) | 0.154 (4/26), n=1 | ≥ 0.70 | ⚠️ 미달 |
| 이탈 recall (tune N1) | 0.875 (7/8), n=1 | ≥ 0.5 (G1) | ✅ |
| 이탈 precision | 미측정 — 본선 | — | — |
| S 등급 MAE | 미측정 — 본선 | — | — |
| F 등급 MAE | 미측정 — 본선 | — | — |
| 근거 첨부율 | 미측정 — 본선 (근거 검색 미구현으로 292건 전부 `evidence=[]`) | — | — |
| 근거 정확도 | 미측정 — 본선 | — | — |
| 환각률(verifier `review` 비율) | 0% (0/292 — NH3 4노드, N1 재캡처 포함) — 규칙 verifier 한정, 수작업 확인 미실시 | 공개 | — |
| 노드당 지연 | 병렬 4: 138.1~150.1 s (N1·P1·P2) · 순차: 422.7~553.5 s (N2~N4). P90 미측정(n=1) | ≤ 60 s | ⚠️ 미달 |
| 노드당 토큰 | 입력 ≈ 7,707 + 캐시 읽기 ≈ 15,849 / 출력 ≈ 30,639 (9/29 1차 순차 캡처 4노드 평균 — 재캡처 미반영) | — | — |
| 노드당 비용 | $0.833 평균 (NH3 4노드, $0.745~$1.008) | ≤ $0.30 | ⚠️ 미달 |
| 출력 절단 | 0 / 35 호출 (NH3 4노드, 16,384 기준) · 재캡처 P1·P2 0/16 | 0 | ✅ |
| 5회 반복 평균±표준편차 | 미측정 — 본선 (전 지표 n=1) | — | — |

> 토큰은 로컬 실행 로그(`results/capture_*.log`, git 미추적)의 호출별 `tokens_in`·`cache_read`·`tokens_out`
> 합을 노드 4개로 평균한 값. N1 의 스키마 재시도로 버려진 호출 1건(출력 5,088)은 로그에 없어 빠져 있다.
> verifier 0건은 탐지 실패가 아니라 대상 부재다 — 280건 본문의 숫자는 `NH3`·`N2`·`2인` 뿐이고 규격 번호는
> 없었다. 결함 삽입 시험에서는 10건 중 10건을 `review` 로 격하했다(`tests/test_verify.py`).
> 수작업 채점은 하지 않았다.

### 골드 26건 대조 (holdout)

| 판정 | 건수 |
|---|---|
| 일치 | 4 (N2 More/압력·Less/온도, N3 More/압력·Reverse/유량) |
| 파라미터 어휘 불일치 | 22 |
| 가이드워드 미생성 | 0 |
| 조합 없음(가이드워드·파라미터 각각은 생성, 짝만 없음) | 0 |

가이드워드 축은 26/26 전부 생성됐다(N4 절차형 3종 포함). 실패는 전부 파라미터 축이다. 골드는 설비 고유
실패모드(장력·곡률반경·본딩·개스킷 사양)와 절차 단계(ESD·퍼징 생략·대피 방송)를 파라미터로 쓰고, 모델은
공정변수 5종(유량·압력·온도·상·조성) + 설비 축 2~5개로 수렴했다. 22건 중 16건은 골드 파라미터 단어가
같은 가이드워드의 생성 본문 어디에도 나오지 않았다 — 이름만 다른 것이 아니라 개념 자체가 없다.
26건 개별 대조표: [docs/진행로그.md](docs/진행로그.md) 2026-09-29 I-1 항.

### 출력 절단 실측 — `max_tokens` 4,096 → 16,384 (N1)

| 회차 | max_tokens | 파라미터 수 | 한도에 닿은 호출 | 판정 셀 | 레코드 | recall |
|---|---|---|---|---|---|---|
| 9/28 run1 | 4,096 | 10 | 0 | 70/70 | 66 | 0.875 (7/8) |
| 9/28 run2 | 4,096 | 11 | 5 | 22/77 | 17 | 0.250 (2/8) |
| 9/28 run3 | 4,096 | 12 | 6 | 12/84 | 8 | 0.125 (1/8) |
| 9/29 live | 16,384 | 11 | 0 | 77/77 | 61 | 0.875 (7/8) |
| 9/29 O-2 (병렬 4) | 16,384 | 12 | 0 | 84/84 | 73 | 0.875 (7/8) |

4,096 에 닿은 11회는 전부 JSON 이 잘려 `content=None` → 그 가이드워드 행 전체 소실로 이어졌다. 9/28 평균
recall 0.417 을 끌어내린 것은 모델 판정이 아니라 이 절단이다. 16,384 에서는 N1~N4 36호출 중 4,096 을
넘긴 호출이 12회(최대 출력 5,088) 있었고 절단은 0회였다.

## § 7 한계 · 본선 로드맵

### 한계

- **튜닝↔홀드아웃 격차**: N1 0.875 대 holdout 0.154. N1 골드 8건은 파라미터가 대부분 공정변수라 모델의
  기본 축과 겹친다. 홀드아웃 실패 22건은 전부 파라미터 축(어휘·개념 부재)이다.
- **골드 어휘를 프롬프트에 넣지 않은 이유**: N2~N4 골드의 파라미터 어휘를 열거 프롬프트에 넣으면 홀드아웃
  누출이다. 원칙만 주는 프롬프트 수정 후 재측정도 "튜닝된 홀드아웃"이 되어 새 홀드아웃이 없다.
- **지연**: 병렬 4 재캡처 노드 138.1~150.1초, 순차 캡처인 홀드아웃 3노드 422.7~553.5초 — 어느 쪽도 NFR-06(60초) 미달이다.
  병렬화 뒤에는 가장 긴 가이드워드 호출(출력 4천 토큰대, 약 60초)과 열거 호출이 바닥이다(§6 재캡처 표).
- **비용**: 노드당 $0.745~$1.008 — NFR-04(≤ $0.30) 미달.
- **n=1**: 모든 지표가 노드당 1회 실측이다. 분산을 모른다.
- **근거 인용 없음**: 280건 전부 `confidence=inferred`, `evidence=[]`. `grounded` 등급은 부여된 적이 없다.
- **운영 한계**: `core/llm` 에 호출 timeout 이 없어 네트워크가 끊기면 한 호출이 19분 매달린 사례가 있다.
  실호출 일일 상한은 프로세스 메모리 카운터라 재시작하면 0 으로 돌아간다([docs/backlog.md](docs/backlog.md)).
- **실무자 관점 평가** ([docs/실무자평가_20260929.md](docs/실무자평가_20260929.md) — 자격 있는 HAZOP 리더 검토 아님, 재생 291건 n=1):
  - P-1 기존 안전장치(Before) 공란 — 판정 프롬프트가 입력 안전장치를 받지 못했다(염소 예시 0/64). M-01 로 고친 뒤 재캡처(O-2): **염소 0/64 → 65/70, LPG 35/69 → 60/72**, 항목은 입력 원문으로만 나온다. 홀드아웃 N2~N4 재생은 재캡처하지 않아 여전히 수정 전 프롬프트 결과다(화면 출처 줄에 "M-01 이전 프롬프트" 표기).
  - P-2 빈도 F 가 한 값으로 뭉친다 — 1차 F=3 이 85~95%, F=1 은 0건. 재캡처 뒤 **염소만 64% 로 풀렸고 LPG 85%·NH3 N1 93% 는 그대로거나 더 뭉쳤다**. F=1 은 여전히 0건. 위험도 순위는 사실상 S 순위다(요약 줄에 F 분포 표시).
  - P-3 S·F 등급 정의가 NH3 선박 벙커링 기준인데 육상 예시 공정에도 쓴다 — 예시·직접 입력 화면에 "참고용" 배지.
  - P-5 노드가 너무 크다(P1 탱크→펌프→로딩암을 한 노드) — 원인마다 방호계층이 달라 LOPA 로 넘길 수 없다. 노드 분할 지원 없음.

### 본선 로드맵

1. **매트릭스 병렬 호출 — 예선 반영(O-1)**: 가이드워드 판정을 `parallel_calls`(기본 4)로 병렬화했다
   (hazop-generation R-10). 파라미터 **청크 분할**(한 호출의 파라미터 수 상한, [docs/지시문_G_병렬매트릭스.md](docs/지시문_G_병렬매트릭스.md))은 본선 과제로 남는다.
2. **평가 하네스 구현** — evaluation-harness T-01~T-05(`eval/`): 규칙 A/B 매칭, 유사도 τ, precision·S/F MAE,
   반복 실측 평균±표준편차.
3. **FR-05 tool use** — 물질 5종(`substance_lookup`)·고장률(`failure_rate`) 조회 tool.
4. **FR-04′ 근거 인용** — KOSHA 지침 발췌에서만 `evidence[]` 생성, 근거 첨부율 측정, `grounded` 부여.

### 예선에서 삭제·미착수한 항목 (PRD v2.0 §2)

| 항목 | 상태 |
|---|---|
| FastAPI | 삭제 — Streamlit 이 `core/` 직접 호출 |
| Knowledge Base(RAG) | 삭제 |
| LLM verifier 2차 호출 | 삭제 — 규칙 기반 1단만 |
| 임베딩 매칭 | 삭제 — 본선 |
| App Runner / Lambda 배포 | 삭제 |
| Dockerfile | 미작성 |
| FR-05 물질·고장률 tool, `data/kb/` | 미착수 |
| FR-04′ 로컬 인용 | 미착수 |
| evaluation-harness `eval/` (T-01~T-05) | 미착수 — 축소 실행만(§6) |

## § 8 실행 방법

아래 설치 경로(`requirements.txt` → `streamlit run`)는 9/29 새 venv 리허설(로컬 clone, Windows)에서 검증했다:
설치 1분 44초, 첫 화면 5.6초, 프리셋 클릭 → 표 3.3초(J-04 화면 재배치 이전 측정 — 재배치 후 로컬 측정은
[docs/진행로그.md](docs/진행로그.md) 2026-09-29 J 항).

```bash
git clone https://github.com/LEETHESAVAGE-kr/aws.git hazop-copilot
cd hazop-copilot
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m streamlit run apps/web/app.py
```

- macOS/Linux 는 `python3.12 -m venv .venv` 와 `.venv/bin/python` 으로 바꾼다(리허설은 Windows 에서만 했다).
- **화면 흐름**: ① **공정 선택**(`data/presets.json` 카탈로그 — NH3 벙커링 4노드 · LPG 저장탱크 출하 · 염소
  톤컨테이너 하역·기화) → 노드 버튼 → ② **LLM 에 보낸 입력**(NodeMeta) / **생성 과정**(열거된 파라미터·가이드워드·
  판정 셀·API 호출 수·지연·비용·절단·review 건수) → ③ **HAZOP 워크시트**(신뢰도 배지·검증 플래그 열) + xlsx·LOPA 초안(Word .docx)·
  신뢰도 리포트 JSON 다운로드 → 접힌 **평가 결과**(골드셋 대비 recall, NH3 4노드만).
- **verifier 시연 토글**: 워크시트 위 체크박스(기본 꺼짐, 골드 재생엔 없음). 켜면 **표시용 사본**의 첫 행 권고에
  근거 없는 규격 번호 `KOSHA GUIDE P-999` 를 붙여 규칙 verifier 를 다시 돌린다 → 그 행이 🔴 review·검증 플래그 열에 표시.
  실측 재생은 플래그 0 이라 이 장치가 작동하는 모습을 보이려는 것이다. 다운로드 3개와 재생 파일은 삽입 없는 원본이다.
- 카탈로그 공정은 **재생**이다: API 키 불필요, 실호출 0회. 화면에 캡처 일시(KST)·모델·비용을 적고, 병렬 캡처면
  " · 병렬 4", M-01 이전 프롬프트로 만든 재생(홀드아웃 N2~N4)이면 그 사실을 같은 줄에 적는다.
  NH3 는 골드셋 34건과 recall 을 실측했고, 예시 공정 2개는 골드셋이 없다(정성 검토용).
- **직접 입력 (빠른 실호출)**: 공정 선택 맨 아래. 공정을 **자연어 문장**으로 설명하고(입력 칸의 회색 예시 참고)
  가이드워드 1개(기본 More)를 골라 누르면 워크시트 한 행 묶음을 실제로 생성한다(약 1분). 호출은 3회 —
  ① 문장 → NodeMeta 해석(저비용 `verifier` 모델, 약 $0.003) ② 파라미터 열거 ③ 가이드워드 판정. 해석 결과는 원문 옆에
  그대로 보여 준다. 설명에 없는 수치는 비워 두고(추정 금지), 압력은 모델이 숫자·단위만 옮기고 **kPag 환산은 코드가 한다**.
  NodeMeta JSON(`{` 로 시작)을 넣으면 해석을 건너뛰어 2회다. 입력은 600자 이내.
  [.env.example](.env.example) 을 참고해 `HAZOP_ALLOW_LIVE=true` 와 `ANTHROPIC_API_KEY` 를 환경변수로 준다
  (Streamlit Cloud 는 App settings → Secrets). 앱은 `.env` 파일을 자동으로 읽지 않는다 — 실행 셸의 환경변수로 넣는다.
- **`HAZOP_LIVE_SCOPE`**: `quick`(기본 — 빠른 실호출만) | `full`(직접 입력 아래에 **노드 전체 실호출** 버튼 추가,
  가이드워드 7~10종, 노드 1건 약 7~9분·약 $0.75~1.01). 모르는 값은 `quick`. 상한(세션 1회·일 5회)은 두 버튼 공용이다.
- **오프라인 시험**: `make test`(= `ruff check .` + `HAZOP_USE_MOCK=true pytest -m "not live"`). 네트워크 0회.
  시험 의존성은 `pip install -e ".[dev]"` 로 설치한다. `make` 가 없으면 두 명령을 직접 실행한다.
- `make demo` 는 `streamlit run apps/web/app.py` 와 같다.
- 배포 URL: https://nwgll5tx3b2deizwqckhcc.streamlit.app — 재생 모드(키 불필요, 실호출 0회). 직접 입력 실호출은 배포 Secrets 의 키로 세션 1회·일 5회.

## § 9 비용

### 개발 중 LLM API 실지출 (Anthropic, `claude-opus-4-8`)

| 일자 | 항목 | 비용(USD) | 구분 |
|---|---|---|---|
| 9/28 | 스모크 1회 | 0.0098 | 실측 |
| 9/28 | T-07 N1 1회 (로그 유실) | ≈ 0.7 | **추정** |
| 9/28 | T-08 N1 3회 (0.713·0.751·0.790) | 2.254 | 실측 |
| 9/29 | N1 캡처 실패(네트워크 단절, 호출 2회 완료) | 0.132 | 실측(3번째 호출 과금 여부 미상) |
| 9/29 | 재캡처 시도(크레딧 잔액 부족으로 거부) | 0 | 실측 |
| 9/29 | N1 live 캡처 | 0.787 (+ 버려진 재시도 ≈ 0.13) | 실측 + **추정** |
| 9/29 | holdout N2·N3·N4 캡처 | 2.519 | 실측 |
| 9/29 | 예시 공정 P1·P2 캡처(지시문 J) | 1.545 | 실측(재생 파일 `cost_usd`) |
| 9/29 | O-2 재캡처 P2·P1·N1 (병렬 4) | 2.402 | 실측 |
| **합계** | | **실측 9.65 + 추정 ≈ 0.83 ≈ 10.5** | |

> 실측은 생성기 로그의 호출별 `cost_usd` 합. 오프라인 시험과 데모 재생 모드는 실호출 0회라 비용 0.
> 화면의 빠른 실호출(로컬·배포)은 이 표에 집계하지 않았다(건당 약 $0.03~0.15).

### 노드당 (9/29 live 4노드 평균, n=1)

| 항목 | 값 |
|---|---|
| 비용 | $0.833 (범위 $0.745~$1.008 — N1 은 재캡처 값) |
| 입력 토큰 | ≈ 7,707 (+ 캐시 읽기 ≈ 15,849) |
| 출력 토큰 | ≈ 30,639 |
| 호출 수 | 8~11 (열거 1 + 가이드워드 7~10) |

### 크레딧·개발 도구

| 항목 | 값 |
|---|---|
| Kiro 크레딧 | 9/11 export-formats 부터 크레딧 없이 spec 손 작성(§5). 사용량 기록 없음 |
| Anthropic API 크레딧 | 9/29 00:53 잔액 부족으로 거부 → 충전 후 재개. 9/29 14:00 잔량 $14 |
| 기타 개발 도구 비용 | Kiro: 대회 계정 크레딧 사용 · Claude Code: 개인 Claude 구독 안에서 사용, 별도 과금 없음 · Streamlit Community Cloud·GitHub: 무료 플랜 |
