# PRD — 위험성평가 코파일럿 (고려대 × AWS AI Innovators Challenge 2026)

버전 v1.2 · 작성 2026-09-04 · 개정 2026-09-05 19:10 (구현 착수 — Claude Code 세션 운용 절 추가) · 예선 제출 2026-09-29 · 팀 1인 · 정본 위치: 프로젝트 루트 `PRD.md`
상위 문서: `AI_Innovators_수상전략서_v1.md` (왜 이 아이템인가 · 심사 구조 · 확률). 이 문서는 "무엇을 만들고 어떤 기준으로 완료 판정하는가"만 다룬다.

> **작업 도구 규칙 (가장 먼저 읽을 것)**
> 이 프로젝트는 **Kiro가 설계 정본, Claude Code가 구현 엔진**이다. 요구사항·설계·태스크는 반드시 Kiro spec(`.kiro/specs/`)으로 먼저 만들고, Claude Code는 그 `tasks.md`의 항목을 구현한다. Kiro를 거치지 않은 기능은 존재하지 않는 것으로 취급한다. 이유는 §7 NFR-01 — 제출 코드 10점과 기술 30점의 일부가 `.kiro/` 디렉토리에서 나온다.

---

## 0. 한 문장 정의

공정 노드 설명(물질·상태·운전조건·설비)을 입력하면, Amazon Bedrock 에이전트가 HAZOP 이탈 시나리오를 생성하고 각 항목에 KOSHA 기술지침·MSDS·문헌 고장률 **근거를 인용으로 붙이고**, 자기 출력의 신뢰도를 항목별로 채점한 뒤, PSM 제출 양식의 HAZOP 워크시트(xlsx)와 LOPA 초안(md)으로 내보내는 서비스. 골드셋(전문가 HAZOP 34 이탈) 대비 성능을 README에 숫자로 공개한다.

성공의 정의(예선): **새 환경에서 README만 보고 5분 안에 실행 → 노드 1개 입력 → 근거가 달린 워크시트 xlsx 다운로드**가 되고, 평가표에 recall·근거정확도·환각률·비용이 적혀 있다.

---

## 1. 배경 (전략서에서 확정된 사실)

- 배점: 기획 20 / 개발 70(기술 30·활용성·완성도 30·코드 10) / 본선 10. 예선 온라인 심사(9/30~10/2)에서 90점 결정.
- 심사자 추정: 정보대학 교수진(문제정의·평가방법) + AWS SA(Bedrock 활용 깊이·Kiro 흔적).
- 승리 공식: 좁은 실무 도메인 × AWS 네이티브 구현 × **측정된 신뢰성** × 3분 데모 임팩트.
- 킬 체크(전략서 §2): 9/7 Bedrock 호출 성공 · 9/10 프롬프트만으로 recall ≥ 0.5 · 텍스트 입력만으로 데모 성립.

---

## 2. 사용자와 시나리오

| 사용자 | 상황 | 이 서비스가 하는 일 |
|---|---|---|
| PSM 컨설턴트(1차 페르소나, 본인) | 신규 사업장 HAZOP 워크시트 초안을 팀 회의 전에 만들어야 함 | 노드별 이탈 초안 + 근거 + 신뢰도 배지 → 회의에서 검토·수정 |
| 중소 화학사업장 안전관리자 | 자기규율 예방체계로 위험성평가를 자체 수행해야 하지만 HAZOP 경험 없음 | 가이드워드 누락 없이 초안 확보, KOSHA 지침 문단으로 학습 |
| 심사위원(온라인) | README 보고 직접 실행 | 데모 노드 프리셋 1클릭 → 결과·평가표 확인 |

핵심 사용 흐름(예선 범위):
1. 노드 입력(폼 또는 JSON): 노드명, 물질(CAS 또는 명칭), 상(액/기), 운전 압력·온도, 설비 목록, 기존 안전장치.
2. "생성" → 에이전트 루프 실행(20~60초).
3. 결과 표: 이탈 행마다 원인·결과·기존 안전장치·S·F·권고 + **근거 인용(문서명·문단)** + **신뢰도 배지(근거 있음/추정/검토 필요)**.
4. xlsx(HAZOP 워크시트 양식) · LOPA 초안 md 다운로드.
5. (선택) "평가 실행" → 골드셋 대비 지표 재계산.

---

## 3. 데이터 명세

### 3.1 골드셋 (보유)
- 원본: `공모전/위험성평가경진대회/NH3-STS-QRA/04_hazop/D1_HAZOP_워크시트.xlsx`, 시트 `HAZOP워크시트` 36행×12열.
- 컬럼: `No, 노드, 가이드워드, 이탈, 원인, 결과, 기존 안전장치(Before), S(1-5), F(1-5), 위험도, 권고, 시나리오 연계`.
- 노드: N1 벙커링선 매니폴드 외(S1·S2·S3 시나리오 연계). 변환 후 `data/gold/hazop_nh3.json` (이탈 단위 레코드, 노드 메타 포함).
- 분할: **노드 단위 홀드아웃**. 프롬프트 튜닝은 N1 계열만, 평가는 나머지 노드. 노드 수가 적으면 이탈 단위 stratified 70/30으로 대체하고 README에 명시.
- 시트 `평가기준`(S·F 등급 정의)은 그대로 프롬프트 컨텍스트와 xlsx 출력 양식에 재사용.

### 3.2 지식 베이스 (수집, 전부 공개 자료)
- KOSHA Guide P-시리즈 중 HAZOP·LOPA·PSM 위험성평가 관련 5~8종 PDF → `data/kb/kosha/`. 문서별 메타(코드·제목·개정연도) `data/kb/manifest.csv`.
- 문헌대장 L-01~27·가정대장 A-01~22(NH3 QRA `01_registers/`) → 고장률·가정 근거 tool의 시드 `data/kb/registers.json`.
- 화학물질 속성: KOSHA 화학물질정보 또는 화학물질안전원 공개 MSDS 항목(비점·인화점·독성 등) → 데모용 물질 20종 캐시 `data/kb/substances.json`. 실시간 API는 비목표.

### 3.3 금지
- **KECC 고객사 실데이터 사용 금지.** 데이터 출처·라이선스 표를 `data/README.md`에 두고 README에서 링크.
- 개인정보 없는 데이터만. Guardrails에 PII 차단을 켠다(NFR-05).

---

## 4. 시스템 설계 (요약 — 상세는 Kiro `design.md`)

```
apps/web (Streamlit)  ──HTTP──▶  services/api (FastAPI)
                                     │
                                     ▼
                           core/agent  (Bedrock Converse API, tool use 루프)
                             ├─ tool: kb_search      → Bedrock Knowledge Base (S3 + 벡터 스토어)
                             ├─ tool: substance_lookup → data/kb/substances.json
                             ├─ tool: failure_rate    → data/kb/registers.json
                             └─ verifier (2차 호출)   → 근거 없는 주장 플래그, 누락 가이드워드 점검
                                     │
                                     ▼
                           core/export  (xlsx 워크시트 · LOPA md · 신뢰도 리포트 json)
eval/  (골드셋 하네스: recall·precision·근거정확도·환각률·지연·비용, 시드 고정 5회)
.kiro/ (specs · steering · hooks · mcp 설정)  ← 심사 대상 산출물
```

- 모델: Bedrock Claude 계열(크로스리전 추론 프로파일 허용). 모델 ID·리전은 `config/models.yaml` 한 곳에서만 정의(교체 비용 0).
- 라우팅: 생성은 상위 모델, verifier·요약은 하위 모델(비용). 프롬프트 캐싱 적용 지점: 시스템 프롬프트 + 평가기준 + 가이드워드 정의.
- 구조화 출력: 이탈 레코드 JSON 스키마(`schemas/deviation.schema.json`)를 tool 결과·최종 출력 모두에 강제. 스키마 검증 실패 시 1회 재시도 후 "검토 필요"로 격하.
- Guardrails: PII 차단, 금칙(허위 규격 번호 생성 방지 — 근거 tool 결과에 없는 KOSHA 코드 인용 시 verifier가 플래그).
- 배포: 예선은 단일 컨테이너(Docker) + 로컬 실행 지침. 여력 있으면 App Runner/ECS 1개 URL. Lambda 전환은 본선.

---

## 5. 기능 요구사항 (FR)

각 FR은 Kiro spec 1개 또는 spec 내 requirement 묶음에 대응한다. 완료 조건은 전부 자동 테스트 또는 산출 파일로 확인 가능해야 한다. 상태는 이 문서에서 갱신한다.

### FR-01 골드셋 변환 (`tools/build_gold.py`) — spec: `gold-dataset`
- xlsx → `data/gold/hazop_nh3.json`. 레코드: `{id, node, node_meta{substance, phase, P, T, equipment, safeguards}, guideword, parameter, deviation, causes[], consequences[], safeguards_before[], S, F, recommendations[], scenario}`.
- 가이드워드 문자열 `"More (압력)"`을 `guideword="More", parameter="압력"`으로 분해.
- 완료: 레코드 수 = 원본 행 수, 필수 필드 결측 0, 테스트 `tests/test_gold.py` 통과.

### FR-02 Bedrock 클라이언트와 설정 (`core/llm/`) — spec: `bedrock-client`
- Converse API 래퍼: 시스템 프롬프트·메시지·tool 정의·JSON 스키마 강제·재시도·토큰/지연/비용 로깅.
- `config/models.yaml`: 리전, 생성 모델 ID, verifier 모델 ID, 온도, 최대 토큰, 캐싱 on/off.
- 완료: 스모크 테스트(실호출 1회, 마커 `@pytest.mark.live`) 통과 · 모의 클라이언트로 오프라인 테스트 가능.
- **킬 체크 9/7 대상.**

### FR-03 이탈 생성 루프 (`core/agent/generate.py`) — spec: `hazop-generation` ★핵심
- 입력: 노드 메타 JSON. 출력: 이탈 레코드 배열(FR-01과 동일 스키마 + `evidence[]`, `confidence`).
- 가이드워드 × 파라미터 매트릭스(No/More/Less/Reverse/Other than/Part of/As well as × 유량·압력·온도·조성·준위 등)를 **먼저 열거**하고, 각 셀에 대해 적용 여부·이탈을 생성(누락 방지 구조).
- S·F는 `평가기준` 시트 정의를 컨텍스트로 주고 정수 1~5로 산출, 위험도 = S×F.
- 완료: N1 노드 입력 시 60초 내 결과, 스키마 검증 100%, 골드셋 N1 대비 recall ≥ 0.5(9/10 킬 체크). 최종 목표 recall ≥ 0.7(홀드아웃 노드).

### FR-04 근거 검색 tool과 인용 (`core/agent/tools/kb_search.py`) — spec: `evidence-citation`
- Bedrock Knowledge Base 구축 스크립트(`infra/kb_setup.py`: S3 업로드 → KB 생성 → 동기화) + 검색 tool(질의 → top-k 문단, 문서명·페이지·문단 텍스트 반환).
- 이탈 레코드의 `evidence[]`에 `{source_id, doc_title, locator, quote}` 첨부. 인용은 **tool이 반환한 텍스트에서만** 가능 — 모델이 스스로 쓴 규격 번호는 verifier가 제거.
- 완료: 데모 노드 결과의 이탈 중 근거 첨부율 ≥ 80%, 수작업 채점 30건에서 근거정확도(인용 문단이 주장을 지지) ≥ 0.8.

### FR-05 물질 속성·고장률 tool (`core/agent/tools/substance.py`, `failure_rate.py`) — spec: `evidence-citation` 내 포함
- `substance_lookup(name|CAS)` → 비점·인화점·독성·증기압 등, 출처 필드 포함. S 등급 산정 근거로 사용.
- `failure_rate(equipment, mode)` → registers.json에서 문헌 고장률·L-번호 반환. F 등급 근거.
- 완료: 데모 물질 20종·설비 10종 조회 성공, 미존재 시 명시적 `not_found` 반환(환각 방지).

### FR-06 자기 검증(verifier) 와 신뢰도 배지 (`core/agent/verify.py`) — spec: `self-verification`
- 2차 호출: 각 이탈에 대해 (a) evidence가 주장을 지지하는가 (b) 수치·규격 주장 중 근거 없는 것 (c) 매트릭스 누락 셀. 출력 `confidence ∈ {grounded, inferred, review}` + 사유.
- 규칙: evidence 없음 → 최고 `inferred`; 근거 없는 수치 주장 존재 → `review`.
- 완료: 의도적으로 근거 없는 규격 번호를 삽입한 테스트 케이스 10건 중 ≥ 9건 플래그.

### FR-07 내보내기 (`core/export/`) — spec: `export-formats`
- xlsx: 골드셋 원본과 **동일한 12열 양식** + 추가 시트 `근거`(이탈 No ↔ 인용) + `신뢰도`. 위험도 셀은 수식 `=H*I` 유지.
- LOPA 초안 md: 위험도 상위 N개 이탈에 대해 IE·IPL 후보·필요 PFD 서술(형식은 NH3 `08_bowtie_lopa/LOPA_S1_C1.md` 준용).
- 신뢰도 리포트 json.
- 완료: 생성 xlsx를 openpyxl로 재로딩 시 스키마 일치, 골든 파일 스냅샷 테스트 통과.

### FR-08 평가 하네스 (`eval/`) — spec: `evaluation-harness` ★차별화
- 명령 1개(`python -m eval.run --split holdout --repeats 5 --seed 42`)로 실행.
- 매칭: 골드 이탈 ↔ 생성 이탈을 (가이드워드, 파라미터) 정확 일치 + 이탈 텍스트 의미 유사도(임베딩 코사인 ≥ τ, τ는 README에 명시)로 매칭. 매칭 방식의 한계도 서술.
- 지표: 이탈 recall·precision, S·F 등급 MAE, 근거 첨부율, 근거정확도(수작업 30건 표 포함), 환각률(verifier `review` 비율 및 수작업 확인), 노드당 지연(초)·토큰·비용(USD).
- 출력: `results/{run_id}/metrics.json` + `results/{run_id}/config.yaml` + README용 마크다운 표 자동 생성.
- 완료: 5회 반복 평균±표준편차 표가 README §평가에 들어가 있고, **불리한 지표도 포함**돼 있다.

### FR-09 API (`services/api/`) — spec: `service-api`
- FastAPI: `POST /generate`(노드 메타 → 결과 json), `GET /export/{run_id}.xlsx`, `GET /health`. 요청·응답 스키마는 `schemas/`와 공유.
- 완료: OpenAPI 문서 자동 생성, 통합 테스트(모의 LLM) 통과.

### FR-10 웹 UI (`apps/web/`, Streamlit) — spec: `web-ui` (W3에만 작업)
- 좌: 노드 입력 폼 + **데모 프리셋 버튼 3개**(NH3 매니폴드, 프로판 저장탱크, 염소 배관 — 프리셋 2·3은 데모용, 골드셋 없음을 UI에 표기). 우: 결과 표(신뢰도 배지 색상), 근거 펼치기, 다운로드 버튼.
- 첫 화면 상단: 60초 HAZOP 설명 + 전략서 §6-1의 시각 장치(NH3 확산 지도 이미지 1장).
- 완료: 심사위원 시나리오(프리셋 1클릭 → xlsx 다운로드) 3분 내 완주, 예외 시 사용자에게 사유 표시.

### FR-11 README·제출 패키지 — spec 없음(steering 규칙 `docs.md`로 관리)
- 구성 고정: ①문제(60초 HAZOP + 사고 사례 1건) ②왜 LLM인가 ③데이터·라이선스 ④아키텍처 다이어그램 ⑤Kiro 개발 방식과 추적 매트릭스 ⑥**평가 결과 표** ⑦한계와 본선 로드맵 ⑧실행 방법(5분) ⑨비용.
- 추적 매트릭스: `R-xx(requirements.md) → 코드 모듈 → T-xx(테스트) → 지표`.
- 3분 데모 영상 링크.
- 완료: 제3자(새 머신)가 README만으로 실행 성공 기록 1건.

---

## 6. Kiro 운용 규칙 (도구 분담)

| 산출물 | 만드는 도구 | 정본 위치 | 비고 |
|---|---|---|---|
| requirements.md(EARS) / design.md / tasks.md | **Kiro spec** | `.kiro/specs/<spec>/` | spec 6개 상한: gold-dataset, bedrock-client, hazop-generation, evidence-citation, self-verification, evaluation-harness. export/api/ui는 hazop-generation·evaluation 안에 requirement로 흡수하거나 W3에 spec 없이 구현 |
| steering | **Kiro** | `.kiro/steering/` | `domain.md`(가이드워드·PSM 용어·KOSHA 문서 체계·S/F 정의), `engineering.md`(Python 3.12, 타입힌트, pytest, ruff, 로깅, 시크릿 금지), `aws.md`(리전·모델 ID는 config에서만, 비용 상한, 태깅), `docs.md`(README 구성·추적 매트릭스 규칙) |
| hooks | **Kiro** | `.kiro/hooks/` | 저장 시 `ruff + pytest -m "not live"`, spec 변경 시 README 추적 매트릭스 재생성, 커밋 전 시크릿 스캔 |
| MCP | Kiro 설정 | `.kiro/settings/mcp.json` | AWS Documentation MCP(Bedrock API 최신 사양), 파일시스템 |
| 구현·리팩터·테스트 작성·대량 편집 | **Claude Code** | 코드 트리 | `tasks.md` 항목 단위로 지시. 완료 시 Kiro에서 해당 task 체크 |
| 실험 반복·평가 실행·결과 표 생성 | Claude Code | `eval/`, `results/` | |

운용 절차(한 기능당):
1. Kiro에서 spec 생성 → requirements.md 검토·수정(EARS 문장에 수용 기준 포함) → design.md → tasks.md.
2. Claude Code에 "`.kiro/specs/<spec>/tasks.md`의 T-03을 구현하라, `CLAUDE.md`와 steering 준수" 형태로 위임.
3. 테스트 통과 → Kiro에서 task 완료 표시 → 커밋 메시지에 `spec:<name> T-03`.
4. 요구사항이 바뀌면 코드가 아니라 **requirements.md를 먼저** 고친다.

**spec 범위 상한 (2026-09-04 추가, gold-dataset 13태스크·bedrock-client 14태스크 검토 후)**: 이후 spec은 태스크 ≤ 8개, 신규 클래스 ≤ 3개. Kiro 요청 프롬프트 끝에 이 상한을 명시한다. PRD에 없는 도구·의존성(mypy --strict, scikit-learn 등)이 spec에 들어오면 requirements에서 삭제하거나 구현 시 제외한다. 이미 생성된 spec은 재생성하지 않고 **압축 구현**한다 — 태스크 번호·클래스명은 추적성을 위해 유지하되 파일 1~2개, 얇은 함수 수준으로.

크레딧 절약: spec 빌드는 기능당 1회. 반복 수정은 Claude Code. 크레딧 소진 시에도 `.kiro/` 구조는 손으로 유지(README에 소비 로그 공개 — 비용 절에 "개발 도구 비용"으로 서술).

---

### 6-1. Claude Code 세션 운용 (2026-09-05 추가)

- 세션은 항상 프로젝트 루트(`hazop-copilot/`)에서 `claude`로 시작한다. CLAUDE.md가 자동 로드된다.
- 지시는 `docs/지시문_*.md`를 그대로 붙여 넣는다. 지시문은 사람이 검토·수정한 뒤 붙이며, 세션 안에서 즉흥으로 범위를 넓히지 않는다.
- 한 세션 = 한 지시문. 끝나면 완료 보고 4줄을 `docs/진행로그.md`에 붙이고 커밋한다. 다음 지시문은 새 세션에서.
- Claude Code가 "requirements에 없다"고 되돌리면, Kiro에서 requirements.md를 고친 뒤 재지시한다. 코드로 우회하지 않는다.
- 실호출(`pytest -m live`, 체크 스크립트)은 비용이 드는 작업이므로 Claude Code가 임의로 반복하지 않게 지시문에 횟수를 적는다.

## 7. 비기능 요구사항 (NFR)

- **NFR-01 Kiro 추적성**: 모든 FR은 `.kiro/specs`의 requirement ID로 역추적 가능. 커밋 이력이 spec 순서와 일치.
- **NFR-02 재현성**: 단일 명령 설치·실행(`make setup && make demo`), 시드 고정, config 사본 저장. 실 LLM 없는 오프라인 테스트 경로 제공(모의 클라이언트).
- **NFR-03 신뢰성 공개**: 평가표에 불리한 지표 포함. 매칭 임계값·수작업 채점 절차 문서화.
- **NFR-04 비용**: 노드 1건 생성+검증 ≤ USD 0.30(목표), 로그로 실측. 대회 크레딧 잔량 주 1회 기록.
- **NFR-05 안전·프라이버시**: Guardrails PII 차단, 실데이터 금지, 시크릿은 환경변수·`.env.example`만 커밋.
- **NFR-06 지연**: 노드 1건 ≤ 60초(P90). 초과 시 UI 진행 표시.
- **NFR-07 코드 품질**: ruff clean, 타입힌트, 테스트 커버리지 핵심 모듈 ≥ 70%, 한글 출력은 `PYTHONIOENCODING=utf-8` 명시.

---

## 8. 마일스톤 (예선 9/29 역산)

| 게이트 | 날짜 | 통과 조건 | 대응 FR |
|---|---|---|---|
| G0 킬체크① | 9/7(일) | Bedrock 실호출 성공 · 골드셋 JSON · spec `gold-dataset`·`bedrock-client` 완성 · steering 4종 초안 | FR-01, FR-02 |
| ↳ 9/4 현황 | 12:50 | steering 4종 ✅ · spec 2종 ✅(과잉 분해, 압축 구현 예정) · git 미초기화 ❌ · data/raw 원본 미복사 ❌ · Bedrock 호출 ❌ · 골드셋 JSON ❌ | — |
| ↳ 9/5 현황 | 19:10 | data/raw 원본 ✅ · 지시문 A/B·체크 스크립트 ✅ · **코드 0줄, git 없음, Bedrock 미확인** → 오늘 밤~9/6에 지시문 0→A→B 순으로 Claude Code 실행. G0 마감까지 약 29시간 | FR-01, FR-02 |
| G1 킬체크② | 9/10(수) | 프롬프트만으로 N1 recall ≥ 0.5. 미달 시 매트릭스 열거 방식 강화 후 9/12 재판정, 재미달 시 B안(MSDS 어시스턴트) 전환 | FR-03 |
| G2 핵심루프 | 9/14(일) | 입력 → 근거 첨부 이탈 → xlsx. KB 구축 완료 | FR-03, FR-04, FR-07 |
| G3 저부하주(휴먼테크 9/22) | 9/21(일) | verifier · 물질/고장률 tool · 하네스 자동화 1차 지표 | FR-05, FR-06, FR-08 |
| G4 서비스 | 9/26(금) | API + Streamlit 데모 · 프리셋 3개 · 비용/지연 실측 · Docker 실행 | FR-09, FR-10 |
| G5 제출 | 9/29(화) | README 완성 · 영상 · 제3자 실행 확인(9/28) · 리포 정리(.kiro 포함) | FR-11 |
| 본선(진출 시) | 10/3~10/18 | React UI · Lambda/App Runner 배포 · 실무자 피드백 2~3인 · 발표자료·QA 30문 | — |

---

## 9. 리스크 레지스터

| # | 리스크 | 확률 | 영향 | 대응 |
|---|---|---|---|---|
| R1 | 대회 계정에서 목표 모델 리전 제한 | 중 | 상 | 크로스리전 추론 프로파일 → Nova 계열 라우팅. `models.yaml`만 수정 |
| R2 | Kiro 크레딧 조기 소진 | 중 | 중 | spec 6개 상한, 반복은 Claude Code, `.kiro/` 수동 유지 |
| R3 | 솔로 범위 초과 | 상 | 상 | G2까지 FR-10 금지. 새 기능은 requirements.md 변경 승인 후에만 |
| R4 | recall 저조(골드셋 표현과 모델 표현 불일치) | 중 | 상 | 매칭에 의미 유사도 도입 + 매트릭스 열거 강제. 그래도 낮으면 한계로 공개 |
| R5 | KB 인용 정확도 낮음(PDF 파싱 품질) | 중 | 중 | 문서 5~8종으로 제한, 청킹 파라미터 실험 1회, 수작업 채점 공개 |
| R6 | 휴먼테크 초록(9/22) 충돌 | 확정 | 중 | G3 주간 저부하 설계 |
| R7 | 데모 중 환각 노출 | 중 | 중 | verifier가 잡는 장면을 데모 시나리오에 포함 |
| R8 | Kiro spec 과잉 분해(9/4 실제 발생: 27태스크) | 확정 | 상 | §6 범위 상한 + 압축 구현. 다음 spec부터 프롬프트에 상한 명시 |
| R9 | steering/aws.md·design.md의 모델 ID가 2024년 레거시(claude-3-5-sonnet-20241022, claude-3-haiku-20240307, titan-embed-v2, us-east-1) | 상 | 중 | G0에서 `list_foundation_models`로 실제 접근 가능 목록 확보 → `models.yaml`·aws.md 갱신. `CostCalculator`는 미등록 모델에 예외 대신 비용 0 + WARNING |
| R10 | 골드셋 이탈 수 불일치(전략서 34 vs 원본 시트 36 데이터행) | 중 | 하 | FR-01 완료 시 실측값을 정본으로 전 문서 통일 |

---

## 10. 오픈 퀘스천 (해결 시 갱신)

- OQ-1 대회 제공 AWS 계정/크레딧의 형태(개인 계정 크레딧? 워크샵 계정?) — 9/5 사무국 확인 → Bedrock 모델 액세스 권한 여부.
- OQ-2 예선 제출 형식(리포 링크? 영상? 문서?) — 홈페이지 FAQ/킥오프 자료 확인. 확인 전까지 README+영상+리포 3종 모두 준비.
- OQ-3 Knowledge Base 벡터 스토어 선택(OpenSearch Serverless 비용 vs S3 Vectors 등 저가 옵션) — 9/8 KB 구축 시 결정, 비용 절에 기록.
- OQ-4 골드셋 노드 수가 홀드아웃에 충분한가 — FR-01 완료 후 판단.
- OQ-5 대회 계정에서 실제 호출 가능한 모델 ID 목록(생성용·verifier용·임베딩용) — G0 첫 작업. 확정 전까지 `models.yaml` 값은 자리표시자로 간주.

---

## 11. 비목표 (Out of Scope — 예선)

- P&ID 도면 이미지 인식, CAD 연동.
- 실시간 MSDS API·법령 API 연동(캐시로 대체).
- 정량 QRA(확산·빈도 계산) — 데모 지도는 NH3 QRA 기존 결과 이미지 1장만 사용.
- 사용자 계정·과금·다중 테넌트.
- React 프런트(본선).
- 파인튜닝.

---

## 12. 저장소 구조 (초기)

```
hazop-copilot/
├─ PRD.md                 ← 이 문서
├─ CLAUDE.md              ← Claude Code 작업 규칙
├─ README.md
├─ .kiro/
│  ├─ specs/{gold-dataset,bedrock-client,hazop-generation,evidence-citation,self-verification,evaluation-harness}/
│  ├─ steering/{domain.md,engineering.md,aws.md,docs.md}
│  ├─ hooks/
│  └─ settings/mcp.json
├─ config/models.yaml
├─ schemas/deviation.schema.json
├─ core/{llm,agent/tools,export}/
├─ services/api/
├─ apps/web/
├─ eval/
├─ tools/build_gold.py
├─ infra/kb_setup.py
├─ data/{gold,kb}/ + data/README.md
├─ results/
├─ tests/
├─ Makefile · pyproject.toml · Dockerfile · .env.example
```
