"""'항목 선택' 양식(10/9 사용자 요청) — 양식 값 → NodeMeta JSON, 예시 버튼이 양식을 채운다, mock 으로 끝까지 돈다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from apps.web import form, service

_APP = Path(__file__).parent.parent / "apps" / "web" / "app.py"
_MOCK_ENV = {"HAZOP_USE_MOCK": "true", "HAZOP_ALLOW_LIVE": "true"}


def _values(**kw: Any) -> dict[str, Any]:
    return {**form.EMPTY, **kw}


_H2 = {"substance": "수소", "phase": "기체", "equipment": ["튜브트레일러", "압축기", "고압 저장용기", "디스펜서"],
       "pressure": 90.0, "design_pressure": 100.0, "capacity": "200 kg", "safeguards": ["안전밸브", "고압 경보(설정 95 MPa)"]}


def test_form_values_become_valid_node_meta() -> None:
    meta, parsed = service.parse_node_text(form.to_node_json(_values(**_H2)), _MOCK_ENV)
    assert parsed["parsed_by"] == "json" and parsed["raw_calls"] == []  # 해석 호출 없음
    assert meta.equipment == _H2["equipment"] and meta.capacity == "200 kg"


def test_units_capacity_and_design_pressure() -> None:
    data = json.loads(form.to_node_json(_values(
        substance="수소", phase="기체", equipment=["압축기"], pressure=90.0, pressure_unit="MPa",
        design_pressure=7.0, design_unit="bar", capacity=" 200 kg ")))
    assert (data["P_kPag"], data["design_P_kPag"], data["capacity"], data["phase"]) == (90000.0, 700.0, "200 kg", "gas")


@pytest.mark.parametrize(("no_safeguards", "safeguards", "listed", "known"), [
    (False, [], [], None),  # 비워 두면 모름 — safeguards_known 없음(기본 false)
    (True, ["안전밸브"], [], True),  # '안전장치 없음' 체크 — 고른 것이 있어도 없음(명시)
    (False, ["안전밸브", "고압 경보(설정 95 MPa)"], ["안전밸브", "고압 경보(설정 95 MPa)"], None),
])
def test_safeguards_none_vs_unknown(no_safeguards: bool, safeguards: list[str], listed: list[str], known: bool | None) -> None:
    data = json.loads(form.to_node_json(_values(substance="수소", equipment=["압축기"],
                                                safeguards=safeguards, no_safeguards=no_safeguards)))
    assert data["safeguards"] == listed and data.get("safeguards_known") is known


def test_missing_fields_block() -> None:
    assert form.missing_fields(_values()) == ["물질", "설비"]
    assert form.missing_fields(_values(substance="수소", equipment=["압축기"])) == []


def test_app_form_chip_fills_and_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    at = _grid(AppTest.from_file(str(_APP), default_timeout=60)).run()
    at.radio(key="input_style").set_value("항목 선택").run()
    cta = next(b for b in at.button if b.label.startswith("HAZOP 초안 생성"))
    assert cta.disabled  # 물질·설비가 비면 막힌다
    assert not any(b.label == "수소충전소" for b in at.button)  # 항목 선택에는 예시 칩이 없다(10/9 사용자)
    at.selectbox(key=form.KEYS["substance"]).set_value("수소")
    at.multiselect(key=form.KEYS["equipment"]).set_value(_H2["equipment"])
    at.text_input(key=form.KEYS["capacity"]).set_value("200 kg").run()
    assert not at.exception
    next(b for b in at.button if b.label.startswith("HAZOP 초안 생성")).click().run()
    assert not at.exception and len(at.dataframe) >= 1
    assert at.session_state["quick_result"].meta["parsed_by"] == "json"
    assert at.session_state["quick_result"].meta["node_meta"]["capacity"] == "200 kg"


def _grid(at: Any) -> Any:
    """기존 화면 시험은 편집 격자(st.dataframe·data_editor)를 본다 — 기본 표 모양은 10/9 부터 펼쳐 보기(HTML)."""
    at.session_state["table_style"] = service.TABLE_STYLES[1]
    return at


def test_full_text_table_is_default_and_not_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    """10/9 피드백 "항목이 잘려 늘려서 봐야 한다" — 기본은 글 전체를 줄바꿈하는 표, 편집 격자는 고를 때만."""
    from streamlit.testing.v1 import AppTest

    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    at = AppTest.from_file(str(_APP), default_timeout=60).run()
    next(b for b in at.button if b.label == "수소충전소").click().run()
    next(b for b in at.button if b.label.startswith("HAZOP 초안 생성")).click().run()
    assert not at.exception and at.radio(key="table_style").value == service.TABLE_STYLES[0]
    record = at.session_state["quick_result"].records[0]
    htmls = [h.proto.body for h in at.get("html") if "hz-full" in h.proto.body]
    assert htmls and record.deviation in htmls[0] and "심각도(1-" in htmls[0]  # 이탈 전문 그대로·우리말 머리글
    assert len(at.dataframe) == 0


def test_full_table_html_escapes_and_splits_lists() -> None:
    from core.criteria import load_criteria

    out = service.full_table_html([{"원인": "<b>밸브</b> · 펌프 정지", "S(1-5)": 3.0, "F(1-5)": float("nan")}],
                                  ["원인", "S(1-5)", "F(1-5)"], load_criteria("kosha_cc37_2026"))
    assert "&lt;b&gt;밸브&lt;/b&gt;<br>• 펌프 정지" in out and ">3<" in out and "nan" not in out


def test_chips_only_in_sentence_style(monkeypatch: pytest.MonkeyPatch) -> None:
    """PRD 첫화면 U-3 + 10/9 사용자: 입력 방식을 먼저 고르고, 예시 칩은 '문장으로 설명'에서만 보인다."""
    from streamlit.testing.v1 import AppTest

    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    at = AppTest.from_file(str(_APP), default_timeout=60).run()
    assert at.radio(key="input_style").value == "문장으로 설명"
    next(b for b in at.button if b.label == "수소충전소").click().run()
    assert "수소" in at.session_state["quick_text"] and at.session_state[form.KEYS["substance"]] is None
    at.radio(key="input_style").set_value("항목 선택").run()
    assert not any(b.label in ("수소충전소", "메탄올 저장탱크", "실란 가스 캐비닛") for b in at.button)
    assert not any("공정 예시" in h.proto.body for h in at.get("html"))


def test_progress_line_for_selected_items_has_no_json_word() -> None:
    from core.agent import NodeMeta

    meta = NodeMeta(node="X1", substance="수소", phase="gas", equipment=["압축기", "디스펜서"])
    _, text, _ = service.progress_text("parsed", {"parsed_by": "json", "node_meta": meta}, None)
    assert text == "✅ 1/3 입력한 항목 확인 — 수소 · 설비 2개 (해석 생략)" and "JSON" not in text


def test_first_screen_title_is_service_name_and_shows_three_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    at = AppTest.from_file(str(_APP), default_timeout=60).run()
    hero = next(h.proto.body for h in at.get("html") if "hz-h1" in h.proto.body)
    assert '<div class="hz-h1">HAZOP Copilot</div>' in hero
    assert all(p in hero for p in ("두 가지 방법", "문장으로 설명", "항목 선택", "모르겠다면", "완성된 사례 보기"))
    assert "골드셋" not in hero
