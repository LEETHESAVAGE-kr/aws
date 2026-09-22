# requirements.md — evaluation-harness
# spec: evaluation-harness · 대응 FR: PRD §5 FR-08 (v2.0)
# 생성: 2026-09-22~23 세션(9/24 일정 당김) · 기준 문서: PRD.md v2.0 §5 FR-08 · §8 9/24 행 · §11 OQ-7
# 작성 방식: 손 작성(PRD §6 "신규 spec 3개는 손 작성"). Kiro 크레딧 미사용.

## 범위

`eval/` 패키지와 `tests/test_eval.py`. 태스크 ≤ 6개(PRD §6 상한).

명령 1개로 끝난다:

```
python -m eval.run --split holdout --repeats 3 --seed 42 --provider anthropic|bedrock|mock
```

이 spec 은 **`core/` 를 수정하지 않는다.** `core/agent/generate.py` · `core/llm/*` ·
`schemas/deviation.schema.json` 은 읽기 전용으로 쓴다. 필요한 관측값을 `core` 가 노출하지
않는 경우(R-04)에는 `AbstractBedrockClient` 를 **감싸는** 방식으로 해결하고 `core` 에 필드를
추가하지 않는다. 이 규율은 export-formats spec 의 "`core/export` 는 `core/agent` 를 임포트하지
않는다" 와 같은 이유다 — 측정 코드가 피측정 코드를 바꾸면 지표가 지표가 아니게 된다.

**포함하지 않는 것**: 프롬프트 수정(FR-03 소관, 지시문 별도) · 근거정확도 수작업 채점
(FR-04′ 를 한 경우에만, 이 spec 밖) · 레코드 수준 `confidence` 판정 개선(FR-06
self-verification spec 소관, R-04 참조) · 임베딩 매칭(본선, PRD §12 비목표) · UI(FR-10).

---

## 이미 존재하는 자산 (재구현 금지)

| 자산 | 경로 | 실측 확인(2026-09-22) |
|---|---|---|
| 생성기 | `core/agent/generate.py` `HazopGenerator.generate(NodeMeta) -> list[DeviationRecord]` | 공개 진입점 1개 |
| 공급자 추상화 | `core/llm/client.py` `AbstractBedrockClient` | `converse()` 가 `ConverseResponse` 반환 |
| 호출 단위 계측 | `core/llm/types.py` `ConverseResponse.usage`(`TokenUsage`) · `.cost_usd` · `.latency_s` | **호출 1건 단위로만 존재** |
| 골드셋 정본 34건 | `data/gold/hazop_nh3.json` | tune 8 + holdout 26 |
| 홀드아웃 26건 | `data/gold/hazop_nh3_eval.json` | N2 9 · N3 7 · N4 10 |
| 분할 정의 | `data/gold/split_node.json` | `tune_nodes=["N1"]`, `holdout_nodes=["N2","N3","N4"]` |
| 산출물 스키마 | `schemas/deviation.schema.json` | `confidence` enum `["inferred","review"]` |

### 홀드아웃 노드 메타 (실측 — 추측으로 바꾸지 않는다)

각 노드의 26건은 **노드당 `node_meta` 가 정확히 1종**이다(2026-09-22 실측: N2·N3·N4 모두
`distinct node_meta = 1`). 따라서 하네스는 노드별 대표 `node_meta` 를 골드 레코드에서 그대로
뽑아 쓰고, 불일치가 나오면 **조용히 첫 번째를 쓰지 말고 예외를 던진다**(R-01).

| 노드 | 골드 건수 | `equipment` | 가이드워드 분포 |
|---|---|---|---|
| N2 | 9 | 이송 호스 | More 4 · Less 2 · Other than 2 · No 1 |
| N3 | 7 | 수급선 매니폴드 | More 2 · No 2 · Less 1 · Other than 1 · Reverse 1 |
| N4 | 10 | 이송 운전 절차 | Too early 3 · Too late 3 · Wrong action 3 · No 1 |

`substance` 는 셋 다 `NH3`, `phase` 는 `unknown`, `P_kPag`·`T_degC`·`safeguards` 는 전부 결측이다.

---

## 요구사항 (EARS 형식)

### R-01 데이터 적재와 노드 메타 도출

**WHEN** `--split holdout` 이면, **THE SYSTEM SHALL** `data/gold/split_node.json` 의
`holdout_nodes` 로 `data/gold/hazop_nh3.json` 을 걸러 골드 레코드를 얻고, 노드별로
`node_meta` 를 모아 **정확히 1종인지 검사한 뒤** 그 값으로 `NodeMeta(node=<노드>, **meta)` 를
만든다.

- `--split tune` 이면 `tune_nodes`(N1, 8건)로 같은 처리를 한다.
- 한 노드에서 서로 다른 `node_meta` 가 2종 이상 나오면 `ValueError` 로 **중단한다**.
  임의로 하나를 고르면 지표의 입력이 무엇이었는지 사후에 알 수 없다.
- 건수는 `split_node.json` 의 `holdout_count`(26)·`tune_count`(8)와 대조하고 다르면 중단한다.

**수용 기준**: `--split holdout` 이 노드 3개·골드 26건을 반환하고, N4 의 `equipment` 가
`["이송 운전 절차"]` 다. 골드 파일을 건드려 한 레코드의 `node_meta.substance` 를 바꾸면
`ValueError` 가 난다.

---

### R-02 매칭 규칙 — 정본 1개 + 보조 1개를 **함께** 낸다

**THE SYSTEM SHALL** 생성 레코드와 골드 레코드를 아래 두 규칙으로 각각 매칭하고
**둘 다 보고한다**.

**규칙 A (정본 — PRD FR-08 문면 그대로)**
`(guideword, parameter)` 정확 일치 **AND** `deviation` 텍스트 유사도 ≥ τ.

**규칙 B (보조 — PRD §10 R4 "보조 지표 병기" 근거)**
`guideword` 정확 일치 **AND** `parameter` **정규화 후** 일치 **AND** `deviation` 유사도 ≥ τ.

- 유사도는 문자 2-gram Jaccard 와 `difflib.SequenceMatcher.ratio()` 중 **2-gram Jaccard 를
  채택**한다. `SequenceMatcher` 는 한국어에서 어순 차이에 과민하고 길이에 따라 비선형으로
  움직인다. 선택 근거를 `metrics.json` 에 `similarity="jaccard_2gram"` 으로 남긴다.
- 정규화(규칙 B 전용): 공백 제거 · 괄호와 그 안쪽 제거 · 조사(`의·이·가·을·를·은·는·에·로·으로`)
  어미 제거 · NFKC. **동의어 사전을 쓰지 않는다** — 골드 어휘를 사전에 넣는 순간 홀드아웃
  누출이다.
- 매칭은 **1:1 이다.** 유사도 내림차순 탐욕 배정으로 한 골드에 한 생성만 붙인다. 중복 배정은
  precision 을 부풀린다.
- τ 기본값 0.5. `--tau` 로 바꿀 수 있고 실제 값은 `metrics.json` 에 반드시 기록한다(OQ-7).

**수용 기준**: 골드 레코드를 그대로 생성 결과로 넣으면 규칙 A·B 모두 recall=1.0·precision=1.0.
같은 골드에 `parameter` 만 `"액위"`→`"액위 "`(뒤 공백)로 바꾸면 **규칙 A 는 떨어지고 규칙 B 는
유지**된다.

---

### R-03 지표 정의

**THE SYSTEM SHALL** 회차마다 다음을 계산한다.

| 지표 | 정의 | 분모 |
|---|---|---|
| `recall` | 매칭된 골드 수 / 골드 수 | 홀드아웃 26 |
| `precision` | 매칭된 생성 수 / 생성 수 | 생성 레코드 수 |
| `S_mae` · `F_mae` | 매칭쌍의 \|생성−골드\| 평균 | **매칭쌍 수** |
| `matrix_miss_rate` | 1 − `judged_cells` / `expected_cells` | 노드별 합산 |
| `review_guideword_rate` | `len(review_guidewords)` / 호출한 가이드워드 수 | 노드별 합산 |
| `latency_s_per_node` | 노드 1건 생성의 벽시계 초 | 노드 |
| `tokens` | `input`·`output`·`cache_read`·`cache_write` 합 | 노드 |
| `cost_usd_per_node` | 노드 누적 비용 | 노드 |

- **매칭쌍이 0 이면 `S_mae`·`F_mae` 는 `null` 이다. 0 으로 적지 않는다.** 0 은 "완벽히 맞았다"로
  읽힌다.
- `precision` 의 분모가 0(생성 0건)이면 `null`.
- 모든 지표는 **회차별 원값을 먼저 저장**하고, 평균±표준편차는 그 위에서 계산한다.
  3회는 표본이 작으므로 표준편차는 `ddof=1`(표본표준편차)로 쓰고 회차 원값도 함께 남긴다.

**수용 기준**: 생성 0건인 mock 시나리오에서 `recall=0.0`, `precision=null`, `S_mae=null` 이고
프로세스가 죽지 않는다.

---

### R-04 관측값 수집 — `core` 를 고치지 않고

**실측 확인(2026-09-22)**: `HazopGenerator` 는 `total_cost_usd`·`expected_cells`·
`judged_cells`·`review_guidewords` 만 노출한다. **지연과 토큰은 집계하지 않는다**
(`generate.py` 에 `latency_s`·`usage` 참조 0건). `ConverseResponse` 는 호출 단위로 셋 다 갖고
있지만 `_generate_batch` 가 `cost_usd` 만 꺼내 쓰고 나머지를 버린다.

**THE SYSTEM SHALL** `AbstractBedrockClient` 를 상속한 `RecordingClient` 로 실제 클라이언트를
감싸 호출 단위 `usage`·`latency_s`·`cost_usd` 를 누적한다. `core/llm` 과 `core/agent` 는
한 줄도 바뀌지 않는다.

- 생성기는 주입받은 클라이언트가 `AbstractBedrockClient` 라는 것만 알면 되므로(REQ-12
  AC-12-1 과 같은 불변식) 래핑으로 충분하다.
- `RecordingClient` 는 호출을 가로채 기록만 하고 **응답을 변형하지 않는다.**
- 노드 경계는 하네스가 `reset()` 으로 긋는다.

**레코드 수준 `review` 비율은 이 spec 이 계산하지 않는다.** 근거:
`schemas/deviation.schema.json` 의 `confidence` 주석이 "`review` 는 … 그 행은 레코드를 만들지
않는다" 라고 규정하고, `generate.py` 는 `confidence="inferred"` 를 하드코딩하며
`ConverseResponse.confidence_override`(= `"review"`)를 **읽지 않는다**(참조 0건). 따라서 레코드
수준 review 비율은 **구조적으로 언제나 0** 이고, 그 0 을 지표로 적으면 거짓이다. FR-08 이
요구하는 "`review` 비율" 은 위 표의 `review_guideword_rate` 로 낸다. 레코드 수준 판정은
self-verification spec(FR-06, 9/25) 소관으로 넘기고 README 한계 절에 적는다.

**수용 기준**: `RecordingClient` 로 감싼 mock 실행에서 토큰 합이 호출별 합과 일치하고,
`git status` 에 `core/` 변경이 0건이다.

---

### R-05 출력물

**THE SYSTEM SHALL** `results/{run_id}/` 아래에 다음을 쓴다. `run_id` 는
`{YYYYMMDD-HHMMSS}-{provider}-{split}` 이다.

| 파일 | 내용 |
|---|---|
| `metrics.json` | 회차 원값 배열 + 평균·표준편차 + τ·유사도 방식·매칭 규칙 A/B 양쪽 |
| `config.yaml` | 실행 시점 `config/models.yaml` 사본 + CLI 인자 + `git rev-parse HEAD` |
| `report.md` | README §평가 에 그대로 붙일 마크다운 표 |
| `raw/{node}-rep{n}.json` | 회차별 생성 레코드 원본 |

- `config.yaml` 사본에서 **`ANTHROPIC_API_KEY`·`AWS_*` 등 비밀값은 쓰지 않는다**(NFR-05,
  AC-12-3). `models.yaml` 에는 원래 키가 없지만 방어적으로 필터를 건다.
- `report.md` 에는 **불리한 지표를 빼지 않는다**(NFR-03). recall 이 낮으면 낮은 대로 적고,
  규칙 A·B 를 같은 표에 둔다.
- `results/` 는 `.gitignore` 에 넣지 않는다 — 실측 기록이 제출물의 일부다.

**수용 기준**: mock 1회 실행이 네 종류 파일을 만들고, `metrics.json` 을 다시 읽어 `report.md`
를 재생성하면 문자열이 같다(표 생성이 순수 함수).

---

### R-06 재현성의 한계를 명시한다

**THE SYSTEM SHALL** `--seed` 를 받아 **하네스 쪽** 난수(회차 순서·탐욕 배정 동률 처리)만
고정하고, **모델 출력은 고정하지 않는다는 사실을 `metrics.json` 과 `report.md` 에 적는다**.

- Anthropic·Bedrock 모두 API 수준 시드가 없다. 게다가 현재 어댑터는 `temperature` 를
  전송하지 않는다(REQ-12 구현 판단) — 즉 샘플링을 우리가 통제하지 못한다.
- 그러므로 "seed=42 면 같은 결과" 는 **거짓이다.** 3회 반복의 표준편차가 이 비결정성을
  드러내는 지표이며, 그것이 3회를 도는 이유다.
- `metrics.json` 에 `"model_output_deterministic": false` 와 사유를 넣는다.

**수용 기준**: `report.md` 하단에 재현성 한계 문장이 있고, `--provider mock` 은 같은 seed 에서
바이트 동일한 `metrics.json` 을 낸다(mock 은 결정적이므로 하네스 자체의 결정성은 검증된다).

---

## 알려진 천장 — 스펙이 숨기지 않는다

골드셋 파라미터 어휘는 steering `domain.md` §2 표준 목록과 거의 겹치지 않는다
(2026-09-22 실측: 홀드아웃 26건 중 표준 어휘 일치 4건). 홀드아웃 고유 어휘는
`곡률반경`·`본딩`·`밀봉`·`ESD`·`퍼징 생략`·`대피 방송`·`밸브 순서` 같은 설비/절차 고유어다.

**규칙 A 는 이 어휘를 모델이 한 글자도 틀리지 않고 재현할 것을 요구한다.** 파라미터 축이
`matrix_enumerate.md` 프롬프트로 노드 메타에서 도출되도록 바뀌었으므로 고정 목록 시절의
상한은 더 이상 그대로 적용되지 않지만, 정확 일치 요구 자체가 여전히 강한 천장이다.
규칙 B 를 병기하는 이유가 이것이고, 두 값의 차이가 곧 "어휘 때문에 잃은 recall" 이다.
이 해석을 README 한계 절에 쓴다. 골드 N2~N4 어휘를 프롬프트에 넣는 것은 **홀드아웃 누출이며
금지**한다.

---

## 완료 조건 (PRD FR-08 그대로)

- `python -m eval.run --split holdout --repeats 3 --seed 42 --provider anthropic` 가
  `results/{run_id}/metrics.json` 을 만든다.
- 홀드아웃 26건 × 3회 평균±표준편차 표가 README §평가 에 있고 **불리한 지표도 포함**한다.
- 오프라인 테스트(`pytest -m "not live"`)가 mock 결과로 지표 계산 로직을 검증한다.
