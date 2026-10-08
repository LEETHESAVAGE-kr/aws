"""지시문 X-G7 — 기본 실행(가이드워드 전체) 지연·비용 실측. 사전 등록: docs/지시문_X_전체가이드워드.md.

    python -m tools.measure_xg7 --parallel 4 --out results/xg7_<시각>

화면과 같은 경로(`service.run_live`)를 부르고, 회차마다 지연·비용·판정 셀·첫 가이드워드 완료 시각·
429 재시도 횟수(우리 재시도 로그 + SDK 재시도 로그)를 `<out>/run_<n>_p<병렬>.json` 에 쓴다. 실 API 비용이 든다.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import time
from pathlib import Path
from typing import Any

from apps.web import service
from core.agent.generate import load_generator_config

#: 부스 칩 "아파트 LPG 공급" — 절차 키워드가 없어 표준 7종(사전 등록).
INPUT = (
    "아파트 단지의 LPG 저장탱크에서 기화기를 거쳐 배관으로 각 세대 가스레인지에 공급한다. "
    "안전장치는 가스누출경보기, 긴급차단밸브, 안전밸브."
)


class _RetryCounter(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.ours: list[str] = []
        self.sdk: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if message.startswith("재시도 attempt="):
            self.ours.append(message)
        elif "Retrying request" in message:
            self.sdk.append(message)


def measure(parallel: int, run: int, out: Path) -> dict[str, Any]:
    config = dataclasses.replace(load_generator_config(), parallel_calls=parallel)
    service.load_generator_config = lambda: config  # type: ignore[assignment] # run_live 가 부르는 이름을 바꾼다
    counter = _RetryCounter()
    for name in ("core.llm.client", "anthropic"):
        logging.getLogger(name).addHandler(counter)
        logging.getLogger(name).setLevel(logging.DEBUG)
    events: list[tuple[float, str, int]] = []
    started = time.perf_counter()

    def on_progress(event: str, payload: dict[str, Any]) -> None:
        events.append((round(time.perf_counter() - started, 1), event, len(payload.get("records") or [])))

    try:
        result = service.run_live(INPUT, service.Result(meta={}), on_progress=on_progress)
    finally:
        for name in ("core.llm.client", "anthropic"):
            logging.getLogger(name).removeHandler(counter)
    m = result.meta
    first = next((t for t, e, _ in events if e == "guideword"), None)
    row = {
        "run": run,
        "parallel": parallel,
        "input": INPUT,
        "captured_at": m["captured_at"],
        "model_id": m.get("model_id"),
        "latency_s": m["latency_s"],
        "cost_usd": m["cost_usd"],
        "records": len(result.records),
        "judged_cells": m["judged_cells"],
        "expected_cells": m["expected_cells"],
        "guidewords": m.get("guidewords"),
        "review_guidewords": m["review_guidewords"],
        "api_calls": len(m["raw_calls"]),
        "truncated_calls": m["truncated_calls"],
        "first_guideword_s": first,
        "events": events,
        "retries_ours": counter.ours,
        "retries_sdk": counter.sdk,
        "retries_429": sum("429" in r for r in counter.ours + counter.sdk),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / f"run_{run}_p{parallel}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parallel", type=int, required=True)
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    row = measure(args.parallel, args.run, args.out)
    print(json.dumps({k: v for k, v in row.items() if k not in ("events", "input")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
