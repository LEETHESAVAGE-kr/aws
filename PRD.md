# PRD — 위험성평가 코파일럿 (고려대 × AWS AI Innovators Challenge 2026)

버전 **v2.0 (예선 축소판)** · 작성 2026-09-04 · 개정 **2026-09-22 (D-7 범위 재정의)** · 예선 제출 2026-09-29(화) · 팀 1인 · 정본 위치: 프로젝트 루트 `PRD.md`
이전 판(v1.2, 9/11)은 `docs/PRD_v1.2_archive_20260911.md`에 보존. 상위 문서: `AI_Innovators_수상전략서_v1.md`.

> **v2.0 개정 이유 (가장 먼저 읽을 것)**
> 9/15 진행보고서 이후 일주일간 작업이 멈췄다(폴더 최종 수정 9/15 13:01). 남은 시간은 **7일, 1인**이며 LLM 실호출은 아직 0회다. v1.2의 FR-01~11 전체는 실행 불가능하므로, 이 판은 **"심사표에서 점수가 나오는 최소 패키지"** 만 남기고 나머지를 본선 로드맵으로 넘긴다. 이 문서에 P0로 표시되지 않은 것은 만들지 않는다.
>
> 작업 도구 규칙은 유지한다: Kiro spec이 설계 정본, Claude Code가 구현 엔진. 다만 Kiro 크레딧이 없으므로 신규 spec·requirement는 **손으로 작성**한다(9/11 export-formats 선례, NFR-01 추적성 유지).

---

## 0. 한 문장 정의 (변경 없음)

공정 노드 설명(물질·상태·운전조건·설비)을 입력하면 LLM 에이전트가 HAZOP 이탈 시나리오를 가이드워드×파라미터 매트릭스로 빠짐없이 생성하고, 항목별 신뢰도를 채점한 뒤, PSM 제출 양식의 HAZOP 워크시트(xlsx)와 LOPA 초안(md)으로 내보내는 서비스. 골드셋(전문가 HAZOP 34 이탈) 대비 성능을 README에 숫자로 공개한다.

**성공의 정의(예선, v2.0)**: 새 환경에서 README만 보고 5분 안에 실행 → NH3 프리셋 1클릭 → 워크시트 xlsx 다운로드가 되고, README 평가표에 **실측 recall·S/F MAE·비용·지연**이 (불리하더라도) 적혀 있다.

---

## 1. 현재 상태 (2026-09-22 실측)

| 항목 | 상태 | 근거 |
|---|---|---|
| 코드 | FR-01 ✅ · FR-02 mock ✅ · FR-03 mock ✅ · FR-07 ✅ (미커밋) | 142 passed(9/11, 샌드박스 Py3.11) |
| git | 마지막 커밋 9/8(`26575ee`), 9/11 작업 미커밋, `.git/index.lock` 잔존 | 9/11 세션 중단 흔적 |
| LLM 실호출 | **0회** | 대회 IAM Identity Center 포털에 AWS 계정 없음(9/15 확인). Anthropic API 키 미발급(`.env` 없음) |
| spec | 4/7 (gold-dataset, bedrock-client, hazop-generation, export-formats). REQ-12·T-15 미추가 | `.kiro/specs/` |
| 게이트 | G0·G1 판정 불능, G2 1/3, **G3(9/21) 미달**, G4(9/26) D-4 | 9/15 보고서 기준 유지 |
| 외부 일정 | 휴먼테크 초록 9/22 | R6 |

**결정(9/15, 유지)**: 개발·측정은 Anthropic Messages API 어댑터로 즉시 진행하고, 제출 직전 개인 AWS Bedrock 계정으로 `models.yaml`의 `provider`만 바꿔 최종 지표를 다시 찍는다. 사무국 문의는 하지 않는다. README 비용 절에 공개한다.

---

## 2. 범위 재정의 — 우선순위 등급

| 등급 | 뜻 | 규칙 |
|---|---|---|
| **P0** | 없으면 제출물이 성립하지 않음 | 9/27까지 반드시 완료. 다른 모든 작업에 우선 |
| **P1** | 심사 점수(기술 30·완성도 30·코드 10)를 직접 올림 | P0 완료 후 9/28까지 |
| **P2** | 여력 시 | 9/28 이후에만. 미완이면 README "본선 로드맵"에 서술 |
| **삭제** | 예선에서 만들지 않음 | README "한계와 본선 로드맵"에 1~2줄 |

### 2-1. FR별 판정

| FR | v1.2 | **v2.0** | 등급 | 비고 |
|---|---|---|---|---|
| FR-01 골드셋 | 완료 | 유지 | — | 34건, tune=N1(8) / holdout=26 |
| FR-02 LLM 클라이언트 | Bedrock 전용 | **공급자 추상화 + Anthropic 어댑터(REQ-12)** | **P0** | 지시문 E-1/E-2 |
| FR-03 이탈 생성 | mock까지 | **실호출 + N1 recall 측정** | **P0** | T-07·T-08 |
| FR-04 근거 검색(Bedrock KB) | KB 구축 | **삭제 → 축소판 FR-04′(로컬 인용)** | P2 | §5 FR-04′ |
| FR-05 물질·고장률 tool | 20종·10종 | **축소: 물질 5종 + 고장률 시드(L-대장)** | P1 | 순수 데이터 작업 |
| FR-06 verifier | LLM 2차 호출 | **규칙 기반 1단만** | P1 | 근거 없는 규격번호·수치 정규식 플래그 |
| FR-07 내보내기 | 완료 | 유지(커밋) | **P0** | `index.lock` 정리 후 커밋 |
| FR-08 평가 하네스 | 임베딩 매칭·5회 반복 | **축소: 정확일치+문자열 유사도, 3회 반복** | **P0** | 실측 숫자가 README에 들어가는 유일한 경로 |
| FR-09 FastAPI | 있음 | **삭제** | 삭제 | Streamlit이 `core/` 직접 호출 |
| FR-10 Streamlit UI | 프리셋 3개 | **프리셋 1개(NH3) + 결과표 + 다운로드** | **P0** | 프리셋 2·3은 P2 |
| FR-11 README·영상 | 9절 구성 | 유지(축약 허용) | **P0** | 제3자 실행 확인 9/28 |
| Guardrails PII | 설정 | **README 서술만** | 삭제 | Anthropic 경로에선 적용 불가, Bedrock 전환 시 설정 1개 |
| Docker | 유지 | Dockerfile 1개 + `make demo` | P1 | `make demo`가 더 중요 |

---

## 3. 데이터 명세 (변경분만)

- 골드셋: v1.2 §3.1 그대로. 정본 34건(R10 종결).
- **KB(§3.2) 축소**: KOSHA Guide PDF 수집·청킹·벡터스토어는 예선 비목표. 대신 `data/kb/registers.json`(문헌대장 L-01~27·가정대장 A-01~22 시드)과 `data/kb/substances.json`(NH3 포함 5종, 출처 필드 필수)만 만든다. FR-04′를 하는 경우에만 KOSHA 지침 **2~3종의 발췌 텍스트**(`data/kb/kosha_excerpts.json`, 문서명·문단번호·원문 인용)를 손으로 정리한다.
- 금지 사항(§3.3)은 변경 없음. KECC 고객사 실데이터 사용 금지.

---

## 4. 시스템 설계 (v2.0)

```
apps/web (Streamlit)  ── 직접 import ──▶  core/agent/generate.py  (매트릭스 열거 → 이탈 판정, 스키마 강제)
                                              │  core/llm/  AbstractBedrockClient
                                              │    ├─ BedrockClient    (provider: bedrock,   제출 시)
                                              │    ├─ AnthropicClient  (provider: anthropic, 개발·측정 시)  ← REQ-12
                                              │    └─ MockBedrockClient (오프라인 테스트)
                                              ├─ tools: substance_lookup · failure_rate   (P1, 로컬 json)
                                              ├─ verify.py  규칙 기반 플래그 → confidence   (P1)
                                              ▼
                                        core/export  (xlsx 5시트 · lopa_draft.md · confidence_report.json)  ✅
eval/run.py   (골드셋 하네스: recall·precision·S/F MAE·지연·비용, 시드 고정 3회)   ← P0
.kiro/        (specs · steering)   ← 심사 대상 산출물
```

- `config/models.yaml`에 `provider: anthropic | bedrock` 키 추가. 호출부(`core/agent`, `core/export`, `tests`)는 `AbstractBedrockClient`만 본다(AC-12-1).
- 프롬프트 캐싱: Anthropic 경로는 시스템 블록 `cache_control: ephemeral`, Bedrock 경로는 기존 캐싱 마커.
- 삭제된 것: FastAPI, Bedrock Knowledge Base, LLM verifier 2차 호출, Guardrails 설정, App Runner.

---

## 5. 기능 요구사항 (v2.0 유효분)

### FR-02 LLM 클라이언트 — spec `bedrock-client` + **REQ-12 (손 추가)** · P0
- REQ-12: `provider=anthropic`이면 Anthropic Messages API로 동일한 `converse()` 계약(시스템·메시지·tool·JSON 스키마 강제·재시도·토큰/비용/지연 로깅) 수행. `provider=bedrock`이면 기존 경로.
- AC-12-1 호출부 무변경 · AC-12-2 오프라인 테스트 네트워크 0회 · AC-12-3 키는 `ANTHROPIC_API_KEY` 환경변수만 · AC-12-4 캐싱 대응 · AC-12-5 429/529/5xx 재시도(3회, 1→2→4s).
- 완료: `pytest -m "not live"` 통과(기존 142 + 어댑터 테스트), `pytest -m live` 스모크 1회 성공 로그(`results/smoke_*/`).

### FR-03 이탈 생성 — spec `hazop-generation` T-07·T-08 · P0
- T-07: N1 노드 실호출 1회 → 스키마 검증 100%, 60초 내 결과, 비용·지연 로그.
- T-08: N1 tune 8건 대비 recall 측정. **G1 기준 recall ≥ 0.5**. 미달 시 프롬프트 1회 수정 후 재측정(총 실호출 상한: 세션당 5회).
- 실호출 횟수는 지시문에 명시하고 Claude Code가 임의 반복하지 않는다.

### FR-05 물질·고장률 tool — spec `evidence-citation`(손 작성, ≤5 태스크) · P1
- `substance_lookup(name|CAS)` → NH3·프로판·염소·수소·메탄올 5종, 각 항목에 `source` 필드. `failure_rate(equipment, mode)` → `registers.json`에서 L-번호·값 반환. 미존재 시 `{"status": "not_found"}`.
- 완료: 5종·설비 5종 조회 테스트, `not_found` 테스트 통과. 생성 루프에 tool 결과를 컨텍스트로 주입(선택, 시간 있을 때).

### FR-06 규칙 기반 verifier — spec `self-verification`(손 작성, ≤4 태스크) · P1
- LLM 호출 없음. 각 이탈에 대해 (a) 규격 번호 패턴(`KOSHA GUIDE P-\d+`, `KS B \d+`, `API \d+` 등)이 tool/발췌에 없으면 플래그 (b) 근거 없는 수치 주장(단위 붙은 숫자) 플래그 (c) 매트릭스 누락 셀 보고.
- `confidence`: 플래그 없음 → `inferred`(근거 tool 없이 생성됐으므로 `grounded` 불가), 플래그 있음 → `review`. FR-04′를 한 경우에만 `grounded` 부여.
- 완료: 의도 삽입 10건 중 ≥ 9건 플래그(기존 결함 재삽입 테스트 방식 재사용).

### FR-04′ 로컬 인용(축소판) — spec `evidence-citation` 내 requirement · P2
- `kosha_excerpts.json`의 발췌를 키워드 검색(BM25 또는 단순 토큰 일치)해 상위 2개를 `evidence[]`에 `{source_id, doc_title, locator, quote}`로 첨부. 인용은 발췌 텍스트에서만.
- 완료: 데모 노드 결과 근거 첨부율 ≥ 50%(v1.2의 80%에서 하향, README에 명시).
- **9/28 이전에 P0·P1이 끝났을 때만** 착수.

### FR-07 내보내기 — spec `export-formats` · P0(커밋만)
- 구현 완료. `index.lock` 삭제 → 로컬 3.12 `make test` → 커밋 `spec:export-formats T-01~T-06`.

### FR-08 평가 하네스 — spec `evaluation-harness`(손 작성, ≤6 태스크) · P0
- 명령 1개: `python -m eval.run --split holdout --repeats 3 --seed 42 --provider anthropic|bedrock`.
- 매칭: (가이드워드, 파라미터) 정확 일치 **AND** 이탈 텍스트 유사도(`difflib.SequenceMatcher` 또는 문자 2-gram Jaccard ≥ τ, τ=0.5 시작, README 명시). 임베딩 매칭은 본선.
- 지표: 이탈 recall·precision, S·F MAE, `review` 비율, 노드당 지연(초)·입출력 토큰·비용(USD). 근거정확도 수작업 채점은 FR-04′를 한 경우에만.
- 출력: `results/{run_id}/metrics.json` + `config.yaml` 사본 + README용 마크다운 표.
- 완료: holdout 26건 × 3회 평균±표준편차 표가 README §평가에 있고, **불리한 지표도 포함**. 오프라인 테스트는 mock 결과로 지표 계산 로직 검증.

### FR-10 Streamlit UI — spec 없음(steering `docs.md`·PRD가 정본) · P0
- 한 화면: 상단 60초 HAZOP 설명 + NH3 확산 지도 이미지 1장 / 좌 "NH3 매니폴드 프리셋" 버튼 + JSON 편집 가능 / 우 결과표(신뢰도 배지 색상) + xlsx·LOPA md 다운로드.
- `core/agent`·`core/export` 직접 호출. 예외 시 사유 표시. 진행 표시(스피너).
- 완료: 프리셋 1클릭 → xlsx 다운로드 3분 내 완주. `make demo` 한 줄로 실행.

### FR-11 README·제출 패키지 · P0
- 구성: ①문제(60초 HAZOP + 사고 사례 1건) ②왜 LLM인가 ③데이터·라이선스 ④아키텍처(v2.0 그림) ⑤Kiro 개발 방식과 추적 매트릭스(spec → 코드 → 테스트 → 지표) ⑥**평가 결과 표(실측)** ⑦한계와 본선 로드맵(삭제 항목 전부 여기) ⑧실행 방법 5분 ⑨비용(개발 중 Anthropic API 사용·제출 시 Bedrock 전환 명시, 개발 도구 비용 포함).
- 3분 데모 영상: 프리셋 클릭 → 결과 → verifier 플래그 장면 → xlsx 열기 → README 평가표.
- 완료: 제3자(새 머신 또는 새 venv)가 README만으로 `make setup && make demo` 성공 기록 1건(9/28).

---

## 6. Kiro 운용 규칙 (v2.0 보정)

- 신규 spec 3개(evidence-citation, self-verification, evaluation-harness)는 **손 작성**. 형식은 기존 spec과 동일(EARS requirements + design + tasks 체크박스), 태스크 상한 evaluation-harness ≤ 6, evidence-citation ≤ 5, self-verification ≤ 4.
- 기존 spec에 requirement를 추가할 때도 손으로(REQ-12 → `bedrock-client/requirements.md`, T-15 → `tasks.md`).
- README ⑤에 "Kiro 크레딧 소진 후 spec 3종·REQ-12는 동일 형식으로 수작업 유지"를 명시(정직성 + NFR-01).
- Claude Code 세션 운용(§6-1)은 변경 없음: 한 세션 = 한 지시문, 완료 보고 4줄을 `docs/진행로그.md`에, 커밋 `spec:<name> T-xx`.

---

## 7. 비기능 요구사항 (v2.0 보정)

- NFR-01 추적성: 유지. 손 작성 spec도 requirement ID를 갖는다.
- NFR-02 재현성: `make setup && make demo`, `python -m eval.run` 단일 명령, mock 경로 오프라인 통과. **변경**: `--provider` 인자로 Anthropic/Bedrock 동일 하네스.
- NFR-03 신뢰성 공개: 유지. recall이 0.5 미만이어도 표에 적는다.
- NFR-04 비용: 노드 1건 ≤ USD 0.30 목표, Anthropic·Bedrock 각각 실측 기록. 개발 기간 총 API 비용 README에 공개.
- NFR-05 안전: 실데이터 금지·시크릿은 환경변수. Guardrails는 서술만.
- NFR-06 지연: 노드 1건 ≤ 60초(P90). 초과 시 UI 진행 표시.
- NFR-07 코드 품질: ruff clean, `pytest -m "not live"` 전부 통과. 커버리지 수치 요구는 삭제.

---

## 8. 마일스톤 (9/22 → 9/29, 일 단위)

| 날짜 | 게이트 | 할 일 | 통과 조건 |
|---|---|---|---|
| **9/22(화)** | G0′ 정리 | ① `index.lock` 삭제 → `make test`(로컬 3.12) → 9/11 작업 커밋 ② REQ-12·T-15 손 추가 ③ Anthropic API 키 발급 → `.env` ④ **지시문 E-1** 세션(어댑터, 오프라인 테스트) | 커밋 2개(export-formats, T-15), `pytest -m "not live"` 통과 |
| **9/23(수)** | **G1** | **지시문 E-2** 세션: T-07 스모크 1회 → T-08 N1 recall. 미달 시 프롬프트 1회 수정·재측정 | **실호출 성공 + recall 숫자 1개**(≥0.5 목표, 미달도 기록) |
| **9/24(목)** | G3′-a | evaluation-harness spec 손 작성 → 지시문 F(FR-08 하네스, mock 검증) → holdout 26건 × 1회 실측 | `results/*/metrics.json` 생성, README용 표 자동 출력 |
| **9/25(금)** | **판단점** + G3′-b | 오전: FR-05 데이터(registers·substances) + evidence-citation·self-verification spec 손 작성. 오후: 지시문 G(FR-06 규칙 verifier). **판단**: 실호출·하네스가 안 돌면 §9 Plan B(mock replay) 확정 | verifier 10/10 테스트, tool `not_found` 테스트 |
| **9/26(토)** | **G4′** | 지시문 H(FR-10 Streamlit 최소 UI) + Dockerfile + `make demo` | 프리셋 1클릭 → xlsx 다운로드 완주 |
| **9/27(일)** | G4′-b | 개인 AWS 계정 Bedrock 모델 액세스 → `provider: bedrock`으로 하네스 3회 반복 실측 → README 평가표 확정. Bedrock 실패 시 Anthropic 실측을 표에 쓰고 사유 명시 | 최종 지표 표 |
| **9/28(월)** | G5-a | README 9절 완성, 3분 영상 녹화, 제3자 실행 확인, 리포 정리(`.kiro/`·`docs/`·`results/`) | 새 venv `make setup && make demo` 성공 |
| **9/29(화)** | **G5 제출** | 오전 최종 점검·제출. (여력 시 FR-04′·프리셋 2 — 제출 후에는 손대지 않음) | 제출 완료 |

하루 예산: 각 날짜의 P0 항목이 끝나지 않으면 다음 날 P1을 밀어낸다. 9/26까지 P0(FR-02·03·07·08·10)가 끝나지 않으면 9/27은 P1을 전부 버리고 P0에 쓴다.

---

## 9. Plan B — mock replay 데모 (9/25 판단점에서 발동)

발동 조건: 9/25 18:00까지 **실호출 성공 로그가 없거나** 하네스가 실측 지표를 내지 못함.
내용: `MockBedrockClient`를 골드셋 기반 재생(replay) 모드로 확장해 UI·xlsx·하네스·영상을 완성. README 평가표에는 "실호출 미실시 — mock 재생 결과, 지표 아님"을 명시하고 이유(자격증명)를 쓴다. 기술 30점의 상당 부분을 포기하는 경로이므로 Plan A(Anthropic 실호출)가 조금이라도 가능하면 택하지 않는다.

---

## 10. 리스크 레지스터 (v2.0)

| # | 리스크 | 확률 | 영향 | 대응 |
|---|---|---|---|---|
| R1 | 개인 Bedrock 계정 모델 액세스 승인 지연 | 중 | 중 | 9/27에 안 되면 Anthropic 실측을 최종 표로. README에 "동일 Claude 계열, 제출 후 Bedrock 전환" 명시 |
| R3 | 솔로 범위 초과(재발) | **상** | 상 | §2 등급표 외 작업 금지. "있으면 좋을" 항목은 `docs/backlog.md` 한 줄 |
| R4 | recall 저조 | 중 | 상 | 프롬프트 수정 1회만. 그래도 낮으면 한계로 공개 + 매트릭스 누락률 등 보조 지표 병기 |
| R6 | 휴먼테크 초록(9/22) 충돌 | 확정 | 중 | 9/22 P0는 30분 정리 작업 + E-1(무인 세션)만 |
| R7 | 데모 중 환각 노출 | 중 | 중 | 규칙 verifier가 플래그하는 장면을 영상에 포함 |
| R11 | **작업 공백 재발**(9/15~9/22 실제 발생) | 상 | 치명 | 매일 저녁 `docs/진행로그.md` 1줄. 이틀 연속 공백이면 Plan B 즉시 |
| R12 | 9/11 미커밋 작업 유실(`index.lock`) | 중 | 상 | 9/22 첫 작업으로 커밋. 커밋 전 코드 수정 금지 |
| R13 | Anthropic API 비용 초과 | 하 | 하 | 크레딧 $10 상한, 실호출 횟수 지시문 명시 |
| R2·R5·R8·R9·R10 | 종결 또는 v2.0에서 무관(KB·Kiro 크레딧·레거시 모델 ID는 `models.yaml` 한 곳) | — | — | 아카이브 참조 |

---

## 11. 오픈 퀘스천 (v2.0)

- OQ-2 예선 제출 형식(리포 링크·영상·문서) — **9/24까지 대회 홈페이지/Slack에서 확인**. 확인 전까지 3종 모두 준비.
- OQ-6 개인 AWS 계정에서 Claude 모델 액세스 리전(us-west-2 우선) — 9/27 실측 시 결정, `models.yaml`만 수정.
- OQ-7 FR-08 유사도 임계값 τ — 9/24 mock 결과로 0.4~0.6 중 선택, README 명시.
- (종결) OQ-1·OQ-5: 대회 계정에 Bedrock 없음(9/15). OQ-3: KB 삭제. OQ-4: holdout 26건으로 진행.

---

## 12. 비목표 (예선, v2.0 추가분)

v1.2 §11 전부 + FastAPI · Bedrock Knowledge Base(S3·벡터스토어) · LLM verifier 2차 호출 · Guardrails 설정 · 임베딩 매칭 · 프리셋 2·3(P2) · App Runner/Lambda · 5회 반복(3회로) · 커버리지 수치.

---

## 13. 저장소 구조 (v2.0 목표)

```
hazop-copilot/
├─ PRD.md (v2.0) · CLAUDE.md · README.md · Makefile · Dockerfile · pyproject.toml · .env.example
├─ .kiro/specs/{gold-dataset,bedrock-client(+REQ-12),hazop-generation,export-formats,
│              evidence-citation*,self-verification*,evaluation-harness*}/     * = 손 작성
├─ .kiro/steering/{domain,engineering,aws,docs}.md
├─ config/models.yaml            (provider · 모델 ID · 리전)
├─ schemas/deviation.schema.json
├─ core/llm/{client,anthropic,mock,config,types}.py
├─ core/agent/{generate,verify}.py · core/agent/tools/{substance,failure_rate}.py
├─ core/export/{xlsx,lopa,report,rows}.py
├─ eval/run.py · results/{run_id}/
├─ apps/web/app.py               (Streamlit)
├─ data/gold/ · data/kb/{registers,substances}.json · data/README.md
├─ tools/{build_gold,check_bedrock_access}.py
├─ tests/ · docs/{지시문_*,진행로그,진행보고서_*}.md
```
