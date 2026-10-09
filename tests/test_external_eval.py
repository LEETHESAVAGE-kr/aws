"""외부 공개 HAZOP 평가셋 — 파일 무결성·오염 차단·포괄률 계산."""

from __future__ import annotations

import json

import pytest

from core.agent.generate import STANDARD_GUIDEWORDS, NodeMeta, load_generator_config
from tools.measure_external_eval import EVAL_PATH, load_eval, score


def test_eval_file_integrity() -> None:
    data = load_eval()
    ids = [n["id"] for n in data["nodes"]]
    assert len(ids) == len(set(ids))
    for n in data["nodes"]:
        NodeMeta(**n["node_meta"])
        assert n["node_meta"]["node"] == n["id"]
    assert all(r["node"] in set(ids) for r in data["records"])
    assert all(r["guideword"] in STANDARD_GUIDEWORDS for r in data["records"])
    assert {s["id"] for s in data["sources"]} == {n["source_id"] for n in data["nodes"]}
    assert all(s["url"].startswith("http") and s["license"] for s in data["sources"])


def test_eval_file_has_no_source_sentences() -> None:
    """원인·결과·권고 문장을 옮기지 않는다 — 레코드 키는 쌍과 출처 노드뿐."""
    for r in load_eval()["records"]:
        assert set(r) <= {"node", "source_node", "guideword", "parameter", "parameter_inferred"}


def test_eval_nodes_never_in_examples_or_presets() -> None:
    """평가 전용: 열거 예시는 꺼져 있어야 하고(ORNL·IJERPH 이름 포함), 앱 카탈로그·재생에 노드가 없어야 한다."""
    assert load_generator_config().enumerate_examples is False
    from apps.web.catalog import load_catalog, nodes_by_id

    eval_ids = {n["id"] for n in load_eval()["nodes"]}
    assert not eval_ids & set(nodes_by_id(load_catalog()))


def test_eval_excludes_iocl_2014_reference() -> None:
    """IOCL 2014(기존 평가셋)는 이 파일에 다시 들어가지 않는다 — 같은 문서를 두 번 세지 않게."""
    data = load_eval()
    assert "Pattikalan" not in json.dumps(data["sources"], ensure_ascii=False)


def test_score_macro_mean_gives_each_source_equal_weight() -> None:
    data = {"nodes": [{"id": "A1", "source_id": "big"}, {"id": "B1", "source_id": "small"}]}
    per_node = {"A1": {"matched": 90, "total": 100}, "B1": {"matched": 1, "total": 10}}
    s = score(per_node, data)
    assert s["by_source"]["big"]["coverage"] == pytest.approx(0.9)
    assert s["macro_mean"] == pytest.approx(0.5)  # (0.9 + 0.1) / 2 — 합산(91/110)과 다르다
    assert s["pooled"] == pytest.approx(91 / 110)
    assert s["min_source"] == "small"


def test_eval_path_is_tracked_reference_dir() -> None:
    assert EVAL_PATH.parent.name == "reference"
