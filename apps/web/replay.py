"""재생 데이터 로더 — FR-10 H-02 (PRD v2.0 §5 FR-10, 지시문 H).

`data/replay/*.json` 은 `tools/capture_replay.py` 가 만든다. 노드마다 `source == "live"` 를 우선하고,
없으면 `gold`(전문가 골드셋 재생 — 생성 결과 아님)를 고른다(I-1 H-06 에서 노드별로 확장).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from core.agent import DeviationRecord

REPLAY_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "data" / "replay"
_SOURCE_PRIORITY: Final[dict[str, int]] = {"live": 0, "gold": 1}


@dataclass
class Result:
    """결과표·요약 줄·다운로드가 공통으로 쓰는 한 번의 실행(또는 재생) 결과."""

    meta: dict[str, Any]
    records: list[DeviationRecord] = field(default_factory=list)

    @property
    def is_gold(self) -> bool:
        return self.meta.get("source") == "gold"


def _to_result(payload: dict[str, Any]) -> Result:
    records = [DeviationRecord.model_validate(r) for r in payload.get("records", [])]
    meta = {k: v for k, v in payload.items() if k != "records"}
    # 9/29 N1 파일은 `recall_n1` 키로 저장됐다(I-1 에서 `recall` 로 개명). 두 키 모두 읽는다.
    if meta.get("recall") is None and meta.get("recall_n1") is not None:
        meta["recall"] = meta["recall_n1"]
    meta.pop("recall_n1", None)
    # I-1 이전 파일엔 split 키가 없다 — data/gold/split_node.json(N1=tune, N2~N4=holdout) 기준으로 채운다.
    meta.setdefault("split", "tune" if meta.get("node", "N1") == "N1" else "holdout")
    return Result(meta=meta, records=records)


def load_replays(directory: Path = REPLAY_DIR) -> dict[str, Result]:
    """노드별 재생 1건씩. `live` > `gold` 순, 같은 source 안에서는 `captured_at` 최신."""
    by_node: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("source") in _SOURCE_PRIORITY:
            by_node.setdefault(str(payload.get("node", "N1")), []).append(payload)
    chosen: dict[str, Result] = {}
    for node, candidates in sorted(by_node.items()):
        # 최신 captured_at 이 먼저 오도록 역정렬한 뒤, 안정 정렬로 source 우선순위를 건다.
        candidates.sort(key=lambda p: str(p.get("captured_at", "")), reverse=True)
        candidates.sort(key=lambda p: _SOURCE_PRIORITY[p["source"]])
        chosen[node] = _to_result(candidates[0])
    return chosen


def load_replay(directory: Path = REPLAY_DIR) -> Result:
    """N1 재생(H-02 호환) — `load_replays()["N1"]`."""
    replays = load_replays(directory)
    if "N1" not in replays:
        raise FileNotFoundError(f"N1 재생 파일 없음: {directory}/*.json (tools/capture_replay.py 로 생성)")
    return replays["N1"]
