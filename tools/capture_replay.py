#!/usr/bin/env python
"""재생(replay) 데이터 캡처 CLI — FR-10 H-01 (PRD v2.0 §5 FR-10, 지시문 H).

Streamlit 데모의 기본 모드는 실호출이 아니라 재생이다(노드 1건 ≈10분·$0.75, 9/28 실측).
이 스크립트가 그 재생 파일을 만든다.

사용:
    PYTHONIOENCODING=utf-8 python tools/capture_replay.py \\
        --node N1 --out data/replay/n1_20260928.json --source live > results_capture.log 2>&1

- `--source live`: `HazopGenerator(get_bedrock_client(), load_generator_config())` 로 1회 생성.
  **비용이 든다.** 키는 `ANTHROPIC_API_KEY` 환경변수만 본다(AC-12-3 — `.env` 를 읽지 않는다).
- `--source gold`: 골드셋의 해당 노드 레코드를 그대로 넣는다(PRD §9 Plan B). 생성 결과 아님.
- `--split {tune,holdout}`: 골드 파일 선택. 기본은 N1 이면 tune, 나머지는 holdout(`data/gold/split_node.json`).

records 가 `schemas/deviation.schema.json` 을 통과하지 못하면 저장하지 않고 종료코드 1.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from jsonschema import Draft7Validator

if __package__ in (None, ""):  # `python tools/capture_replay.py` 로 직접 실행한 경우
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import DeviationRecord, HazopGenerator, NodeMeta  # noqa: E402
from core.agent.generate import load_generator_config  # noqa: E402
from core.llm import ConfigValidationError, get_bedrock_client, load_model_config  # noqa: E402
from tools._replay import recall_for_node  # noqa: E402

logger = logging.getLogger("capture_replay")

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
GOLD_PATHS: Final[dict[str, Path]] = {
    "tune": REPO_ROOT / "data" / "gold" / "hazop_nh3_tune.json",
    "holdout": REPO_ROOT / "data" / "gold" / "hazop_nh3_eval.json",
}
SCHEMA_PATH: Final[Path] = REPO_ROOT / "schemas" / "deviation.schema.json"
SCHEMA_VERSION: Final[int] = 1

# N1: tests/test_generate.py::N1_META 와 동일 값(복사 — 테스트 모듈은 배포본에 없다).
# N2~N4: data/gold/hazop_nh3_eval.json 각 노드 첫 레코드의 node_meta 그대로(노드 안 레코드 전부 동일,
# 9/29 확인). P_kPag·T_degC 는 골드에서도 null 이라 기본값(None)에 맡긴다.
NODE_METAS: Final[dict[str, NodeMeta]] = {
    node: NodeMeta(node=node, substance="NH3", phase="unknown", equipment=[equipment], safeguards=[])
    for node, equipment in (
        ("N1", "벙커링선 매니폴드"),
        ("N2", "이송 호스"),
        ("N3", "수급선 매니폴드"),
        ("N4", "이송 운전 절차"),
    )
}


def default_split(node: str) -> str:
    return "tune" if node == "N1" else "holdout"


def _gold_rows(node: str, split: str) -> list[dict[str, Any]]:
    rows = json.loads(GOLD_PATHS[split].read_text(encoding="utf-8"))
    return [g for g in rows if g["node"] == node]


def _schema_errors(records: list[DeviationRecord]) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = [r.model_dump() for r in records]
    return [f"{list(e.path)}: {e.message}" for e in Draft7Validator(schema).iter_errors(payload)]


def capture_gold(node: str, split: str) -> dict[str, Any]:
    """골드셋 재생. 지연·비용·recall 은 의미가 없으므로 `null`."""
    records = [DeviationRecord.model_validate(g) for g in _gold_rows(node, split)]
    return {
        "source": "gold",
        "provider": None,
        "model_id": None,
        "node_meta": NODE_METAS[node].model_dump(),
        "latency_s": None,
        "cost_usd": None,
        "expected_cells": None,
        "judged_cells": None,
        "review_guidewords": [],
        "recall": None,
        "records": records,
    }


def capture_live(node: str, split: str) -> dict[str, Any]:
    """실호출 1회. 원시 호출마다 출력 토큰·stop_reason 을 기록해 절단 여부를 남긴다."""
    config = load_model_config()
    client = get_bedrock_client()
    raw_calls: list[dict[str, Any]] = []
    do_converse = client._do_converse  # noqa: SLF001 — 재시도까지 포함한 원시 호출을 세기 위한 관측 훅

    def _observed(*args: Any, **kwargs: Any) -> Any:
        response = do_converse(*args, **kwargs)
        raw_calls.append({"tokens_out": response.usage.output, "stop_reason": response.stop_reason})
        return response

    client._do_converse = _observed  # type: ignore[method-assign]  # noqa: SLF001

    generator = HazopGenerator(client, load_generator_config())
    started = time.perf_counter()
    records = generator.generate(NODE_METAS[node])
    latency = time.perf_counter() - started

    max_tokens = config.generation.max_tokens
    truncated = sum(
        1 for c in raw_calls if c["stop_reason"] == "max_tokens" or c["tokens_out"] >= max_tokens
    )
    gold = _gold_rows(node, split)
    recall = recall_for_node(records, gold) if gold else None
    if recall is not None:
        logger.info("recall=%.3f (%d/%d) split=%s", recall["recall"], recall["matched"],
                    recall["total"], split)
        for row in recall["rows"]:
            verdict = "일치" if row["matched"] else (
                f"불일치(gw_seen={row['guideword_seen']}, param_seen={row['parameter_seen']})"
            )
            logger.info("  %-11s %-10s → %s", row["guideword"], row["parameter"], verdict)
        logger.info("produced=%s", recall["produced"])
    logger.info(
        "records=%d latency_s=%.1f cost_usd=%.4f cells=%d/%d review_gw=%s raw_calls=%d "
        "truncated_calls=%d (max_tokens=%d)",
        len(records), latency, generator.total_cost_usd, generator.judged_cells,
        generator.expected_cells, generator.review_guidewords, len(raw_calls), truncated, max_tokens,
    )
    return {
        "source": "live",
        "provider": config.provider,
        "model_id": config.generation.model_id,
        "node_meta": NODE_METAS[node].model_dump(),
        "latency_s": round(latency, 1),
        "cost_usd": round(generator.total_cost_usd, 4),
        "expected_cells": generator.expected_cells,
        "judged_cells": generator.judged_cells,
        "review_guidewords": list(generator.review_guidewords),
        "recall": (
            {k: recall[k] for k in ("recall", "matched", "total")} if recall is not None else None
        ),
        "max_tokens": max_tokens,
        "raw_calls": raw_calls,
        "truncated_calls": truncated,
        "records": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--node", default="N1", choices=sorted(NODE_METAS))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", default="live", choices=["live", "gold"])
    parser.add_argument("--split", choices=sorted(GOLD_PATHS), default=None,
                        help="골드 파일 선택(기본: N1=tune, 그 외=holdout)")
    args = parser.parse_args(argv)
    split = args.split or default_split(args.node)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    try:
        capture = capture_live if args.source == "live" else capture_gold
        body = capture(args.node, split)
    except ConfigValidationError as exc:
        logger.error("config/models.yaml 미완성: %s", exc)
        return 1

    records: list[DeviationRecord] = body.pop("records")
    errors = _schema_errors(records)
    if errors:
        logger.error("스키마 위반 %d건 — 저장하지 않는다: %s", len(errors), errors[:5])
        return 1

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source": body.pop("source"),
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "node": args.node,
        "split": split,
        **body,
        "records": [r.model_dump() for r in records],
    }
    out = args.out if args.out.is_absolute() else REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("saved %s (source=%s, records=%d)", out, payload["source"], len(records))
    return 0


if __name__ == "__main__":
    sys.exit(main())
