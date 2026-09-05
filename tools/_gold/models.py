"""gold-dataset 데이터 모델 및 컬럼 스키마 — design.md §3, requirements.md REQ-02.

`NodeMeta` / `GoldRecord` / `SplitConfig` 는 design.md §3 의 dataclass 정의를 그대로 따른다.
(steering `engineering.md` §3 은 데이터 모델에 pydantic v2 를 권장하나, 이 spec 의 출력 검증
경로는 `schemas/gold_record.schema.json` JSON Schema 이며 design.md §3 이 dataclass 를 명시하므로
spec 을 따랐다. 충돌 사실은 완료 보고에 기록한다.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

type NodeId = str

# REQ-02 · xlsx 헤더 ↔ 내부 필드명. 열 순서가 아니라 헤더 이름으로 매핑한다.
COLUMN_MAP: Final[dict[str, str]] = {
    "No": "row_no",
    "노드": "node_raw",
    "가이드워드": "guideword_raw",
    "이탈": "deviation",
    "원인": "causes_raw",
    "결과": "consequences_raw",
    "기존 안전장치(Before)": "safeguards_raw",
    "S(1-5)": "severity",
    "F(1-5)": "frequency",
    "위험도": "risk_score_raw",
    "권고": "recommendations_raw",
    "시나리오 연계": "scenario",
}

REQUIRED_COLUMNS: Final[list[str]] = list(COLUMN_MAP)

PHASE_VALUES: Final[frozenset[str]] = frozenset({"liquid", "gas", "liquid/gas", "unknown"})


@dataclass
class NodeMeta:
    """노드 수준 메타데이터. `node_raw` 셀에서 파싱하며 실패 시 기본값을 쓴다 (REQ-05)."""

    substance: str = "unknown"
    phase: str = "unknown"
    P_kPag: float | None = None
    T_degC: float | None = None
    equipment: list[str] = field(default_factory=list)
    safeguards: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "substance": self.substance,
            "phase": self.phase,
            "P_kPag": self.P_kPag,
            "T_degC": self.T_degC,
            "equipment": list(self.equipment),
            "safeguards": list(self.safeguards),
        }


@dataclass
class GoldRecord:
    """이탈 1건 = 골드셋 레코드 1건 (REQ-03)."""

    id: str
    node: NodeId
    node_meta: NodeMeta
    guideword: str
    parameter: str
    deviation: str
    causes: list[str] = field(default_factory=list)
    consequences: list[str] = field(default_factory=list)
    safeguards_before: list[str] = field(default_factory=list)
    S: int | None = None
    F: int | None = None
    risk_score: int | None = None
    recommendations: list[str] = field(default_factory=list)
    scenario: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON Schema(`gold_record.schema.json`) 의 키 순서 그대로 직렬화한다."""
        return {
            "id": self.id,
            "node": self.node,
            "node_meta": self.node_meta.to_dict(),
            "guideword": self.guideword,
            "parameter": self.parameter,
            "deviation": self.deviation,
            "causes": list(self.causes),
            "consequences": list(self.consequences),
            "safeguards_before": list(self.safeguards_before),
            "S": self.S,
            "F": self.F,
            "risk_score": self.risk_score,
            "recommendations": list(self.recommendations),
            "scenario": self.scenario,
        }


@dataclass
class SplitConfig:
    """분할 기록 — `split_config.json` (REQ-08, AC-08 필수 5필드)."""

    split_type: str
    tune_nodes: list[str] | None
    seed: int | None
    tune_count: int
    eval_count: int
    timestamp: str
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "split_type": self.split_type,
            "tune_nodes": list(self.tune_nodes) if self.tune_nodes is not None else None,
            "seed": self.seed,
            "tune_count": self.tune_count,
            "eval_count": self.eval_count,
            "timestamp": self.timestamp,
            "fallback_reason": self.fallback_reason,
        }
