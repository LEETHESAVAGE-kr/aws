"""지시문 Y-G5 — 근거 인용(evidence_k) 켠 실호출 3회. 사전 등록: docs/지시문_Y_근거다변화_신뢰도_공정순서.md.

    python -m tools.measure_yg5 --k 2 --out results/yg5_<시각>

NH3 N1(튜닝)·N2(홀드아웃)는 `tools/capture_replay.capture_live`(재생 캡처와 같은 경로, NH3 기준),
직접 입력은 `service.run_live`(화면과 같은 경로, C-C-37 기준)를 부른다. 결과는 `results/`(gitignore) 에만 —
`data/replay/` 는 바꾸지 않는다. 실 API 비용이 든다.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

from apps.web import service
from core.agent import verify
from core.agent.generate import load_generator_config
from tools import capture_replay
from tools.measure_xg7 import INPUT

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """`.env`(BOM 가능) 의 KEY=VALUE 를 비어 있는 환경변수에만 넣는다 — 값은 출력하지 않는다."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#") and not os.environ.get(key.strip()):
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def _summary(records: list[Any], expected: int | None = None, judged: int | None = None) -> dict[str, Any]:
    out, summary = verify(records, expected_cells=expected, judged_cells=judged)
    docs = Counter(str(e["source_id"]).split("#")[0] for r in out for e in r.evidence)
    return {
        "confidence": dict(Counter(r.confidence for r in out)),
        "records_with_evidence": sum(bool(r.evidence) for r in out),
        "citations": sum(len(r.evidence) for r in out),
        "fabricated_citations_removed": sum(len(r.citation_flags) for r in out),
        "by_rule": summary.by_rule,
        "cited_documents": dict(docs),
        "sample": [
            {"guideword": r.guideword, "parameter": r.parameter, "deviation": r.deviation, "evidence": r.evidence}
            for r in out if r.evidence
        ][:5],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", choices=["N1", "N2", "direct"], default=None)
    args = parser.parse_args(argv)
    _load_dotenv()
    service.apply_provider(os.environ)  # HAZOP_PROVIDER=kiro 면 Kiro API 로
    os.environ.setdefault("HAZOP_ALLOW_LIVE", "true")
    config = dataclasses.replace(load_generator_config(), evidence_k=args.k)
    capture_replay.load_generator_config = lambda: config  # type: ignore[assignment]
    service.load_generator_config = lambda: config  # type: ignore[assignment]
    out = args.out if args.out.is_absolute() else REPO_ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in ("N1", "N2", "direct"):
        if args.only and name != args.only:
            continue
        started = time.perf_counter()
        if name == "direct":
            result = service.run_live(INPUT, service.Result(meta={}))
            m = result.meta
            row = {"run": name, "criteria_id": m.get("criteria_id"), "latency_s": m["latency_s"],
                   "cost_usd": m["cost_usd"], "records": len(result.records), "recall": None,
                   "cells": f"{m['judged_cells']}/{m['expected_cells']}", "review_guidewords": m["review_guidewords"],
                   **_summary(result.records, m["expected_cells"], m["judged_cells"])}
        else:
            body = capture_replay.capture_live(name, capture_replay.default_split(name))
            row = {"run": name, "criteria_id": "nh3_sts_bunkering", "latency_s": body["latency_s"],
                   "cost_usd": body["cost_usd"], "records": len(body["records"]), "recall": body["recall"],
                   "cells": f"{body['judged_cells']}/{body['expected_cells']}",
                   "review_guidewords": body["review_guidewords"],
                   **_summary(body["records"], body["expected_cells"], body["judged_cells"])}
        row.update({"evidence_k": args.k, "wall_s": round(time.perf_counter() - started, 1)})
        (out / f"{name}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "sample"}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
