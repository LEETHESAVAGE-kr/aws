# tasks.md — evaluation-harness
# spec: evaluation-harness · 대응 FR: PRD §5 FR-08 (v2.0)
# 생성: 2026-09-22~23 세션 (9/24 일정 당김) · 태스크 6개 (PRD §6 상한 ≤6) · T-01~T-05 오프라인, T-06 만 실호출

## 범례

☐ 미착수 · ☑ 완료 · 【오프라인】 실호출 없이 끝남 · 【실호출】 API 키·모델 ID 필요

각 태스크는 대응 요구사항(R-xx)과 검증 방법을 갖는다. 검증이 없는 태스크는 없다.

---

## T-01 골드 적재와 노드 메타 도출 (`eval/data.py`) 【오프라인】 ☐

**대응**: R-01

**작업**
1. `load_split(split: str) -> list[tuple[NodeMeta, list[dict]]]`.
   `data/gold/split_node.json` 의 `holdout_nodes`/`tune_nodes` 로 `hazop_nh3.json` 을 거른다.
2. 노드별 `node_meta` 를 집합으로 모아 **1종인지 검사**. 2종 이상이면 `ValueError`.
3. 건수를 `holdout_count`(26)·`tune_count`(8)와 대조. 다르면 `ValueError`.
4. `NodeMeta(node=<노드명>, **meta)` 로 조립해 반환.

**검증**
- `--split holdout` → 노드 3개·골드 26건, N4 `equipment == ["이송 운전 절차"]`.
- `--split tune` → 노드 1개(N1)·골드 8건.
- **결함 재삽입**: 임시로 한 레코드의 `node_meta.substance` 를 바꾸면 `ValueError`.
  건수 대조를 지우면 골드 1건을 뺐을 때 조용히 통과해야 한다(= 시험이 그걸 잡는지 확인).

---

## T-02 매칭 (`eval/matching.py`) 【오프라인】 ☐

**대응**: R-02

**작업**
1. `_normalize_for_similarity`(NFKC·공백 제거)와 `_normalize_parameter`
   (NFKC·공백·괄호·말미 조사 제거). **동의어 사전 금지.**
2. `jaccard_2gram(a, b) -> float`. 1글자는 자기 자신을 bigram 으로, 빈 문자열끼리는 0.0.
3. `match(gold, generated, tau, rule) -> list[Pair]`. 규칙 A/B 의 키 조건만 다르고
   점수·배정 로직은 공유. 1:1 탐욕 배정, 동률은 `(gold_id, gen_id)` 사전순.

**검증**
- 골드를 그대로 생성으로 넣으면 A·B 모두 전건 매칭.
- `parameter` 뒤 공백 1개 → A 하락, B 유지.
- 같은 이탈 텍스트를 가진 생성 2건 → 골드 1건에 **1건만** 붙는다.
- **결함 재삽입**: 배정에서 `used_gold` 검사를 빼면 중복 배정 시험이 깨져야 한다.

---

## T-03 지표 계산 (`eval/metrics.py`) 【오프라인】 ☐

**대응**: R-03

**작업**
1. `NodeResult` 데이터클래스(생성·골드·호출기록·지연·셀 수·review 가이드워드).
2. 노드 지표: recall·precision·S_mae·F_mae·matrix_miss_rate·review_guideword_rate·
   schema_downgrade_count·latency_s·llm_latency_s·tokens·cost_usd.
3. **null 규율**: 매칭 0 → MAE `null`, 생성 0 → precision `null`. 0 으로 채우지 않는다.
4. `aggregate()`: 회차 원값 `values` 배열 + `mean` + `sd`(`ddof=1`, n<2 면 `null`).

**검증**
- 생성 0건 시나리오: `recall=0.0`, `precision=null`, `S_mae=null`, 예외 없음.
- 과생성(골드 26 + 잡음 26): precision ≈ 0.5, recall 불변.
- `values` 길이 == `repeats`.
- **결함 재삽입**: MAE 의 `null` 을 `0.0` 으로 바꾸면 생성 0건 시험이 깨져야 한다.
  `ddof=1` 을 `ddof=0` 으로 바꾸면 sd 단언이 깨져야 한다.

---

## T-04 관측 래퍼 (`eval/recording.py`) 【오프라인】 ☐

**대응**: R-04

**작업**
1. `RecordingClient(AbstractBedrockClient)` — `converse()` 를 감싸 호출별
   `usage`·`cost_usd`·`latency_s`·`call_id`·`confidence_override` 를 `calls` 에 누적.
   **응답은 변형하지 않고 그대로 반환.**
2. `reset()` · `snapshot()`.
3. `_do_converse` 가 아니라 `converse` 를 감싼다(재시도 포함 관측 — design §2).
4. **`_do_converse` 를 반드시 정의한다** — `@abstractmethod` 라 없으면 인스턴스화가
   `TypeError` 로 죽는다(design §2 함정, 2026-09-22 실측). 본문은 `raise AssertionError`.

**검증**
- mock 실행에서 `sum(calls.usage.input)` 이 호출별 합과 일치.
- `HazopGenerator(RecordingClient(mock))` 결과가 `HazopGenerator(mock)` 결과와 **동일**
  (래퍼가 투명한지).
- `git status --porcelain` 에 `core/` 0건 — **이 태스크의 핵심 수용 기준.**
- `_do_converse` 가 도달 불가인지 확인(직접 호출하면 `AssertionError`).
- **결함 재삽입**: `converse` 에서 응답을 복사·변형하면 투명성 시험이 깨져야 한다.
  `_do_converse` 본문을 `pass` 로 바꾸면 위 도달불가 시험이 깨져야 한다.

---

## T-05 CLI·출력물·리포트 (`eval/run.py`, `eval/report.py`) 【오프라인】 ☐

**대응**: R-05, R-06

**작업**
1. 인자: `--split --repeats --seed --provider --tau --out --dry-run --max-calls`(기본 120).
2. `--dry-run` 은 예상 호출 수만 출력하고 종료. `--max-calls` 초과면 **시작 전 중단**.
3. `results/{run_id}/` 에 `metrics.json`·`config.yaml`·`report.md`·`raw/*.json`.
   `config.yaml` 사본에서 비밀값 키를 필터(NFR-05).
4. `report.render(metrics) -> str` 은 **순수 함수**. 규칙 A·B 를 같은 표에.
   재현성 한계·어휘 천장 고정 문구를 `report.py` 상수로 박는다.
5. `metrics.json` 에 `model_output_deterministic: false` + 사유.

**검증**
- `--provider mock --seed 42` 2회 실행이 **바이트 동일한** `metrics.json`(하네스 결정성).
- `metrics.json` 을 다시 읽어 `render()` 하면 `report.md` 와 문자열 일치.
- `config.yaml` 사본에 `KEY`·`SECRET`·`TOKEN` 문자열 0건.
- `--dry-run` 이 실호출 0회.
- **결함 재삽입**: 고정 문구 상수를 지우면 리포트 시험이 깨져야 한다.

---

## T-06 홀드아웃 실측 【실호출】 ☐

**대응**: 완료 조건 · PRD §8 9/24 행

**선행 조건(이것이 없으면 시작하지 않는다)**
- `.env` 에 `ANTHROPIC_API_KEY`(사용자 작업)
- `config/models.yaml` 의 `model_id` 기입(사람이 모델 목록에서 선택)
- **G1 판정(지시문 E-2) 완료** — recall 숫자 1개가 먼저 나와야 한다

**작업**
1. `--provider mock` 으로 τ 스윕(0.4/0.5/0.6) → OQ-7 을 **실측으로** 결정하고 README 에 명시.
2. `--dry-run` 으로 호출 수 확인 → 예산 확인 후 본 실행.
3. `--split holdout --repeats 3 --seed 42 --provider anthropic` **1회**(= 3회차).
   재실행하지 않는다. 실패하면 원인을 보고하고 멈춘다.
4. `report.md` 를 README §평가 에 붙인다. **불리한 지표를 빼지 않는다**(NFR-03).

**검증**
- `results/{run_id}/metrics.json` 존재, `values` 길이 3.
- 노드당 지연 P90 ≤ 60초(NFR-06) 충족 여부를 **사실대로** 기록.
- 규칙 A·B 의 차이를 어휘 천장으로 해석한 1문단을 README 한계 절에.

---

## 체크리스트 요약

| 태스크 | 대응 R | 실호출 | 상태 |
|---|---|---|---|
| T-01 골드 적재·노드 메타 | R-01 | 없음 | ☐ |
| T-02 매칭(규칙 A/B) | R-02 | 없음 | ☐ |
| T-03 지표·집계 | R-03 | 없음 | ☐ |
| T-04 RecordingClient | R-04 | 없음 | ☐ |
| T-05 CLI·출력물·리포트 | R-05·R-06 | 없음 | ☐ |
| T-06 홀드아웃 실측 | 완료 조건 | **있음** | ☐ (축소 실행 — `tools/capture_replay.py` + `tools/_replay.py` 규칙 매칭, README §6) |

## 추적 매트릭스 (NFR-01)

| 요구사항 | 태스크 | 테스트 |
|---|---|---|
| R-01 데이터 적재 | T-01 | `test_load_split_holdout`, `test_node_meta_conflict_raises`, `test_count_mismatch_raises` |
| R-02 매칭 | T-02 | `test_exact_match_full_recall`, `test_whitespace_rule_a_vs_b`, `test_one_to_one_assignment` |
| R-03 지표 | T-03 | `test_zero_generated_nulls`, `test_overgeneration_precision`, `test_aggregate_values_length` |
| R-04 관측 | T-04 | `test_recording_transparent`, `test_token_sum_matches`, `test_core_untouched` |
| R-05 출력물 | T-05 | `test_metrics_files_written`, `test_report_is_pure`, `test_config_copy_has_no_secrets` |
| R-06 재현성 한계 | T-05 | `test_mock_byte_identical`, `test_report_has_determinism_note` |
| 완료 조건 | T-06 | 수작업 — `results/{run_id}/metrics.json` 실측 |
