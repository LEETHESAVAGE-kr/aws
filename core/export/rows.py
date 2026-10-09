"""입력 정규화 — R-01 (spec:export-formats, PRD §5 FR-07).

골드셋 JSON(dict)과 FR-03 의 `DeviationRecord` 를 같은 `WorksheetRow` 로 평탄화한다.
이 모듈은 프로젝트 내부 모듈을 임포트하지 않는다 — `core/agent` 를 끌어오면 `core/llm` →
AWS SDK 의존이 따라오므로, `DeviationRecord` 는 `model_dump()` 를 가진 객체로만 다룬다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from core.criteria import load_criteria

# 원본 `data/raw/D1_HAZOP_워크시트.xlsx` 실측 헤더 12열 — 순서·문자열 그대로 (R-02)
HEADERS: Final[tuple[str, ...]] = (
    "No",
    "노드",
    "가이드워드",
    "이탈",
    "원인",
    "결과",
    "기존 안전장치(Before)",
    "S(1-5)",
    "F(1-5)",
    "위험도",
    "권고",
    "시나리오 연계",
)

LIST_JOINER: Final[str] = "·"


@dataclass(frozen=True)
class WorksheetRow:
    """워크시트 1행. 12열 값 + 부속 시트·리포트·LOPA 가 쓰는 원문 정보."""

    no: int
    node_label: str
    guideword_label: str
    deviation: str
    causes: str
    consequences: str
    safeguards_before: str
    S: int | None  # 도메인 표기(S·F 등급)를 골드셋·DeviationRecord 와 맞춘다. None = 정보 부족 보류(Z-3)
    F: int | None
    recommendations: str
    scenario: str
    # 워크시트 밖 정보
    node: str
    risk_score: int | None
    evidence: tuple[dict[str, Any], ...]
    confidence: str | None
    causes_list: tuple[str, ...]
    safeguards_list: tuple[str, ...]
    recommendations_list: tuple[str, ...]
    criteria_id: str | None = None  # Y-2 — None 이면 골드셋 NH3 기준
    missing: tuple[str, ...] = ()  # Z-3 — 비어 있지 않으면 정보 부족 보류 행

    @property
    def held(self) -> bool:
        """정보 부족 보류 행(Z-3) — 위험도 순위·분포에서 뺀다."""
        return self.risk_score is None

    def cells(self) -> list[object]:
        """12열 값. 위험도(J) 자리는 `None` — 수식은 xlsx 쪽이 행 번호로 만든다."""
        return [
            self.no,
            self.node_label,
            self.guideword_label,
            self.deviation,
            self.causes,
            self.consequences,
            self.safeguards_before,
            self.S,
            self.F,
            None,
            self.recommendations,
            self.scenario,
        ]


def _as_mapping(record: object) -> Mapping[str, Any]:
    dump = getattr(record, "model_dump", None)
    if callable(dump):
        return dump()
    if isinstance(record, Mapping):
        return record
    raise TypeError(f"레코드는 Mapping 또는 model_dump() 를 가진 객체여야 한다: {type(record)!r}")


def _str_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(str(v) for v in value)  # type: ignore[union-attr]


def node_label(node: str, equipment: Iterable[str]) -> str:
    """노드 열 조립(R-01): 1개면 `"N1 벙커링선 매니폴드"`, 0개면 노드만, 2개 이상은 `·` 연결."""
    items = [e for e in equipment if e]
    if not items:
        return node
    return f"{node} {LIST_JOINER.join(items)}"


def guideword_label(guideword: str, parameter: str) -> str:
    return f"{guideword} ({parameter})"


def normalize_rows(records: Iterable[object]) -> list[WorksheetRow]:
    """dict 목록 또는 `DeviationRecord` 목록 → `WorksheetRow` 목록. `No` 는 입력 순서 1부터."""
    rows: list[WorksheetRow] = []
    for no, record in enumerate(records, start=1):
        m = _as_mapping(record)
        node = str(m.get("node", ""))
        meta = m.get("node_meta") or {}
        equipment = _str_list(meta.get("equipment") if isinstance(meta, Mapping) else None)
        s = None if m.get("S") is None else int(m["S"])
        f = None if m.get("F") is None else int(m["F"])
        causes = _str_list(m.get("causes"))
        safeguards = _str_list(m.get("safeguards_before"))
        recommendations = _str_list(m.get("recommendations"))
        consequences = _str_list(m.get("consequences"))
        evidence_raw = m.get("evidence") or ()
        evidence = tuple(dict(e) for e in evidence_raw if isinstance(e, Mapping))
        confidence = m.get("confidence")
        rows.append(
            WorksheetRow(
                no=no,
                node_label=node_label(node, equipment),
                guideword_label=guideword_label(str(m["guideword"]), str(m["parameter"])),
                deviation=str(m.get("deviation", "")),
                causes=LIST_JOINER.join(causes),
                consequences=LIST_JOINER.join(consequences),
                safeguards_before=LIST_JOINER.join(safeguards),
                S=s,
                F=f,
                recommendations=LIST_JOINER.join(recommendations),
                scenario=str(m.get("scenario", "") or ""),
                node=node,
                # 입력값이 있어도 재계산 — 워크시트 수식과 일치시킨다(Y-2: 기준이 대조표면 표 값)
                risk_score=None if s is None or f is None else load_criteria(m.get("criteria_id")).risk(s, f),
                evidence=evidence,
                confidence=str(confidence) if confidence is not None else None,
                causes_list=causes,
                safeguards_list=safeguards,
                recommendations_list=recommendations,
                criteria_id=m.get("criteria_id"),
                missing=_str_list(m.get("missing")) if m.get("status") == "insufficient" else (),
            )
        )
    return rows
