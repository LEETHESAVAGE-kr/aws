"""§8 C 합의 생성 실측 — 사전 등록: docs/사전등록_C_합의생성_20261009.md (규칙을 여기서 바꾸지 않는다).

    python -m tools.measure_consensus --out results/consensus_<시각> [--only N1|N2|direct]

입력마다 합의 실행 2벌. A = 실제 경로(N1·N2 는 `HazopGenerator.generate`, 직접 입력은 `service.run_live`),
B = A 와 같은 파라미터·NodeMeta 로 판정만 3회. 지연·비용은 A 로만 잰다. 판정 6회(A1~3·B1~3)로 단일 실행
안정성 기준을 만든다. 결과는 `results/`(gitignore). 실 API 비용이 든다.
"""

from __future__ import annotations

import argparse
import dataclasses
import itertools
import json
import logging
import os
import time
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from apps.web import service
from core.agent import consensus as cs
from core.agent.generate import (
    HazopGenerator,
    NodeMeta,
    _build_records,
    _select_guidewords,
    load_generator_config,
)
from core.criteria import GOLD_CRITERIA, OFFICIAL_CRITERIA
from core.llm import get_bedrock_client
from tools import capture_replay
from tools._replay import recall_for_node
from tools.measure_xg7 import INPUT, _RetryCounter
from tools.measure_yg5 import _load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
LATENCY_CAP_S = 160.0  # 사전등록 §5-2
EMPTY_CAUSE_CAP = 0.20  # 사전등록 §5-4


# ── 지표(오프라인 — 시험 가능) ────────────────────────────────────────────────
def cell_keys(guidewords: list[str], parameters: list[str]) -> list[tuple[str, str]]:
    """분모 = 가이드워드 × 열거 파라미터 전 셀(사전등록 §3 ①)."""
    return [(gw, cs.norm_param(p)) for gw in guidewords for p in parameters]


def pass_states(passes: dict[str, list[dict[str, Any] | None]], run: int, keys: list[tuple[str, str]]) -> dict:
    """판정 1회(run)의 셀 상태."""
    tables = {gw: cs.cells_by_param(batches[run]) for gw, batches in passes.items()}
    return {k: cs.cell_state(tables.get(k[0], {}).get(k[1])) for k in keys}


def vote_states(states: list[dict], keys: list[tuple[str, str]]) -> dict:
    """여러 판정의 셀 투표(합의와 같은 규칙). 전부 누락이면 누락."""
    return {k: cs.vote([s[k] for s in states]) or cs.MISSING for k in keys}


def agreement(x: dict, y: dict) -> float:
    return sum(x[k] == y[k] for k in x) / len(x) if x else float("nan")


def stability(singles: list[dict], keys: list[tuple[str, str]]) -> dict[str, Any]:
    """단일 15쌍 평균 · A1 vs B1 · 합의 A vs B · 3+3 분할 10가지 평균. singles = [A1,A2,A3,B1,B2,B3]."""
    pairs = [agreement(a, b) for a, b in itertools.combinations(singles, 2)]
    splits = []
    for group in itertools.combinations(range(6), 3):
        if 0 not in group:
            continue  # (G, 여집합) 과 (여집합, G) 는 같은 분할 — 0 이 든 쪽만 센다(10가지)
        rest = [i for i in range(6) if i not in group]
        splits.append(agreement(vote_states([singles[i] for i in group], keys),
                                vote_states([singles[i] for i in rest], keys)))
    a, b = vote_states(singles[:3], keys), vote_states(singles[3:], keys)
    return {
        "cells": len(keys),
        "single_mean_15pairs": mean(pairs),
        "single_min": min(pairs),
        "single_max": max(pairs),
        "single_A1_vs_B1": agreement(singles[0], singles[3]),
        "consensus_A_vs_B": agreement(a, b),
        "consensus_split_mean_10": mean(splits),
        "consensus_split_min": min(splits),
        "matches": {"single_15pairs_sum": sum(round(p * len(keys)) for p in pairs),
                    "consensus_A_vs_B": round(agreement(a, b) * len(keys))},
    }


def sentence_stats(records: list[Any]) -> dict[str, Any]:
    """문장 합의 분포(사전등록 §3 ⑥). 해당 행만."""
    applicable = [r for r in records if r.status != cs.HELD and r.consensus]
    dist: dict[str, Counter] = {f: Counter() for f in cs.LIST_FIELDS}
    for r in applicable:
        for f in cs.LIST_FIELDS:
            dist[f].update(f"{c['agree']}/{c['of']}" for c in r.consensus.get(f, []))
    empty = sum(not r.causes for r in applicable)
    split = sum(len(set(r.consensus["S_values"])) > 1 or len(set(r.consensus["F_values"])) > 1 for r in applicable)
    return {
        "applicable_rows": len(applicable),
        "held_rows": sum(r.status == cs.HELD for r in records),
        "agree_distribution": {f: dict(sorted(c.items(), reverse=True)) for f, c in dist.items()},
        "rows_without_kept_cause": empty,
        "rows_without_kept_cause_rate": empty / len(applicable) if applicable else None,
        "grade_split_rows": split,
        "grade_split_rate": split / len(applicable) if applicable else None,
    }


# ── 실행 ──────────────────────────────────────────────────────────────────────
def _fixed(generator: HazopGenerator, items: list[dict[str, str]]) -> HazopGenerator:
    """B 벌 — 열거 호출 없이 A 의 파라미터 목록을 그대로 쓴다."""
    generator._enumerate_parameters = lambda _meta: [dict(p) for p in items]  # type: ignore[method-assign]
    return generator


def _strip(raw: dict[str, list[dict[str, Any] | None]]) -> dict[str, list[dict[str, Any] | None]]:
    return {gw: [None if b is None else {k: v for k, v in b.items() if k != "_passages"} for b in runs]
            for gw, runs in raw.items()}


def _judge_cost(gen: HazopGenerator) -> list[float]:
    """실행별 판정 비용 합(가이드워드 전체)."""
    return [sum(costs[r] for costs in gen.consensus_costs.values()) for r in range(3)]


def run_input(name: str, config: Any) -> dict[str, Any]:
    counter = _RetryCounter()
    for logger_name in ("core.llm.client", "anthropic"):
        logging.getLogger(logger_name).addHandler(counter)
        logging.getLogger(logger_name).setLevel(logging.DEBUG)
    try:
        holder: dict[str, HazopGenerator] = {}
        started = time.perf_counter()
        if name == "direct":
            criteria_id = OFFICIAL_CRITERIA

            class _Kept(HazopGenerator):
                def __init__(self, *a: Any, **k: Any) -> None:
                    super().__init__(*a, **k)
                    holder["A"] = self

            original = service.HazopGenerator
            service.HazopGenerator = _Kept  # type: ignore[misc]
            try:
                result = service.run_live(INPUT, service.Result(meta={}))
            finally:
                service.HazopGenerator = original  # type: ignore[misc]
            latency_a = time.perf_counter() - started
            gen_a, records_a = holder["A"], result.records
            node_meta = NodeMeta(**result.meta["node_meta"])
            cost_a = result.meta["cost_usd"]  # 입력 해석 포함
            gold: list[dict[str, Any]] = []
        else:
            criteria_id = GOLD_CRITERIA
            node_meta = capture_replay.NODE_METAS[name]
            gen_a = HazopGenerator(get_bedrock_client(), config, criteria_id=criteria_id)
            records_a = gen_a.generate(node_meta)
            latency_a = time.perf_counter() - started
            cost_a = gen_a.total_cost_usd
            gold = capture_replay._gold_rows(name, capture_replay.default_split(name))  # noqa: SLF001
        retries_a = (len(counter.ours), len(counter.sdk))

        started_b = time.perf_counter()
        gen_b = _fixed(HazopGenerator(get_bedrock_client(), config, criteria_id=criteria_id), gen_a.parameter_items)
        records_b = gen_b.generate(node_meta)
        latency_b = time.perf_counter() - started_b
    finally:
        for logger_name in ("core.llm.client", "anthropic"):
            logging.getLogger(logger_name).removeHandler(counter)

    guidewords = _select_guidewords(node_meta)
    keys = cell_keys(guidewords, gen_a.parameters)
    singles = [pass_states(gen_a.consensus_raw, r, keys) for r in range(3)] + [
        pass_states(gen_b.consensus_raw, r, keys) for r in range(3)]
    judge_a = _judge_cost(gen_a)
    single_cost = (cost_a - sum(judge_a)) + mean(judge_a)  # 해석·열거 + 판정 1벌
    held_single = [sum(s[k] == cs.HELD for k in keys) for s in singles]
    out: dict[str, Any] = {
        "run": name,
        "criteria_id": criteria_id,
        "node_meta": node_meta.model_dump(),
        "parameters": gen_a.parameters,
        "guidewords": guidewords,
        "stability": stability(singles, keys),
        "held": {
            "consensus_A": sum(r.status == cs.HELD for r in records_a),
            "consensus_B": sum(r.status == cs.HELD for r in records_b),
            "single_6": held_single,
            "single_mean": mean(held_single),
        },
        "cost": {"A_total_usd": round(cost_a, 4), "B_total_usd": round(gen_b.total_cost_usd, 4),
                 "A_judge_per_run_usd": [round(c, 4) for c in judge_a],
                 "single_equivalent_usd": round(single_cost, 4),
                 "ratio_vs_single": round(cost_a / single_cost, 2) if single_cost else None},
        "latency": {"A_s": round(latency_a, 1), "B_s": round(latency_b, 1), "cap_s": LATENCY_CAP_S},
        "cells": {"A": f"{gen_a.judged_cells}/{gen_a.expected_cells}", "B": f"{gen_b.judged_cells}/{gen_b.expected_cells}"},
        "review_guidewords": {"A": gen_a.review_guidewords, "B": gen_b.review_guidewords},
        "failed_runs": {"A": {gw: sum(b is None for b in r) for gw, r in gen_a.consensus_raw.items()},
                        "B": {gw: sum(b is None for b in r) for gw, r in gen_b.consensus_raw.items()}},
        "retries_A": {"ours": retries_a[0], "sdk": retries_a[1]},
        "retries_total": {"ours": len(counter.ours), "sdk": len(counter.sdk)},
        "sentences": {"A": sentence_stats(records_a), "B": sentence_stats(records_b)},
    }
    if gold:
        def rec(records: list[Any]) -> dict[str, Any]:
            r = recall_for_node(records, gold)
            return {"recall": r["recall"], "matched": r["matched"], "total": r["total"]}

        per_pass = []
        for gen in (gen_a, gen_b):
            for run in range(3):
                batches = [b[run] for b in gen.consensus_raw.values() if b[run] is not None]
                per_pass.append(rec(_build_records(node_meta, batches, criteria_id)[0]))
        out["recall_internal"] = {"consensus_A": rec(records_a), "consensus_B": rec(records_b), "single_6": per_pass}
    out["_raw"] = {"A": _strip(gen_a.consensus_raw), "B": _strip(gen_b.consensus_raw)}
    out["_records"] = {"A": [r.model_dump() for r in records_a], "B": [r.model_dump() for r in records_b]}
    return out


def verdict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """사전등록 §5. 합친 셀 기준 안정성 + 직접 입력 A 지연."""
    cells = sum(r["stability"]["cells"] for r in rows)
    single = sum(r["stability"]["single_mean_15pairs"] * r["stability"]["cells"] for r in rows) / cells
    cons = sum(r["stability"]["consensus_A_vs_B"] * r["stability"]["cells"] for r in rows) / cells
    direct = next((r for r in rows if r["run"] == "direct"), None)
    latency_ok = direct is not None and direct["latency"]["A_s"] <= LATENCY_CAP_S
    stable_up = cons > single
    if stable_up and latency_ok:
        branch = "기본 켬(consensus_runs: 3)"
    elif stable_up:
        branch = "기본 N=1 유지 · 합의는 '정밀 생성' 별도 실행으로 제안(켜는 결정은 사용자)"
    else:
        branch = "합의 끔(consensus_runs: 1)"
    empty = {r["run"]: r["sentences"]["A"]["rows_without_kept_cause_rate"] for r in rows}
    return {
        "pooled_cells": cells,
        "pooled_single_mean": single,
        "pooled_consensus_A_vs_B": cons,
        "stability_up": stable_up,
        "per_input_lower": [r["run"] for r in rows
                            if r["stability"]["consensus_A_vs_B"] <= r["stability"]["single_mean_15pairs"]],
        "direct_latency_A_s": direct["latency"]["A_s"] if direct else None,
        "latency_ok": latency_ok,
        "branch": branch,
        "empty_cause_rate_A": empty,
        "empty_cause_over_cap": [k for k, v in empty.items() if v is not None and v > EMPTY_CAUSE_CAP],
        "complete": {r["run"] for r in rows} == {"N1", "N2", "direct"},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", choices=["N1", "N2", "direct"], default=None)
    args = parser.parse_args(argv)
    _load_dotenv()
    os.environ.setdefault("HAZOP_ALLOW_LIVE", "true")
    logging.basicConfig(level=logging.WARNING)
    config = dataclasses.replace(load_generator_config(), consensus_runs=3)
    service.load_generator_config = lambda: config  # type: ignore[assignment]
    out = args.out if args.out.is_absolute() else REPO_ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(dataclasses.asdict(config), indent=2), encoding="utf-8")
    rows = []
    for name in ("N1", "N2", "direct"):
        if args.only and name != args.only:
            continue
        row = run_input(name, config)
        (out / f"{name}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if not k.startswith("_") and k != "node_meta"},
                         ensure_ascii=False), flush=True)
    if rows:
        v = verdict(rows)
        v["complete"] = bool(v["complete"])
        (out / "verdict.json").write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(v, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
