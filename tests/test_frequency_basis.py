"""질문봉쇄 Q-03 — 빈도 근거(`frequency_basis`) 필수·안전장치 미상 고정 문구·분포 막대·자동 문구, Q-08 인용 행 수."""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any

import pytest
from jsonschema import Draft7Validator
from openpyxl import load_workbook

from apps.web import service
from apps.web.replay import Result
from core.agent import HazopGenerator, NodeMeta
from core.agent.generate import (
    FREQUENCY_BASIS_EMPTY,
    FREQUENCY_BASIS_UNKNOWN,
    GeneratorConfig,
    batch_schema,
)
from core.criteria import GOLD_CRITERIA, OFFICIAL_CRITERIA, load_criteria
from core.export import export_all
from core.llm import ConverseResponse, Message, MockBedrockClient

if TYPE_CHECKING:
    from pathlib import Path

_PARAMS = ["유량", "압력", "온도", "준위", "조성", "상"]
_GUARDED = NodeMeta(node="X1", substance="수소", phase="gas", equipment=["압축기", "저장용기"],
                    safeguards=["안전밸브", "긴급차단밸브"])
_UNKNOWN = NodeMeta(node="X1", substance="수소", phase="gas", equipment=["압축기", "저장용기"])


def _factory(basis: str, seen: list[dict[str, Any]]) -> Any:
    def make(system: str, messages: list[Message], **kwargs: Any) -> ConverseResponse:
        seen.append({"system": system, "schema": kwargs.get("response_schema")})
        if "파라미터 축" in system:
            return ConverseResponse(content=json.dumps({"parameters": [{"name": n, "rationale": "r"} for n in _PARAMS]}))
        gw = next(g for g in ("No", "More", "Less", "Reverse", "Other than", "Part of", "As well as")
                  if f"\n{g} —" in str(messages[0].content))
        cells = [{"parameter": p, "applicable": True, "deviation": f"{p} 이탈", "causes": ["c"], "consequences": ["r"],
                  "safeguards_before": [], "S": 3, "F": 2, "recommendations": ["k"], "evidence": [],
                  "confidence": "inferred"} for p in _PARAMS]
        if "frequency_basis" in kwargs["response_schema"]["properties"]["cells"]["items"]["required"]:
            cells = [{**c, "frequency_basis": basis} for c in cells]
        return ConverseResponse(content=json.dumps({"guideword": gw, "cells": cells}, ensure_ascii=False))

    return make


def _run(meta: NodeMeta, basis: str, on: bool = True, criteria_id: str = OFFICIAL_CRITERIA) -> tuple[list[Any], list[Any]]:
    seen: list[dict[str, Any]] = []
    gen = HazopGenerator(MockBedrockClient(response_factory=_factory(basis, seen)),
                         GeneratorConfig(frequency_basis=on), criteria_id=criteria_id)
    return gen.generate(meta), seen


def _judge_calls(seen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in seen if "파라미터 축" not in c["system"]]


def test_schema_requires_basis_when_on() -> None:
    """빈도 근거가 빠진 셀은 판정 스키마 검증에서 떨어진다(필수)."""
    schema = batch_schema(load_criteria(OFFICIAL_CRITERIA), frequency_basis=True)
    cell = {"parameter": "압력", "applicable": True, "deviation": "d", "S": 3, "F": 2}
    assert not list(Draft7Validator(schema).iter_errors({"guideword": "More", "cells": [{**cell, "frequency_basis": "안전밸브"}]}))
    assert list(Draft7Validator(schema).iter_errors({"guideword": "More", "cells": [cell]}))
    assert "frequency_basis" not in json.dumps(batch_schema(load_criteria(OFFICIAL_CRITERIA)))  # 끄면 그대로


def test_basis_rule_reaches_prompt_and_records() -> None:
    records, seen = _run(_GUARDED, "긴급차단밸브가 원인을 끊어 F2")
    judge = _judge_calls(seen)
    assert judge and all("`frequency_basis`" in c["system"] for c in judge)
    assert all("frequency_basis" in c["schema"]["properties"]["cells"]["items"]["required"] for c in judge)
    assert records and {r.frequency_basis for r in records} == {"긴급차단밸브가 원인을 끊어 F2"}
    assert all("frequency_basis" in r.model_dump() for r in records)


def test_unknown_safeguards_get_fixed_phrase_not_model_text() -> None:
    """입력에 안전장치가 없으면 모델이 무엇을 적든 고정 문구 — 지어낸 근거를 남기지 않는다."""
    records, _ = _run(_UNKNOWN, "가스감지기로 F1")
    assert {r.frequency_basis for r in records} == {FREQUENCY_BASIS_UNKNOWN}


def test_empty_basis_is_marked_not_blank() -> None:
    records, _ = _run(_GUARDED, "  ")
    assert {r.frequency_basis for r in records} == {FREQUENCY_BASIS_EMPTY}


@pytest.mark.parametrize(("on", "criteria_id"), [(False, OFFICIAL_CRITERIA), (True, GOLD_CRITERIA)])
def test_off_or_gold_criteria_is_byte_identical(on: bool, criteria_id: str) -> None:
    records, seen = _run(_GUARDED, "x", on=on, criteria_id=criteria_id)
    assert records and all("`frequency_basis`" not in c["system"] for c in seen)
    assert all(r.frequency_basis is None and "frequency_basis" not in r.model_dump() for r in records)


def test_xlsx_gets_basis_column_only_when_present(tmp_path: Path) -> None:
    with_basis, _ = _run(_GUARDED, "안전밸브")
    without, _ = _run(_GUARDED, "안전밸브", on=False)
    for records, expect in ((with_basis, True), (without, False)):
        out = tmp_path / str(expect)
        wb = load_workbook(io.BytesIO(export_all(records, out)["xlsx"].read_bytes()))
        head = [c.value for c in wb["HAZOP워크시트"][1]]
        assert (head[-1] == "빈도 근거") is expect and len(head) == (13 if expect else 12)
        if expect:
            assert wb["HAZOP워크시트"]["M2"].value == "안전밸브"


def test_screen_table_has_basis_column() -> None:
    records, _ = _run(_GUARDED, "안전밸브")
    result = Result(meta={"source": "live-run", "criteria_id": OFFICIAL_CRITERIA}, records=records)
    table = service.worksheet_table(result)
    assert table[0][service.BASIS_COLUMN] == "안전밸브"
    assert service.review_column_order(table)[-1] == service.BASIS_COLUMN  # 맨 뒤 — 기본으로 눈에 덜 띄게


def _result(fs: list[int]) -> Result:
    records, _ = _run(_GUARDED, "안전밸브")
    rows = [r.model_copy(update={"F": f}) for r, f in zip(records, fs, strict=False)]
    return Result(meta={"source": "live-run", "criteria_id": OFFICIAL_CRITERIA}, records=rows)


def test_concentration_warning_above_limit_only() -> None:
    crowded = _result([2] * 8 + [1, 3])  # 80%
    spread = _result([2] * 7 + [1, 3, 3])  # 70% — 기준 이하
    assert service.f_concentration(crowded) == pytest.approx(0.8)
    # 입력에 안전장치가 있는데도 몰림 → '없어서'가 아니라 IPL 적격 장치가 적다는 문구(지시문 S-4-4)
    assert service.concentration_warning(crowded) == service.CONCENTRATION_WARNING_IPL
    assert service.concentration_warning(spread) is None
    html = service.distribution_html(crowded)
    assert html and "빈도" in html and "중(2) 8" in html and "심각도" in html and "위험도" in html
    # 10/15 개편: 판정 구간 행 수의 합 = 등급을 매긴 행 수, 머리말은 가장 높은 판정부터 말한다
    bands = service.risk_band_counts(crowded)
    assert sum(n for _, _, n in bands) == 10 and bands[0][0] == "위험작업 불허"


def test_evidence_line_counts_cited_rows() -> None:
    result = _result([2] * 10)
    assert service.evidence_line(result) == f"법령·MSDS 인용 0/{len(result.records)}행"
    assert service.evidence_line(result) in service.summary_line(result)
