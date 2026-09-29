"""공정 카탈로그 로더 — FR-10 J-01 (PRD v2.0 §5 FR-10, 지시문 J).

`data/presets.json` 이 정본이다. 데모 화면(`app.py`)·결과표(`service.py`)·캡처 도구
(`tools/capture_replay.py`)가 모두 여기서 노드 입력을 읽는다.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any, Final

from jsonschema import Draft7Validator

from core.agent import NodeMeta

_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CATALOG_PATH: Final[Path] = _ROOT / "data" / "presets.json"
_SCHEMA_PATH: Final[Path] = _ROOT / "schemas" / "deviation.schema.json"


@cache
def _node_meta_validator() -> Draft7Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft7Validator(schema["items"]["properties"]["node_meta"])


def validate_node_meta(payload: dict[str, Any]) -> NodeMeta:
    """`NodeMeta` 검증 + 산출물 스키마의 `node_meta` 제약(phase enum 등). 위반이면 `ValueError`.

    스키마를 먼저 보는 이유: `NodeMeta.phase` 는 자유 문자열이지만 레코드 스키마는 enum 이라,
    여기서 막지 않으면 API 비용을 쓴 뒤 저장 단계에서 스키마 위반으로 버려진다.
    """
    errors = [f"{'.'.join(map(str, e.path)) or '(root)'}: {e.message}"
              for e in _node_meta_validator().iter_errors(payload)]
    if errors:
        raise ValueError("NodeMeta 스키마 위반 — " + "; ".join(errors))
    return NodeMeta.model_validate(payload)


def load_catalog(path: Path = CATALOG_PATH) -> list[dict[str, Any]]:
    """공정 목록. 각 노드의 `node_meta` 를 검증해 `NodeMeta` 로 바꿔 둔다. 노드 id 는 전체에서 유일."""
    processes: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["processes"]
    seen: set[str] = set()
    for process in processes:
        for node in process["nodes"]:
            if node["id"] in seen:
                raise ValueError(f"노드 id 중복: {node['id']}")
            seen.add(node["id"])
            meta = validate_node_meta(node["node_meta"])
            if meta.node != node["id"]:
                raise ValueError(f"노드 id 와 node_meta.node 불일치: {node['id']} ≠ {meta.node}")
            node["node_meta"] = meta
    return processes


def nodes_by_id(processes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """노드 id → 노드(+ `process` 키로 소속 공정). 카탈로그 순서 유지."""
    return {node["id"]: {**node, "process": p} for p in processes for node in p["nodes"]}
