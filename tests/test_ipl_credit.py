"""지시문 S — IPL 빈도 크레딧: 분류표(S-1)·판정 프롬프트·스키마(S-2)·검증기 산수(S-3)·화면(S-4)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from jsonschema import Draft7Validator

from core import ipl
from core.agent import HazopGenerator, NodeMeta
from core.agent.generate import GeneratorConfig, batch_schema
from core.criteria import GOLD_CRITERIA, OFFICIAL_CRITERIA, all_criteria, load_criteria
from core.llm import ConverseResponse, Message, MockBedrockClient

_PARAMS = ["유량", "압력", "온도", "준위", "조성", "상"]
_GUARDED = NodeMeta(node="X1", substance="프로판", phase="liquid", equipment=["저장탱크", "출하 펌프"],
                    safeguards=["안전밸브", "긴급차단밸브(ESV)", "가스누출감지기"])
#: 지시문 S-5-3 — D1 N2 의 5종. 분류표상 전부 감지만·절차라 크레딧 0 이 예상된다.
_D1_N2 = ["계류 감시(육안)", "육안 확인", "연 1회 수압시험(명목)", "항만 VTS(간접)", "예냉 절차"]


# ── S-1 분류표 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("name", "cls", "eligible"),
    [
        ("안전밸브", "prevention", True),
        ("긴급차단밸브(ESV)", "prevention", True),
        ("고압 인터록", "prevention", True),
        ("역류방지밸브", "prevention", True),
        ("브레이크어웨이 커플링", "prevention", True),
        ("가스누출감지기", "detection_only", False),
        ("고압 경보(설정 95 MPa)", "detection_only", False),
        ("CCTV", "detection_only", False),
        ("긴급차단밸브 연동 가스감지기", "prevention", True),  # 차단 연동이면 예방으로 재분류
        ("방류벽", "mitigation", False),
        ("살수설비", "mitigation", False),
        ("작업 절차서", "procedural", False),
        ("풍선", "unknown", False),  # 분류표에 없으면 자동 인정하지 않는다
    ],
)
def test_classify(name: str, cls: str, eligible: bool) -> None:
    got = ipl.classify(name)
    assert (got.cls, got.eligible) == (cls, eligible)


def test_d1_n2_safeguards_earn_no_credit() -> None:
    """S-5-3 예상의 근거 — D1 N2 5종은 하나도 IPL 적격이 아니다."""
    assert [ipl.classify(n).eligible for n in _D1_N2] == [False] * 5
    assert {ipl.classify(n).cls for n in _D1_N2} == {"detection_only", "procedural"}


def test_rules_and_sources_are_in_the_file() -> None:
    data = ipl.table()
    assert data["rules"]["credit_per_ipl"] == 1 and data["rules"]["max_credits"] == 2
    assert data["rules"]["min_frequency"] == 1 and data["rules"]["severity_credit"] is False
    assert "강도는 현재 안전조치를 고려하지 않는다" in data["rules"]["severity_note"]
    for key in ("id", "name", "issuer", "doc", "locator", "url", "retrieved_at", "license", "notes"):
        assert data[key], key
    assert any("사업장 LOPA 가 있으면 그것이 우선한다" in n for n in data["notes"])
    assert {i["class"] for i in data["safeguard_classes"]} == {"prevention", "detection_only", "mitigation", "procedural"}
    assert all(i["reason"] for i in data["safeguard_classes"])


@pytest.mark.parametrize(("base", "n", "expected"), [(3, 0, 3), (3, 1, 2), (3, 2, 1), (3, 5, 1), (2, 2, 1), (1, 1, 1)])
def test_expected_frequency(base: int, n: int, expected: int) -> None:
    assert ipl.expected_frequency(base, n) == expected


def test_ipl_file_is_not_a_rating_criteria() -> None:
    assert "ipl_credit" not in [c.id for c in all_criteria()]


# ── S-2 판정 프롬프트·스키마 ──────────────────────────────────────────────────
def _factory(seen: list[dict[str, Any]], credited: list[dict[str, Any]], base: int = 3, f: int = 1) -> Any:
    def make(system: str, messages: list[Message], **kwargs: Any) -> ConverseResponse:
        seen.append({"system": system, "schema": kwargs.get("response_schema")})
        if "파라미터 축" in system:
            return ConverseResponse(content=json.dumps({"parameters": [{"name": n, "rationale": "r"} for n in _PARAMS]}))
        gw = next(g for g in ("No", "More", "Less", "Reverse", "Other than", "Part of", "As well as")
                  if f"\n{g} —" in str(messages[0].content))
        required = kwargs["response_schema"]["properties"]["cells"]["items"]["required"]
        cells = []
        for p in _PARAMS:
            cell = {"parameter": p, "applicable": True, "deviation": f"{p} 이탈", "causes": ["c"], "consequences": ["r"],
                    "safeguards_before": [], "S": 3, "F": f, "recommendations": ["k"], "evidence": [],
                    "confidence": "inferred"}
            if "frequency_basis" in required:
                cell["frequency_basis"] = "안전밸브·ESV 인정, 감지기는 감지만"
            if "ipl_credited" in required:
                cell |= {"frequency_base": base, "ipl_credited": credited}
            cells.append(cell)
        return ConverseResponse(content=json.dumps({"guideword": gw, "cells": cells}, ensure_ascii=False))

    return make


_TWO = [{"name": "안전밸브", "class": "prevention", "applies": True},
        {"name": "긴급차단밸브(ESV)", "class": "prevention", "applies": True}]


def _run(on: bool = True, criteria_id: str = OFFICIAL_CRITERIA, credited: list[dict[str, Any]] | None = None,
         basis: bool = True, base: int = 3, f: int = 1) -> tuple[list[Any], list[dict[str, Any]]]:
    seen: list[dict[str, Any]] = []
    gen = HazopGenerator(MockBedrockClient(response_factory=_factory(seen, _TWO if credited is None else credited, base, f)),
                         GeneratorConfig(frequency_basis=basis, ipl_credit=on), criteria_id=criteria_id)
    return gen.generate(_GUARDED), [c for c in seen if "파라미터 축" not in c["system"]]


def test_schema_requires_ipl_fields_when_on() -> None:
    schema = batch_schema(load_criteria(OFFICIAL_CRITERIA), frequency_basis=True, ipl_credit=True)
    cell = {"parameter": "압력", "applicable": True, "deviation": "d", "S": 3, "F": 1, "frequency_basis": "x"}
    ok = {**cell, "frequency_base": 3, "ipl_credited": _TWO}
    assert not list(Draft7Validator(schema).iter_errors({"guideword": "More", "cells": [ok]}))
    for drop in ("frequency_base", "ipl_credited"):
        bad = {k: v for k, v in ok.items() if k != drop}
        assert list(Draft7Validator(schema).iter_errors({"guideword": "More", "cells": [bad]})), drop
    over = {**ok, "frequency_base": 4}  # C-C-37 빈도는 3단계
    assert list(Draft7Validator(schema).iter_errors({"guideword": "More", "cells": [over]}))


def test_prompt_block_is_read_from_the_file() -> None:
    """규칙 수치·분류표 문장이 ipl_credit.json 에서 온다 — 파일의 항목마다 라벨·사유가 프롬프트에 있다."""
    records, judge = _run()
    system = judge[0]["system"]
    assert "frequency = max(1, frequency_base − min(2, 인정 수))" in system
    for item in ipl.table()["safeguard_classes"]:
        assert item["label"] in system and item["reason"] in system
    assert "{" not in system.split("## 빈도 크레딧")[1]  # 채우지 않은 자리표시자 없음
    assert all("ipl_credited" in c["schema"]["properties"]["cells"]["items"]["required"] for c in judge)
    assert records and all(r.frequency_base == 3 and len(r.ipl_credited) == 2 and r.F == 1 for r in records)
    dumped = records[0].model_dump()
    assert dumped["ipl_credited"][0] == {"name": "안전밸브", "class": "prevention", "applies": True}


@pytest.mark.parametrize(("on", "criteria_id", "basis"),
                         [(False, OFFICIAL_CRITERIA, True), (True, GOLD_CRITERIA, True), (True, OFFICIAL_CRITERIA, False)])
def test_off_is_byte_identical(on: bool, criteria_id: str, basis: bool) -> None:
    """끄거나(플래그·골드 기준·빈도 근거 꺼짐) 하면 판정 시스템·스키마·레코드가 S 이전과 같다."""
    records, judge = _run(on=on, criteria_id=criteria_id, basis=basis, f=1)
    reference, ref_judge = _run(on=False, criteria_id=criteria_id, basis=basis, f=1)
    assert [c["system"] for c in judge] == [c["system"] for c in ref_judge]
    assert [c["schema"] for c in judge] == [c["schema"] for c in ref_judge]
    assert all("빈도 크레딧" not in c["system"] and "ipl_credited" not in json.dumps(c["schema"]) for c in judge)
    assert [r.model_dump() for r in records] == [r.model_dump() for r in reference]
    assert all("ipl_credited" not in r.model_dump() and "frequency_base" not in r.model_dump() for r in records)


def test_output_schema_takes_the_three_fields_together() -> None:
    from pathlib import Path

    schema = json.loads((Path(__file__).parents[1] / "schemas" / "deviation.schema.json").read_text(encoding="utf-8"))
    records, _ = _run()
    full = records[0].model_dump(mode="json")
    assert not list(Draft7Validator(schema).iter_errors([full]))
    partial = {k: v for k, v in full.items() if k != "frequency_base"}
    assert list(Draft7Validator(schema).iter_errors([partial]))  # 하나만 빠져도 떨어진다
    old = {k: v for k, v in full.items() if k not in ("frequency_base", "ipl_credited")}
    assert not list(Draft7Validator(schema).iter_errors([old]))  # 이 기능 이전 레코드는 그대로 통과


# ── S-3 검증기 산수 규칙 ──────────────────────────────────────────────────────
def _flags(record: Any) -> dict[str, list[str]]:
    from core.agent import verify

    out, summary = verify([record])
    by: dict[str, list[str]] = {}
    for f in summary.flags:
        by.setdefault(f.rule, []).append(f.matched)
    return {"confidence": [out[0].confidence], **by}


def _record(**update: Any) -> Any:
    records, _ = _run()
    return records[0].model_copy(update=update)


def test_clean_credit_is_not_flagged() -> None:
    assert _flags(_record()) == {"confidence": ["inferred"]}


def test_v_ipl_1_arithmetic() -> None:
    got = _flags(_record(F=2))  # 기본 3 − 인정 2 = 1 인데 2
    assert got["confidence"] == ["review"] and got["ipl_arithmetic"][0].startswith("빈도 산수 불일치")
    assert _flags(_record(frequency_base=3, ipl_credited=[], F=3)) == {"confidence": ["inferred"]}


def test_v_ipl_2_not_in_input() -> None:
    got = _flags(_record(ipl_credited=[*_TWO[:1], {"name": "고압 인터록", "class": "prevention", "applies": True}]))
    assert got["confidence"] == ["review"]
    assert got["ipl_not_in_input"] == ["입력에 없는 안전장치 인정 (고압 인터록)"]
    assert "ipl_ineligible" not in got  # 인터록 자체는 적격 — 입력에 없다는 것만 문제


def test_v_ipl_3_ineligible() -> None:
    detector = {"name": "가스누출감지기", "class": "prevention", "applies": True}  # 모델이 예방이라 우겨도
    got = _flags(_record(ipl_credited=[_TWO[0], detector]))
    assert got["confidence"] == ["review"] and got["ipl_ineligible"] == ["IPL 비적격 장치 인정 (가스누출감지기 — 감지만)"]
    declared = _flags(_record(ipl_credited=[_TWO[0], {**_TWO[1], "class": "mitigation"}]))
    assert declared["ipl_ineligible"] == ["IPL 비적격 장치 인정 (긴급차단밸브(ESV) — 완화)"]


def test_records_without_credit_fields_are_untouched() -> None:
    records, _ = _run(on=False)
    assert _flags(records[0]) == {"confidence": ["inferred"]}


# ── S-4 화면 ──────────────────────────────────────────────────────────────────
def _credit_result(credited: list[dict[str, Any]]) -> Any:
    from apps.web.replay import Result

    records, _ = _run(credited=[], f=3)  # 기본 3 · 인정 0 · 반영 3
    first = records[0].model_copy(update={"frequency_base": 3, "ipl_credited": credited,
                                          "F": ipl.expected_frequency(3, len(credited))})
    return Result(meta={"source": "live-run", "criteria_id": OFFICIAL_CRITERIA}, records=[first, *records[1:]])


def test_table_shows_base_to_credited_and_prefix() -> None:
    from apps.web import service

    table = service.worksheet_table(_credit_result(_TWO))
    assert table[0][service.FREQ_SHIFT_COLUMN] == "3→1" and table[1][service.FREQ_SHIFT_COLUMN] == "3"
    assert table[0][service.BASIS_COLUMN].startswith(
        "✓ 안전밸브(예방) · ✓ 긴급차단밸브(ESV)(예방) · – 가스누출감지기(감지만) — ")
    assert table[1][service.BASIS_COLUMN].startswith("– 안전밸브(예방) · – 긴급차단밸브(ESV)(예방) · – 가스누출감지기(감지만) — ")
    order = service.review_column_order(table)
    assert order.index(service.FREQ_SHIFT_COLUMN) + 1 == order.index("F(1-5)")  # 편집 표: 읽기 전용 표시 + 반영 후 숫자
    assert "F(1-5)" not in service.read_only_order(order)  # 읽기 보기: 한 열
    edited = service.with_edits(table, {0: {"F(1-5)": 2}})
    assert edited[0][service.FREQ_SHIFT_COLUMN] == "3→2"


def test_summary_and_warning_lines() -> None:
    from apps.web import service

    result = _credit_result(_TWO)
    assert "IPL 인정 1행 / 검토 0행" in service.summary_line(result)
    assert service.concentration_warning(result) == service.CONCENTRATION_WARNING_IPL  # 안전장치 입력 있음 + F=3 몰림
    bad = _credit_result([_TWO[0], {"name": "가스누출감지기", "class": "prevention", "applies": True}])
    assert "IPL 인정 1행 / 검토 1행" in service.summary_line(bad)
    records, _ = _run(on=False)
    assert service.ipl_line(type(result)(meta=result.meta, records=records)) is None  # 이전 결과엔 줄 없음


def test_unknown_safeguards_keep_old_warning() -> None:
    from apps.web import service
    from apps.web.replay import Result

    records, _ = _run(credited=[], f=3)
    bare = [r.model_copy(update={"node_meta": r.node_meta.model_copy(update={"safeguards": []})}) for r in records]
    result = Result(meta={"source": "live-run", "criteria_id": OFFICIAL_CRITERIA}, records=bare)
    assert service.concentration_warning(result) == service.CONCENTRATION_WARNING


@pytest.mark.parametrize(("credited", "shown", "line"), [(_TWO, "3→1", "IPL 인정 1행"), ([], ">3<", "IPL 인정 0행")])
def test_app_shows_credit(monkeypatch: pytest.MonkeyPatch, credited: list[dict[str, Any]], shown: str, line: str) -> None:
    """S-4-6 AppTest — 인정 2건이면 `3→1`·요약 n=1, 비면 `3` 만."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("HAZOP_USE_MOCK", "true")
    at = AppTest.from_file(str(Path(__file__).parents[1] / "apps" / "web" / "app.py"), default_timeout=60).run()
    at.session_state["quick_result"] = _credit_result(credited)
    at.run()
    assert not at.exception
    assert any(line in c.value for c in at.caption)
    full = next(h.proto.body for h in at.get("html") if "hz-full" in h.proto.body)
    assert "빈도 (기본→반영)" in full and shown in full
    if not credited:
        assert "→" not in full.split("<tbody>")[1]  # 인정 0 이면 화살표 없이 값 하나
    assert any("IPL 적격 장치가 적습니다" in c.value for c in at.caption)  # 안전장치 입력 있음 + F=3 몰림


# ── S-5 재캡처 준비 ───────────────────────────────────────────────────────────
def test_capture_records_ipl_flag_and_safeguard_override(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.web import service
    from apps.web.replay import load_replays
    from tools import capture_replay

    client = MockBedrockClient(response_factory=service._mock_factory(load_replays()["N1"]))
    monkeypatch.setattr(capture_replay, "get_bedrock_client", lambda: client)
    monkeypatch.setitem(capture_replay.NODE_METAS, "N2", capture_replay.NODE_METAS["N2"])  # 덮어쓰기를 시험 뒤 되돌린다
    out = tmp_path / "n2_sg.json"
    assert capture_replay.main(["--node", "N2", "--out", str(out), "--safeguards", ",".join(_D1_N2)]) == 0
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["ipl_credit"] is True and saved["ipl_credit_effective"] is True
    assert saved["node_meta"]["safeguards"] == _D1_N2
    assert all("ipl_credited" in r for r in saved["records"] if r.get("status") != "insufficient")


def test_extract_ipl_rows(tmp_path: Any) -> None:
    from apps.web.replay import Result
    from tools import extract_ipl_rows

    path = tmp_path / "r.json"
    result = _credit_result(_TWO)
    path.write_text(json.dumps({"node": "X1", "records": [r.model_dump(mode="json") for r in result.records]},
                               ensure_ascii=False), encoding="utf-8")
    assert isinstance(result, Result)
    rows = extract_ipl_rows.extract([path], limit=20)
    assert len(rows) == 1 and rows[0]["빈도"] == "3→1" and "안전밸브(예방)" in rows[0]["인정 IPL"]
    md = extract_ipl_rows.to_markdown(rows)
    assert md.splitlines()[0].startswith("| # | 파일 |") and "동의" in md.splitlines()[0]
