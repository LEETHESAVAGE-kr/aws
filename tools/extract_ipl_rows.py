r"""IPL 인정 행 추출 — 지시문 S-5-2. 재생 JSON 에서 `ipl_credited` 가 비어 있지 않은 행을 뽑아 사람 검토표(마크다운)로.

    python -m tools.extract_ipl_rows data/replay/p1_2026101X.json data/replay/n2sg_2026101X.json \
        --limit 20 --out docs/IPL검토_20261015.md

표 끝 두 열(동의/비동의·메모)은 사람이 채운다. 실호출 없음 — 파일만 읽는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from core import ipl

COLUMNS = ("#", "파일", "노드", "가이드워드", "파라미터", "이탈", "빈도", "인정 IPL", "빈도 근거", "동의/비동의", "메모")


def extract(paths: list[Path], limit: int = 20) -> list[dict[str, Any]]:
    """파일 순서·레코드 순서대로 IPL 을 1개 이상 인정한 행을 최대 `limit` 개."""
    rows: list[dict[str, Any]] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for r in data.get("records", []):
            credited = r.get("ipl_credited") or []
            if not credited:
                continue
            rows.append({
                "#": len(rows) + 1, "파일": path.name, "노드": r.get("node", data.get("node", "")),
                "가이드워드": r.get("guideword", ""), "파라미터": r.get("parameter", ""), "이탈": r.get("deviation", ""),
                "빈도": f"{r.get('frequency_base')}→{r.get('F')}",
                "인정 IPL": " · ".join(f"{i['name']}({ipl.CLASS_LABELS.get(i.get('class', ''), i.get('class'))})"
                                      for i in credited),
                "빈도 근거": r.get("frequency_basis", ""), "동의/비동의": "", "메모": "",
            })
            if len(rows) >= limit:
                return rows
    return rows


def to_markdown(rows: list[dict[str, Any]]) -> str:
    def cell(value: Any) -> str:
        return str(value).replace("|", r"\|").replace("\n", " ")

    lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    lines += ["| " + " | ".join(cell(row[c]) for c in COLUMNS) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IPL 인정 행 추출 — 사람 검토표(마크다운)")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--out", type=Path, default=None, help="없으면 표준출력")
    args = parser.parse_args(argv)
    rows = extract(args.paths, args.limit)
    text = to_markdown(rows)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    print(f"IPL 인정 행 {len(rows)}개", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
