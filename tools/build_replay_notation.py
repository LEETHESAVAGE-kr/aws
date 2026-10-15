"""재생 결과 문장 교열 대응표 빌더 — `docs/교열_20261015/결과표_교열_*.md` → `data/replay_notation.json`.

교열표(사람이 검산한 AS-IS → TO-BE, 행 id·칸 단위)의 줄을 모두 옮긴다 — R1 종결 통일 · R2 기호 · R3 '~에 의한' 풀기
· R4 조어·한자어 · R5 명사 연쇄 · R6 영어 · R7 조사·호응. 10/15 처음엔 R1~R3 만 넣었다가 같은 날 사용자 요청으로 낱말 수정
86줄도 넣었다(뜻을 바꾼 줄 없음 — 86줄 전부 읽고 확인). 내용 오류로 보이는 줄은 교열표 '확인 필요'에만 있고 여기 없다.

저장된 재생 JSON(`data/replay/`)은 고치지 않는다. `apps/web/replay.py` 가 불러올 때 이 표를 (행 id, 칸, 원문 그대로)가
맞는 문장에만 적용한다 — 원문이 한 글자라도 다르면(옛 캡처·재캡처) 그대로 둔다.

    python tools/build_replay_notation.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = sorted((ROOT / "docs" / "교열_20261015").glob("결과표_교열_*_*.md"))
#: 2차 교열(10/15 오후, 사용자 교정 예시의 공통 규칙). 표마다 AS-IS 는 앞 단계까지 적용한 화면 문장이다 —
#: 1단계 E(한국어 뒤 영어 괄호 빼기)·U(사용자 예시) → 2단계 T1~T5(번역투). 단계를 거쳐 (원문 → 최종문)으로 합친다.
STAGES = [
    sorted((ROOT / "docs" / "교열_20261015").glob("결과표_2차교열_1_*.md")),
    sorted((ROOT / "docs" / "교열_20261015").glob("결과표_2차교열_2_*.md")),
]
OUT = ROOT / "data" / "replay_notation.json"
NOTATION_RULES = {"R1", "R2", "R3", "R4", "R5", "R6", "R7", "E", "U", "T1", "T2", "T3", "T4", "T5"}
FIELDS = {
    "이탈": "deviation", "원인": "causes", "결과": "consequences", "기존 안전장치": "safeguards_before",
    "권고": "recommendations", "시나리오 연계": "scenario", "필요한 정보": "missing",
}
_PIPE = "\x00"
_ROW = re.compile(r"^\| [inp]\d")


def parse(path: Path) -> list[dict[str, object]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not _ROW.match(line):
            continue
        cells = [c.strip().replace(_PIPE, "|") for c in line.replace("\\|", _PIPE).split("|")[1:-1]]
        if len(cells) != 5:
            raise ValueError(f"{path.name}: 열 수 {len(cells)} — {line[:60]}")
        ids, field, before, after, rules = cells
        rows.append({
            "ids": [i.strip() for i in ids.split(",")],
            "field": FIELDS[field],
            "from": before,
            "to": after,
            "rules": sorted(r for r in re.split(r"[ ,·]+", rules) if r),
        })
    return rows


def compose(first: list[dict[str, object]], stages: list[list[dict[str, object]]]) -> list[dict[str, object]]:
    """1차 줄(원문 → 1차문) 위에 단계 줄(앞 단계 문장 → 새 문장)을 차례로 얹어 (원문 → 최종문) 줄로 합친다.

    앞 단계에서 바뀌지 않은 문장은 AS-IS 가 곧 원문이다. 같은 (칸, 원문, 최종문)은 행 id 를 묶어 한 줄로 둔다.
    """
    origin: dict[tuple[str, str, str], str] = {}  # (id, 칸, 지금 문장) → 원문
    for r in first:
        for rid in r["ids"]:  # type: ignore[attr-defined]
            origin[(rid, r["field"], r["to"])] = r["from"]  # type: ignore[index]
    for stage in stages:
        for r in stage:
            for rid in r["ids"]:  # type: ignore[attr-defined]
                src = origin.pop((rid, r["field"], r["from"]), r["from"])  # type: ignore[arg-type]
                origin[(rid, r["field"], r["to"])] = src  # type: ignore[index]
    grouped: dict[tuple[str, str, str], list[str]] = {}
    for (rid, field, now), src in origin.items():
        if now != src:
            grouped.setdefault((field, src, now), []).append(rid)
    return [{"ids": ids, "field": f, "from": a, "to": b} for (f, a, b), ids in grouped.items()]


def build() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """(교열표 모든 줄, 대응표 항목). 규칙 밖 줄이 있으면 실패한다."""
    first = [row for path in TABLES for row in parse(path)]
    stages = [[row for path in paths for row in parse(path)] for paths in STAGES]
    rows = first + [r for s in stages for r in s]
    outside = [r for r in rows if not set(r["rules"]) <= NOTATION_RULES]  # type: ignore[arg-type]
    if outside:
        raise ValueError(f"규칙 밖 줄 {len(outside)}개: {outside[0]}")
    return rows, compose(first, stages)


def main() -> None:
    rows, kept = build()
    data = {
        "_comment": (
            "재생 결과 문장 교열 대응표(교열 10/15). 저장된 재생 JSON 은 고치지 않고 화면·내려받기에서만 적용한다. "
            "1차 교열표(R1 종결·R2 기호·R3 '~에 의한'·R4 조어·R5 명사 연쇄·R6 영어·R7 조사·호응)와 2차 교열표"
            "(E 영어 괄호 빼기·U 사용자 예시·T1~T5 번역투)를 단계대로 합친 (원문 → 최종문)이며 뜻은 바꾸지 않았다. "
            "빌더: tools/build_replay_notation.py, 원본: docs/교열_20261015/"
        ),
        "rules": sorted(NOTATION_RULES),
        "source_tables": [p.name for p in TABLES] + [p.name for paths in STAGES for p in paths],
        "rows_total": len(rows),
        "rows_excluded_wording": 0,
        "entries": kept,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"{OUT.relative_to(ROOT)}: 항목 {len(kept)}개 (교열표 {len(rows)}줄)")


if __name__ == "__main__":
    main()
