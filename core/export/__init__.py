"""내보내기 공개 인터페이스 — spec:export-formats (PRD §5 FR-07, design.md §3·§7).

LLM 무관. `core/llm`·`core/agent` 를 임포트하지 않는다 — 자격증명 없이 동작해야 한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .lopa import DEFAULT_TOP_N, render_lopa, write_lopa
from .report import ConfidenceReport, build_report, report_json, write_report
from .rows import HEADERS, WorksheetRow, normalize_rows
from .xlsx import SHEET_ORDER, export_xlsx

if TYPE_CHECKING:
    from collections.abc import Iterable

XLSX_NAME = "hazop.xlsx"
REPORT_NAME = "confidence_report.json"
LOPA_NAME = "lopa_draft.md"


def export_all(
    records: Iterable[object],
    out_dir: Path,
    *,
    generated_at: str | None = None,
    coverage: tuple[int, int] | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Path]:
    """골드셋 dict 목록이든 `DeviationRecord` 목록이든 같은 경로로 세 산출물을 쓴다.

    `generated_at` 은 재현성을 위해 호출자가 주입한다(R-08). 기본 `None` → 산출물에 시각 없음.
    `coverage=(expected_cells, judged_cells)` 는 FR-03 생성기 관측값(없으면 리포트에 `null`).
    """
    rows = normalize_rows(records)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "xlsx": export_xlsx(rows, out_dir / XLSX_NAME),
        "report": write_report(
            build_report(rows, generated_at=generated_at, coverage=coverage),
            out_dir / REPORT_NAME,
        ),
        "lopa": write_lopa(rows, out_dir / LOPA_NAME, top_n=top_n, generated_at=generated_at),
    }
    return paths


__all__ = [
    "HEADERS",
    "LOPA_NAME",
    "REPORT_NAME",
    "SHEET_ORDER",
    "XLSX_NAME",
    "ConfidenceReport",
    "WorksheetRow",
    "build_report",
    "export_all",
    "export_xlsx",
    "normalize_rows",
    "render_lopa",
    "report_json",
    "write_lopa",
    "write_report",
]
