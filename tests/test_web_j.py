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
