"""오프라인 시험 — FR-10 J-01·J-03·J-04 (지시문 J): 공정 카탈로그·직접 입력 빠른 실호출·화면 재배치. 네트워크 0회."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from apps.web import service
from apps.web.catalog import CATALOG_PATH, load_catalog
from apps.web.replay import REPLAY_DIR, load_replays
from core.agent import NodeMeta

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_APP = REPLAY_DIR.parents[1] / "apps" / "web" / "app.py"
_MOCK_ENV = {"HAZOP_USE_MOCK": "true", "HAZOP_ALLOW_LIVE": "true"}
_DIRECT = "직접 입력 (빠른 실호출)"
_SENTENCE = "수소충전소 압축기에서 디스펜서로 고압 수소를 보낸다. 안전장치는 긴급차단밸브."


@pytest.fixture(autouse=True)
def _reset_daily_counter() -> None:
    service._daily_runs.clear()


# ── J-01 공정 카탈로그 ─────────────────────────────────────────────────────────
def test_catalog_loads_validated_unique_nodes() -> None:
    catalog = load_catalog()
    assert [p["id"] for p in catalog] == ["nh3_sts", "lpg_loading", "cl2_unloading"]
    assert [p["gold"] for p in catalog] == [True, False, False]
    ids = [n["id"] for p in catalog for n in p["nodes"]]
    assert ids == ["N1", "N2", "N3", "N4", "P1", "P2"]
    assert all(isinstance(n["node_meta"], NodeMeta) for p in catalog for n in p["nodes"])
    # NH3 는 I-1 의 하드코딩 값 그대로(J-01 "추측 금지") — PRESETS 도 예전 dict 와 같다.
    assert {k: service.PRESETS[k] for k in ("N1", "N2", "N3", "N4")} == {
        "N1": "벙커링선 매니폴드", "N2": "이송 호스", "N3": "수급선 매니폴드", "N4": "이송 운전 절차",
    }
    for node in catalog[0]["nodes"]:
        m = node["node_meta"]
        assert (m.substance, m.phase, m.P_kPag, m.T_degC, m.safeguards) == ("NH3", "unknown", None, None, [])


def _dup(c: dict[str, Any]) -> None:
    c["processes"][1]["nodes"][0]["id"] = "N1"


def _bad_phase(c: dict[str, Any]) -> None:
    c["processes"][1]["nodes"][0]["node_meta"]["phase"] = "액상"


def _id_mismatch(c: dict[str, Any]) -> None:
    c["processes"][2]["nodes"][0]["node_meta"]["node"] = "P9"


@pytest.mark.parametrize(("mutate", "message"), [(_dup, "중복"), (_bad_phase, "스키마"), (_id_mismatch, "불일치")])
def test_catalog_rejects_bad_entries(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None], message: str
) -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    mutate(catalog)
    path = tmp_path / "presets.json"
    path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_catalog(path)


def test_capture_non_gold_node_saves_null_recall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools import capture_replay

    assert capture_replay.default_split("P1") == "none"
    assert capture_replay.default_split("N2") == "holdout"
    client = service.MockBedrockClient(response_factory=service._mock_factory(load_replays()["N1"]))
    monkeypatch.setattr(capture_replay, "get_bedrock_client", lambda: client)
    out = tmp_path / "p1.json"
    # --split 을 줘도 골드 없는 노드는 none 으로 고정된다.
    assert capture_replay.main(["--node", "P1", "--out", str(out), "--source", "live", "--split", "holdout"]) == 0
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert (saved["node"], saved["split"], saved["recall"]) == ("P1", "none", None)
    assert saved["records"] and {r["node_meta"]["substance"] for r in saved["records"]} == {"프로판"}
    assert saved["parameters"] and len(saved["raw_calls"]) == len(client.calls)
    # 예시 공정 재생은 recall 표에 행을 만들지 않는다.
    replays = load_replays(tmp_path)
    assert "P1" in replays and service.evaluation_table(replays)[:-1] == []
    with pytest.raises(ValueError, match="골드셋이 없는"):
        capture_replay.main(["--node", "P1", "--out", str(out), "--source", "gold"])


# ── J-03 직접 입력 빠른 실호출 ─────────────────────────────────────────────────
def test_run_quick_makes_two_calls_for_one_guideword() -> None:
    node = {**service.NODES["P1"]["node_meta"].model_dump(), "node": "X1"}
    result = service.run_quick(json.dumps(node, ensure_ascii=False), "More", load_replays()["N1"], _MOCK_ENV)
    m = result.meta
    assert len(m["raw_calls"]) == 2  # 열거 1 + 가이드워드 1
    assert result.records and {r.guideword for r in result.records} == {"More"}
    assert (m["source"], m["mock"], m["guidewords"], m["recall"]) == ("quick", True, ["More"], None)
    assert m["expected_cells"] == len(m["parameters"]) == m["judged_cells"]
    assert {r.node for r in result.records} == {"X1"}
    assert "X1 골드셋 없음" in service.summary_line(result)
    assert set(service.export_files(result)) == {"xlsx", "lopa", "report"}
    assert service.process_view(result)["api_calls"] == 2


@pytest.mark.parametrize(
    ("node", "guideword"),
    [
        ({"substance": "프로판", "phase": "액상", "P_kPag": 1, "T_degC": 1, "equipment": [], "safeguards": []}, "More"),
        ({"substance": "프로판"}, "More"),
        ({"substance": "프로판", "phase": "gas", "P_kPag": 1, "T_degC": 1, "equipment": [], "safeguards": []}, "Much"),
    ],
)
def test_run_quick_rejects_bad_input_before_any_call(
    node: dict[str, Any], guideword: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_: object, **__: object) -> None:
        raise AssertionError("API 를 부르면 안 된다")

    monkeypatch.setattr(service, "HazopGenerator", _boom)
    with pytest.raises(ValueError):
        service.run_quick(json.dumps(node, ensure_ascii=False), guideword, load_replays()["N1"], _MOCK_ENV)


# ── 자연어 입력 (사용자 결정 9/29, PRD FR-10 밖) ──────────────────────────────
def _parse_client(payload: dict[str, Any]) -> service.MockBedrockClient:
    return service.MockBedrockClient(
        response_factory=lambda **_: service.ConverseResponse(content=json.dumps(payload, ensure_ascii=False))
    )


def test_run_quick_natural_language_adds_one_parse_call() -> None:
    result = service.run_quick(_SENTENCE, "More", load_replays()["N1"], _MOCK_ENV)
    m = result.meta
    assert [c.get("stage") for c in m["raw_calls"]] == ["parse", None, None]  # 해석 1 + 열거 1 + 판정 1
    assert (m["parsed_by"], m["node_text"], m["parse_model"]) == ("llm", _SENTENCE, "mock")
    assert m["node_meta"]["substance"] == "수소" and {r.guideword for r in result.records} == {"More"}


def test_parse_json_input_makes_no_call() -> None:
    client = _parse_client({})
    node = service.NODES["P2"]["node_meta"].model_dump()
    meta, parsed = service.parse_node_text(json.dumps(node, ensure_ascii=False), _MOCK_ENV, client)
    assert meta.substance == "염소" and parsed["parsed_by"] == "json" and client.calls == []


def test_parse_sends_sentence_with_schema_and_validates_reply() -> None:
    reply = {"node": "X1", "substance": "수소", "phase": "gas", "pressure": {"value": 90, "unit": "MPa"},
             "T_degC": None, "equipment": ["압축기"], "safeguards": []}
    client = _parse_client(reply)
    meta, parsed = service.parse_node_text(_SENTENCE, _MOCK_ENV, client)
    assert meta.P_kPag == 90000 and meta.T_degC is None and parsed["cost_usd"] == 0.0  # 환산은 코드가 한다
    (call,) = client.calls
    assert _SENTENCE in str(call["messages"][0].content) and "{text}" not in str(call["messages"][0].content)
    schema = call["response_schema"]
    assert schema["properties"]["phase"]["enum"] == ["liquid", "gas", "liquid/gas", "unknown"]
    assert "P_kPag" not in schema["properties"] and "pressure" in schema["required"]
    assert "node" in schema["required"] and "$comment" not in json.dumps(schema)
    # 모델이 enum 밖 값을 내면 core/llm 이 응답 스키마로 1회 재시도 후 content=None → 생성 전에 막힌다.
    # (그 뒤의 validate_node_meta 는 _parse_schema 와 산출물 스키마가 어긋날 때를 위한 2차 방어라 여기선 닿지 않는다.)
    bad = _parse_client({**reply, "phase": "기체"})
    with pytest.raises(ValueError, match="2회 위반"):
        service.parse_node_text(_SENTENCE, _MOCK_ENV, bad)
    assert len(bad.calls) == 2


@pytest.mark.parametrize(
    ("pressure", "kpag"),
    [(None, None), ({"value": 7, "unit": "bar"}, 700), ({"value": 350, "unit": "kPa"}, 350),
     ({"value": 10, "unit": "kgf/cm2"}, 980.665)],
)
def test_parse_converts_pressure_in_code(pressure: dict[str, Any] | None, kpag: float | None) -> None:
    reply = {"node": "X1", "substance": "프로판", "phase": "liquid", "pressure": pressure, "T_degC": 25,
             "equipment": ["저장탱크"], "safeguards": []}
    meta, _ = service.parse_node_text(_SENTENCE, _MOCK_ENV, _parse_client(reply))
    assert meta.P_kPag == kpag


@pytest.mark.parametrize("text", ["", "   ", "가" * (service.NODE_TEXT_LIMIT + 1)])
def test_parse_rejects_empty_or_long_text_before_call(text: str) -> None:
    client = _parse_client({})
    with pytest.raises(ValueError):
        service.parse_node_text(text, _MOCK_ENV, client)
    assert client.calls == []


def test_parser_uses_low_cost_verifier_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")  # 생성자만 — 호출하지 않는다
    config = service.load_model_config()
    assert service._parser_client().model_short == config.verifier.model_id != config.generation.model_id


@pytest.mark.parametrize(
    ("value", "scope"), [(None, "quick"), ("quick", "quick"), ("FULL", "full"), ("everything", "quick")]
)
def test_live_scope(value: str | None, scope: str) -> None:
    assert service.live_scope({} if value is None else {"HAZOP_LIVE_SCOPE": value}) == scope


# ── J-04 화면 — 직접 입력 mock 경로·상한 공용·HAZOP_LIVE_SCOPE 분기 ─────────────
@pytest.mark.parametrize("scope", ["quick", "full"])
def test_app_direct_input_quick_run_on_mock(monkeypatch: pytest.MonkeyPatch, scope: str) -> None:
    from streamlit.testing.v1 import AppTest

    for key, value in {**_MOCK_ENV, "HAZOP_LIVE_SCOPE": scope}.items():
        monkeypatch.setenv(key, value)
    at = AppTest.from_file(str(_APP), default_timeout=30).run()
    at.selectbox[0].select(_DIRECT).run()
    assert not at.exception
    assert len(at.dataframe) == 0
    assert any("노드 전체" in b.label for b in at.button) is (scope == "full")
    # 입력 칸은 비어 있고 예시는 placeholder 로만 보인다 — 비어 있으면 버튼이 막힌다.
    assert at.text_area[0].value == "" and "예시)" in at.text_area[0].placeholder
    assert next(b for b in at.button if b.label.startswith("빠른 실호출")).disabled is True
    at.text_area[0].input(_SENTENCE).run()
    quick = next(b for b in at.button if b.label.startswith("빠른 실호출"))
    assert quick.disabled is False
    quick.click().run()
    assert not at.exception
    assert len(at.dataframe) == 1
    assert {v.split(" (")[0] for v in at.dataframe[0].value["가이드워드"]} == {"More"}  # "More (압력)" 형식
    assert any("API 호출 3회" in m.value for m in at.markdown)  # 해석 1 + 열거 1 + 판정 1
    assert any(_SENTENCE in c.value for c in at.code)  # 입력 문장이 해석 결과 옆에 보인다
    # 상한은 공용 — 빠른 실호출 1회 뒤엔 노드 전체 버튼도 막힌다.
    assert all(b.disabled for b in at.button if "실호출" in b.label)
    assert any("세션" in c.value for c in at.caption)


def test_app_direct_input_disabled_without_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("HAZOP_ALLOW_LIVE", raising=False)
    at = AppTest.from_file(str(_APP), default_timeout=30).run()
    at.selectbox[0].select(_DIRECT).run()
    assert not at.exception
    assert [b.disabled for b in at.button] == [True]
    assert any("HAZOP_ALLOW_LIVE" in c.value for c in at.caption)
