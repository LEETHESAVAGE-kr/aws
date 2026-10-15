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
OUT = ROOT / "data" / "replay_notation.json"
NOTATION_RULES = {"R1", "R2", "R3", "R4", "R5", "R6", "R7"}
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


def main() -> None:
    rows = [row for path in TABLES for row in parse(path)]
    kept = [r for r in rows if set(r["rules"]) <= NOTATION_RULES]  # type: ignore[arg-type]
    data = {
        "_comment": (
            "재생 결과 문장 교열 대응표(교열 10/15). 저장된 재생 JSON 은 고치지 않고 화면·내려받기에서만 적용한다. "
            "교열표의 모든 줄(R1 종결·R2 기호·R3 '~에 의한'·R4 조어·R5 명사 연쇄·R6 영어·R7 조사·호응)이며 뜻은 바꾸지 않았다. "
            "빌더: tools/build_replay_notation.py, 원본: docs/교열_20261015/"
        ),
        "rules": sorted(NOTATION_RULES),
        "source_tables": [p.name for p in TABLES],
        "rows_total": len(rows),
        "rows_excluded_wording": len(rows) - len(kept),
        "entries": [{k: r[k] for k in ("ids", "field", "from", "to")} for r in kept],
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"{OUT.relative_to(ROOT)}: {len(kept)}줄 (제외 {len(rows) - len(kept)}줄, 표 {len(TABLES)}개)")


if __name__ == "__main__":
    main()
