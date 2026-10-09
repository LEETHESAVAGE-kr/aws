"""외부 공개 HAZOP 평가셋으로 점검 항목 포괄률 재기 — `data/reference/external_eval_202610.json`.

    python -m tools.measure_external_eval --dry-run                 # 노드·쌍 수만 (호출 0)
    python -m tools.measure_external_eval --out results/exteval_<시각> [--only kais2019] [--limit 3]

노드마다 서비스와 같은 생성기(`HazopGenerator.generate`, 공식 기준 C-C-37)를 1회 돌리고, 그 노드의 출처 쌍과
(가이드워드 정확 + 파라미터 공백 제거) 일치로 포괄률을 잰다 — `tools/_replay.recall_for_node` 와 같은 규칙.
출처별 포괄률은 쌍을 합쳐서, 전체는 **출처마다 같은 무게의 평균**으로 낸다(큰 출처 하나가 숫자를 좌우하지 않게).
실 API 비용이 든다. 결과는 `results/`(gitignore).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from core.agent.generate import HazopGenerator, NodeMeta, load_generator_config
from core.criteria import OFFICIAL_CRITERIA
from tools._replay import recall_for_node

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_PATH = REPO_ROOT / "data" / "reference" / "external_eval_202610.json"


def load_eval(path: Path = EVAL_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def score(per_node: dict[str, dict[str, Any]], data: dict[str, Any]) -> dict[str, Any]:
    """노드별 (matched, total) → 출처별 포괄률(쌍 합산)과 출처 평균(매크로). 실행 실패 노드는 분모에서 빼지 않는다(0 매칭)."""
    node_src = {n["id"]: n["source_id"] for n in data["nodes"]}
    acc: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for nid, r in per_node.items():
        acc[node_src[nid]][0] += r["matched"]
        acc[node_src[nid]][1] += r["total"]
    by_source = {s: {"matched": m, "total": t, "coverage": m / t if t else None} for s, (m, t) in acc.items()}
    covs = [v["coverage"] for v in by_source.values() if v["coverage"] is not None]
    return {
        "by_source": by_source,
        "macro_mean": mean(covs) if covs else None,
        "min_source": min(by_source.items(), key=lambda kv: kv[1]["coverage"])[0] if covs else None,
        "pooled": sum(v["matched"] for v in by_source.values()) / max(1, sum(v["total"] for v in by_source.values())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--only", default=None, help="source_id 하나만")
    parser.add_argument("--limit", type=int, default=None, help="노드 수 상한(시험용)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    data = load_eval()
    nodes = [n for n in data["nodes"] if not args.only or n["source_id"] == args.only][: args.limit]
    gold = defaultdict(list)
    for r in data["records"]:
        gold[r["node"]].append(r)
    if args.dry_run:
        for n in nodes:
            print(n["id"], n["source_id"], len(gold[n["id"]]), n["label"])
        print(len(nodes), "nodes,", sum(len(gold[n["id"]]) for n in nodes), "pairs")
        return 0
    if not args.out:
        parser.error("--out 이 필요하다(실호출)")
    from core.llm import get_bedrock_client
    from tools.measure_yg5 import _load_dotenv

    _load_dotenv()
    os.environ.setdefault("HAZOP_ALLOW_LIVE", "true")
    config = dataclasses.replace(load_generator_config(), consensus_runs=1)
    assert not config.enumerate_examples, "enumerate_examples 가 켜져 있으면 ORNL·IJERPH 이름이 프롬프트에 들어가 평가가 오염된다"
    out = args.out if args.out.is_absolute() else REPO_ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    per_node: dict[str, dict[str, Any]] = {}
    cost = 0.0
    for n in nodes:
        started = time.perf_counter()
        gen = HazopGenerator(get_bedrock_client(), config, criteria_id=OFFICIAL_CRITERIA)
        try:
            records = gen.generate(NodeMeta(**n["node_meta"]))
        except Exception as exc:  # noqa: BLE001 — 한 노드 실패가 전체를 멈추지 않게, 0 매칭으로 기록
            records = []
            print(n["id"], "ERROR", type(exc).__name__, exc, flush=True)
        r = recall_for_node(records, gold[n["id"]])
        cost += gen.total_cost_usd
        per_node[n["id"]] = {"matched": r["matched"], "total": r["total"], "recall": r["recall"],
                             "missed": [f"{x['guideword']}|{x['parameter']}" for x in r["rows"] if not x["matched"]],
                             "parameters": gen.parameters, "records": len(records),
                             "cost_usd": round(gen.total_cost_usd, 4), "latency_s": round(time.perf_counter() - started, 1)}
        print(json.dumps({"node": n["id"], **{k: v for k, v in per_node[n["id"]].items() if k != "parameters"}},
                         ensure_ascii=False), flush=True)
        (out / "per_node.json").write_text(json.dumps(per_node, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {**score(per_node, data), "nodes": len(per_node), "cost_usd": round(cost, 4),
               "model_config": {"consensus_runs": 1, "evidence_k": config.evidence_k,
                                "inference_boundary": config.inference_boundary}}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
