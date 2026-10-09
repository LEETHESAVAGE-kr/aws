"""오프라인 시험 — spec:self-verification T-02 (R-01~R-04). 네트워크 0회."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from core.agent import DeviationRecord, verify

_ROOT = Path(__file__).resolve().parents[1]
_REPLAY = _ROOT / "data" / "replay"
_LIVE = sorted(_REPLAY.glob("n[1-4]_20260929.json"))
log = logging.getLogger(__name__)

# design.md §5 — (필드, 삽입 문자열). 규격 5 + 수치 5, 필드 분산.
DEFECTS: list[tuple[str, str]] = [
    ("deviation", "KOSHA GUIDE P-140"),
    ("causes", "API 520"),
    ("consequences", "NFPA 55"),
    ("safeguards_before", "KS B 6750"),
    ("recommendations", "산업안전보건기준에 관한 규칙 제261조"),
    ("causes", "10 kPag"),
    ("consequences", "-33 ℃"),
    ("safeguards_before", "25 ppm"),
    ("recommendations", "15 %"),
    ("consequences", "30 분"),
]


def _records(node: str = "n1") -> list[DeviationRecord]:
    payload = json.loads((_REPLAY / f"{node}_20260929.json").read_text(encoding="utf-8"))
    return [DeviationRecord.model_validate(r) for r in payload["records"]]


def _inject(record: DeviationRecord, field: str, text: str) -> DeviationRecord:
    value = getattr(record, field)
    new = f"{value} ({text})" if isinstance(value, str) else [f"{value[0]} ({text})", *value[1:]] if value else [text]
    return record.model_copy(update={field: new})


def _one(record: DeviationRecord, **update: object) -> DeviationRecord:
    base = {"deviation": "", "causes": [], "consequences": [], "safeguards_before": [], "recommendations": [], "scenario": ""}
    return record.model_copy(update={**base, **update})


def test_injected_defects_flagged() -> None:
    clean = _records()
    targets = clean[:: len(clean) // len(DEFECTS)][: len(DEFECTS)]
    assert verify(targets)[1].flagged == 0  # 삽입 전 깨끗해야 삽입 효과만 잰다
    injected = [_inject(r, f, t) for r, (f, t) in zip(targets, DEFECTS, strict=True)]
    out, summary = verify(injected)
    reviewed = [r.confidence == "review" for r in out]
    log.info("결함 삽입 10건 중 review %d건 · by_rule=%s", sum(reviewed), summary.by_rule)
    assert sum(reviewed) >= 9
    assert sum(reviewed[:5]) >= 4 and sum(reviewed[5:]) >= 4  # R-01·R-02 각각
    assert summary.by_rule == {"unverified_standard": 5, "unsupported_number": 5, "fabricated_citation": 0}


def test_node_meta_numbers_not_flagged() -> None:  # AC-02-1
    base = _records()[0]
    record = _one(
        base.model_copy(update={"node_meta": base.node_meta.model_copy(update={"P_kPag": 350, "T_degC": -33})}),
        causes=["350 kPag 초과 운전", "-33 ℃ 이하 냉각", "350.0 kPa 도달"],
    )
    out, summary = verify([record])
    assert summary.flags == () and out[0].confidence == "inferred"
    other = _one(base, causes=["350 kPag 초과 운전"])  # P_kPag 가 없으면 같은 문자열도 플래그
    assert verify([other])[1].by_rule["unsupported_number"] == 1


def test_same_match_counted_once_per_record() -> None:  # AC-01-2
    record = _one(_records()[0], causes=["API 520 준수"], recommendations=["API  520 재검토", "NFPA 55"])
    flags = verify([record])[1].flags
    assert [(f.field, f.matched) for f in flags] == [("causes[0]", "API 520"), ("recommendations[1]", "NFPA 55")]


def test_deviation_numbers_not_targeted() -> None:  # AC-02-3
    base = _records()[0]
    assert verify([_one(base, deviation="압력 10% 상승")])[1].flags == ()
    assert verify([_one(base, causes=["압력 10% 상승"])])[1].flags[0].matched == "10%"


def test_evidence_suppresses_standard_flag() -> None:  # R-01 — evidence 에 있으면 근거 있음
    base = _one(_records()[0], causes=["API 520 기준 릴리프 용량"])
    cited = base.model_copy(update={"evidence": [{"doc_title": "API 520 Part I", "quote": "..."}]})
    assert verify([base])[1].flagged == 1
    assert verify([cited])[1].flagged == 0


def test_order_count_and_originals_preserved() -> None:  # R-03
    clean = _records()
    records = [*clean[:3], _inject(clean[3], "causes", "API 520"), clean[4]]
    before = [r.model_dump() for r in records]
    out, summary = verify(records)
    assert [r.id for r in out] == [r.id for r in records]
    assert [r.confidence for r in out] == ["inferred"] * 3 + ["review", "inferred"]
    assert [r.model_dump() for r in records] == before  # 원본 불변
    assert out[0] is records[0] and out[3] is not records[3]
    assert "grounded" not in {r.confidence for r in out}
    assert (summary.total, summary.flagged) == (5, 1)


def test_missing_cells_reported() -> None:  # R-04
    assert verify([], expected_cells=77, judged_cells=70)[1].missing_cells == 7
    assert verify([])[1].missing_cells is None


def test_verify_accepts_mappings() -> None:
    record = _inject(_records()[0], "causes", "NFPA 55")
    assert verify([record.model_dump()])[0][0].confidence == "review"


def test_no_llm_import() -> None:
    source = (_ROOT / "core" / "agent" / "verify.py").read_text(encoding="utf-8")
    assert "core.llm" not in source and "..llm" not in source


@pytest.mark.parametrize("path", _LIVE, ids=lambda p: p.stem)
def test_live_replay_baseline_logged(path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """9/29 live 재생 전체의 플래그 수 — 단언하지 않고 기록만 한다(design.md §5)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    out, summary = verify(
        payload["records"], expected_cells=payload.get("expected_cells"), judged_cells=payload.get("judged_cells")
    )
    with caplog.at_level(logging.INFO):
        log.info(
            "%s: total=%d flagged=%d by_rule=%s missing_cells=%s",
            path.stem, summary.total, summary.flagged, summary.by_rule, summary.missing_cells,
        )
    assert len(out) == len(payload["records"])


def test_numbers_written_in_input_not_flagged() -> None:
    """10/9 배포 실호출: 입력 안전장치의 설정값(95·100 MPa)과 MPa 로 적은 운전압력(90 MPa → 90000 kPa)이 🔴 로 잡혔다."""
    from core.agent.generate import NodeMeta

    meta = NodeMeta(node="X1", substance="수소", phase="gas", P_kPag=90000.0,
                    equipment=["고압 저장용기"], safeguards=["고압 경보(설정 95 MPa)", "안전밸브(설정 100 MPa)"])
    rec = {"id": "x1-001", "node": "X1", "node_meta": meta.model_dump(), "guideword": "More", "parameter": "압력",
           "deviation": "과압", "causes": ["90 MPa 초과 운전"], "consequences": ["파열"],
           "safeguards_before": ["고압 경보(설정 95 MPa)", "안전밸브(설정 100 MPa)"], "S": 4, "F": 2,
           "recommendations": ["120 MPa 설계 검토"], "criteria_id": "kosha_cc37_2026"}
    _, summary = verify([rec])
    assert [f.matched for f in summary.flags] == ["120 MPa"]  # 입력에 없던 수치만
