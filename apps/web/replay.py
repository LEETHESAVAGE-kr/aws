"""재생 데이터 로더 — FR-10 H-02 (PRD v2.0 §5 FR-10, 지시문 H).

`data/replay/*.json` 은 `tools/capture_replay.py` 가 만든다. `source == "live"` 를 우선하고,
없으면 `gold`(전문가 골드셋 재생 — 생성 결과 아님)를 고른다.
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


def load_replay(directory: Path = REPLAY_DIR) -> Result:
    """`live` > `gold` 순, 같은 source 안에서는 `captured_at` 최신을 고른다."""
    candidates: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("source") in _SOURCE_PRIORITY:
            candidates.append(payload)
    if not candidates:
        raise FileNotFoundError(f"재생 파일 없음: {directory}/*.json (tools/capture_replay.py 로 생성)")
    # 최신 captured_at 이 먼저 오도록 역정렬한 뒤, 안정 정렬로 source 우선순위를 건다.
    candidates.sort(key=lambda p: str(p.get("captured_at", "")), reverse=True)
    candidates.sort(key=lambda p: _SOURCE_PRIORITY[p["source"]])
    chosen = candidates[0]
    records = [DeviationRecord.model_validate(r) for r in chosen.get("records", [])]
    meta = {k: v for k, v in chosen.items() if k != "records"}
    return Result(meta=meta, records=records)
