"""신뢰도 리포트 JSON — R-06·R-08 (spec:export-formats, PRD §5 FR-07).

아직 측정할 수 없는 값은 0 이 아니라 `null` 로 남긴다 — 0 은 측정 결과처럼 읽힌다(NFR-03).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, Field

from core.criteria import Criteria, load_criteria

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .rows import WorksheetRow

GENERATED_BY: Final[str] = "hazop-copilot FR-07"

# 위험도 구간 — steering domain.md §4.3 이 정의한 방법론 값(데이터가 아니라 상수).
# data/gold/rating_scale.json 의 문자열과 일치해야 하며 test_export 가 대조한다.
RISK_BANDS: Final[tuple[tuple[int, int, str], ...]] = (
    (15, 25, "높음"),
    (8, 14, "중간(ALARP)"),
    (1, 7, "낮음"),
)
CONFIDENCE_KEYS: Final[tuple[str, ...]] = ("grounded", "single_source", "inferred", "review", "unassigned")
PENDING_REASONS: Final[dict[str, str]] = {
    "evidence_attachment_rate": "근거 인용 0건 — evidence[] 가 전부 비어 있음(근거 인용을 끈 실행·골드셋 포함)",
    "matrix_coverage": "FR-03 HazopGenerator 관측값(expected_cells, judged_cells) 필요 — 골드셋에는 없음",
}


def rows_criteria(rows: Sequence[WorksheetRow]) -> Criteria:
    """산출물 1벌의 평가기준(Y-2). 기준이 섞이면 위험도·구간을 한 표로 셀 수 없으므로 거부한다."""
    ids = {r.criteria_id or None for r in rows}
    if len(ids) > 1:
        raise ValueError(f"한 산출물에 평가기준이 섞였다: {sorted(map(str, ids))}")
    return load_criteria(ids.pop() if ids else None)


def risk_band(score: int, criteria: Criteria | None = None) -> str:
    """위험도 구간 이름. 기준을 주면 그 기준의 구간(Y-2), 없으면 골드셋 NH3 구간."""
    if criteria is not None:
        return criteria.band(score)
    for low, high, name in RISK_BANDS:
        if low <= score <= high:
            return name
    raise ValueError(f"위험도 {score} 는 1~25 밖이다")


class ConfidenceReport(BaseModel):
    generated_by: str = GENERATED_BY
    generated_at: str | None = None
    record_count: int
    nodes: list[str]
    confidence_distribution: dict[str, int]
    evidence_attachment_rate: float | None
    matrix_coverage: dict[str, float | int] | None
    risk_distribution: dict[str, int]
    sf_matrix: dict[str, dict[str, int]]
    criteria_id: str | None = None
    criteria_name: str | None = None
    pending: dict[str, str] = Field(default_factory=dict)


def build_report(
    rows: Sequence[WorksheetRow],
    *,
    generated_at: str | None = None,
    coverage: tuple[int, int] | None = None,
) -> ConfidenceReport:
    """`coverage=(expected_cells, judged_cells)` 는 FR-03 생성기의 관측값. 없으면 `null`."""
    dist = dict.fromkeys(CONFIDENCE_KEYS, 0)
    for r in rows:
        key = r.confidence if r.confidence in CONFIDENCE_KEYS else None
        dist[key or "unassigned"] += 1

    attached = sum(1 for r in rows if r.evidence)
    rate: float | None = round(attached / len(rows), 4) if attached and rows else None

    matrix_coverage: dict[str, float | int] | None = None
    if coverage is not None:
        expected, judged = coverage
        matrix_coverage = {
            "expected": expected,
            "judged": judged,
            "ratio": round(judged / expected, 4) if expected else 0.0,
        }

    criteria = rows_criteria(rows)
    risk_dist = {name: 0 for _, _, name, _ in criteria.bands()}
    sf: dict[str, dict[str, int]] = {
        str(s): {str(f): 0 for f in range(1, criteria.f_max + 1)} for s in range(1, criteria.s_max + 1)
    }
    for r in rows:
        risk_dist[criteria.band(r.risk_score)] += 1
        sf[str(r.S)][str(r.F)] += 1

    pending = {
        key: reason
        for key, reason in PENDING_REASONS.items()
        if (key == "evidence_attachment_rate" and rate is None)
        or (key == "matrix_coverage" and matrix_coverage is None)
    }

    return ConfidenceReport(
        generated_at=generated_at,
        record_count=len(rows),
        nodes=sorted({r.node for r in rows}),
        confidence_distribution=dist,
        evidence_attachment_rate=rate,
        matrix_coverage=matrix_coverage,
        risk_distribution=risk_dist,
        sf_matrix=sf,
        criteria_id=criteria.id,
        criteria_name=criteria.name,
        pending=pending,
    )


def report_json(report: ConfidenceReport) -> str:
    """결정적 직렬화(키 순서 = 모델 선언 순서, 한글 보존, 개행 종료)."""
    return json.dumps(report.model_dump(), ensure_ascii=False, indent=2) + "\n"


def write_report(report: ConfidenceReport, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_json(report), encoding="utf-8")
    return path


__all__: list[str] = [
    "CONFIDENCE_KEYS",
    "ConfidenceReport",
    "GENERATED_BY",
    "PENDING_REASONS",
    "RISK_BANDS",
    "build_report",
    "report_json",
    "risk_band",
    "write_report",
]
