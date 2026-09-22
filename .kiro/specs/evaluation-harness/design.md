# design.md — evaluation-harness
# spec: evaluation-harness · 대응 FR: PRD §5 FR-08 (v2.0)
# 생성: 2026-09-22~23 세션 (9/24 일정 당김) · 작성 방식: 손 작성

## 1. 모듈 구성

```
eval/
  __init__.py
  data.py        R-01  골드 적재 · 노드 메타 도출 · 건수 대조
  matching.py    R-02  정규화 · 2-gram Jaccard · 1:1 탐욕 배정 · 규칙 A/B
  metrics.py     R-03  회차 지표 · 집계(평균/표본표준편차) · null 규율
  recording.py   R-04  RecordingClient(AbstractBedrockClient)
  report.py      R-05  metrics.json → report.md (순수 함수)
  run.py         CLI   python -m eval.run
```

신규 클래스 2개(`RecordingClient`, `NodeResult` 데이터클래스). 나머지는 함수.

### 의존 방향

```
eval.run ──▶ eval.data / eval.matching / eval.metrics / eval.report
   │
   └──▶ eval.recording ──▶ core.llm.client.AbstractBedrockClient   (읽기 전용 상속)
   └──▶ core.agent.generate.HazopGenerator / NodeMeta               (읽기 전용 호출)
```

`core` → `eval` 방향 의존은 **없다.** `core` 는 `eval` 의 존재를 모른다.

---

## 2. R-04 를 래핑으로 푸는 이유와 방법

문제: 지연·토큰이 `ConverseResponse` 에는 있는데 `HazopGenerator` 가 버린다
(`_generate_batch` 가 `response.cost_usd` 만 더한다). 노드당 지연·토큰은 FR-08 필수 지표다.

선택지는 둘이었다.

| 안 | 내용 | 판정 |
|---|---|---|
| (가) `HazopGenerator` 에 `total_tokens`·`total_latency_s` 추가 | 간단 | **기각.** 측정 코드가 피측정 코드를 바꾼다. `core/agent` 변경은 REQ-12 AC-12-1 이 지켜온 불변식도 깬다 |
| (나) `AbstractBedrockClient` 구현체로 감싼다 | 생성기는 추상 클래스만 보므로 투명 | **채택** |

```python
class RecordingClient(AbstractBedrockClient):
    def __init__(self, inner: AbstractBedrockClient) -> None:
        self._inner = inner
        self.model_short = inner.model_short
        self.cost_limit_usd = inner.cost_limit_usd
        self.reset()

    def reset(self) -> None:
        self.calls: list[CallRecord] = []

    def converse(self, **kw) -> ConverseResponse:
        r = self._inner.converse(**kw)
        self.calls.append(CallRecord(r.usage, r.cost_usd, r.latency_s, r.call_id,
                                     r.confidence_override))
        return r            # 원본을 그대로 돌려준다 — 변형 금지
```

`_do_converse` 가 아니라 **`converse` 를 감싼다.** `AbstractBedrockClient.converse` 가
비용 상한·재시도 훅을 이미 돌리므로, 그 바깥에서 관측해야 "실제로 일어난 일" 이 잡힌다.
`_do_converse` 를 감싸면 재시도가 몇 번 돌았는지 보이지 않는다.

> **함정 (2026-09-22 실측 확인).** `_do_converse` 는 `@abstractmethod`(`client.py:277`)다.
> `converse` 만 재정의한 래퍼는 **인스턴스화 자체가 안 된다** —
> `TypeError: Can't instantiate abstract class … without an implementation for abstract
> method '_do_converse'`. 실제로 재현해서 확인했다.
> 따라서 `RecordingClient` 는 `_do_converse` 를 **반드시 정의**하되, 도달할 수 없는 경로이므로
> 본문은 `raise AssertionError("RecordingClient.converse 가 위임하므로 호출될 수 없다")` 로
> 둔다. `pass` 나 `...` 로 두면 상속 구조가 바뀌었을 때 조용히 빈 응답을 만들어 지표가
> 0 으로 채워진다. T-04 검증에 이 예외가 실제로 도달 불가인지 확인하는 시험을 넣는다.

`confidence_override` 도 여기서 같이 줍는다. 생성기가 이 값을 읽지 않으므로(R-04) 하네스만이
"스키마 검증 2회 실패" 가 몇 번 일어났는지 관측할 수 있는 위치다. 이 수는
`review_guideword_rate` 와 **별개로** `schema_downgrade_count` 로 기록한다 — 둘은 다른
사건이다(전자는 `content is None`, 후자는 검증 실패 후 격하).

---

## 3. 매칭 알고리즘 (R-02)

```
후보쌍 = {(g, p) | g ∈ 골드, p ∈ 생성, 규칙의 키 조건 만족}
각 쌍의 점수 = jaccard_2gram(g.deviation, p.deviation)
점수 < τ 인 쌍 버림
점수 내림차순 정렬 (동률은 (골드 id, 생성 id) 사전순 — seed 무관하게 결정적)
위에서부터 탐욕 배정, 이미 쓰인 골드/생성은 건너뜀
```

동률 처리를 seed 가 아니라 **id 사전순**으로 둔 것은 의도적이다. R-06 이 "하네스는 결정적,
모델은 비결정적" 을 주장하려면 매칭이 seed 에 흔들리면 안 된다.

### 2-gram Jaccard

```python
def _bigrams(s: str) -> set[str]:
    s = _normalize_for_similarity(s)      # NFKC + 공백 제거
    return {s[i:i+2] for i in range(len(s) - 1)} or {s}
def jaccard_2gram(a: str, b: str) -> float:
    A, B = _bigrams(a), _bigrams(b)
    return len(A & B) / len(A | B) if (A | B) else 0.0
```

1글자 문자열은 bigram 이 비므로 `or {s}` 로 자기 자신을 넣는다. 빈 문자열끼리는 0.0
(분모 0 → 1.0 으로 두면 빈 이탈끼리 완전 일치가 되어 recall 이 부풀려진다).

### 규칙 B 의 파라미터 정규화

```
NFKC → 공백 제거 → 괄호와 내부 제거 → 말미 조사 제거(의 이 가 을 를 은 는 에 로 으로)
```
동의어 사전 없음(R-02). `액위` 와 `준위` 는 **다른 값으로 남는다** — 둘을 같다고 선언하려면
골드를 봐야 하고 그것이 누출이다.

---

## 4. 실행 흐름 (`eval/run.py`)

```
1. 인자 파싱 (--split --repeats --seed --provider --tau --out)
2. eval.data.load_split(split)      → [(NodeMeta, [골드 레코드])] · 건수 대조
3. provider 로 클라이언트 생성       → get_bedrock_client() 또는 mock
   RecordingClient 로 감쌈
4. for rep in range(repeats):
       for node, gold in nodes:
           recorder.reset()
           t0 = perf_counter()
           records = HazopGenerator(recorder).generate(node)     # 노드마다 새 인스턴스
           node_result = NodeResult(records, gold, recorder.snapshot(),
                                    latency_s=perf_counter() - t0,
                                    expected_cells=..., judged_cells=...,
                                    review_guidewords=...)
           raw 저장
5. eval.metrics.aggregate(...) → metrics.json
6. eval.report.render(metrics)  → report.md
```

**노드마다 `HazopGenerator` 를 새로 만든다.** `generate()` 가 `self.review_guidewords`
등을 초기화하긴 하지만, 상태를 공유하는 인스턴스를 돌려쓰면 한 노드의 실패가 다음 노드의
집계에 섞일 여지가 생긴다. 인스턴스 생성 비용은 0 에 가깝다.

`latency_s` 는 `RecordingClient` 가 모은 호출별 합이 아니라 **노드 `generate()` 전체의
벽시계**다. FR-08·NFR-06 의 "노드 1건 ≤ 60초" 가 사용자 체감 시간이기 때문이다. 호출별 합은
`llm_latency_s` 로 따로 적어 둘의 차(프롬프트 조립·파싱 오버헤드)를 볼 수 있게 한다.

### 실호출 예산

`--repeats 3` × 노드 3개 × (파라미터 열거 1 + 가이드워드 수) 호출. 가이드워드가 노드당
5~7개면 **1회차 약 18~24 호출, 3회차 54~72 호출**이다. `--dry-run` 으로 호출 수만 먼저
출력하고, `--max-calls`(기본 120) 를 넘으면 시작 전에 중단한다. PRD R13(크레딧 $10 상한)과
"실호출 횟수는 지시문에 명시" 규율을 하네스 자체가 강제한다.

---

## 5. `metrics.json` 스키마 (요지)

```json
{
  "run_id": "20260924-134500-anthropic-holdout",
  "git_sha": "a95884d…",
  "split": "holdout", "repeats": 3, "seed": 42, "tau": 0.5,
  "similarity": "jaccard_2gram",
  "model_output_deterministic": false,
  "determinism_note": "API 수준 시드 없음 · temperature 미전송(REQ-12) — seed 는 하네스만 고정",
  "gold_count": 26,
  "reps": [ { "rep": 0, "nodes": [ { "node": "N2",
        "rule_a": {"recall":0.0,"precision":0.0,"matched":0,"S_mae":null,"F_mae":null},
        "rule_b": {"recall":0.11,"precision":0.08,"matched":1,"S_mae":1.0,"F_mae":0.0},
        "generated": 12, "expected_cells": 35, "judged_cells": 35,
        "matrix_miss_rate": 0.0, "review_guideword_rate": 0.0,
        "schema_downgrade_count": 0,
        "latency_s": 41.2, "llm_latency_s": 39.8,
        "tokens": {"input":..., "output":..., "cache_read":..., "cache_write":...},
        "cost_usd": 0.11 } ] } ],
  "aggregate": { "rule_a": {"recall":{"mean":..,"sd":..,"values":[..]}, ... },
                 "rule_b": {...}, "cost_usd_per_node": {...}, "latency_s": {...} }
}
```

`values` 배열을 항상 함께 둔다. 3개짜리 표본의 평균±표준편차만 남기면 나중에 어느 회차가
튀었는지 복원할 수 없다.

---

## 6. `report.md` 표 (README §평가 에 그대로 붙는다)

```markdown
| 지표 | 규칙 A (정확일치) | 규칙 B (정규화) |
|---|---|---|
| 이탈 recall | 0.00 ± 0.00 | 0.12 ± 0.04 |
| 이탈 precision | 0.00 ± 0.00 | 0.09 ± 0.03 |
| S MAE (매칭 n=3) | — | 0.67 ± 0.58 |
...
| 매트릭스 누락률 | 0.00 ± 0.00 |
| 노드당 지연(초) | 41.2 ± 6.1 |
| 노드당 비용(USD) | 0.11 ± 0.02 |
```

- 매칭 0 인 칸은 `—` 로 찍고 각주로 "매칭쌍 0 — MAE 정의되지 않음" 을 단다.
- 표 아래에 재현성 한계 1문장(R-06)과 어휘 천장 1문장(요구사항 §알려진 천장)을 고정 문구로
  붙인다. 이 두 문장은 `report.py` 의 상수이며 실행자가 지울 수 없다.

---

## 7. 오프라인 검증 전략 (R-05·완료 조건)

`--provider mock` 은 `MockBedrockClient` 를 쓴다. 지표 계산 로직 검증은 **실호출 없이**
다음 네 시나리오로 한다.

| 시나리오 | 입력 | 기대 |
|---|---|---|
| 완전 일치 | 골드를 그대로 생성 결과로 주입 | 규칙 A·B 모두 recall 1.0 · precision 1.0 · MAE 0.0 |
| 공백 차이 | `parameter` 뒤 공백 1개 | 규칙 A 하락 · **규칙 B 유지** |
| 생성 0건 | 빈 리스트 | recall 0.0 · precision null · MAE null · 프로세스 생존 |
| 과생성 | 골드 26 + 잡음 26 | recall 유지 · precision ≈ 0.5 · 1:1 배정 확인 |

결함 재삽입(프로젝트 관례)으로 각 시험이 실제로 깨지는지 확인한다: 1:1 배정을 중복 허용으로
바꾸면 과생성 시나리오의 precision 이 틀려야 하고, MAE 의 `null` 을 `0.0` 으로 바꾸면 생성
0건 시나리오가 깨져야 한다.

---

## 8. 결정 기록

| # | 결정 | 근거 |
|---|---|---|
| D1 | 규칙 A·B 병기 | PRD FR-08 문면은 A. 어휘 천장을 A 하나로 덮으면 "모델이 못한다" 와 "지표가 가혹하다" 가 구별되지 않는다. PRD §10 R4 가 보조 지표 병기를 허용 |
| D2 | `SequenceMatcher` 대신 2-gram Jaccard | 한국어 어순 민감도. `metrics.json` 에 방식 기록 |
| D3 | `RecordingClient` 래핑 | `core` 무수정(R-04). AC-12-1 과 같은 불변식 |
| D4 | 레코드 수준 review 비율 미산출 | 구조적으로 항상 0 — 적으면 거짓. FR-06 소관 |
| D5 | 매칭 동률을 id 사전순으로 | 하네스 결정성 주장(R-06)의 전제 |
| D6 | MAE 분모 0 → `null` | 0 은 "완벽" 으로 읽힌다 |
| D7 | `--max-calls` 기본 120 | R13 비용 상한을 코드가 강제 |
| D8 | τ 는 9/24 mock 스윕(0.4/0.5/0.6)으로 고른다 | OQ-7. 실측 없이 고르면 사후선택 |
