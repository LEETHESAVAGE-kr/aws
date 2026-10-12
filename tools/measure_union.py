"""합치기(합집합) 골드셋 대조 — 사전등록: docs/사전등록_합치기_20261011.md (규칙을 여기서 바꾸지 않는다).

    python -m tools.measure_union --out results/union_<시각> [--only N1]

노드마다 판정 3번 한 벌 → 한 번 생성 #1~#3 · 공통 답 · 합치기를 같은 원자료에서 만든다. 실 API 비용이 든다.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Any

from core.agent import consensus as cs
from core.agent.generate import HazopGenerator, _build_records, load_generator_config
from core.criteria import GOLD_CRITERIA
from core.llm import Message, get_bedrock_client
from tools import capture_replay
from tools._replay import normalize_parameter, recall_for_node
from tools.measure_yg5 import _load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
NODES = ("N1", "N2", "N3", "N4")
JUDGE_SYSTEM = (
    "당신은 HAZOP 검토자입니다. 기준 원인 하나와 후보 원인 문장 목록을 받습니다. "
    "후보 중 기준 원인과 같은 사고 원인(같은 기기·같은 고장 또는 오조작 방식)을 가리키는 것의 번호를 모두 고르세요. "
    "표현이 달라도 같은 원인이면 고르고, 결과·대책이 비슷할 뿐 원인이 다르면 고르지 마세요. 없으면 빈 목록."
)
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"matches": {"type": "array", "items": {"type": "integer"}}},
    "required": ["matches"],
}
#: (기준 이탈, 기준 원인, 후보 문장) → 고른 후보 번호(0부터)
Judge = Callable[[str, str, list[str]], list[int]]


def _key(guideword: str, parameter: str) -> tuple[str, str]:
    return guideword, normalize_parameter(parameter)


def causes_by_cell(records: Sequence[Any]) -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    for r in records:
        out.setdefault(_key(r.guideword, r.parameter), []).extend(r.causes or [])
    return out


def score(gold: Sequence[Mapping[str, Any]], modes: Mapping[str, Sequence[Any]], judge: Judge) -> dict[str, Any]:
    """사전등록 §3-1. 후보 = 그 칸에서 한 번 생성 실행들이 낸 원인 전부 — 합치기·공통 답의 대표 문장은 그 부분집합이다."""
    cells = {name: causes_by_cell(recs) for name, recs in modes.items()}
    singles = [n for n in modes if n.startswith("single")]
    hits = dict.fromkeys(modes, 0)
    rows = []
    for g in gold:
        key = _key(g["guideword"], g["parameter"])
        pool = list(dict.fromkeys(t for n in singles for t in cells[n].get(key, [])))
        gold_cause = " / ".join(g.get("causes") or [])
        picked = [pool[i] for i in judge(str(g.get("deviation", "")), gold_cause, pool) if 0 <= i < len(pool)] if pool else []
        row = {"id": g.get("id"), "key": list(key), "gold_cause": gold_cause, "candidates": pool, "picked": picked}
        for name in modes:
            row[name] = any(t in picked for t in cells[name].get(key, []))
            hits[name] += row[name]
        rows.append(row)
    return {"total": len(gold), "hits": hits, "rows": rows}


def burden(records: Sequence[Any]) -> dict[str, int]:
    applicable = [r for r in records if r.status != cs.HELD]
    return {"rows": len(applicable), "cause_sentences": sum(len(r.causes or []) for r in applicable)}


def haiku_judge() -> Judge:
    from core.llm.gateway_client import GatewayClient

    client = GatewayClient(profile="verifier")

    def judge(deviation: str, cause: str, candidates: list[str]) -> list[int]:
        listing = "\n".join(f"{i}. {t}" for i, t in enumerate(candidates))
        user = f"기준 이탈: {deviation}\n기준 원인: {cause}\n\n후보:\n{listing}\n\n같은 원인을 가리키는 후보 번호를 JSON 으로."
        resp = client.converse(JUDGE_SYSTEM, [Message(role="user", content=user)], response_schema=JUDGE_SCHEMA)
        return [int(i) for i in json.loads(resp.content or '{"matches": []}').get("matches", [])]

    return judge


def run_node(name: str, config: Any, judge: Judge) -> dict[str, Any]:
    node_meta = capture_replay.NODE_METAS[name]
    gold = capture_replay._gold_rows(name, capture_replay.default_split(name))  # noqa: SLF001
    started = time.perf_counter()
    gen = HazopGenerator(get_bedrock_client(), config, criteria_id=GOLD_CRITERIA)
    union = gen.generate(node_meta)
    latency = time.perf_counter() - started
    raw = gen.consensus_raw
    similarity = cs.e5_similarity()
    inter_batches = [b for gw in raw if (b := cs.merge_batches(raw[gw], gen.parameters, similarity)) is not None]
    modes: dict[str, list[Any]] = {
        f"single{k + 1}": _build_records(node_meta, [r[k] for r in raw.values() if r[k] is not None], GOLD_CRITERIA)[0]
        for k in range(3)
    }
    modes["intersection"] = _build_records(node_meta, inter_batches, GOLD_CRITERIA)[0]
    modes["union"] = union
    causes = score(gold, modes, judge)
    return {
        "node": name,
        "parameters": gen.parameters,
        "latency_s": round(latency, 1),
        "cost_usd": round(gen.total_cost_usd, 4),
        "failed_runs": {gw: sum(b is None for b in r) for gw, r in raw.items()},
        "valid": all(b is not None for r in raw.values() for b in r),  # 부록 A — 실패 판정이 있으면 합산 제외
        "cause_recall": {"total": causes["total"], "hits": causes["hits"]},
        "cell_recall": {n: recall_for_node(recs, gold)["matched"] for n, recs in modes.items()},
        "burden": {n: burden(recs) for n, recs in modes.items()},
        "_judge_rows": causes["rows"],
    }


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    excluded = [r["node"] for r in rows if not r.get("valid", True)]
    rows = [r for r in rows if r.get("valid", True)]
    total = sum(r["cause_recall"]["total"] for r in rows)

    def pooled(metric: str, mode: str) -> int:
        return sum(r[metric]["hits"][mode] if metric == "cause_recall" else r[metric][mode] for r in rows)

    out: dict[str, Any] = {"nodes": [r["node"] for r in rows], "excluded_invalid": excluded, "gold_total": total}
    for metric in ("cause_recall", "cell_recall"):
        singles = [pooled(metric, f"single{k}") for k in (1, 2, 3)]
        out[metric] = {"single": singles, "single_mean": round(mean(singles), 2),
                       "intersection": pooled(metric, "intersection"), "union": pooled(metric, "union")}
    out["burden_cause_sentences"] = {m: sum(r["burden"][m]["cause_sentences"] for r in rows)
                                     for m in ("single1", "single2", "single3", "intersection", "union")}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", choices=NODES, default=None)
    args = parser.parse_args(argv)
    _load_dotenv()
    os.environ.setdefault("HAZOP_ALLOW_LIVE", "true")
    logging.basicConfig(level=logging.WARNING)
    config = dataclasses.replace(load_generator_config(), consensus_runs=3, consensus_union=True)
    out = args.out if args.out.is_absolute() else REPO_ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(dataclasses.asdict(config), indent=2), encoding="utf-8")
    judge = haiku_judge()
    rows = []
    for name in NODES:
        if args.only and name != args.only:
            continue
        row = run_node(name, config, judge)
        (out / f"{name}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if not k.startswith("_")}, ensure_ascii=False), flush=True)
    if rows:
        s = summary(rows)
        (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(s, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
