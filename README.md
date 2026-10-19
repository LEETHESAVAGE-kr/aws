# 위험성평가 코파일럿 (HAZOP Copilot)

고려대 × AWS AI Innovators Challenge 2026 출품작이다. 공정 노드 설명(물질·상태·운전조건·설비)을 넣으면
LLM 이 HAZOP 가이드워드×파라미터 매트릭스를 칸마다 판정해 워크시트 초안(xlsx)과 LOPA 후보 시나리오(Word)를 만든다.
정답 워크시트와 다른 팀의 공개 HAZOP 에 대조한 성능은 불리한 값까지 §6 에 적었다.

- 배포: https://nwgll5tx3b2deizwqckhcc.streamlit.app (저장된 실행 결과 보기는 API 키 없이 동작)
- 실행: [§8](#-8-실행-방법)

---

## § 1 문제

HAZOP(위험과 운전성 분석)은 공정을 노드(배관·설비 구간이나 운전 절차)로 나누고, 노드마다 파라미터(유량·압력·
온도·준위·조성·상 등)에 가이드워드 7종(No·More·Less·Reverse·Other than·Part of·As well as)을 붙여 설계 의도에서
벗어난 이탈을 빠짐없이 찾는 방법이다. 운전 절차 노드에는 Too early·Too late·Wrong action 같은 절차형 가이드워드를
쓴다. 이탈마다 원인·결과·기존 안전장치를 적고 심각도(S)×빈도(F)로 위험도를 매긴 뒤 권고를 낸다. 결과물은 12열
워크시트(`No, 노드, 가이드워드, 이탈, 원인, 결과, 기존 안전장치, S, F, 위험도, 권고, 시나리오 연계`)다
(용어 정의: [.kiro/steering/domain.md](.kiro/steering/domain.md)).

**사고 사례.** 2019년 5월 17일 충남 서산 대산석유화학단지 한화토탈 공장의 스티렌모노머(SM) 저장탱크에서 유증기가
분출됐다. 고온의 SM 함유 물질을 6일간 보관하는 동안 중합방지제 효과가 떨어져 중합반응이 시작됐고, 탱크 온도가
146 ℃ 이상으로 오르며 약 97.5톤이 비상 방출구로 새어 나왔다. 5월 31일까지 주민·근로자 2,509명이 진료를 받았다.
온도 높음·조성 다름·중합방지제 적음은 모두 HAZOP 에서 다루는 이탈이다
([대전일보, 2019-05-31, 정부 합동조사 중간 결과](https://www.daejonilbo.com/news/articleView.html?idxno=1372037)).

**현장의 부담.** HAZOP 은 공정안전관리(PSM) 위험성평가의 중심 산출물이고, 컨설팅 현장에서는 워크시트 초안 작성에
인력과 시간이 가장 많이 든다(작성자가 이 업무를 직접 해 본 경험에 근거한 서술이며 측정값은 아니다). 기존 HAZOP
소프트웨어는 양식을 관리할 뿐 이탈을 만들어 주지 않는다. 범용 챗봇은 근거 없이 그럴듯한 이탈과 규격 번호를 지어낼
수 있는데, 안전 문서에서는 그런 출력이 곧 위험이다. 그래서 이 앱은 매트릭스의 모든 칸을 판정하게 하고, 출력을
스키마로 검증하고, 근거가 없는 주장은 사람이 검토할 항목으로 표시한다.

## § 2 왜 LLM인가

- 가이드워드×파라미터 칸 하나를 채우려면 "이 노드의 이 설비에서 이 조합이 물리적으로 말이 되는가"를 판단하고
  원인·결과·안전장치를 공정에 맞는 문장으로 써야 한다. 노드마다 설비 구성이 달라 고정 규칙표로는 대신할 수 없다.
- 생성은 두 단계다([core/agent/generate.py](core/agent/generate.py)).
  1. 노드 설명에서 파라미터를 6~12개 뽑는다([matrix_enumerate.md](core/agent/prompts/matrix_enumerate.md)).
  2. 가이드워드 하나에 호출 한 번으로 모든 파라미터 칸을 판정하고 서술한다
     ([deviation_generate.md](core/agent/prompts/deviation_generate.md)). 판정해야 할 칸 수와 실제 판정한 칸 수를 세어 누락을 기록한다.
- 출력은 tool use 의 `input_schema` 로 JSON 형식을 강제하고 [schemas/deviation.schema.json](schemas/deviation.schema.json) 으로
  한 번 더 검증한다. 검증에 실패하면 1회 다시 부르고, 그래도 실패한 가이드워드 행은 `confidence="review"` 로 낮춘다.
  429·529·5xx 응답은 1·2·4초 간격으로 3회까지 다시 부른다.
- 근거 인용: 판정 호출에 법령·고시·MSDS 발췌(호출당 최대 10문단)를 함께 넣고, 모델이 인용한 구절이 원문과 글자 단위로
  맞지 않으면 코드가 지우고 검토 대상으로 돌린다.
- 생성 뒤 [core/agent/verify.py](core/agent/verify.py) 가 근거 없는 규격·법령 번호와 단위 붙은 수치를 정규식으로 찾아
  `review` 로 낮춘다. 이 검사에는 LLM 을 쓰지 않는다.

## § 3 데이터 · 라이선스

출처·라이선스·재생성 방법은 [data/README.md](data/README.md) 에 있다.

| 데이터 | 내용 | 쓰임 |
|---|---|---|
| NH3 정답 워크시트 ([data/gold/](data/gold/)) | 작성자가 제12회 위험성평가 경진대회에 출품한 암모니아 벙커링 HAZOP 워크시트(본인 저작물) 34건. 원본 xlsx 는 저장소에 넣지 않고 변환한 JSON 만 둔다 | 노드 단위로 나눠 N1 은 프롬프트 조정, N2·N3·N4 는 평가에만 쓴다 ([split_node.json](data/gold/split_node.json)) |
| 공개 HAZOP 평가셋 ([data/reference/](data/reference/)) | 다른 팀이 공개한 HAZOP 워크시트의 (가이드워드, 파라미터) 쌍. 원인·결과 문장은 옮기지 않았다 | 평가 전용. 검색·예시·학습에 쓰지 않는다 |
| 근거 문서 ([data/kb/](data/kb/)) | 법령·고시 조문 186문단, MSDS 122문단, S·F 평가기준 3종(KOSHA C-C-37-2026 등), IPL 크레딧 규칙 | 판정 호출의 근거 인용 |
| 저장된 실행 결과 ([data/replay/](data/replay/)) | 실제 호출 결과를 [tools/capture_replay.py](tools/capture_replay.py) 로 저장한 JSON | 화면의 예시 공정과 §6 표 |
| 공정 목록 ([data/presets.json](data/presets.json)) | NH3 벙커링 4노드, 예시 공정 2개(LPG 저장탱크 출하·염소 톤컨테이너 기화), LPG 충전소 4노드 | 화면의 공정 선택. 예시 공정 2개는 정답이 없어 정성 검토용이다 |

- 고객사 실데이터와 개인정보는 쓰지 않는다.
- 화면 글꼴은 S-Core 에스코어 드림(무료 배포 글꼴, 수정·판매 금지)이며 눈누가 jsDelivr 에 올린 파일을 불러온다.

## § 4 아키텍처

```text
apps/web/app.py (Streamlit)        화면 배선 (공정 선택 → 입력 → 생성 과정 → 워크시트 → 검토 → 내보내기)
  ├─ service.py                    실제 호출 실행·호출 횟수 제한·결과표·내보내기
  ├─ catalog.py / replay.py        공정 목록, 저장된 실행 결과 불러오기
  └─ prompts/node_parse.md         자연어 공정 설명 → 노드 입력(JSON) 변환
        │
        ▼
core/agent/generate.py   ① 파라미터 열거 → ② 가이드워드별 칸 판정 (스키마 강제·재시도·격하, 가이드워드 판정 7개 동시 호출)
core/agent/consensus.py  같은 입력을 3번 판정해 합치는 선택 기능 (LLM 호출 없음)
core/agent/verify.py     근거 없는 규격 번호·수치 → review (LLM 호출 없음)
core/retrieval.py        근거 검색: BM25 + multilingual-e5-small 순위 융합
core/criteria.py         S·F 평가기준 (기준마다 단계 수·산정 방식이 다르다)
core/ipl.py · policy.py  IPL 빈도 크레딧, 입력에 없는 정보는 판정을 보류하는 규칙
        │
        ▼
core/llm/                공급자 추상화 — config/models.yaml 또는 HAZOP_PROVIDER 로 선택
  ├─ anthropic_client.py Anthropic Messages API (개발·측정)
  ├─ gateway_client.py   대회 AI 모델 게이트웨이 (OpenAI 호환, Bedrock 의 Claude)
  ├─ client.py           Amazon Bedrock Converse API
  └─ mock.py             오프라인 시험용
        │
        ▼
core/export/             xlsx 5시트(워크시트·평가기준·스크리닝·근거·신뢰도) · LOPA 초안(Markdown, 화면에서는 Word) · 신뢰도 JSON
```

- 모델 ID·리전·`max_tokens` 는 [config/models.yaml](config/models.yaml) 에서만 읽는다(`claude-opus-4-8`, `max_tokens: 16384`).
- 대회 계정에 Bedrock 권한이 없어(2026-09-15 확인) Bedrock 에 직접 보낸 호출은 0회다. Converse 어댑터는 모의 시험으로만 검증했다.
  10/14 측정은 대회가 제공한 게이트웨이(`bedrock-claude-opus-4-8`)를 거쳤다.

## § 5 Kiro 개발 방식 · 추적 매트릭스

- 기능마다 `.kiro/specs/<spec>/{requirements,design,tasks}.md` 를 먼저 쓰고, 코드는 tasks.md 의 T-xx 단위로 구현했다.
  커밋 메시지는 `spec:<name> T-xx — 요약` 형식이다(`git log --oneline --grep=spec`).
- steering 4종: [domain.md](.kiro/steering/domain.md)(HAZOP·LOPA 용어, S·F 등급) · [engineering.md](.kiro/steering/engineering.md) ·
  [aws.md](.kiro/steering/aws.md) · [docs.md](.kiro/steering/docs.md)(README 구성·평가표 규칙).
- spec 6종 가운데 [gold-dataset](.kiro/specs/gold-dataset/requirements.md) · [bedrock-client](.kiro/specs/bedrock-client/requirements.md) ·
  [hazop-generation](.kiro/specs/hazop-generation/requirements.md) 은 Kiro 가 만들었다. Kiro 크레딧이 떨어진 9/11 이후의
  [export-formats](.kiro/specs/export-formats/requirements.md) · [evaluation-harness](.kiro/specs/evaluation-harness/requirements.md) ·
  [self-verification](.kiro/specs/self-verification/requirements.md) 과 bedrock-client 의 REQ-12·T-15 는 같은 형식(EARS)으로 손으로 썼다.
- 시험: `pytest -m "not live"` 527 passed, 3 deselected(실제 호출 시험, 2026-10-19), `ruff check .` 통과.

### 추적 매트릭스

ID 는 각 spec 원문 그대로다(gold-dataset·bedrock-client 는 `REQ-xx`, 나머지는 `R-xx`).

| 요구사항 ID | 코드 모듈 | 테스트 ID | 측정 지표 |
|------------|----------|----------|----------|
| gold-dataset REQ-01·02 xlsx 입력·12열 매핑 | `tools/build_gold.py` | T-02·T-03·T-11 | 통합 테스트 통과 |
| gold-dataset REQ-03 출력 스키마 | `tools/_gold/models.py`, `tools/build_gold.py` | T-08·T-10·T-11 | 34건 스키마 검증 통과 |
| gold-dataset REQ-04~07 파싱·결측 검사 | `tools/build_gold.py` | T-04~T-08 | 통합 테스트 통과 |
| gold-dataset REQ-08 노드 단위 분할 | `tools/build_gold.py` (`NodeSplitter`) | T-09 | 조정용 8 / 평가용 26 |
| gold-dataset REQ-09 CLI·종료 코드 | `tools/build_gold.py::main` | T-10·T-11·T-13 | 통합 테스트 통과 |
| bedrock-client REQ-01 설정 로드 | `core/llm/config.py` | T-02 | 통합 테스트 통과 |
| bedrock-client REQ-02~04 Converse 호출·tool use·스키마 강제 | `core/llm/client.py` | T-06·T-07·T-10 | 모의 시험 통과, 실제 호출 스키마 통과 100%(재시도 포함) |
| bedrock-client REQ-05 재시도 | `core/llm/client.py` (`bedrock_retry`) | T-05 | 통합 테스트 통과 |
| bedrock-client REQ-06·07 로깅·비용 상한 경고 | `core/llm/client.py` | T-07 | $0.30 경고 발동 확인 |
| bedrock-client REQ-08 프롬프트 캐싱 | `core/llm/client.py`, `core/llm/anthropic_client.py` | T-04·T-10 | 캐시 읽기 2,186 토큰 확인 |
| bedrock-client REQ-09 비용 계산 | `core/llm/client.py` (`CostCalculator`) | T-03 | 통합 테스트 통과 |
| bedrock-client REQ-10 모의 클라이언트 | `core/llm/mock.py` | T-08·T-09·T-11 | 오프라인 시험 네트워크 0회 |
| bedrock-client REQ-11 실제 호출 확인 | `tests/test_llm_live.py` | T-12 | 9/28 1회 성공($0.0098) |
| bedrock-client REQ-12 공급자 교체 | `core/llm/anthropic_client.py`, `core/llm/__init__.py` | T-15 | 호출부 변경 없이 교체 |
| hazop-generation R-01·02 입출력 스키마 | `core/agent/generate.py`, `schemas/deviation.schema.json` | T-01·T-02 | 스키마 검증 100% |
| hazop-generation R-03 파라미터 열거 | `core/agent/prompts/matrix_enumerate.md`, `generate.py` | T-03·T-04 | 노드당 10~12개 |
| hazop-generation R-04 매트릭스 판정 | `core/agent/prompts/deviation_generate.md`, `generate.py` | T-04·T-06 | 판정 칸 317/317 |
| hazop-generation R-05 S·F·위험도 | `generate.py` | T-04·T-06 | 위험도 = S×F |
| hazop-generation R-06 스키마 실패 처리 | `generate.py` | T-04·T-06 | review 로 낮춘 가이드워드 0 |
| hazop-generation R-07 오프라인 시험 | `tests/test_generate.py` | T-06 | 통합 테스트 통과 |
| hazop-generation R-08 캐싱 적용 지점 | `generate.py` | T-05 | 캐시 읽기 2,186 토큰 확인 |
| hazop-generation R-09 완료 조건 | `generate.py`, `tools/capture_replay.py` | T-07·T-08 | 지연 ≤ 60초 ⚠️ / N1 recall ≥ 0.5 ✅ / 평가용 ≥ 0.7 ⚠️ |
| hazop-generation R-10 가이드워드 동시 호출 | `generate.py` (`parallel_calls`) | T-09 | 순차·동시 결과 바이트 동일(모의) |
| export-formats R-01 입력 정규화 | `core/export/rows.py` | T-01 | 통합 테스트 통과 |
| export-formats R-02~05 xlsx 5시트 | `core/export/xlsx.py` | T-02·T-03 | 12열·5시트·`=H*I` 수식 |
| export-formats R-06 신뢰도 JSON | `core/export/report.py` | T-04 | 통합 테스트 통과 |
| export-formats R-07 LOPA 초안 | `core/export/lopa.py` | T-05 | 통합 테스트 통과 |
| export-formats R-08·09 재현성 | `tests/test_export.py`, `tests/golden/export_gold34.snapshot.json` | T-06 | 기준 스냅샷 일치 |
| evaluation-harness R-01~06 평가 하네스 | `eval/` — 미구현 | T-01~T-05 ☐ | 미측정 |
| evaluation-harness 축소 실행 | `tools/_replay.py::recall_for_node` | T-06(축소) | 평가용 recall 0.154, n=1 |
| self-verification R-01 규격 번호 | `core/agent/verify.py` | T-02 | 심은 5건 중 5건 표시 |
| self-verification R-02 수치 주장 | `core/agent/verify.py` | T-02 | 심은 5건 중 5건, 오탐 0 |
| self-verification R-03 격하·요약 | `core/agent/verify.py`, `apps/web/service.py` | T-02·T-03 | 10건 중 10건 `review` |
| self-verification R-04 누락 칸 | `VerifySummary.missing_cells` | T-02 | 4노드 실측 0 |

## § 6 평가 결과

모든 값은 노드당 1회 실행(n=1)이다. recall 매칭 규칙은 가이드워드가 같고 파라미터 이름이 정규화(공백·조사 제거) 뒤 같으면
일치로 본다(`tools/_replay.py::recall_for_node`). 이탈 문장의 유사도는 보지 않는다.

### 필수 지표 ([.kiro/steering/docs.md](.kiro/steering/docs.md) §3)

| 지표 | 값 | 목표 | 달성 여부 |
|------|----|------|----------|
| 이탈 recall (평가용 N2~N4) | 0.154 (4/26) | ≥ 0.70 | ⚠️ 미달 |
| 이탈 recall (조정용 N1) | 0.875 (7/8) | ≥ 0.5 | ✅ |
| 이탈 precision · S MAE · F MAE | 미측정 | — | — |
| 근거 첨부율 · 근거 정확도 | 미측정 (저장된 NH3 결과 292건은 근거 인용 기능 이전 실행이라 전부 `evidence=[]`) | — | — |
| 환각률(verifier `review` 비율) | 0% (0/292) — 규칙 검사 한정, 사람 확인 안 함 | 공개 | — |
| 노드당 지연 | 동시 7: 79.2~125.5 s · 동시 4: 138.1~150.1 s · 순차: 422.7~553.5 s. P90 미측정 | ≤ 60 s | ⚠️ 미달 |
| 노드당 토큰 | 입력 ≈ 7,707 + 캐시 읽기 ≈ 15,849 / 출력 ≈ 30,639 (9/29 NH3 4노드 평균) | — | — |
| 노드당 비용 | $0.833 평균 (NH3 4노드, $0.745~$1.008) | ≤ $0.30 | ⚠️ 미달 |
| 출력 절단 | 0 / 35 호출 (`max_tokens` 16,384) | 0 | ✅ |
| 5회 반복 평균±표준편차 | 미측정 | — | — |

> verifier 0건은 검사가 실패해서가 아니라 잡을 대상이 없어서다. 9/29 결과 본문의 숫자는 `NH3`·`N2`·`2인` 뿐이고 규격 번호는
> 없었다. 결함을 일부러 심은 시험에서는 10건 중 10건을 `review` 로 낮췄다([tests/test_verify.py](tests/test_verify.py)).
> 수작업 채점은 하지 않았다.

### NH3 정답 워크시트 대조

| 노드 | 구분 | 레코드 | 판정 칸 | 지연(s) | 비용($) | recall |
|---|---|---|---|---|---|---|
| N1 벙커링선 매니폴드 | 조정용 | 73 | 84/84 | 150.1 | 0.812 | 0.875 (7/8) |
| N2 이송 호스 | 평가용 | 61 | 70/70 | 422.7 | 0.745 | 0.222 (2/9) |
| N3 수급선 매니폴드 | 평가용 | 61 | 70/70 | 444.5 | 0.767 | 0.286 (2/7) |
| N4 이송 운전 절차 | 평가용 | 97 | 100/100 | 553.5 | 1.008 | 0.000 (0/10) |
| 평가용 합계 (9/29) | | 219 | 240/240 | 1420.7 | 2.519 | 0.154 (4/26) |
| 평가용 합계 (10/14 다시 실행) | | 228 | 267/267 | 310.6 | 3.822 | 0.154 (4/26) |

> 9/29: Anthropic API, `claude-opus-4-8`. N1 은 안전장치 입력 수정·동시 호출 4개 적용 뒤 결과이고, N2~N4 는 그 전에 순차로 실행한 결과다.
> 10/14: 대회 게이트웨이, KOSHA C-C-37 기준, 근거 인용·판정 보류·빈도 근거 켬, 동시 호출 7개. recall 은 9/29 와 같다.

일치한 4건은 N2 More/압력·Less/온도, N3 More/압력·Reverse/유량이다. 가이드워드는 26건 모두 생성됐고(N4 절차형 3종 포함)
놓친 22건은 전부 파라미터 쪽이다. 정답은 설비 고유의 고장 방식(장력·곡률반경·본딩·개스킷 사양)과 절차 단계(ESD·퍼징 생략·
대피 방송)를 파라미터로 쓰는데, 모델은 공정변수 5종(유량·압력·온도·상·조성)과 설비 파라미터 2~5개로 모였다. 22건 중
16건은 정답 파라미터 낱말이 같은 가이드워드의 생성 본문 어디에도 없었다. 이름이 다른 것이 아니라 개념 자체가 빠졌다.

### 다른 팀의 공개 HAZOP 대조 (2026-10-10)

다른 팀이 쓴 표의 (가이드워드, 파라미터) 쌍을 이 앱이 다시 만들어내는 비율(coverage)이다. 원인·결과 문장이 맞는지는 재지 않는다.
설정은 한 번 생성, 근거 인용·판정 보류 켬, KOSHA C-C-37 기준이다. 화면의 '다른 팀의 HAZOP 과 대조' 패널도 같은 값을
[external_eval_summary.json](data/reference/external_eval_summary.json) 에서 읽는다. 상세: [docs/결과_외부평가_20261010.md](docs/결과_외부평가_20261010.md).

| 출처 | 공정 | 다시 만든 쌍 | coverage |
|---|---|---|---|
| Assam 2010 | 천연가스 압축기지·배관 | 15/17 | 0.88 |
| KAIS 2019 | 아크릴 수지 회분식 라디칼 중합 | 47/57 | 0.82 |
| IOCL 2016 | 석유제품 터미널(HSD·MS·에탄올 입고·출하) | 30/38 | 0.79 |
| ORNL 2023 | 무수 암모니아 연료 저장·공급(엔진 시험동) | 29/39 | 0.74 |
| 공정 HAZOP 4건 평균 | | | 0.81 |

- 평가셋에 함께 모았던 작업 절차 HAZOP 1건(IJERPH 2017, 항만 터미널 하역)은 가이드워드 대응 규칙이 달라 같은 기준으로 잴 수 없어 뺐다.
- 정전기·부식·속도·계류처럼 작업 고유의 파라미터는 적게 만든다(부식·속도는 나오지 않음). 편집 표에서 사람이 채워야 하는 부분이다.
- ORNL·IJERPH 의 파라미터 이름은 10/8 파라미터 예시 실험에 들어간 적이 있다. 그 예시 기능(`enumerate_examples`)은 꺼 둔다.

LPG 충전소 4노드(IOCL 2014 부록 A, 쌍 44개)에서는 0.909(40/44)였다. 다만 이 기준은 4노드 모두 같은 공정변수 점검표(유량·압력·
온도·준위·조성)라 모델이 기본으로 내는 파라미터와 겹치고, 노드 입력도 그 워크시트 설명을 옮겨 쓴 것이다. NH3 평가용 0.154 와
나란히 읽으면 안 된다. 놓친 4건 중 3건은 More 판정 호출 하나가 10칸 중 1칸만 돌려줘서, 1건은 열거에 `조성` 이 없어서 생겼다.

### 바꿔 본 설정과 결과

| 시도 | 결과 | 채택 |
|---|---|---|
| 가이드워드 판정 동시 호출 (순차 → 4 → 7) | 같은 노드 3개에서 순차 417~511 s → 동시 4개 138~150 s. 같은 입력에서 4개 138.8 s → 7개 79.2 s, 429 재시도 0회. 비용은 줄지 않음 | 7 |
| `max_tokens` 4,096 → 16,384 | 4,096 에서는 11회 호출이 잘려 그 가이드워드 행이 통째로 빠졌다(N1 recall 0.125~0.875). 16,384 에서 절단 0회 | 16,384 |
| 판정 프롬프트에 입력 안전장치 전달 | 기존 안전장치 칸 채움 염소 0/64 → 65/70, LPG 35/69 → 60/72 | 켬 |
| 공개 HAZOP 파라미터 25개를 열거 예시로 제공 (규칙을 측정 전에 커밋) | 평가용 26건 중 열거 목록에 들어간 파라미터 4/26, 3회 반복 모두 예시 없을 때와 같음 | 끔 |
| 근거 인용 (법령·고시·MSDS 발췌 2건/파라미터) | 비용 +14~72%. 원문과 다른 인용(N1 7건·N2 4건)을 코드가 지우고 검토 대상으로 돌림. recall 변화 없음 | 켬 (비용 규칙은 넘었으나 작성자 결정) |
| 입력에 없는 정보가 필요한 칸은 판정 보류 | 보류 6~23칸(같은 문장에서도 15 → 6 으로 흔들림), 상한 40% 이내 | 켬 |
| 같은 입력을 3번 판정해 합치기 | 판정 일치율 N1 0.708 → 0.881. 지연 217~354 s, 비용 약 3배. NH3 정답 34건의 원인 중 9건을 담음(한 번 생성은 7~8건) | 선택 기능 |

> 근거 인용을 켠 실행에서 LPG 입력에 수소 MSDS 를 2회 인용했다. 같은 가연성 가스를 다루는 문서일 뿐 이 물질의 근거는 아니다.
> 검색이 물질을 가려내지 못한다. 3번 생성 합치기의 사전 규칙: [docs/사전등록_C_합의생성_20261009.md](docs/사전등록_C_합의생성_20261009.md),
> [docs/사전등록_합치기_20261011.md](docs/사전등록_합치기_20261011.md).

## § 7 한계 · 본선 로드맵

### 한계

- 조정용 N1 0.875 와 평가용 0.154 의 차이가 크다. N1 정답 8건은 대부분 공정변수라 모델의 기본 파라미터와 겹친다.
  평가용 노드의 정답 어휘를 프롬프트에 넣으면 평가 데이터가 새므로 넣지 않았고, 새로 확보한 평가 데이터도 없다.
- 공개 예시 자료를 고를 때 평가용 노드에서 놓친 유형을 이미 알고 있었다. 그 뒤로 이 평가용 노드는 깨끗한 평가 데이터가 아니다.
- 지연은 동시 호출 7개에서도 60초 목표를 넘는다. 가장 긴 가이드워드 판정 한 건(약 47~50초)과 파라미터 열거(약 17초)가 바닥이다.
- 노드당 비용 $0.745~$1.008 로 목표($0.30)를 넘고, 근거 인용을 켠 뒤 차이가 더 커졌다.
- 모든 지표가 n=1 이라 분산을 모른다.
- 화면에 저장된 NH3 결과는 근거 인용 기능 이전에 만든 것이라 `evidence` 가 비어 있다.
- 빈도(F)가 한 값으로 몰린다. 1차 실행에서 F=3 이 85~95% 였고, 수정 뒤에도 염소만 64% 로 풀렸다. 위험도 순위는 사실상 S 순위다.
- 노드가 크면(LPG 탱크→펌프→로딩암을 한 노드) 원인마다 방호계층이 달라 LOPA 로 바로 넘길 수 없다. 노드 분할 기능은 없다.
- 실무자 관점 검토([docs/실무자평가_20260929.md](docs/실무자평가_20260929.md))는 자격 있는 HAZOP 리더의 검토가 아니다.
- `core/llm` 호출에 timeout 이 없어 네트워크가 끊겨 한 호출이 19분 멈춘 적이 있다. 실제 호출 일일 상한은 프로세스 메모리에 있어
  재시작하면 0 으로 돌아간다([docs/backlog.md](docs/backlog.md)).

### 본선 로드맵

1. 평가 하네스(`eval/`, evaluation-harness T-01~T-05): 유사도 매칭, precision·S/F MAE, 반복 측정 평균±표준편차.
2. 파라미터가 많은 노드는 한 호출의 파라미터 수를 나눠 지연을 줄인다.
3. 물질·고장률 조회 tool.
4. 근거 첨부율·근거 정확도 측정.

## § 8 실행 방법

9/29 Windows 새 가상환경에서 아래 순서로 설치 1분 44초, 첫 화면 5.6초를 확인했다.

```bash
git clone https://github.com/LEETHESAVAGE-kr/aws.git hazop-copilot
cd hazop-copilot
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m streamlit run apps/web/app.py
```

- macOS/Linux 는 `python3.12 -m venv .venv` 와 `.venv/bin/python` 을 쓴다(확인은 Windows 에서만 했다).
- 공정 목록의 예시는 저장된 실행 결과를 보여 준다. API 키가 필요 없고 호출도 하지 않는다.
- 새 공정을 문장으로 설명해 실제로 생성하려면 환경변수를 준다([.env.example](.env.example) 참고, Streamlit Cloud 는 App settings → Secrets).
  앱은 `.env` 파일을 자동으로 읽지 않는다.

| 환경변수 | 뜻 |
|---|---|
| `HAZOP_ALLOW_LIVE=true` | 실제 호출 허용 |
| `HAZOP_PROVIDER` | `anthropic`(기본) 또는 `gateway` |
| `ANTHROPIC_API_KEY` / `KIRO_API_KEY` | 각 공급자의 키 |
| `HAZOP_SESSION_LIMIT` · `HAZOP_DAILY_LIMIT` | 실제 호출 상한(기본 브라우저 접속당 1회·하루 5회) |

- 가이드워드 7종 전체 생성은 약 1.5~2분, 10/9 측정 기준 $0.78~1.09 다(문장 해석 1 + 열거 1 + 판정 7회). 입력은 600자 이내.
- 오프라인 시험: `make test`(= `ruff check .` + `HAZOP_USE_MOCK=true pytest -m "not live"`). 시험 의존성은 `pip install -e ".[dev]"`.
  `make` 가 없으면 두 명령을 직접 실행한다.

## § 9 비용

### 개발 중 API 지출 (Anthropic, `claude-opus-4-8`)

| 기간 | 내용 | 비용(USD) |
|---|---|---|
| 9/28~9/29 | 예선: 연결 확인, N1 측정, NH3 4노드·예시 공정 2개 저장, 동시 호출 적용 뒤 다시 실행 | 9.65 (실측) + 약 0.83 (로그 유실분 추정) |
| 10/8 | 파라미터 예시 실험, LPG 충전소 4노드, 짧은 실행 3회 | 4.26 |
| 10/9 | 근거 인용 3회, 판정 보류 3회, 3번 생성 합치기 측정 | 17.32 |
| 합계 | | 실측 31.23 + 추정 약 0.83 ≈ 32.1 |

> 실측은 생성기 로그의 호출별 `cost_usd` 합이다. 오프라인 시험과 저장된 결과 보기는 호출이 없어 비용 0 이다.
> 대회 게이트웨이 사용분(10/14 NH3 4노드 다시 실행 $6.14 등)은 대회 제공 예산이라 이 표에 넣지 않았다.

### 노드당 (9/29 NH3 4노드 평균, n=1)

| 항목 | 값 |
|---|---|
| 비용 | $0.833 (범위 $0.745~$1.008) |
| 입력 토큰 | ≈ 7,707 (+ 캐시 읽기 ≈ 15,849) |
| 출력 토큰 | ≈ 30,639 |
| 호출 수 | 8~11 (열거 1 + 가이드워드 7~10) |

개발 도구: Kiro 는 대회 계정 크레딧(9/11 소진), Claude Code 는 개인 구독 안에서 사용해 별도 과금이 없다.
Streamlit Community Cloud·GitHub 는 무료 플랜이다.
