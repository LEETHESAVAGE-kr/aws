"""오프라인 시험 — spec:hazop-generation T-06 (R-03~R-07).

`docs/프롬프트초안_FR-03_20260908.md` §8 의 시험 목록을 구현한다. 전부 `MockBedrockClient`
경로이므로 AWS 자격증명 없이 `pytest -m "not live"` 로 통과해야 한다(live 마커 없음).

tasks.md T-06 은 `@pytest.mark.not live` 라고 적었으나 `not live` 는 마커가 아니라 `-m`
표현식이다(그대로 쓰면 문법 오류). 괄호 안 설명대로 "마커 없음 = 오프라인"으로 구현했다.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft7Validator

from core.agent import DeviationRecord, HazopGenerator, NodeMeta
from core.agent.generate import (
    DEVIATION_BATCH_SCHEMA,
    PROCEDURAL_GUIDEWORDS,
    STANDARD_GUIDEWORDS,
    _select_guidewords,
    load_generator_config,
)
from core.llm import (
    ConfigValidationError,
    ConverseResponse,
    Message,
    MockBedrockClient,
    get_bedrock_client,
    load_model_config,
)
from tools._replay import recall_n1

_LOG = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_GOLD_PATH = _ROOT / "data" / "gold" / "hazop_nh3.json"
_TUNE_PATH = _ROOT / "data" / "gold" / "hazop_nh3_tune.json"
_GENERATE_PY = _ROOT / "core" / "agent" / "generate.py"
_DEVIATION_SCHEMA = json.loads(
    (_ROOT / "schemas" / "deviation.schema.json").read_text(encoding="utf-8")
)

# 모의 응답이 열거하는 파라미터 축 — PARAMETER_LIST_SCHEMA 의 minItems 6 을 만족한다.
MOCK_PARAMETERS = ["유량", "압력", "온도", "조성", "계측", "밀봉"]

N1_META = NodeMeta(
    node="N1",
    substance="NH3",
    phase="unknown",
    equipment=["벙커링선 매니폴드"],
    safeguards=[],
)
N4_META = NodeMeta(
    node="N4",
    substance="NH3",
    phase="unknown",
    equipment=["이송 운전 절차"],
    safeguards=[],
)


# ── 모의 응답 공장 ────────────────────────────────────────────────────────────
def _is_enumeration(system: str) -> bool:
    return "파라미터 축" in system


def _parameter_payload() -> str:
    return json.dumps(
        {"parameters": [{"name": p, "rationale": "근거"} for p in MOCK_PARAMETERS]},
        ensure_ascii=False,
    )


def _batch_payload(
    guideword: str,
    parameters: list[str] = MOCK_PARAMETERS,
    *,
    extra_cell_field: dict[str, Any] | None = None,
    drop_last_cell: bool = False,
) -> str:
    cells: list[dict[str, Any]] = []
    for index, parameter in enumerate(parameters):
        cell: dict[str, Any] = {"parameter": parameter, "applicable": index % 3 != 2}
        if cell["applicable"]:
            cell.update(
                {
                    "deviation": f"{parameter} 이탈",
                    "causes": ["원인"],
                    "consequences": ["결과"],
                    "safeguards_before": [],
                    "S": 4,
                    "F": 3,
                    "recommendations": ["권고"],
                    "evidence": [],
                    "confidence": "inferred",
                }
            )
            if extra_cell_field:
                cell.update(extra_cell_field)
        else:
            cell["skip_reason"] = "물리적으로 성립하지 않음"
        cells.append(cell)
    if drop_last_cell:
        cells.pop()
    return json.dumps({"guideword": guideword, "cells": cells}, ensure_ascii=False)


def _factory(
    *,
    broken_guideword: str | None = None,
    extra_cell_field: dict[str, Any] | None = None,
    drop_last_cell: bool = False,
):
    """system/user 를 보고 열거 호출과 배치 호출을 갈라 응답한다."""

    def make(system: str, messages: list[Message], **_: Any) -> ConverseResponse:
        if _is_enumeration(system):
            return ConverseResponse(content=_parameter_payload())
        user = messages[0].content
        assert isinstance(user, str)
        guideword = _guideword_of(user)
        if broken_guideword is not None and guideword == broken_guideword:
            return ConverseResponse(content='{"guideword": 123}')  # 스키마 위반
        return ConverseResponse(
            content=_batch_payload(
                guideword, extra_cell_field=extra_cell_field, drop_last_cell=drop_last_cell
            )
        )

    return make


def _guideword_of(user_text: str) -> str:
    for guideword in STANDARD_GUIDEWORDS + PROCEDURAL_GUIDEWORDS:
        if f"\n{guideword} —" in user_text:
            return guideword
    raise AssertionError(f"가이드워드를 찾지 못했다: {user_text[:200]}")


def _generator(**kwargs: Any) -> tuple[HazopGenerator, MockBedrockClient]:
    client = MockBedrockClient(response_factory=_factory(**kwargs))
    return HazopGenerator(client=client), client


# ── R-01 입력 스키마 ──────────────────────────────────────────────────────────
def test_nodemeta_accepts_all_gold_records() -> None:
    """골드셋 34건의 `node_meta` 를 그대로 검증할 수 있어야 한다 (R-01 수용 기준)."""
    gold = json.loads(_GOLD_PATH.read_text(encoding="utf-8"))
    assert len(gold) == 34
    for record in gold:
        meta = NodeMeta.model_validate(record["node_meta"])
        assert meta.substance == "NH3"


# ── R-03·R-04 매트릭스 완전성 ─────────────────────────────────────────────────
def test_matrix_cells_are_all_judged() -> None:
    """열거 파라미터 N개 × 가이드워드 k종 = N×k 셀이 전부 판정된다."""
    generator, client = _generator()
    generator.generate(N1_META)

    assert generator.expected_cells == len(MOCK_PARAMETERS) * len(STANDARD_GUIDEWORDS)
    assert generator.judged_cells == generator.expected_cells
    # 호출 수 = 열거 1회 + 가이드워드 행 7회
    assert len(client.calls) == 1 + len(STANDARD_GUIDEWORDS)


def test_missing_cell_is_detected(caplog: pytest.LogCaptureFixture) -> None:
    """셀이 빠지면 커버리지 점검이 잡아낸다 — 예외는 던지지 않는다(R-04)."""
    generator, _ = _generator(drop_last_cell=True)
    with caplog.at_level("WARNING"):
        generator.generate(N1_META)
    assert generator.judged_cells < generator.expected_cells
    assert any("매트릭스 누락" in message for message in caplog.messages)


def test_inapplicable_cells_do_not_become_records() -> None:
    """`applicable=false` 셀은 반환되지만 레코드가 되지는 않는다."""
    generator, _ = _generator()
    records = generator.generate(N1_META)
    applicable_per_row = sum(1 for i in range(len(MOCK_PARAMETERS)) if i % 3 != 2)
    assert len(records) == applicable_per_row * len(STANDARD_GUIDEWORDS)


# ── R-04 절차형 가이드워드 조건부 포함 ────────────────────────────────────────
def test_guideword_axis_is_conditional() -> None:
    """표준 장치 노드는 7종, 운전 절차 노드는 10종 (R-04 수용 기준)."""
    assert _select_guidewords(N1_META) == STANDARD_GUIDEWORDS
    assert len(_select_guidewords(N4_META)) == 10
    assert _select_guidewords(N4_META)[-3:] == PROCEDURAL_GUIDEWORDS


def test_procedural_node_calls_ten_rows() -> None:
    generator, client = _generator()
    generator.generate(N4_META)
    assert len(client.calls) == 1 + 10


# ── R-05 위험도는 코드가 계산한다 ─────────────────────────────────────────────
def test_risk_score_is_computed_by_code() -> None:
    """모델이 무엇을 주든 `risk_score` 는 S×F 다. S=4·F=3 이면 12(ALARP 구간)."""
    record = DeviationRecord(
        id="n1-001",
        node="N1",
        node_meta=N1_META,
        guideword="More",
        parameter="압력",
        deviation="토출압 과다",
        S=4,
        F=3,
        risk_score=99,  # 모델이 틀린 값을 넣은 상황
    )
    assert record.risk_score == 12

    generator, _ = _generator()
    for generated in generator.generate(N1_META):
        assert generated.risk_score == generated.S * generated.F


def test_batch_schema_rejects_risk_score_field() -> None:
    """호출 단위 스키마에는 `risk_score` 가 없다 — 모델이 넣으면 검증에서 거부된다.

    R-05 수용 기준("mock 이 틀린 risk_score 를 반환해도")은 이 스키마와 함께 읽어야 한다.
    스키마가 먼저 막기 때문에 그 값이 코드까지 도달하지 못한다. 위 시험이 계산 규칙을,
    이 시험이 차단을 각각 맡는다.
    """
    payload = json.loads(_batch_payload("More", extra_cell_field={"risk_score": 99}))
    errors = list(Draft7Validator(DEVIATION_BATCH_SCHEMA).iter_errors(payload))
    assert errors, "risk_score 가 들어와도 스키마가 통과시키고 있다"


# ── R-06 스키마 강제와 격하 ───────────────────────────────────────────────────
def test_every_call_enforces_a_schema() -> None:
    generator, client = _generator()
    generator.generate(N1_META)
    assert client.calls, "호출이 한 번도 일어나지 않았다"
    for call in client.calls:
        assert call["response_schema"] is not None


def test_broken_row_is_recorded_as_review_without_exception() -> None:
    """스키마 위반 응답(재시도 포함 2회)은 그 행만 review 로 남기고 나머지는 계속 진행한다."""
    generator, _ = _generator(broken_guideword="More")
    records = generator.generate(N1_META)

    assert generator.review_guidewords == ["More"]
    assert "More" not in {record.guideword for record in records}
    assert {record.guideword for record in records} == set(STANDARD_GUIDEWORDS) - {"More"}


# ── R-02 산출물 스키마 ────────────────────────────────────────────────────────
def test_records_validate_against_deviation_schema() -> None:
    generator, _ = _generator()
    records = generator.generate(N1_META)
    payload = [record.model_dump() for record in records]
    errors = list(Draft7Validator(_DEVIATION_SCHEMA).iter_errors(payload))
    assert not errors, f"스키마 위반: {[e.message for e in errors][:3]}"
    assert all(record.confidence == "inferred" for record in records)
    assert all(record.evidence == [] for record in records)


def test_record_ids_are_lowercase_and_sequential() -> None:
    """`id` 는 골드셋과 같은 소문자 패턴이다 — design.md 의 '{node}-{seq:03d}' 는 대문자라 위반."""
    generator, _ = _generator()
    records = generator.generate(N1_META)
    assert records[0].id == "n1-001"
    assert records[1].id == "n1-002"


# ── R-08 캐싱 경계 ────────────────────────────────────────────────────────────
def test_system_prompt_is_stable_across_guideword_rows() -> None:
    """캐싱이 이득이 되려면 행마다 시스템 블록이 동일해야 한다(가변부는 user 턴).

    `cachePoint` 자체는 `core/llm` 의 `BedrockClient` 가 붙인다(client.py `_do_converse`).
    `converse(system: str)` 시그니처상 generate.py 가 블록을 조립할 수 없으므로, 이 spec 이
    책임지는 부분은 '무엇을 시스템에 두는가'다.
    """
    generator, client = _generator()
    generator.generate(N1_META)
    batch_systems = {call["system"] for call in client.calls[1:]}
    assert len(batch_systems) == 1, "행마다 시스템 프롬프트가 달라 캐시가 무효가 된다"
    system = batch_systems.pop()
    assert "심각도" in system or "severity" in system, "S·F 등급표가 시스템에 없다"
    assert "N1" not in system, "노드 고유 정보가 시스템에 섞여 캐시 경계가 깨졌다"


# ── R-07 프롬프트 외부화 ──────────────────────────────────────────────────────
def test_prompt_files_exist_and_load() -> None:
    from core.agent.generate import _load_prompt, _split_prompt

    for name in ("matrix_enumerate.md", "deviation_generate.md"):
        text = _load_prompt(name)
        assert text.strip()
        system, user = _split_prompt(text)
        assert system and user, f"{name} 에 USER 구분자가 없다"


def test_no_prompt_literals_in_generate_py() -> None:
    """`generate.py` 에 5줄 이상 한글 리터럴이 없어야 한다(docstring 제외)."""
    source = _GENERATE_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstring_nodes = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    offenders = [
        node.value[:60]
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstring_nodes
        and node.value.count("\n") >= 4
        and any("가" <= ch <= "힣" for ch in node.value)
    ]
    assert not offenders, f"프롬프트가 코드에 박혀 있다: {offenders}"


# ── 범위 밖임을 명시하는 시험 ─────────────────────────────────────────────────
def test_fabricated_safeguards_pass_through() -> None:
    """노드 메타에 안전장치가 없는데 모델이 채워 넣으면 **지금은 통과시킨다**.

    프롬프트로만 억제하고 코드로 막지 않는다. 이 판정은 FR-06(self-verification) 소관이며,
    이 시험은 그 경계를 문서화하기 위해 존재한다. FR-06 구현 시 이 시험은 뒤집혀야 한다.
    """
    generator, _ = _generator(extra_cell_field={"safeguards_before": ["존재하지 않는 인터락"]})
    records = generator.generate(N1_META)
    assert records[0].safeguards_before == ["존재하지 않는 인터락"]
    assert N1_META.safeguards == []


# ── 실호출 시험 — T-07 / T-08 (지시문 E-2) ────────────────────────────────────
# `pytest -m live` 로만 돈다. 노드 1건 생성 = converse 8회(파라미터 열거 1 + 가이드워드 7)다.
_G1_RECALL_THRESHOLD = 0.5
_T07_LATENCY_BUDGET_S = 60.0

# recall 규칙은 tools/_replay.py 가 정본이다(FR-10 H-01 — 캡처 도구와 같은 함수를 쓴다).
_recall_n1 = recall_n1


def _live_generator() -> HazopGenerator:
    """실 클라이언트 기반 생성기. 설정·자격증명이 없으면 skip 한다."""
    try:
        config = load_model_config()
    except ConfigValidationError as exc:
        pytest.skip(f"config/models.yaml 미완성: {exc}")
    if config.provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY 없음")
    return HazopGenerator(get_bedrock_client(), load_generator_config())


def _log_comparison(label: str, result: dict[str, Any]) -> None:
    """골드 8건 × 생성 결과 대조표. 미달일 때 원인(가이드워드 vs 파라미터)을 가르기 위한 것."""
    _LOG.info("[%s] recall=%.3f (%d/%d)", label, result["recall"], result["matched"], result["total"])
    _LOG.info("[%s] 생성된 (가이드워드, 파라미터): %s", label, result["produced"])
    for row in result["rows"]:
        if row["matched"]:
            verdict = "일치"
        elif not row["guideword_seen"]:
            verdict = "가이드워드 자체가 생성 안 됨"
        elif not row["parameter_seen"]:
            verdict = "파라미터 어휘 불일치"
        else:
            verdict = "가이드워드·파라미터 각각 존재하나 조합이 없음"
        _LOG.info("  %-11s %-6s → %s", row["guideword"], row["parameter"], verdict)


@pytest.mark.live
def test_generate_live_n1() -> None:
    """T-07 실호출 스모크 — N1 1회 생성. 지연·레코드 수·스키마 100% 를 단언한다 (R-09).

    단언은 전부 **로그를 남긴 뒤** 실행한다. 지연 초과로 실패하더라도 토큰·비용·recall 이
    출력에 남아야 원인을 판정할 수 있기 때문이다(지시문 E-2: 초과 시 재실행 금지).
    """
    generator = _live_generator()
    started = time.perf_counter()
    records = generator.generate(N1_META)
    elapsed = time.perf_counter() - started

    invalid = [r for r in records if list(Draft7Validator(_DEVIATION_SCHEMA).iter_errors([r.model_dump()]))]
    gold = [g for g in json.loads(_TUNE_PATH.read_text(encoding="utf-8")) if g["node"] == "N1"]
    result = _recall_n1(records, gold)

    _LOG.info(
        "[T-07] records=%d latency_s=%.1f cost_usd=%.4f cells=%d/%d review_gw=%s",
        len(records), elapsed, generator.total_cost_usd,
        generator.judged_cells, generator.expected_cells, generator.review_guidewords,
    )
    _log_comparison("T-07", result)

    assert records, "레코드가 0건이다"
    assert not invalid, f"스키마 위반 {len(invalid)}건 — 100% 통과가 아니다"
    assert elapsed <= _T07_LATENCY_BUDGET_S, (
        f"노드 지연 {elapsed:.1f}s > {_T07_LATENCY_BUDGET_S}s — 노드 1건은 converse "
        f"{1 + len(_select_guidewords(N1_META))}회(열거 1 + 가이드워드 {len(_select_guidewords(N1_META))})를 "
        "순차 호출한다. 원인은 호출 수 또는 max_tokens 다."
    )


@pytest.mark.live
def test_recall_live_n1_x3() -> None:
    """T-08 G1 킬체크 — 프롬프트 수정 없이 N1 을 3회 생성해 recall 평균·분산을 본다.

    판정을 단언으로 박는다. 표만 출력하면 미달이 눈에 띄지 않은 채 남기 때문이다.
    """
    runs: list[dict[str, Any]] = []
    for attempt in range(1, 4):
        generator = _live_generator()
        started = time.perf_counter()
        records = generator.generate(N1_META)
        elapsed = time.perf_counter() - started
        gold = [g for g in json.loads(_TUNE_PATH.read_text(encoding="utf-8")) if g["node"] == "N1"]
        result = _recall_n1(records, gold)
        result.update(
            {"attempt": attempt, "latency_s": elapsed,
             "cost_usd": generator.total_cost_usd, "records": len(records)}
        )
        runs.append(result)
        _log_comparison(f"T-08 run{attempt}", result)

    recalls = [r["recall"] for r in runs]
    mean = sum(recalls) / len(recalls)
    _LOG.info("[T-08] === 회차별 요약 ===")
    for r in runs:
        _LOG.info(
            "  run%d recall=%.3f (%d/%d) records=%d cost_usd=%.4f latency_s=%.1f",
            r["attempt"], r["recall"], r["matched"], r["total"],
            r["records"], r["cost_usd"], r["latency_s"],
        )
    _LOG.info("[T-08] recall 평균=%.3f 최소=%.3f 최대=%.3f", mean, min(recalls), max(recalls))

    assert mean >= _G1_RECALL_THRESHOLD, (
        f"G1 미달 — recall 평균 {mean:.3f} < {_G1_RECALL_THRESHOLD}. "
        "프롬프트를 고치지 말고 위 대조표로 원인을 보고할 것(지시문 E-2)."
    )
