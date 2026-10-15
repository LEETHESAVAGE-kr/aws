"""화면 문구 일관성 — PRD_본선_질문봉쇄 Q-02(내부 워크시트 문구 제거·외부 대조 패널)·Q-05(숫자 단일 소스).

화면을 AppTest 로 실제로 그려 보이는 문자열을 모두 모은 뒤 검사한다. 소스 grep 이 아니라 렌더 결과를 보므로
데이터 파일(presets.json)이나 상수에서 들어온 문구도 잡힌다.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from google.protobuf import text_format

from apps.web import guide, service
from apps.web.replay import REPLAY_DIR, load_replays
from core.agent.generate import PROCEDURAL_GUIDEWORDS, STANDARD_GUIDEWORDS

_APP = REPLAY_DIR.parents[1] / "apps" / "web" / "app.py"
_MOCK_ENV = {"HAZOP_USE_MOCK": "true", "HAZOP_ALLOW_LIVE": "true"}
_CASES = "완성된 사례 보기"
#: 화면 어디에도 나오면 안 되는 말(Q-02 v2 결정 — 정확도 이야기는 외부 공개 평가셋으로만).
BANNED = re.compile(r"정답지|골드셋|34건")


def _walk(node: Any) -> list[Any]:
    out = [node]
    for child in getattr(node, "children", {}).values():
        out += _walk(child)
    return out


def rendered_text(at: Any) -> str:
    """AppTest 화면의 글자 전부 — 요소 proto 의 문자열(UTF-8 그대로) + 표 값. 탭·버튼·캡션·HTML 본문이 다 들어온다."""
    parts: list[str] = []
    for node in _walk(at._tree):  # noqa: SLF001 — 화면 전체를 한 번에 훑는 공개 API 가 없다
        proto = getattr(node, "proto", None)
        if proto is not None:
            parts.append(text_format.MessageToString(proto, as_utf8=True))
        value = getattr(node, "value", None)
        if hasattr(value, "to_string"):  # st.table·st.dataframe — 값은 Arrow 바이트라 proto 문자열로는 안 읽힌다
            parts.append(value.to_string())
    return "\n".join(parts)


def _screens(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """(화면 이름, 글자) — 첫 화면 + 사례 보기의 모든 공정 × (노드 각각 + 공정 전체)."""
    from streamlit.testing.v1 import AppTest

    for key, value in _MOCK_ENV.items():
        monkeypatch.setenv(key, value)
    at = AppTest.from_file(str(_APP), default_timeout=60).run()
    assert not at.exception
    screens = [("첫 화면", rendered_text(at))]
    at.radio(key="mode").set_value(_CASES).run()
    replays = load_replays()
    for process in service.CATALOG:
        at.selectbox(key="process_name").select(process["name"]).run()
        for node in process["nodes"]:
            if node["id"] in replays:
                at.button(key=f"preset_{node['id']}").click().run()
                assert not at.exception, node["id"]
                screens.append((f"{process['name']} {node['id']}", rendered_text(at)))
        at.button(key="preset_all").click().run()
        assert not at.exception, process["id"]
        screens.append((f"{process['name']} 전체", rendered_text(at)))
    return screens


@pytest.fixture(scope="module")
def screens() -> list[tuple[str, str]]:
    """화면에 실제로 나가는 재생(날짜 상한 없음)으로 그린다 — conftest 의 고정을 이 모듈만 푼다."""
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("HAZOP_REPLAY_BEFORE", raising=False)
        return _screens(mp)


@pytest.fixture(autouse=True)
def _current(current_replays: None) -> None:
    """이 모듈의 시험 몸통(load_replays 호출)도 현재 재생을 본다."""


def test_no_internal_worksheet_wording_on_any_screen(screens: list[tuple[str, str]]) -> None:
    """Q-02-3: '정답지'·'골드셋'·'34건' 이 화면 어디에도 없다."""
    hits = [(name, m.group(0)) for name, text in screens for m in BANNED.finditer(text)]
    assert hits == []


def test_external_panel_numbers_come_from_summary_file(screens: list[tuple[str, str]]) -> None:
    """Q-02-9: 패널 숫자 = external_eval_summary.json. 낮은 출처(IJERPH)도 빠지지 않는다. 오염 고지·평가 전용 문구 포함."""
    summary = json.loads(service.EXTERNAL_SUMMARY_PATH.read_text(encoding="utf-8"))
    dataset = json.loads(service.EXTERNAL_SET_PATH.read_text(encoding="utf-8"))
    panel = service.external_eval()
    assert {r["출처"] for r in panel["rows"]} == {service.EXTERNAL_SHORT[k] for k in summary["by_source"]}
    for source, got in summary["by_source"].items():
        row = next(r for r in panel["rows"] if r["출처"] == service.EXTERNAL_SHORT[source])
        assert row["다시 찾아낸 쌍"] == f"{got['matched']}/{got['total']}" and row["coverage"] == f"{got['coverage']:.2f}"
    assert f"출처별 평균 {summary['macro_mean']:.2f}" in panel["total"] and f"전체 합산 {summary['pooled']:.2f}" in panel["total"]
    assert f"{summary['nodes']}노드" in panel["head"] and "212개" in panel["head"]
    text = next(t for name, t in screens if name.endswith(" N1"))
    # 교열 10/15 — 화면에는 평가셋의 화면용 필드가 나오고, 작업 메모(실험 번호·설정 이름) 원문은 나오지 않는다
    for needle in (service.EXTERNAL_PANEL_TITLE, dataset["display_eval_only"], dataset["display_contamination"], "IJERPH 2017"):
        assert needle in text, needle
    for memo in (dataset["contamination_note"], "few-shot", "F-06", "enumerate_examples"):
        assert memo not in text, memo


def test_summary_file_is_the_local_run_copy() -> None:
    """추적 사본이 로컬 원자료(gitignore)와 같은 값이다 — 로컬 원자료가 있는 PC 에서만 확인한다."""
    local = REPLAY_DIR.parents[1] / "results" / "exteval_20261010" / "summary.json"
    if not local.exists():
        pytest.skip("results/ 는 gitignore — 원자료가 있는 PC 에서만")
    tracked = json.loads(service.EXTERNAL_SUMMARY_PATH.read_text(encoding="utf-8"))
    raw = json.loads(local.read_text(encoding="utf-8"))
    assert {k: tracked[k] for k in raw} == raw


def test_cells_tile_says_completeness_not_accuracy(screens: list[tuple[str, str]]) -> None:
    """Q-02-5: '판정 셀' 은 완전성. '누락 0' 을 타일 이름으로 쓰지 않는다."""
    text = next(t for name, t in screens if name.endswith(" N1"))
    assert service.CELLS_TILE_SUB in text and "판정 셀 (누락 0)" not in text


def test_counts_come_from_one_source(screens: list[tuple[str, str]]) -> None:
    """Q-05: 가이드워드 수·파라미터 수·호출 수가 상수·저장 결과와 같다. '—' 호출 수와 빈 노드 입력 `{}` 가 없다."""
    allowed_gw = {1, len(STANDARD_GUIDEWORDS), len(STANDARD_GUIDEWORDS) + len(PROCEDURAL_GUIDEWORDS)}
    low, high = service.param_range(load_replays()) or (0, 0)
    for name, text in screens:
        for m in re.finditer(r"가이드워드 (\d+)종", text):
            assert int(m.group(1)) in allowed_gw, (name, m.group(0))
        for m in re.finditer(r"표준 (\d+)", text):
            assert int(m.group(1)) == len(STANDARD_GUIDEWORDS), (name, m.group(0))
        assert "API 호출 —" not in text and "노드(—)" not in text, name
        if name != "첫 화면":  # 저장된 결과는 노드 하나든 공정 전체든 호출 수를 보인다(Q-05-3)
            assert re.search(r"API 호출 \d+회", text), name
        assert not re.search(r'body: "\{\}"', text), name  # st.json({}) — 빈 노드 입력
        for m in re.finditer(r"노드당 (\d+)~(\d+)개", text):
            assert (int(m.group(1)), int(m.group(2))) == (low, high), (name, m.group(0))
    first = screens[0][1]
    assert guide.GUIDEWORD_TAB in first and f"노드당 {low}~{high}개" in first
