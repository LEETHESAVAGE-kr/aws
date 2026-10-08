"""LOPA 초안 Markdown — R-07·R-08 (spec:export-formats, PRD §5 FR-07). **A안: 정량 자리표시자.**

이 프로젝트가 가진 것은 정성 등급 S·F(1~5)뿐이다. steering domain.md §4.3 은 정량 빈도·확률을
스크리닝 F 등급과 혼용하지 말라고 못 박는다. 그래서 이 모듈은 IEF·PFD·TMEL·RRF·SIL 을 **계산하지
않는다** — 전부 `TBD` 자리표시자이며, 문헌 근거(FR-04/FR-05)가 확보되면 그때 채운다.
IE·IPL 후보도 레코드에 적힌 텍스트만 그대로 옮긴다(NFR-03).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from core.criteria import load_criteria

from .report import risk_band

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .rows import WorksheetRow

DEFAULT_TOP_N: Final[int] = 5
TBD: Final[str] = "TBD (문헌 근거 필요 — FR-04/FR-05)"
IPL_UNJUDGED: Final[str] = "3원칙(독립성·유효성·감사가능성): 미판정"
DISCLAIMER: Final[str] = (
    "정성 스크리닝(S×F) 기반 초안. IEF·PFD·TMEL·RRF 등 정량값은 미산정이며 "
    "문헌 근거(FR-04/FR-05) 확보 전에는 채우지 않는다."
)
QUANT_ROWS: Final[tuple[str, ...]] = (
    "IE 빈도(IEF)",
    "조건수정자(점화·재실·치명 확률)",
    "목표 완화 빈도(TMEL)",
    "IPL 별 PFD",
    "요구 위험 감소율(RRF)",
    "요구 SIL",
)


def select_top(rows: Sequence[WorksheetRow], top_n: int = DEFAULT_TOP_N) -> list[WorksheetRow]:
    """위험도 내림차순, 동률은 No 오름차순 (R-07)."""
    return sorted(rows, key=lambda r: (-r.risk_score, r.no))[:top_n]


def _section(k: int, r: WorksheetRow) -> list[str]:
    criteria = load_criteria(r.criteria_id)  # Y-2 — 곱이면 'S×F', 대조표면 '대조표(S·F 조합)'
    lines = [
        f"## 시나리오 {k}: No.{r.no} {r.guideword_label} — {r.deviation}",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 노드 | {r.node_label} |",
        f"| 가이드워드 | {r.guideword_label} |",
        f"| S / F | {r.S} / {r.F} |",
        f"| 위험도({criteria.method_text()}) | {r.risk_score} — {risk_band(r.risk_score, criteria)} |",
        f"| 시나리오 연계 | {r.scenario or '-'} |",
        "",
        "### 시나리오 서술",
        "",
        f"원인({r.causes or '기재 없음'}) → 이탈({r.deviation}) → 결과({r.consequences or '기재 없음'})",
        "",
        "### IE(개시사건) 후보 — 레코드 `원인` 원문",
        "",
    ]
    if r.causes_list:
        lines += [f"- {c} — IEF: {TBD}" for c in r.causes_list]
    else:
        lines.append("- (원인 기재 없음)")
    lines += ["", "### IPL(독립방호계층) 후보 — 레코드 `기존 안전장치`·`권고` 원문", ""]
    ipl = [f"- [기존] {s} — PFD: {TBD} · {IPL_UNJUDGED}" for s in r.safeguards_list]
    ipl += [f"- [권고] {s} — PFD: {TBD} · {IPL_UNJUDGED}" for s in r.recommendations_list]
    lines += ipl or ["- (기재 없음)"]
    lines += ["", "### 정량 산정 — 미산정", "", "| 항목 | 값 |", "|---|---|"]
    lines += [f"| {name} | {TBD} |" for name in QUANT_ROWS]
    lines.append("")
    return lines


def render_lopa(
    rows: Sequence[WorksheetRow],
    *,
    top_n: int = DEFAULT_TOP_N,
    generated_at: str | None = None,
) -> str:
    top = select_top(rows, top_n)
    lines = [
        f"# LOPA 초안 — 위험도 상위 {len(top)}건",
        "",
        f"> {DISCLAIMER}",
        "",
        f"생성 시각: {generated_at or '미기록'} · 대상 이탈 {len(rows)}건 중 상위 {len(top)}건 · "
        "형식: NH3 QRA `LOPA_S1_C1.md` 준용(정량 절은 자리표시자)",
        "",
    ]
    for k, r in enumerate(top, start=1):
        lines += _section(k, r)
    return "\n".join(lines).rstrip("\n") + "\n"


def write_lopa(
    rows: Sequence[WorksheetRow],
    path: Path,
    *,
    top_n: int = DEFAULT_TOP_N,
    generated_at: str | None = None,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_lopa(rows, top_n=top_n, generated_at=generated_at), encoding="utf-8")
    return path


__all__ = [
    "DEFAULT_TOP_N",
    "DISCLAIMER",
    "IPL_UNJUDGED",
    "QUANT_ROWS",
    "TBD",
    "render_lopa",
    "select_top",
    "write_lopa",
]
