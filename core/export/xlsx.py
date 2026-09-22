"""xlsx 내보내기 — R-02~R-05 (spec:export-formats, PRD §5 FR-07).

원본 `data/raw/D1_HAZOP_워크시트.xlsx` 의 실측 구조(requirements.md 실측표)를 재현한다.
위험도(J)는 값이 아니라 수식 `=H{r}*I{r}` 이다 — `risk_score` 값을 셀에 넣지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from .rows import HEADERS, WorksheetRow

if TYPE_CHECKING:
    from collections.abc import Sequence

    from openpyxl.worksheet.worksheet import Worksheet

# ── 실측 상수 (지시문 D · requirements 실측표. 추측으로 바꾸지 않는다) ─────────────
SHEET_ORDER: Final[tuple[str, ...]] = ("HAZOP워크시트", "평가기준", "스크리닝", "근거", "신뢰도")
COLUMN_WIDTHS: Final[dict[str, float]] = {
    "A": 4.5,
    "B": 17,
    "C": 15,
    "D": 20,
    "E": 22,
    "F": 24,
    "G": 17,
    "H": 6,
    # I 는 원본 미지정 — 설정하지 않는다
    "J": 7,
    "K": 30,
    "L": 10,
}
HEADER_FILL: Final[str] = "1F4E79"
FREEZE_PANES: Final[str] = "A2"
LEGEND_TEXT: Final[str] = "범례: S·F=입력 점수, 위험도=수식(S×F). hazop-copilot FR-07 생성물."

EVIDENCE_HEADERS: Final[tuple[str, ...]] = ("No", "source_id", "doc_title", "locator", "quote")
EVIDENCE_EMPTY_NOTE: Final[str] = (
    "근거 없음 — FR-04(evidence-citation) 미완료. evidence[] 가 채워지면 이 시트가 자동으로 채워진다."
)
CONFIDENCE_HEADERS: Final[tuple[str, ...]] = ("No", "confidence", "사유")
CONFIDENCE_UNASSIGNED: Final[str] = "미부여"
# R-05 표. 이 spec 은 판정하지 않고 표시만 한다(판정은 FR-06).
CONFIDENCE_REASONS: Final[dict[str | None, tuple[str, str]]] = {
    "grounded": ("grounded", "근거 인용 첨부·검증 통과 (FR-04/FR-06)"),
    "inferred": ("inferred", "모델 추론 — 근거 미첨부(FR-04)·검증 미수행(FR-06)"),
    "review": ("review", "스키마 검증 2회 실패 행 — 사람 검토 필요"),
    None: (CONFIDENCE_UNASSIGNED, "입력에 confidence 필드 없음(골드셋 등 사람 작성 레코드)"),
}

_RATING_SCALE_PATH: Final[Path] = (
    Path(__file__).parent.parent.parent / "data" / "gold" / "rating_scale.json"
)

_THIN: Final[Side] = Side(style="thin")
_BORDER: Final[Border] = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HEADER_FONT: Final[Font] = Font(bold=True, color="FFFFFF")
_HEADER_FILL: Final[PatternFill] = PatternFill("solid", fgColor=HEADER_FILL)
_HEADER_ALIGN: Final[Alignment] = Alignment(horizontal="center", vertical="center", wrap_text=True)
_BODY_ALIGN: Final[Alignment] = Alignment(vertical="top", wrap_text=True)


def _load_rating_scale() -> dict[str, Any]:
    return json.loads(_RATING_SCALE_PATH.read_text(encoding="utf-8"))


def _write_header(ws: Worksheet, headers: Sequence[str]) -> None:
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=text)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _HEADER_ALIGN
        cell.border = _BORDER


def risk_formula(row: int) -> str:
    """위험도 열 수식. 원본과 같은 형태 `=H2*I2` (R-02)."""
    return f"=H{row}*I{row}"


# ── 시트 1: HAZOP워크시트 (R-02) ───────────────────────────────────────────────
def _write_worksheet(ws: Worksheet, rows: Sequence[WorksheetRow]) -> int:
    """12열 워크시트를 쓰고 마지막 데이터 행 번호를 돌려준다."""
    _write_header(ws, HEADERS)
    for letter, width in COLUMN_WIDTHS.items():
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = FREEZE_PANES

    r = 1
    for r, row in enumerate(rows, start=2):
        values = row.cells()
        values[9] = risk_formula(r)  # J 열 — 값 대신 수식
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=r, column=col, value=value)
            cell.alignment = _BODY_ALIGN
            cell.border = _BORDER
    last = r
    # 원본 레이아웃: 데이터 다음 빈 행 1 + 범례 행 1 (A열 1칸)
    ws.cell(row=last + 2, column=1, value=LEGEND_TEXT)
    return last


# ── 시트 2: 평가기준 (R-03) ─────────────────────────────────────────────────────
def _write_rating(ws: Worksheet, scale: dict[str, Any]) -> None:
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["C"].width = 60
    ws.append(["구분", "등급", "정의"])
    for item in scale["severity"]:
        ws.append(["S 강도", int(item["grade"]), item["definition"]])
    for item in scale["frequency"]:
        ws.append(["F 빈도", int(item["grade"]), item["definition"]])
    ws.append([None, None, None])
    ws.append(["위험도 구간", "판정", "조치"])
    for band in scale["risk_bands"]:
        ws.append([band["range"], band["judgement"], band["action"]])
    ws.append([None, None, None])
    for note in scale.get("notes", []):
        ws.append([note, None, None])


# ── 시트 3: 스크리닝 — 5×5 매트릭스만 (R-03) ────────────────────────────────────
def screening_formula(s: int, f: int, last_row: int) -> str:
    return f"=COUNTIFS(HAZOP워크시트!$H$2:$H${last_row},{s},HAZOP워크시트!$I$2:$I${last_row},{f})"


def _write_screening(ws: Worksheet, last_row: int) -> None:
    last = max(last_row, 2)  # 데이터 0건이어도 수식 범위가 깨지지 않게
    ws.column_dimensions["A"].width = 12
    ws.append(["5×5 매트릭스 (이탈 건수 분포, COUNTIFS로 워크시트와 자동 연동)"])
    ws.append(["S＼F", "F1", "F2", "F3", "F4", "F5"])
    for s in range(5, 0, -1):
        ws.append([f"S{s}", *[screening_formula(s, f, last) for f in range(1, 6)]])


# ── 시트 4: 근거 (R-04) ─────────────────────────────────────────────────────────
def _write_evidence(ws: Worksheet, rows: Sequence[WorksheetRow]) -> None:
    _write_header(ws, EVIDENCE_HEADERS)
    for col, width in zip("ABCDE", (6, 16, 30, 16, 60), strict=True):
        ws.column_dimensions[col].width = width
    written = 0
    for row in rows:
        for e in row.evidence:
            ws.append(
                [row.no, e.get("source_id"), e.get("doc_title"), e.get("locator"), e.get("quote")]
            )
            written += 1
    if written == 0:
        ws.cell(row=2, column=1, value=EVIDENCE_EMPTY_NOTE)


# ── 시트 5: 신뢰도 (R-05) ───────────────────────────────────────────────────────
def confidence_label(confidence: str | None) -> tuple[str, str]:
    """(표기, 사유). 표에 없는 값은 그대로 표기하고 사유는 '알 수 없는 등급'."""
    if confidence in CONFIDENCE_REASONS:
        return CONFIDENCE_REASONS[confidence]
    return (str(confidence), "알 수 없는 등급 — FR-06 표에 없음")


def _write_confidence(ws: Worksheet, rows: Sequence[WorksheetRow]) -> None:
    _write_header(ws, CONFIDENCE_HEADERS)
    for col, width in zip("ABC", (6, 12, 60), strict=True):
        ws.column_dimensions[col].width = width
    for row in rows:
        label, reason = confidence_label(row.confidence)
        ws.append([row.no, label, reason])


# ── 공개 진입점 ───────────────────────────────────────────────────────────────
def export_xlsx(
    rows: Sequence[WorksheetRow],
    path: Path,
    *,
    rating_scale: dict[str, Any] | None = None,
) -> Path:
    """시트 5개(`SHEET_ORDER`)를 가진 통합문서를 `path` 에 쓴다."""
    scale = rating_scale if rating_scale is not None else _load_rating_scale()
    wb = Workbook()
    ws_main = wb.active
    ws_main.title = SHEET_ORDER[0]
    last_row = _write_worksheet(ws_main, rows)
    _write_rating(wb.create_sheet(SHEET_ORDER[1]), scale)
    _write_screening(wb.create_sheet(SHEET_ORDER[2]), last_row)
    _write_evidence(wb.create_sheet(SHEET_ORDER[3]), rows)
    _write_confidence(wb.create_sheet(SHEET_ORDER[4]), rows)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


__all__ = [
    "COLUMN_WIDTHS",
    "CONFIDENCE_REASONS",
    "CONFIDENCE_UNASSIGNED",
    "EVIDENCE_EMPTY_NOTE",
    "EVIDENCE_HEADERS",
    "CONFIDENCE_HEADERS",
    "FREEZE_PANES",
    "LEGEND_TEXT",
    "SHEET_ORDER",
    "confidence_label",
    "export_xlsx",
    "risk_formula",
    "screening_formula",
]
