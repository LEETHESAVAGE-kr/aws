"""R-12 / T-14 파라미터 축 천장 측정 — 공개 HAZOP 예시 포함/미포함 (spec:hazop-generation, 본선 F-06).

사전 등록(requirements.md R-12, 커밋 2ac788e) 그대로: 노드 N2·N3·N4 × 조건(off/on) × 반복 3, **열거 호출만**.
천장 = 노드별 홀드아웃 골드 레코드 중 정규화한 파라미터가 열거 목록에 있는 비율. recall 은 이 값을 넘을 수 없다.
조건은 반복마다 번갈아 돈다(시간에 따른 모델 쪽 변화가 한 조건에만 몰리지 않게).

    .venv/Scripts/python -m tools.measure_enumerate --repeats 3
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from core.agent import HazopGenerator
from core.agent.generate import _PARAM_EXAMPLES_PATH, load_generator_config
from core.llm import get_bedrock_client
from tools._replay import normalize_parameter
from tools.capture_replay import NODE_METAS, REPO_ROOT, _gold_rows

NODES: Final[tuple[str, ...]] = ("N2", "N3", "N4")
ARMS: Final[tuple[bool, ...]] = (False, True)


def ceiling(parameters: list[str], gold: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """(골드 레코드 중 파라미터가 열거에 있는 수, 그 골드 파라미터들)."""
    produced = {normalize_parameter(p) for p in parameters}
    hits = [g["parameter"] for g in gold if normalize_parameter(g["parameter"]) in produced]
    return len(hits), hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    out = args.out or REPO_ROOT / "results" / f"f06_{datetime.now(UTC):%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "config" / "models.yaml", out / "models.yaml")
    shutil.copy(_PARAM_EXAMPLES_PATH, out / _PARAM_EXAMPLES_PATH.name)

    client = get_bedrock_client()
    base = load_generator_config()
    runs: list[dict[str, Any]] = []
    for rep in range(1, args.repeats + 1):
        for node in NODES:
            gold = _gold_rows(node, "holdout")
            for arm in ARMS if rep % 2 else tuple(reversed(ARMS)):
                generator = HazopGenerator(client, replace(base, enumerate_examples=arm))
                started = time.perf_counter()
                parameters = [p["name"] for p in generator._enumerate_parameters(NODE_METAS[node])]  # noqa: SLF001
                hit, hits = ceiling(parameters, gold)
                runs.append({
                    "rep": rep, "node": node, "examples": arm, "parameters": parameters,
                    "ceiling_hit": hit, "gold_total": len(gold), "gold_hits": hits,
                    "cost_usd": round(generator.total_cost_usd, 5),
                    "latency_s": round(time.perf_counter() - started, 1),
                })
                print(f"rep{rep} {node} examples={arm!s:5} ceiling {hit}/{len(gold)} {hits} | {parameters}", flush=True)

    summary: dict[str, Any] = {}
    for arm in ARMS:
        rows = [r for r in runs if r["examples"] is arm]
        per_rep = [
            sum(r["ceiling_hit"] for r in rows if r["rep"] == rep) for rep in range(1, args.repeats + 1)
        ]
        total = sum(len(_gold_rows(n, "holdout")) for n in NODES)
        summary["on" if arm else "off"] = {
            "ceiling_per_rep": [f"{h}/{total}" for h in per_rep],
            "ceiling_mean": round(sum(per_rep) / len(per_rep) / total, 3),
            "cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
        }
    payload = {"spec": "hazop-generation R-12 (사전 등록 2ac788e)", "nodes": NODES, "runs": runs, "summary": summary}
    (out / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
