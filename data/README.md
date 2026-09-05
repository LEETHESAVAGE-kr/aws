# data/ — 데이터 출처와 라이선스

## 디렉터리

| 경로 | 내용 | git |
|---|---|---|
| `data/raw/` | 원본 xlsx (전문가 HAZOP 워크시트) | **git-ignored** |
| `data/gold/` | `tools/build_gold.py` 변환 산출물 (JSON) | tracked |

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
