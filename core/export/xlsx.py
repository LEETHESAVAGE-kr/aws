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

from .report import rows_criteria
from .rows import HEADERS, WorksheetRow, consensus_detail, consensus_verdict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from openpyxl.worksheet.worksheet import Worksheet

    from core.criteria import Criteria

# ── 실측 상수 (지시문 D · requirements 실측표. 추측으로 바꾸지 않는다) ─────────────
SHEET_ORDER: Final[tuple[str, ...]] = ("HAZOP워크시트", "평가기준", "스크리닝", "법령·MSDS 인용", "신뢰도")
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
    "인용 없음 — 이 결과는 법령·MSDS 발췌를 인용하지 않았다(인용을 끈 실행·전문가 정답지·인용 0건). 행 내용은 AI 추론이다."
)
CONFIDENCE_HEADERS: Final[tuple[str, ...]] = ("No", "confidence", "사유")
#: Z-3 정보 부족 보류 행이 있을 때만 붙는 시트 — 무엇이 없어서 판단하지 않았는지.
HELD_SHEET: Final[str] = "확인 필요"
#: §8 C 합의 생성 — 같은 입력으로 판정을 N번 돌린 결과의 문장별 일치. 합의 결과일 때만 붙는다.
REPEAT_SHEET: Final[str] = "반복 일치"
REPEAT_HEADERS: Final[tuple[str, ...]] = ("No", "가이드워드", "판정", "구분", "문장·값", "일치", "반영")
HELD_HEADERS: Final[tuple[str, ...]] = ("No", "가이드워드", "이탈 초안", "필요한 정보")
HELD_LEGEND: Final[str] = "S·F·위험도 빈칸 = 정보 부족으로 판정 보류(입력·공식 문서에 없는 사업장 정보가 필요 — '확인 필요' 시트)."
#: R-10 검토 기록 — 검토가 있을 때만 6번째 시트로 붙는다(AC-10-1). "원 No" 는 검토 전 화면 번호.
REVIEW_SHEET: Final[str] = "검토 기록"
REVIEW_HEADERS: Final[tuple[str, ...]] = ("원 No", "검토", "가이드워드", "이탈", "수정한 열")
CONFIDENCE_UNASSIGNED: Final[str] = "미부여"
# R-05 표. 이 spec 은 판정하지 않고 표시만 한다(판정은 FR-06).
CONFIDENCE_REASONS: Final[dict[str | None, tuple[str, str]]] = {
    "grounded": ("문서 2건 이상 인용", "서로 다른 공식 문서 2건 이상 인용 · 인용 원문 대조 통과 · 검증 플래그 0 (Y-4)"),
    "single_source": ("문서 1건 인용", "공식 문서 1건 인용 · 인용 원문 대조 통과 · 검증 플래그 0 (Y-4)"),
    "inferred": ("AI 추론", "공식 문서 인용 없음 — 모델 추론 · 검증 플래그 0"),
    "review": ("검토 필요", "검증 플래그(근거 없는 규격·수치, 원문과 다른 인용) 또는 스키마 2회 실패 — 사람 검토 필요"),
    "insufficient": ("정보 부족", "입력·공식 문서에 없는 사업장 정보(미상)가 있어야 판단할 수 있어 S·F 를 매기지 않고 보류 (Z-3)"),
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
def sheet_headers(criteria: Criteria) -> list[str]:
    """12열 머리글 — S·F 열 이름에 기준의 단계 수를 적는다(Y-2). 골드셋 기준이면 원본 `HEADERS` 그대로."""
    headers = list(HEADERS)
    headers[HEADERS.index("S(1-5)")] = f"S(1-{criteria.s_max})"
    headers[HEADERS.index("F(1-5)")] = f"F(1-{criteria.f_max})"
    return headers


def _write_worksheet(ws: Worksheet, rows: Sequence[WorksheetRow], criteria: Criteria) -> int:
    """12열 워크시트를 쓰고 마지막 데이터 행 번호를 돌려준다."""
    _write_header(ws, sheet_headers(criteria))
    for letter, width in COLUMN_WIDTHS.items():
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = FREEZE_PANES

    r = 1
    for r, row in enumerate(rows, start=2):
        values = row.cells()
        # J 열 — 값 대신 수식(곱 =H*I, 대조표 =INDEX(...)). 보류 행(S·F 빈칸)은 비운다(Z-3)
        values[9] = None if row.held else criteria.excel_formula(r)
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=r, column=col, value=value)
            cell.alignment = _BODY_ALIGN
            cell.border = _BORDER
    last = r
    # 원본 레이아웃: 데이터 다음 빈 행 1 + 범례 행 1 (A열 1칸)
    legend = LEGEND_TEXT if criteria.method == "product" else LEGEND_TEXT.replace(
        "위험도=수식(S×F)", f"위험도=수식(대조표, {criteria.short})"
    )
    if any(row.held for row in rows):
        legend += " " + HELD_LEGEND
    ws.cell(row=last + 2, column=1, value=legend)
    return last


# ── 시트 2: 평가기준 (R-03) ─────────────────────────────────────────────────────
def _definition(item: dict[str, Any]) -> str:
    return f"{item['label']}: {item['definition']}" if item.get("label") else str(item["definition"])


def _write_rating(ws: Worksheet, scale: dict[str, Any], criteria: Criteria | None = None) -> None:
    """골드셋 기준은 예전 배치 그대로. 공식 기준(Y-2)은 끝에 대조표·위험관리기준·출처를 덧붙인다."""
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["C"].width = 60
    ws.append(["구분", "등급", "정의"])
    for item in scale["severity"]:
        ws.append(["S 강도", int(item["grade"]), _definition(item)])
    for item in scale["frequency"]:
        ws.append(["F 빈도", int(item["grade"]), _definition(item)])
    ws.append([None, None, None])
    ws.append(["위험도 구간", "판정", "조치"])
    for band in scale["risk_bands"]:
        ws.append([band["range"], band["judgement"], band["action"]])
    ws.append([None, None, None])
    for note in scale.get("notes", []):
        ws.append([note, None, None])
    if criteria is None or "scale_file" in criteria.data:
        return
    if criteria.method == "lookup":
        ws.append([None, None, None])
        ws.append(["위험도 대조표", "S＼F", *[f"F{f}" for f in range(1, criteria.f_max + 1)]])
        for s in range(criteria.s_max, 0, -1):
            ws.append([None, f"S{s}", *[criteria.risk(s, f) for f in range(1, criteria.f_max + 1)]])
    for level in scale.get("risk_levels", []):
        ws.append([f"위험도 {level['level']}", level["label"], level["management"]])
    ws.append([None, None, None])
    ws.append(["기준", criteria.short, criteria.name])
    ws.append(["출처", scale.get("issuer"), f"{scale.get('doc')} — {scale.get('locator')}"])
    ws.append(["URL", scale.get("retrieved_at"), scale.get("url")])
    ws.append(["이용 조건", None, scale.get("license")])


# ── 시트 3: 스크리닝 — 5×5 매트릭스만 (R-03) ────────────────────────────────────
def screening_formula(s: int, f: int, last_row: int) -> str:
    return f"=COUNTIFS(HAZOP워크시트!$H$2:$H${last_row},{s},HAZOP워크시트!$I$2:$I${last_row},{f})"


def _write_screening(ws: Worksheet, last_row: int, s_max: int = 5, f_max: int = 5) -> None:
    last = max(last_row, 2)  # 데이터 0건이어도 수식 범위가 깨지지 않게
    ws.column_dimensions["A"].width = 12
    ws.append([f"{s_max}×{f_max} 매트릭스 (이탈 건수 분포, COUNTIFS로 워크시트와 자동 연동)"])
    ws.append(["S＼F", *[f"F{f}" for f in range(1, f_max + 1)]])
    for s in range(s_max, 0, -1):
        ws.append([f"S{s}", *[screening_formula(s, f, last) for f in range(1, f_max + 1)]])


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
    review_log: Sequence[Sequence[object]] | None = None,
) -> Path:
    """시트 5개(`SHEET_ORDER`)를 가진 통합문서를 `path` 에 쓴다.

    `review_log`(R-10)가 비지 않으면 `검토 기록` 시트를 덧붙인다 — 행은 `REVIEW_HEADERS` 순서의 값.
    """
    criteria = rows_criteria(rows)  # Y-2 — 레코드의 기준(섞이면 ValueError)
    if rating_scale is not None:
        scale = rating_scale
    elif "scale_file" in criteria.data:
        scale = _load_rating_scale()
    else:
        scale = criteria.data
    wb = Workbook()
    ws_main = wb.active
    ws_main.title = SHEET_ORDER[0]
    last_row = _write_worksheet(ws_main, rows, criteria)
    _write_rating(wb.create_sheet(SHEET_ORDER[1]), scale, criteria)
    _write_screening(wb.create_sheet(SHEET_ORDER[2]), last_row, criteria.s_max, criteria.f_max)
    _write_evidence(wb.create_sheet(SHEET_ORDER[3]), rows)
    _write_confidence(wb.create_sheet(SHEET_ORDER[4]), rows)
    held = [row for row in rows if row.held]
    if held:
        ws_held = wb.create_sheet(HELD_SHEET)
        _write_header(ws_held, HELD_HEADERS)
        for col, width in zip("ABCD", (6, 18, 40, 50), strict=True):
            ws_held.column_dimensions[col].width = width
        for row in held:
            ws_held.append([row.no, row.guideword_label, row.deviation, " · ".join(row.missing)])
    repeated = [row for row in rows if row.consensus]
    if repeated:
        ws_rep = wb.create_sheet(REPEAT_SHEET)
        _write_header(ws_rep, REPEAT_HEADERS)
        for col, width in zip("ABCDEFG", (6, 18, 30, 8, 60, 12, 18), strict=True):
            ws_rep.column_dimensions[col].width = width
        for row in repeated:
            verdict = consensus_verdict(row.consensus, row.held)
            details = consensus_detail(row.consensus) or [("", "", "", "")]
            for kind, text, agree, used in details:
                ws_rep.append([row.no, row.guideword_label, verdict, kind, text, agree, used])
    if review_log:
        ws_review = wb.create_sheet(REVIEW_SHEET)
        _write_header(ws_review, REVIEW_HEADERS)
        for entry in review_log:
            ws_review.append(list(entry))
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
    "HELD_HEADERS",
    "HELD_SHEET",
    "CONFIDENCE_HEADERS",
    "FREEZE_PANES",
    "LEGEND_TEXT",
    "REVIEW_HEADERS",
    "REVIEW_SHEET",
    "SHEET_ORDER",
    "confidence_label",
    "export_xlsx",
    "risk_formula",
    "screening_formula",
]
