"""재생 결과 표기 대응표(교열 10/15) — 저장본은 그대로, 화면·내려받기에서만 표기 규칙을 적용한다."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest

from apps.web import replay, service
from apps.web.replay import NOTATION_PATH, REPLAY_DIR, apply_notation, load_notation, load_replays
from tools.build_replay_notation import NOTATION_RULES, TABLES, parse

if TYPE_CHECKING:
    from pathlib import Path

_NUM = re.compile(r"\d+(?:\.\d+)?")
NOTATION = json.loads(NOTATION_PATH.read_text(encoding="utf-8"))


def test_table_is_built_from_the_review_tables() -> None:
    """대응표는 교열표에서 표기 규칙(R1·R2·R3)만 쓴 줄 그대로다 — 손으로 넣은 줄이 없다."""
    rows = [r for path in TABLES for r in parse(path)]
    kept = [{k: r[k] for k in ("ids", "field", "from", "to")} for r in rows if set(r["rules"]) <= NOTATION_RULES]
    assert NOTATION["entries"] == kept
    assert NOTATION["rows_total"] == len(rows) and NOTATION["rows_excluded_wording"] == len(rows) - len(kept)


def test_entries_keep_numbers_and_change_something() -> None:
    for e in NOTATION["entries"]:
        assert _NUM.findall(e["from"]) == _NUM.findall(e["to"]), e
        assert e["from"] != e["to"], e


@pytest.mark.usefixtures("current_replays")
def test_every_entry_lands_exactly_once_on_current_replays() -> None:
    """화면에 나가는 재생에서 대응표 줄이 하나도 빠지지 않고 한 번씩 맞는다 — 재캡처로 원문이 바뀌면 여기서 깨진다."""
    replays = load_replays()
    expected = sum(len(e["ids"]) for e in NOTATION["entries"])
    assert sum(r.meta["notation_applied"] for r in replays.values()) == expected


@pytest.mark.usefixtures("current_replays")
def test_replay_files_stay_as_captured() -> None:
    """적용한 화면 문장은 바뀌었지만, 같은 행의 재생 파일 원문은 AS-IS 그대로다."""
    shown = {r.id: r for res in load_replays().values() for r in res.records}
    raw = {}
    for path in sorted(REPLAY_DIR.glob("*.json")):
        for rec in json.loads(path.read_text(encoding="utf-8")).get("records", []):
            raw.setdefault(rec["id"], []).append(rec)
    e = next(e for e in NOTATION["entries"] if e["field"] == "deviation")
    rid = e["ids"][0]
    assert shown[rid].deviation == e["to"]
    assert any(rec["deviation"] == e["from"] for rec in raw[rid])


def test_text_mismatch_is_left_alone() -> None:
    """원문이 한 글자라도 다르면(옛 캡처·재캡처) 바꾸지 않는다. 원본 레코드도 그대로."""
    table = load_notation()
    e = next(e for e in NOTATION["entries"] if e["field"] == "deviation")
    base = next(r for res in load_replays().values() for r in res.records)
    hit = base.model_copy(update={"id": e["ids"][0], "deviation": e["from"]})
    miss = base.model_copy(update={"id": e["ids"][0], "deviation": e["from"] + " "})
    out, n = apply_notation([hit, miss], table)
    assert n == 1 and out[0].deviation == e["to"] and out[1].deviation == e["from"] + " "
    assert hit.deviation == e["from"]  # model_copy — 원본 불변


def test_consensus_rows_are_skipped() -> None:
    """합의 생성 행은 반복 일치가 문장을 글자로 맞추므로 표기 대응표를 적용하지 않는다."""
    table = load_notation()
    e = next(e for e in NOTATION["entries"] if e["field"] == "causes")
    base = next(r for res in load_replays().values() for r in res.records)
    row = base.model_copy(update={"id": e["ids"][0], "causes": [e["from"]], "consensus": {"runs": 3}})
    out, n = apply_notation([row], table)
    assert n == 0 and out[0].causes == [e["from"]]


@pytest.mark.usefixtures("current_replays")
def test_provenance_says_notation_was_applied() -> None:
    replays = load_replays()
    live = next(r for r in replays.values() if r.meta["notation_applied"])
    assert service.NOTATION_NOTE.format(n=live.meta["notation_applied"]) in service.provenance_line(live)
    bare = service.Result(meta={**live.meta, "notation_applied": 0}, records=live.records)
    assert "표기 규칙" not in service.provenance_line(bare)


def test_missing_table_means_no_change(tmp_path: Path) -> None:
    assert load_notation(tmp_path / "없음.json") == {}
    records = next(iter(load_replays().values())).records
    assert apply_notation(records, {}) == (records, 0)


def test_module_table_is_the_file() -> None:
    assert load_notation() == replay._NOTATION
