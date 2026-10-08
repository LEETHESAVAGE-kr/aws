"""spec:export-formats T-06 — 오프라인 테스트 + 골든 스냅샷 (R-01~R-09).

전부 오프라인이다. `core/export` 는 LLM 무관이며, FR-03 mock 경로 시험 1건만 `core.agent` 를
임포트한다(양방향 입력 완료 조건). 스냅샷 갱신: `UPDATE_SNAPSHOT=1 pytest tests/test_export.py`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import openpyxl
import pytest

from core.export import (
    HEADERS,
    LOPA_NAME,
    REPORT_NAME,
    SHEET_ORDER,
    XLSX_NAME,
    ConfidenceReport,
    WorksheetRow,
    build_report,
    export_all,
    export_xlsx,
    normalize_rows,
    render_lopa,
    report_json,
)
from core.export.lopa import DISCLAIMER, TBD, select_top
from core.export.report import RISK_BANDS
from core.export.rows import node_label
from core.export.xlsx import (
    COLUMN_WIDTHS,
    CONFIDENCE_UNASSIGNED,
    EVIDENCE_EMPTY_NOTE,
    EVIDENCE_HEADERS,
    FREEZE_PANES,
)

if TYPE_CHECKING:
    from openpyxl.workbook.workbook import Workbook

_ROOT = Path(__file__).parent.parent
_GOLD_PATH = _ROOT / "data" / "gold" / "hazop_nh3.json"
_RATING_PATH = _ROOT / "data" / "gold" / "rating_scale.json"
_SNAPSHOT_PATH = Path(__file__).parent / "golden" / "export_gold34.snapshot.json"
_EXPORT_DIR = _ROOT / "core" / "export"

# 정량 표기 금지 패턴 (R-07): "/yr", "PFD=숫자", "1E-5" 류
_QUANT_RE = re.compile(r"\d\s*/\s*yr|PFD\s*=\s*\d|\d[eE]-\d")


def _gold() -> list[dict[str, Any]]:
    return json.loads(_GOLD_PATH.read_text(encoding="utf-8"))


def _rows() -> list[WorksheetRow]:
    return normalize_rows(_gold())


def _wb(tmp_path: Path, rows: list[WorksheetRow] | None = None) -> Workbook:
    path = export_xlsx(rows if rows is not None else _rows(), tmp_path / "out.xlsx")
    return openpyxl.load_workbook(path)


def _record_with_evidence() -> dict[str, Any]:
    rec = dict(_gold()[0])
    rec["evidence"] = [
        {"source_id": "KOSHA-P-1", "doc_title": "가이드", "locator": "§3", "quote": "인용문"}
    ]
    rec["confidence"] = "grounded"
    return rec


# ── R-01 정규화 ───────────────────────────────────────────────────────────────
def test_gold_rows_match_original_labels() -> None:
    rows = _rows()
    assert len(rows) == 34
    assert rows[0].no == 1
    assert rows[0].node_label == "N1 벙커링선 매니폴드"
    assert rows[0].guideword_label == "No (유량)"
    assert all(r.confidence is None for r in rows)  # 골드셋은 미부여 — inferred 로 채우지 않는다
    assert all(r.evidence == () for r in rows)
    assert all(r.risk_score == r.S * r.F for r in rows)


def test_node_label_rules() -> None:
    assert node_label("N1", []) == "N1"
    assert node_label("N1", ["매니폴드"]) == "N1 매니폴드"
    assert node_label("N1", ["매니폴드", "호스"]) == "N1 매니폴드·호스"


def test_risk_score_is_recomputed_from_s_and_f() -> None:
    rec = dict(_gold()[0])
    rec["risk_score"] = 99  # 어긋난 입력값
    row = normalize_rows([rec])[0]
    assert row.risk_score == rec["S"] * rec["F"]


def test_dict_and_model_inputs_normalize_identically() -> None:
    from core.agent import DeviationRecord

    gold = _gold()
    models = [
        DeviationRecord.model_validate({**g, "evidence": [], "confidence": "inferred"})
        for g in gold
    ]
    from_dict = normalize_rows(gold)
    from_model = normalize_rows(models)
    for a, b in zip(from_dict, from_model, strict=True):
        assert a.cells() == b.cells()
        assert b.confidence == "inferred"


# ── R-02 HAZOP워크시트 ────────────────────────────────────────────────────────
def test_worksheet_structure_matches_original(tmp_path: Path) -> None:
    ws = _wb(tmp_path)[SHEET_ORDER[0]]
    assert ws.max_row == 37 and ws.max_column == 12  # 1 헤더 + 34 + 빈 행 + 범례
    assert [c.value for c in ws[1]] == list(HEADERS)
    assert ws.freeze_panes == FREEZE_PANES
    widths = {k: v.width for k, v in ws.column_dimensions.items() if v.width}
    assert widths == {k: float(v) for k, v in COLUMN_WIDTHS.items()}
    assert "I" not in widths
    assert ws["A36"].value is None and isinstance(ws["A37"].value, str)


def test_risk_column_is_formula_not_value(tmp_path: Path) -> None:
    ws = _wb(tmp_path)[SHEET_ORDER[0]]
    for r in range(2, 36):
        assert ws.cell(row=r, column=10).value == f"=H{r}*I{r}"
    # risk_score 값(정수)이 J 열 어디에도 들어가지 않는다
    assert not any(isinstance(ws.cell(row=r, column=10).value, int) for r in range(2, 36))


def test_worksheet_row_values(tmp_path: Path) -> None:
    ws = _wb(tmp_path)[SHEET_ORDER[0]]
    first = [c.value for c in ws[2]]
    assert first[:4] == [1, "N1 벙커링선 매니폴드", "No (유량)", "이송 개시 후 유량 전무"]
    assert first[7:9] == [2, 3]
    assert first[11] == "기타"


# ── R-03 평가기준·스크리닝 ────────────────────────────────────────────────────
def test_sheet_order_and_rating_sheet(tmp_path: Path) -> None:
    wb = _wb(tmp_path)
    assert wb.sheetnames == list(SHEET_ORDER)
    ws = wb["평가기준"]
    scale = json.loads(_RATING_PATH.read_text(encoding="utf-8"))
    assert ws.max_row == 18 and ws.max_column == 3
    assert [ws.cell(row=r, column=2).value for r in range(2, 7)] == [1, 2, 3, 4, 5]
    assert ws["C2"].value == scale["severity"][0]["definition"]
    assert ws["A14"].value == scale["risk_bands"][0]["range"]


def test_screening_matrix_formulas(tmp_path: Path) -> None:
    ws = _wb(tmp_path)["스크리닝"]
    assert ws["A2"].value == "S＼F" and ws["A3"].value == "S5" and ws["A7"].value == "S1"
    b3 = ws["B3"].value
    assert b3.startswith("=COUNTIFS(") and "$H$2:$H$35" in b3 and "$I$2:$I$35" in b3
    assert ws["F7"].value.endswith(",1,HAZOP워크시트!$I$2:$I$35,5)")
    assert ws.max_row == 7  # 시나리오 선정표는 포함하지 않는다(R-03 결정)


# ── R-04 근거 / R-05 신뢰도 ───────────────────────────────────────────────────
def test_evidence_sheet_has_note_when_empty(tmp_path: Path) -> None:
    ws = _wb(tmp_path)["근거"]
    assert [c.value for c in ws[1]] == list(EVIDENCE_HEADERS)
    assert ws.max_row == 2 and ws["A2"].value == EVIDENCE_EMPTY_NOTE


def test_evidence_sheet_lists_attached_evidence(tmp_path: Path) -> None:
    rows = normalize_rows([_record_with_evidence()])
    ws = _wb(tmp_path, rows)["근거"]
    assert ws.max_row == 2
    assert [c.value for c in ws[2]] == [1, "KOSHA-P-1", "가이드", "§3", "인용문"]


def test_confidence_sheet_gold_is_unassigned(tmp_path: Path) -> None:
    ws = _wb(tmp_path)["신뢰도"]
    assert ws.max_row == 35
    assert {ws.cell(row=r, column=2).value for r in range(2, 36)} == {CONFIDENCE_UNASSIGNED}


def test_confidence_sheet_shows_labels(tmp_path: Path) -> None:
    gold = _gold()[:3]
    gold[0] = {**gold[0], "confidence": "inferred"}
    gold[1] = {**gold[1], "confidence": "review"}
    gold[2] = {**gold[2], "confidence": "grounded"}
    ws = _wb(tmp_path, normalize_rows(gold))["신뢰도"]
    assert [ws.cell(row=r, column=2).value for r in (2, 3, 4)] == ["추론", "검토 필요", "근거 다수"]  # Y-4 표기


# ── R-06 리포트 ───────────────────────────────────────────────────────────────
def test_report_gold_fields() -> None:
    rep = build_report(_rows())
    assert rep.record_count == 34
    assert rep.nodes == ["N1", "N2", "N3", "N4"]
    assert rep.confidence_distribution == {
        "grounded": 0,
        "single_source": 0,
        "inferred": 0,
        "review": 0,
        "unassigned": 34,
    }
    assert rep.evidence_attachment_rate is None  # 0 이 아니라 null (FR-04 전)
    assert rep.matrix_coverage is None
    assert sum(rep.risk_distribution.values()) == 34
    assert sum(sum(v.values()) for v in rep.sf_matrix.values()) == 34
    assert set(rep.pending) == {"evidence_attachment_rate", "matrix_coverage"}


def test_report_fills_values_when_available() -> None:
    rows = normalize_rows([_record_with_evidence(), _gold()[1]])
    rep = build_report(rows, generated_at="2026-09-11T00:00:00", coverage=(42, 42))
    assert rep.evidence_attachment_rate == 0.5
    assert rep.matrix_coverage == {"expected": 42, "judged": 42, "ratio": 1.0}
    assert rep.confidence_distribution["grounded"] == 1
    assert rep.pending == {}
    assert rep.generated_at == "2026-09-11T00:00:00"


def test_risk_bands_match_rating_scale() -> None:
    scale = json.loads(_RATING_PATH.read_text(encoding="utf-8"))
    expected = [(b["range"], b["judgement"]) for b in scale["risk_bands"]]
    assert [(f"{lo}~{hi}", name) for lo, hi, name in RISK_BANDS] == expected


# ── R-07 LOPA (A안) ───────────────────────────────────────────────────────────
def test_lopa_top_n_order() -> None:
    rows = _rows()
    top = select_top(rows, 5)
    expected = sorted(rows, key=lambda r: (-r.risk_score, r.no))[:5]
    assert [r.no for r in top] == [r.no for r in expected]
    assert all(top[i].risk_score >= top[i + 1].risk_score for i in range(4))


def test_lopa_is_qualitative_placeholder() -> None:
    md = render_lopa(_rows())
    assert DISCLAIMER in md
    assert md.count("\n## 시나리오 ") == 5
    assert md.count(TBD) >= 5 * 6
    assert "미판정" in md
    assert not [line for line in md.splitlines() if _QUANT_RE.search(line)]


def test_lopa_uses_only_record_text() -> None:
    rows = _rows()
    md = render_lopa(rows, top_n=1)
    top = select_top(rows, 1)[0]
    for text in (*top.causes_list, *top.safeguards_list, *top.recommendations_list):
        assert text in md


# ── R-08 재현성 · export_all ──────────────────────────────────────────────────
def test_export_all_is_reproducible(tmp_path: Path) -> None:
    a = export_all(_gold(), tmp_path / "a")
    b = export_all(_gold(), tmp_path / "b")
    assert set(a) == {"xlsx", "report", "lopa"}
    assert a["report"].name == REPORT_NAME and a["lopa"].name == LOPA_NAME
    assert a["xlsx"].name == XLSX_NAME
    assert a["report"].read_bytes() == b["report"].read_bytes()
    assert a["lopa"].read_text(encoding="utf-8") == b["lopa"].read_text(encoding="utf-8")
    wa, wb_ = openpyxl.load_workbook(a["xlsx"]), openpyxl.load_workbook(b["xlsx"])
    for name in SHEET_ORDER:
        va = [[c.value for c in row] for row in wa[name].iter_rows()]
        vb = [[c.value for c in row] for row in wb_[name].iter_rows()]
        assert va == vb


def test_generated_at_is_injected_not_measured(tmp_path: Path) -> None:
    paths = export_all(_gold(), tmp_path, generated_at="2026-09-11")
    rep = json.loads(paths["report"].read_text(encoding="utf-8"))
    assert rep["generated_at"] == "2026-09-11"
    assert "생성 시각: 2026-09-11" in paths["lopa"].read_text(encoding="utf-8")


def test_fr03_mock_output_exports_through_same_path(tmp_path: Path) -> None:
    """양방향 입력 완료 조건 — FR-03 생성 결과(mock)를 골드셋과 같은 함수로 내보낸다."""
    from test_generate import N1_META, _generator

    generator, _client = _generator()
    records = generator.generate(N1_META)
    assert records
    paths = export_all(
        records, tmp_path, coverage=(generator.expected_cells, generator.judged_cells)
    )
    wb = openpyxl.load_workbook(paths["xlsx"])
    ws = wb[SHEET_ORDER[0]]
    assert ws.max_row == len(records) + 3
    assert ws["J2"].value == "=H2*I2"
    assert {wb["신뢰도"].cell(row=r, column=2).value for r in range(2, len(records) + 2)} == {"추론"}
    assert wb["근거"]["A2"].value == EVIDENCE_EMPTY_NOTE
    rep = json.loads(paths["report"].read_text(encoding="utf-8"))
    assert rep["confidence_distribution"]["inferred"] == len(records)
    assert rep["matrix_coverage"]["ratio"] == 1.0
    assert rep["evidence_attachment_rate"] is None


def test_export_package_has_no_llm_or_agent_imports() -> None:
    for py in _EXPORT_DIR.glob("*.py"):
        src = py.read_text(encoding="utf-8")
        imports = [
            line for line in src.splitlines() if line.lstrip().startswith(("import ", "from "))
        ]
        for banned in ("core.llm", "core.agent", "boto3", "botocore", "..llm", "..agent"):
            assert not [line for line in imports if banned in line], f"{py.name}: {banned}"


# ── R-09 골든 스냅샷 ──────────────────────────────────────────────────────────
def _snapshot(tmp_path: Path) -> dict[str, Any]:
    paths = export_all(_gold(), tmp_path / "snap")
    wb = openpyxl.load_workbook(paths["xlsx"])
    ws = wb[SHEET_ORDER[0]]
    return {
        "sheets": wb.sheetnames,
        "worksheet": {
            "max_row": ws.max_row,
            "max_column": ws.max_column,
            "headers": [c.value for c in ws[1]],
            "widths": {k: v.width for k, v in ws.column_dimensions.items() if v.width},
            "risk_formulas": [ws.cell(row=r, column=10).value for r in range(2, ws.max_row - 1)],
            "freeze": ws.freeze_panes,
            "row2": [c.value for c in ws[2]],
            "row35": [c.value for c in ws[35]],
        },
        "rating": {"max_row": wb["평가기준"].max_row, "max_column": wb["평가기준"].max_column},
        "screening": {"b3": wb["스크리닝"]["B3"].value, "max_row": wb["스크리닝"].max_row},
        "evidence": {"max_row": wb["근거"].max_row},
        "confidence": {
            "max_row": wb["신뢰도"].max_row,
            "values": sorted({wb["신뢰도"].cell(row=r, column=2).value for r in range(2, 36)}),
        },
        "report": json.loads(paths["report"].read_text(encoding="utf-8")),
        "lopa_headings": [
            line
            for line in paths["lopa"].read_text(encoding="utf-8").splitlines()
            if line.startswith("## ")
        ],
    }


def test_golden_snapshot(tmp_path: Path) -> None:
    current = _snapshot(tmp_path)
    if os.environ.get("UPDATE_SNAPSHOT") == "1":
        _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SNAPSHOT_PATH.write_text(
            json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        pytest.skip("스냅샷을 갱신했다")
    assert _SNAPSHOT_PATH.exists(), "스냅샷 없음 — UPDATE_SNAPSHOT=1 로 생성"
    expected = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert current == expected


def test_report_json_is_valid_model_roundtrip() -> None:
    rep = build_report(_rows())
    text = report_json(rep)
    assert text.endswith("\n")
    assert ConfidenceReport.model_validate_json(text) == rep
