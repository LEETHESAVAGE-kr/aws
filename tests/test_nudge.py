"""모바일 화면 이동(10/15) — 버튼을 눌러 바뀐 곳이 화면 밖이면 스크롤·깜빡임. PC 는 그대로."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from apps.web import nudge

APP = str(Path(__file__).resolve().parents[1] / "apps" / "web" / "app.py")


def _nudges(at: AppTest) -> list[str]:
    """화면 트리에서 nudge 스크립트를 담은 요소의 proto 문자열.

    스크립트 첫 줄의 표지(`/* nudge <번호> */`)로 찾는다 — 'nudge' 낱말만 보면 CSS 규칙·상자 키(`panel_nudge`)도 걸린다.
    """
    out: list[str] = []

    def walk(node: object) -> None:
        children = getattr(node, "children", None)
        if isinstance(children, dict):
            for child in children.values():
                walk(child)
        proto = getattr(node, "proto", None)
        if proto is not None and "/* nudge " in str(proto):
            out.append(str(proto))

    walk(at._tree)
    return out


@pytest.mark.parametrize("target", sorted(set(nudge.TARGETS) - nudge.ALWAYS))
def test_script_does_nothing_outside_mobile(target: str) -> None:
    """스크롤·깜빡임은 전부 모바일 판정 안에 있다 — PC 에서는 스타일도 넣지 않는다."""
    s = nudge.script(target, 1)
    guard = f"if (window.parent.matchMedia({nudge.MOBILE_QUERY!r}".replace("'", '"')
    head, _, body = s.partition(guard)
    assert body, "모바일 판정이 없다"
    for action in ("scrollIntoView", "classList", "createElement('style')"):
        assert action not in head and action in body
    assert nudge.TARGETS[target] in body


def test_rows_target_scrolls_on_pc_too() -> None:
    """판정 막대를 누르면 표가 화면 아래에 있어 PC 에서도 이동한다(10/15)."""
    s = nudge.script("rows", 1)
    assert "matchMedia" not in s and "scrollIntoView" in s and nudge.TARGETS["rows"] in s


def test_each_press_is_a_new_script() -> None:
    """같은 HTML 이면 Streamlit 이 다시 그리지 않아 두 번째 누름이 무시된다 — 번호가 달라야 한다."""
    assert nudge.script("result", 1) != nudge.script("result", 2)


def test_node_button_emits_result_nudge_once() -> None:
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.radio(key="mode").set_value("완성된 사례 보기").run()
    assert _nudges(at) == []  # 모드만 바꿨을 때는 그 자리에서 바뀐다 — 이동 없음
    at.button(key="preset_N2").click().run()
    first = _nudges(at)
    assert len(first) == 1 and nudge.TARGETS["result"] in first[0]
    at.button(key="preset_N2").click().run()
    second = _nudges(at)
    assert len(second) == 1 and second != first  # 다시 눌러도 새 스크립트
    at.run()
    assert _nudges(at) == []  # 버튼과 무관한 재실행은 이동하지 않는다


def test_process_select_and_whole_process_emit_result_nudge() -> None:
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.radio(key="mode").set_value("완성된 사례 보기").run()
    at.button(key="preset_all").click().run()
    assert any(nudge.TARGETS["result"] in p for p in _nudges(at))
    other = next(o for o in at.selectbox(key="process_name").options if o != at.selectbox(key="process_name").value)
    at.selectbox(key="process_name").set_value(other).run()
    assert any(nudge.TARGETS["result"] in p for p in _nudges(at))


def test_example_chip_emits_input_nudge() -> None:
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert _nudges(at) == []
    at.button(key="chip_0").click().run()
    found = _nudges(at)
    assert len(found) == 1 and nudge.TARGETS["input"] in found[0]
    assert at.session_state["quick_text"]  # 칩이 칸을 채운 것은 그대로
