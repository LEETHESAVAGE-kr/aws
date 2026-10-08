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


# ── 기존 안전장치 전달·정규화 (지시문 M-01, 실무자평가 P-1·P-6·P-9) ────────────
P1_META = NodeMeta(
    node="P1",
    substance="프로판",
    phase="liquid",
    P_kPag=700,
    T_degC=25,
    equipment=["LPG 저장탱크", "출하 펌프", "로딩암"],
    safeguards=["안전밸브", "긴급차단밸브(ESV)", "가스누출감지기"],
)
#: 수정 전(900f974) `deviation_generate.md` 시스템 블록의 sha256. 노드별 값이 시스템으로 새면 캐시가 깨진다(R-08).
_SYSTEM_SHA256 = "35210ae713a27f2593b6f754fd7f63cfea3052d54c39bf7d2b364e3cd34189ee"


def _safeguards_of(generated: list[str], meta: NodeMeta = P1_META) -> list[str]:
    generator, _ = _generator(extra_cell_field={"safeguards_before": generated})
    return generator.generate(meta)[0].safeguards_before


def test_fabricated_safeguards_are_dropped_when_input_is_empty() -> None:
    """입력 안전장치가 없으면 모델이 무엇을 채워도 빈 배열(M-01 (e)). 예전엔 통과시켰다."""
    assert _safeguards_of(["존재하지 않는 인터락"], N1_META) == []


def test_batch_user_turn_carries_node_conditions_and_safeguards() -> None:
    """(a) 판정 호출 사용자 메시지에 safeguards·P·T·phase 가 들어간다 — 시스템에는 없다."""
    generator, client = _generator()
    generator.generate(P1_META)
    for call in client.calls[1:]:
        user = call["messages"][0].content
        for text in ("안전밸브", "긴급차단밸브(ESV)", "가스누출감지기", "700", "25", "liquid"):
            assert text in user, f"사용자 턴에 {text} 없음"
        assert "긴급차단밸브(ESV)" not in call["system"]


def test_batch_user_turn_marks_missing_values() -> None:
    generator, client = _generator()
    generator.generate(N1_META)
    user = client.calls[1]["messages"][0].content
    assert "압력(kPag): 미상" in user and "기존 안전장치: 없음" in user


def test_system_prompt_bytes_unchanged() -> None:
    """(f) 시스템 블록(캐시 프리픽스)이 수정 전과 바이트 동일."""
    import hashlib

    from core.agent.generate import _load_prompt, _split_prompt

    system, _ = _split_prompt(_load_prompt("deviation_generate.md"))
    assert hashlib.sha256(system.encode("utf-8")).hexdigest() == _SYSTEM_SHA256


def test_safeguard_exact_match_kept() -> None:
    """(b) 정확 일치는 그대로, 순서는 입력 순서."""
    assert _safeguards_of(["가스누출감지기", "안전밸브"]) == ["안전밸브", "가스누출감지기"]


@pytest.mark.parametrize("generated", ["ESV", "ESV(긴급차단밸브)", "esv", "긴급차단밸브"])
def test_safeguard_token_overlap_maps_to_input_original(generated: str) -> None:
    """(c) 토큰 겹침 → 입력 원문. "ESV(긴급차단밸브)" 는 부분문자열 비교로는 안 잡힌다."""
    assert _safeguards_of([generated]) == ["긴급차단밸브(ESV)"]


def test_safeguard_duplicates_collapse() -> None:
    assert _safeguards_of(["ESV", "ESV(긴급차단밸브)", "긴급차단밸브(ESV)"]) == ["긴급차단밸브(ESV)"]


def test_safeguard_overlapping_two_inputs_adopts_both() -> None:
    """한 항목이 입력 둘과 겹치면 둘 다 채택한다."""
    assert _safeguards_of(["안전밸브·ESV"]) == ["안전밸브", "긴급차단밸브(ESV)"]


@pytest.mark.parametrize("generated", ["gas detector", "체크밸브", "누출감지기"])
def test_safeguard_unrelated_is_dropped_with_warning(
    generated: str, caplog: pytest.LogCaptureFixture
) -> None:
    """(d) 어느 입력과도 토큰이 안 겹치면 버리고 WARNING 1줄.

    "체크밸브" ↔ "긴급차단밸브"·"안전밸브": 토큰이 통째로 달라 붙지 않는다.
    "누출감지기" ↔ "가스누출감지기": 같은 장치일 수 있지만 토큰 규칙상 버려진다 — 규칙의 한계를 고정해 둔다.
    """
    with caplog.at_level(logging.WARNING, logger="core.agent.generate"):
        assert _safeguards_of([generated]) == []
    dropped = [r for r in caplog.records if "safeguards_before" in r.getMessage()]
    assert dropped and generated in dropped[0].getMessage()
    assert "gw=" in dropped[0].getMessage() and "param=" in dropped[0].getMessage()


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


# ── R-10 가이드워드 판정 병렬화 (지시문 O-1) ──────────────────────────────────
import threading  # noqa: E402

from core.agent.generate import GeneratorConfig  # noqa: E402


def _parallel_factory(*, broken_guideword: str | None = None, delay_s: float = 0.02):
    """앞 가이드워드일수록 늦게 끝나는 응답(완료 순서 ≠ 목록 순서)과 가이드워드별 다른 비용.

    동시에 떠 있는 호출 수의 최댓값도 잰다 — 병렬이 실제로 일어났는지의 증거.
    """
    lock = threading.Lock()
    state = {"inflight": 0, "max_inflight": 0}
    base = _factory(broken_guideword=broken_guideword)

    def make(system: str, messages: list[Message], **kwargs: Any) -> ConverseResponse:
        with lock:
            state["inflight"] += 1
            state["max_inflight"] = max(state["max_inflight"], state["inflight"])
        try:
            response = base(system=system, messages=messages, **kwargs)
            if _is_enumeration(system):
                response.cost_usd = 0.5
                return response
            user = messages[0].content
            assert isinstance(user, str)
            index = STANDARD_GUIDEWORDS.index(_guideword_of(user))
            time.sleep(delay_s * (len(STANDARD_GUIDEWORDS) - index))
            response.cost_usd = 2.0 ** -(index + 2)  # 이진 분수 — 합산 순서와 무관하게 정확히 더해진다
            return response
        finally:
            with lock:
                state["inflight"] -= 1

    return make, state


def _run_parallel(parallel_calls: int, **kwargs: Any):
    make, state = _parallel_factory(**kwargs)
    client = MockBedrockClient(response_factory=make)
    generator = HazopGenerator(client, GeneratorConfig(parallel_calls=parallel_calls))
    records = generator.generate(N1_META)
    return generator, client, records, state


def test_parallel_preserves_guideword_order_and_sequential_ids() -> None:
    _, _, records, state = _run_parallel(4)
    assert state["max_inflight"] > 1, "parallel_calls=4 인데 호출이 한 번도 겹치지 않았다(순차로 돌았다)"
    order = list(dict.fromkeys(r.guideword for r in records))
    assert order == STANDARD_GUIDEWORDS
    assert [r.id for r in records] == [f"n1-{i:03d}" for i in range(1, len(records) + 1)]


def test_parallel_and_sequential_results_are_byte_identical() -> None:
    seq, _, seq_records, seq_state = _run_parallel(1, delay_s=0.0)
    par, _, par_records, _ = _run_parallel(4)
    assert seq_state["max_inflight"] == 1
    dump = lambda rs: json.dumps([r.model_dump() for r in rs], ensure_ascii=False)  # noqa: E731
    assert dump(par_records) == dump(seq_records)
    assert (par.expected_cells, par.judged_cells) == (seq.expected_cells, seq.judged_cells)
    assert par.total_cost_usd == seq.total_cost_usd
    assert par.review_guidewords == seq.review_guidewords == []


def test_parallel_broken_row_is_isolated_to_review() -> None:
    """스키마 위반 2회(재시도 포함) → 그 가이드워드만 review, 나머지 6종 정상, 호출 = 열거 1 + 7 + 재시도 1."""
    generator, client, records, _ = _run_parallel(4, broken_guideword="Reverse")
    assert generator.review_guidewords == ["Reverse"]
    assert list(dict.fromkeys(r.guideword for r in records)) == [
        g for g in STANDARD_GUIDEWORDS if g != "Reverse"
    ]
    assert len(client.calls) == 1 + len(STANDARD_GUIDEWORDS) + 1


def test_parallel_cost_equals_sum_of_calls() -> None:
    """합계 = 열거 0.5 + Σ 2^-(i+2). 공유 변수 경쟁이 있으면 일부가 사라진다."""
    generator, client, _, _ = _run_parallel(4)
    expected = 0.5 + sum(2.0 ** -(i + 2) for i in range(len(STANDARD_GUIDEWORDS)))
    assert generator.total_cost_usd == expected
    assert len(client.calls) == 1 + len(STANDARD_GUIDEWORDS)


def test_parallel_exception_in_one_row_degrades_only_that_row() -> None:
    make, _ = _parallel_factory(delay_s=0.0)

    def flaky(system: str, messages: list[Message], **kwargs: Any) -> ConverseResponse:
        user = messages[0].content
        if not _is_enumeration(system) and isinstance(user, str) and _guideword_of(user) == "Less":
            raise TimeoutError("네트워크")
        return make(system=system, messages=messages, **kwargs)

    generator = HazopGenerator(
        MockBedrockClient(response_factory=flaky), GeneratorConfig(parallel_calls=4)
    )
    records = generator.generate(N1_META)
    assert generator.review_guidewords == ["Less"]
    assert "Less" not in {r.guideword for r in records} and len({r.guideword for r in records}) == 6


def test_parallel_calls_config_default_and_validation(tmp_path: Path) -> None:
    assert load_model_config().parallel_calls == 7  # config/models.yaml (X-G7 10/8 실측으로 4 → 7)
    assert load_generator_config().parallel_calls == 7
    assert GeneratorConfig().parallel_calls == 1  # 직접 생성은 순차(응답 목록 mock 호환)
    base = (_ROOT / "config" / "models.yaml").read_text(encoding="utf-8")
    absent = tmp_path / "absent.yaml"
    absent.write_text(base.replace("  parallel_calls: 7", "  # (없음)"), encoding="utf-8")
    assert load_model_config(absent).parallel_calls == 4  # 필드 없는 옛 yaml 호환
    for bad in ("0", "true", "2.5"):
        broken = tmp_path / f"bad_{bad}.yaml"
        broken.write_text(base.replace("  parallel_calls: 7", f"  parallel_calls: {bad}"), encoding="utf-8")
        with pytest.raises(ConfigValidationError, match="parallel_calls"):
            load_model_config(broken)


def test_provenance_line_marks_parallel_capture() -> None:
    from apps.web import service

    meta = {"source": "live", "captured_at": "2026-09-29T08:00:00+00:00", "model_id": "m", "cost_usd": 1.0}
    assert "병렬" not in service.provenance_line(service.Result(meta=meta))
    assert "병렬" not in service.provenance_line(service.Result(meta={**meta, "parallel_calls": 1}))
    assert " · 병렬 4" in service.provenance_line(service.Result(meta={**meta, "parallel_calls": 4}))


def test_generate_batch_does_not_mutate_self() -> None:
    """스레드에서 도는 `_generate_batch` 는 `self.x = …`·`self.x += …`·`self.x.append(…)` 를 하지 않는다.

    공유 float 의 `+=` 경쟁은 GIL 아래서 거의 재현되지 않아 합계 시험만으로는 못 잡는다 — 구조로 고정한다.
    """
    tree = ast.parse(_GENERATE_PY.read_text(encoding="utf-8"))
    func = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_generate_batch"
    )
    offenders: list[str] = []
    for node in ast.walk(func):
        targets = (
            node.targets if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AugAssign | ast.AnnAssign) else []
        )
        for target in targets:
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                offenders.append(f"L{node.lineno} self.{target.attr}")
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"append", "extend", "insert"}
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "self"
        ):
            offenders.append(f"L{node.lineno} self.{node.func.value.attr}.{node.func.attr}")
    assert not offenders, offenders


# ── R-11 진행 알림 · generate_quick (본선 T-10·T-11) ─────────────────────────────
def _dump(records: list[DeviationRecord]) -> str:
    return json.dumps([r.model_dump() for r in records], ensure_ascii=False)


def _run_with_progress(parallel_calls: int, callback: Any = None):
    make, _ = _parallel_factory(delay_s=0.01)
    generator = HazopGenerator(MockBedrockClient(response_factory=make), GeneratorConfig(parallel_calls=parallel_calls))
    events: list[tuple[str, dict[str, Any], int]] = []

    def record(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload, threading.get_ident()))
        if callback is not None:
            callback(event, payload)

    return generator, generator.generate(N1_META, on_progress=record), events


def test_progress_events_arrive_in_completion_order_and_final_records_unchanged() -> None:
    baseline = _run_parallel(1, delay_s=0.0)[2]  # 콜백 없는 순차 실행
    for workers in (1, 4):
        generator, records, events = _run_with_progress(workers)
        assert _dump(records) == _dump(baseline)  # AC-11-1 — 콜백·병렬 무관
        assert events[0][0] == "parameters" and events[0][1]["parameters"] == generator.parameters
        gw_events = [p for e, p, _ in events if e == "guideword"]
        assert [p["done"] for p in gw_events] == list(range(1, len(STANDARD_GUIDEWORDS) + 1))
        assert {p["total"] for p in gw_events} == {len(STANDARD_GUIDEWORDS)}
        assert sorted(p["guideword"] for p in gw_events) == sorted(STANDARD_GUIDEWORDS)
        assert len(gw_events[-1]["records"]) == len(records)  # 마지막 알림 = 전부
        sizes = [len(p["records"]) for p in gw_events]
        assert sizes == sorted(sizes)  # 중간 표는 줄지 않는다
        if workers == 4:  # 앞 가이드워드가 늦게 끝나도록 만든 응답 — 완료 순서로 알린다
            assert gw_events[0]["guideword"] != STANDARD_GUIDEWORDS[0]


def test_progress_callback_runs_on_calling_thread() -> None:
    _, _, events = _run_with_progress(4)
    assert {tid for _, _, tid in events} == {threading.get_ident()}  # AC-11-2


def test_progress_callback_exception_does_not_stop_generation(caplog: pytest.LogCaptureFixture) -> None:
    def boom(*_: Any) -> None:
        raise RuntimeError("화면 오류")

    _, baseline, _ = _run_with_progress(4)
    with caplog.at_level(logging.WARNING):
        generator, records, _ = _run_with_progress(4, callback=boom)
    assert _dump(records) == _dump(baseline)  # AC-11-3
    assert "진행 알림 콜백 예외" in caplog.text


def test_progress_does_not_change_generator_counts() -> None:
    plain, _, _, _ = _run_parallel(4)
    noisy, _, _ = _run_with_progress(4)
    assert (noisy.judged_cells, noisy.expected_cells, noisy.total_cost_usd) == (
        plain.judged_cells, plain.expected_cells, plain.total_cost_usd,
    )  # AC-11-4


def test_generate_quick_two_calls_and_events() -> None:
    client = MockBedrockClient(response_factory=_factory())
    generator = HazopGenerator(client, GeneratorConfig(parallel_calls=4))
    events: list[str] = []
    records = generator.generate_quick(N1_META, "More", on_progress=lambda e, _: events.append(e))
    assert len(client.calls) == 2 and events == ["parameters", "guideword"]
    assert records and {r.guideword for r in records} == {"More"}
    assert generator.expected_cells == len(generator.parameters) == generator.judged_cells


def test_generate_quick_skips_judgement_when_enumeration_fails() -> None:
    client = MockBedrockClient(response_factory=lambda **_: ConverseResponse(content=None))
    generator = HazopGenerator(client, GeneratorConfig(parallel_calls=4))
    assert generator.generate_quick(N1_META, "More") == []
    assert generator.parameters == []
    assert client.calls and all(_is_enumeration(c["system"]) for c in client.calls)  # 열거(+재시도)뿐, 판정 0회



# ── R-12 공개 HAZOP 예시 (본선 T-13) ──────────────────────────────────────────
from core.agent.generate import (  # noqa: E402
    _PARAM_EXAMPLES_PATH,
    _split_prompt,
    render_param_examples,
)
from tools._replay import normalize_parameter  # noqa: E402


def _enumeration_system(enumerate_examples: bool) -> str:
    client = MockBedrockClient(response_factory=_factory())
    HazopGenerator(client, GeneratorConfig(enumerate_examples=enumerate_examples))._enumerate_parameters(N1_META)
    return str(client.calls[0]["system"])


def test_examples_off_keeps_enumeration_prompt_bytes() -> None:
    original = _split_prompt((_ROOT / "core" / "agent" / "prompts" / "matrix_enumerate.md").read_text(encoding="utf-8"))[0]
    assert _enumeration_system(False) == original  # AC-12-1
    on = _enumeration_system(True)
    assert on.startswith(original) and on.endswith(render_param_examples())


def test_examples_never_contain_holdout_gold_parameters() -> None:
    gold = json.loads((_ROOT / "data" / "gold" / "hazop_nh3_eval.json").read_text(encoding="utf-8"))
    blocked = {normalize_parameter(g["parameter"]) for g in gold}
    data = json.loads(_PARAM_EXAMPLES_PATH.read_text(encoding="utf-8"))
    names = [n for ex in data["examples"] for n in ex["parameters"]]
    assert names and not {normalize_parameter(n) for n in names} & blocked  # AC-12-2


def test_examples_carry_source_and_license_without_prose() -> None:
    data = json.loads(_PARAM_EXAMPLES_PATH.read_text(encoding="utf-8"))
    for ex in data["examples"]:
        assert ex["source"].count("http") == 1 and ex["license"]  # AC-12-3
        assert all(len(n.split()) <= 4 for n in ex["parameters"])  # 이름만 — 프롬프트 제약과 같은 4어절
