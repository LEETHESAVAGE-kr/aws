"""프리셋 자기검증 — PRD_본선_질문봉쇄 Q-04. 앱이 준 예시 문장의 수치가 입력 확인에서 '빠진 정보'로 뜨면 안 된다.

실호출 응답(tests/golden/parse_presets_20261014.json)을 모의 클라이언트로 재생한다 — 오프라인. 문장 속 수치는
정규식으로 뽑아, 해석 결과(NodeMeta)의 해당 칸에 환산값으로 떨어졌는지 본다.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest

from apps.web import service
from core.llm import ConverseResponse, MockBedrockClient

_ROOT = Path(__file__).resolve().parents[1]
_GOLDEN = json.loads((_ROOT / "tests" / "golden" / "parse_presets_20261014.json").read_text(encoding="utf-8"))
NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*(MPa|bar|kPa|℃|°C|m³|kg)")


def _app_examples() -> list[tuple[str, str]]:
    """app.py 의 EXAMPLES — streamlit 을 실행하지 않고 리터럴만 읽는다."""
    tree = ast.parse((_ROOT / "apps" / "web" / "app.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "EXAMPLES")
    return [(label, text) for label, text, *_ in ast.literal_eval(node.value)]


def _parse(text: str, reply: str) -> tuple[Any, dict[str, Any]]:
    client = MockBedrockClient(response_factory=lambda **_: ConverseResponse(content=reply))
    return service.parse_node_text(text, environ={}, client=client)


def test_recorded_replies_cover_current_presets() -> None:
    """녹화 응답이 지금 화면의 예시 문장과 같다 — 예시를 고치면 다시 녹화해야 한다는 신호."""
    assert [(r["label"], r["text"]) for r in _GOLDEN["recorded"]] == _app_examples()


@pytest.mark.parametrize("recorded", _GOLDEN["recorded"], ids=lambda r: r["label"])
def test_every_number_in_preset_lands_in_node_meta(recorded: dict[str, str]) -> None:
    meta, info = _parse(recorded["text"], recorded["reply"])
    text = recorded["text"]
    for m in NUMBER.finditer(text):
        value, unit = float(m.group(1)), m.group(2)
        if unit in service.PRESSURE_TO_KPA:
            field = "design_P_kPag" if "설계" in text[max(0, m.start() - 8): m.start()] else "P_kPag"
            assert getattr(meta, field) == pytest.approx(value * service.PRESSURE_TO_KPA[unit]), m.group(0)
        elif unit in ("℃", "°C"):
            assert meta.T_degC == pytest.approx(value), m.group(0)
        else:
            assert meta.capacity and m.group(1) in meta.capacity, m.group(0)
    if "상압" in text:
        assert meta.P_kPag == 0, "상압은 게이지압 0"
    missing = service.missing_inputs(meta)
    assert "P_kPag" not in missing, missing  # 10/14 증상: 예시에 압력이 있는데 '입력에 없는 정보: 운전압력'
    assert "운전압력" in service.parsed_values_line(meta, info)


def test_pressure_in_design_slot_without_design_word_is_moved() -> None:
    """수정 전 프롬프트의 응답(90 MPa 가 설계압력 칸) — 코드 보정이 운전압력으로 옮기고 그 사실을 남긴다."""
    bad = _GOLDEN["bad_20261014"]
    meta, info = _parse(bad["text"], bad["reply"])
    assert meta.P_kPag == pytest.approx(90_000) and meta.design_P_kPag is None
    assert info["parse_fixes"] and "P_kPag" not in service.missing_inputs(meta)
    assert "운전압력 90 MPa(=90,000 kPag)" in service.parsed_values_line(meta, info)


def test_real_design_pressure_is_left_alone() -> None:
    """'설계'라고 적힌 압력은 설계압력 칸에 그대로 둔다(보정이 과하게 옮기지 않는다)."""
    text = "LPG 저장탱크(설계압력 1.8 MPa)에서 펌프로 출하한다."
    reply = json.dumps({"node": "X1", "substance": "프로판", "phase": "liquid", "pressure": None, "T_degC": None,
                        "design_pressure": {"value": 1.8, "unit": "MPa"}, "capacity": None,
                        "equipment": ["LPG 저장탱크", "펌프"], "safeguards": [], "safeguards_known": False})
    meta, info = _parse(text, reply)
    assert meta.design_P_kPag == pytest.approx(1800) and meta.P_kPag is None and info["parse_fixes"] == []
