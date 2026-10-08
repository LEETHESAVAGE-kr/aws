# data/ — 데이터 출처와 라이선스

## 디렉터리

| 경로 | 내용 | git |
|---|---|---|
| `data/raw/` | 원본 xlsx (전문가 HAZOP 워크시트) | **git-ignored** |
| `data/gold/` | `tools/build_gold.py` 변환 산출물 (JSON) | tracked |
| `data/replay/` | `tools/capture_replay.py` 캡처 산출물 — 노드별 생성 결과 JSON(`source=live`) 또는 골드 재생(`source=gold`). 출처 = 본 저장소 실행 로그(LLM 생성물, 외부 데이터 아님) | tracked |
| `data/kb/hazop_param_examples.json` | R-12 공개 HAZOP 예시 — 공개 워크시트 3건(IJERPH 2017 CC-BY · IOCL 2014 인도 환경허가 공개 제출물 · ORNL 2023 미국 정부 보고서)의 설비·절차형 **파라미터 이름만** 직역. 원문 문장·원본 파일 없음(원본은 리포 밖 `../참고자료/공개_HAZOP_워크시트/`). 항목별 출처 URL·이용 조건은 파일 안에 | tracked |
| `data/reference/iocl_lpg_2014.json` | 지시문 W 외부 공개 HAZOP 대조 기준(**골드셋 아님**) — IOCL LPG Bottling Plant Risk Assessment 2014 부록 A 워크시트 N1~N4 의 (가이드워드, 파라미터) 쌍 44개만. 원인·결과 문장 없음. 인도 환경허가 공개 제출물(저작권 표시 미확인) — 이름(사실)만 옮김 | tracked |
| `data/presets.json` | 데모 공정 카탈로그(FR-10 J-01) — 공정별 노드 입력(`node_meta`). NH3 4노드는 `data/gold` 의 node_meta 와 같은 값, LPG·염소 예시 공정 2개는 저장소 소유자가 작성한 가상의 입력(실데이터 아님, 골드셋 없음) | tracked |

## 원본 출처 — `data/raw/D1_HAZOP_워크시트.xlsx`

이 파일은 **저장소 소유자 본인이 제12회 위험성평가 경진대회에 출품한 작품**(암모니아 벙커링
위험성평가)의 산출물 D1이며, 본인이 직접 작성한 저작물이다. 시트 3종(`HAZOP워크시트` 34개 이탈 ·
`평가기준` S/F 등급 정의 · `스크리닝` 5×5 매트릭스와 시나리오 선정 논리)으로 구성된다.
원본을 `data/raw/` 에 두고 `.gitignore` 로 제외하는 이유는 두 가지다. ① 경진대회 심사가
진행 중인 미공개 출품작이므로 저장소 공개 시점과 대회 공개 시점을 분리해야 하고,
② CLAUDE.md 불변규칙 1(고객사 실데이터·개인정보 반입 금지)에 따라 원본 바이너리는 로컬에만
두고 저장소에는 기계 판독 가능한 파생 JSON만 남긴다는 방침 때문이다. 원본은 KECC 고객사
실데이터가 아니며 개인정보를 포함하지 않는다.

**재현 방법**: 원본 xlsx를 `data/raw/D1_HAZOP_워크시트.xlsx` 경로에 두고 `make build-gold`
를 실행하면 `data/gold/` 의 JSON 6종이 재생성된다. 원본이 없으면 이 저장소만으로는 골드셋을
다시 만들 수 없고, `data/gold/*.json` 을 그대로 사용한다.

## 라이선스

`data/raw/` 의 원본 xlsx와 `data/gold/` 의 파생 JSON은 저작권자(저장소 소유자) 본인에게
저작권이 있으며, 고려대 × AWS AI Innovators Challenge 2026 출품작 「위험성평가 코파일럿」의
개발·심사 목적으로만 사용한다. 제3자 재배포·상업적 이용은 허용하지 않는다. 향후 `data/kb/`
에 수록할 KOSHA Guide 등 외부 문서는 각 문서의 라이선스(공공누리 유형)를
`data/kb/manifest.csv` 의 `license` 열에 개별 기재한다.

## 산출물 (`data/gold/`)

| 파일 | 내용 |
|---|---|
| `hazop_nh3.json` | 전체 골드셋 34 레코드 (`schemas/gold_record.schema.json` 검증 통과) |
| `hazop_nh3_tune.json` | 프롬프트 튜닝용 — 노드 N1, 8 레코드 |
| `hazop_nh3_eval.json` | 홀드아웃 — 노드 N2·N3·N4, 26 레코드 |
| `split_node.json` | 노드 단위 홀드아웃 명세 (tune/holdout 노드·레코드 id 목록) |
| `split_config.json` | 분할 기록 (REQ-08: split_type·tune_nodes·counts·timestamp) |
| `rating_scale.json` | `평가기준` 시트 원문 — S/F 등급 정의와 위험도 구간 |

원본 시트 35개 비공백 행 중 마지막 1행은 범례(설명 문구)이므로 REQ-07 규칙(`이탈` 빈 값)에
따라 건너뛴다. 따라서 레코드 수는 34이다.

## 평가기준 라이브러리 (`data/kb/criteria/`, 지시문 Y-2 · 2026-10-09)

S·F 등급·위험도 산정 기준 1개 = 파일 1개. 원문 단계 수를 바꾸지 않는다. 골드셋 노드(NH3 N1~N4)는
골드셋 기준, 그 밖(직접 입력)은 C-C-37 이 기본이다(steering `domain.md` §4 적용 범위).

| 파일 | 출처 (원문 확인 위치) | 단계·산정 | 이용 조건 (2026-10-09 확인) |
|---|---|---|---|
| `kosha_cc37_2026.json` | 한국산업안전보건공단 C-C-37-2026 「연속공정의 위험과 운전분석(HAZOP) 기법에 관한 기술지원규정」(공표 2026-01-30, P-82-2023 후속 — P-82·P-86 은 같은 날 폐지) 6.5, <표 2~5> 인쇄 9~10쪽, <표 7> 인쇄 13쪽. https://portal.kosha.or.kr/archive/resources/tech-support/search/chemistry | S 4 · F 3, 위험도 대조표 1~5 (곱 아님) | 공공누리 표시 없음(목록·상세·PDF). 등급 정의 짧은 표만 출처 명시 인용, PDF 원문은 저장소에 넣지 않는다. 기술적 권고규정 |
| `moel_guide_3x3_2023.json` | 고용노동부 「새로운 위험성평가 안내서」(2023. 5., 발간등록번호 11-1492000-000993-01) PDF 75~76쪽(인쇄 61~62쪽). https://www.moel.go.kr/policy/policydata/view.do?bbs_seq=20230501085 | S 3 · F 3, 곱 1~9 | 국가기관 저작물(저작권법 제24조의2① 적용 추정 — 공공누리 표시 미확인). 작업 단위 예시라 화면 안내 비교용 |
| `nh3_sts_bunkering.json` | 골드셋 `rating_scale.json` 을 가리킨다(`scale_file`) | S 5 · F 5, 곱 1~25 | 본인 저작물 |

확인했으나 넣지 않은 것: 고용노동부고시 제2024-76호 「사업장 위험성평가에 관한 지침」은 등급표가 없다(제7조⑤ 방법 열거·제9조② 사업장 자체 기준). KOSHA C-C-67-2026 작업위험성평가는 덧셈식(강도 0~6 + 빈도 + 확률)이라 HAZOP 셀 판정과 맞지 않는다. KRAS 5×4 척도 정의는 원문 미확보.
