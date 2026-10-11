"""tools/measure_union.score — 사전등록_합치기_20261011 §3-1 (판정자는 가짜)."""

from __future__ import annotations

from types import SimpleNamespace

from tools.measure_union import score


def _rec(gw: str, param: str, *causes: str) -> SimpleNamespace:
    return SimpleNamespace(guideword=gw, parameter=param, causes=list(causes), status="applicable")


def test_score_counts_exact_sentence_per_mode_and_blind_pool() -> None:
    gold = [{"id": "g1", "guideword": "More", "parameter": "압력", "deviation": "고압", "causes": ["밸브 오조작"]},
            {"id": "g2", "guideword": "No", "parameter": "유량", "deviation": "무유량", "causes": ["펌프 정지"]}]
    modes = {
        "single1": [_rec("More", "압력", "열팽창")],
        "single2": [_rec("More", "압력", "밸브 잘못 닫음")],
        "single3": [_rec("More", "압력", "열팽창", "밸브를 잘못 닫음")],
        "intersection": [_rec("More", "압력", "열팽창")],
        "union": [_rec("More", "압력", "열팽창", "밸브 잘못 닫음")],
    }
    seen: list[list[str]] = []

    def judge(_dev: str, _cause: str, pool: list[str]) -> list[int]:
        seen.append(pool)
        return [i for i, t in enumerate(pool) if "밸브" in t]

    result = score(gold, modes, judge)
    assert seen == [["열팽창", "밸브 잘못 닫음", "밸브를 잘못 닫음"]]  # 칸 없는 g2 는 판정자를 부르지 않는다
    assert result["hits"] == {"single1": 0, "single2": 1, "single3": 1, "intersection": 0, "union": 1}
    assert result["total"] == 2


def test_score_union_rep_only() -> None:
    """합치기 칸은 대표 문장만 — 같은 묶음의 다른 문장만 맞았으면 적중 아님(사전등록 §3-1)."""
    gold = [{"guideword": "More", "parameter": "압력", "causes": ["밸브 오조작"]}]
    modes = {"single1": [_rec("More", "압력", "밸브 잘못 닫음")], "single2": [_rec("More", "압력", "밸브 오작동 닫힘")],
             "union": [_rec("More", "압력", "밸브 오작동 닫힘")]}
    result = score(gold, modes, lambda _d, _c, pool: [pool.index("밸브 잘못 닫음")])
    assert result["hits"] == {"single1": 1, "single2": 0, "union": 0}
