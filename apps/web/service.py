"""데모 UI 의 시험 가능한 로직 — FR-10 H-02 (지시문 H) · J-01·J-03 (지시문 J).

모드 판정·실호출 상한·실행(노드 전체 / 빠른 실호출)·결과표·내보내기. `app.py` 는 위젯 배선만 하고
여기를 부른다. `core/` 는 호출만 한다(PRD §4).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
import threading
import time
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from core.agent import HazopGenerator, NodeMeta, VerifySummary, verify
from core.agent.generate import (
    GUIDEWORD_DEFINITIONS,
    PROCEDURAL_GUIDEWORDS,
    STANDARD_GUIDEWORDS,
    load_generator_config,
)
from core.export import export_all, normalize_rows
from core.export.rows import HEADERS
from core.export.xlsx import confidence_label
from core.llm import (
    ConfigValidationError,
    ConverseResponse,
    MockBedrockClient,
    get_bedrock_client,
    load_model_config,
)

from .catalog import load_catalog, nodes_by_id, validate_node_meta
from .replay import Result

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, MutableMapping

    from core.agent import DeviationRecord
    from core.llm import AbstractBedrockClient, Message

LIVE_NOTE: Final[str] = "약 7~9분 · 약 $0.75~1.01 소요(9/29 실측 4노드)"
QUICK_NOTE: Final[str] = "약 1분 · API 호출 2회(파라미터 열거 1 + 가이드워드 1)"
SESSION_LIMIT: Final[int] = 1
DAILY_LIMIT: Final[int] = 5
SECRET_KEYS: Final[tuple[str, ...]] = ("HAZOP_ALLOW_LIVE", "HAZOP_LIVE_SCOPE", "ANTHROPIC_API_KEY")
LIVE_SCOPES: Final[tuple[str, ...]] = ("quick", "full")
BADGES: Final[dict[str | None, str]] = {"grounded": "🟢", "inferred": "🟡", "review": "🔴"}
CONFIDENCE_COLUMN: Final[str] = "신뢰도"
FLAG_COLUMN: Final[str] = "검증 플래그"
#: 공정 카탈로그(J-01, `data/presets.json`). 노드 id → 노드(+ `process`).
CATALOG: Final[list[dict[str, Any]]] = load_catalog()
NODES: Final[dict[str, dict[str, Any]]] = nodes_by_id(CATALOG)
#: 노드 id → 설비명(H-06 호환). NH3 노드는 설비 1개라 예전 하드코딩 값과 같다.
PRESETS: Final[dict[str, str]] = {
    nid: ", ".join(n["node_meta"].equipment) for nid, n in NODES.items()
}
#: data/gold/split_node.json 의 holdout_count.
HOLDOUT_GOLD_TOTAL: Final[int] = 26
EVAL_HEADERS: Final[tuple[str, ...]] = (
    "노드", "split", "레코드", "judged/expected", "절단", "지연(s)", "비용($)", "recall(m/n)",
)

# 프로세스 전역 일일 카운터 — Streamlit 은 세션마다 스크립트를 다시 돌리지만 import 된 모듈은 공유한다.
# ponytail: 단일 프로세스 메모리 카운터. 재시작하면 0 으로 돌아간다 — 다중 인스턴스면 외부 저장소로.
_daily_runs: dict[date, int] = {}
_daily_lock = threading.Lock()


def _is_true(value: object) -> bool:
    return str(value).strip().lower() == "true"


# ── 모드 판정 (H-02 ⑥) ───────────────────────────────────────────────────────
def sync_secrets(secrets: Mapping[str, object], environ: MutableMapping[str, str] = os.environ) -> None:
    """`st.secrets` 값을 `os.environ` 으로 복사한다 — `core/llm` 은 환경변수만 본다(AC-12-3).

    이미 환경변수에 있는 값은 덮어쓰지 않는다.
    """
    for key in SECRET_KEYS:
        if key in secrets and not environ.get(key):
            environ[key] = str(secrets[key])


def is_mock(environ: Mapping[str, str] = os.environ) -> bool:
    return _is_true(environ.get("HAZOP_USE_MOCK", "false"))


def live_scope(environ: Mapping[str, str] = os.environ) -> str:
    """`HAZOP_LIVE_SCOPE` — `quick`(직접 입력 빠른 실호출만, 기본) | `full`(노드 전체 실호출 버튼도).

    모르는 값은 `quick` 으로 본다 — 비싼 쪽으로 새지 않게.
    """
    value = environ.get("HAZOP_LIVE_SCOPE", "quick").strip().lower()
    return value if value in LIVE_SCOPES else "quick"


def live_block_reason(environ: Mapping[str, str] = os.environ) -> str | None:
    """실호출 모드를 켤 수 없는 사유. `None` 이면 활성.

    `HAZOP_ALLOW_LIVE=true` 와 `ANTHROPIC_API_KEY` 가 **모두** 있어야 한다. mock 모드
    (`HAZOP_USE_MOCK=true`)는 네트워크를 쓰지 않으므로 키 없이 허용한다(오프라인 시험용).
    """
    if not _is_true(environ.get("HAZOP_ALLOW_LIVE", "false")):
        return "실호출 비활성 — 공개 데모는 재생 모드만 제공합니다(HAZOP_ALLOW_LIVE 미설정)."
    if not environ.get("ANTHROPIC_API_KEY", "").strip() and not is_mock(environ):
        return "실호출 비활성 — ANTHROPIC_API_KEY 가 없습니다."
    return None


# ── 상한 (H-02 ⑥) ────────────────────────────────────────────────────────────
def quota_block_reason(session_runs: int, today: date | None = None) -> str | None:
    """세션 1회·일 5회 상한. 초과면 사유 문자열."""
    if session_runs >= SESSION_LIMIT:
        return f"이 세션의 실호출 {SESSION_LIMIT}회를 이미 썼습니다."
    used = _daily_runs.get(today or date.today(), 0)
    if used >= DAILY_LIMIT:
        return f"오늘 실호출 상한 {DAILY_LIMIT}회에 도달했습니다({used}/{DAILY_LIMIT})."
    return None


def reserve_live_run(session_runs: int, today: date | None = None) -> str | None:
    """상한을 확인하고 통과하면 일일 카운터를 1 올린다. 거부되면 사유를 돌려준다."""
    day = today or date.today()
    with _daily_lock:
        reason = quota_block_reason(session_runs, day)
        if reason is None:
            _daily_runs[day] = _daily_runs.get(day, 0) + 1
        return reason


# ── 실행 ─────────────────────────────────────────────────────────────────────
def _mock_factory(replay: Result) -> Callable[..., ConverseResponse]:
    """재생 레코드를 되돌려주는 모의 응답 — `tests/test_generate.py::_factory` 와 같은 방식.

    열거 호출이면 재생 레코드의 파라미터 축을(스키마 minItems 6 을 채우도록 보충),
    가이드워드 호출이면 그 가이드워드의 재생 레코드를 셀로 돌려준다.
    """
    by_key = {(r.guideword, r.parameter): r for r in replay.records}
    parameters = list(dict.fromkeys(r.parameter for r in replay.records))
    for filler in ("유량", "압력", "온도", "준위", "조성", "상"):
        if len(parameters) >= 6:
            break
        if filler not in parameters:
            parameters.append(filler)
    parameters = parameters[:12]

    def make(system: str, messages: list[Message], **_: Any) -> ConverseResponse:
        if "파라미터 축" in system:
            payload: dict[str, Any] = {
                "parameters": [{"name": p, "rationale": "mock 재생"} for p in parameters]
            }
            return ConverseResponse(content=json.dumps(payload, ensure_ascii=False))
        user = str(messages[0].content)
        guideword = next(
            (g for g in STANDARD_GUIDEWORDS + PROCEDURAL_GUIDEWORDS if f"\n{g} —" in user), ""
        )
        cells: list[dict[str, Any]] = []
        for parameter in parameters:
            record = by_key.get((guideword, parameter))
            if record is None:
                cells.append(
                    {"parameter": parameter, "applicable": False, "skip_reason": "mock: 재생 데이터에 없음"}
                )
                continue
            cells.append(
                {
                    "parameter": parameter,
                    "applicable": True,
                    "deviation": record.deviation,
                    "causes": record.causes,
                    "consequences": record.consequences,
                    "safeguards_before": record.safeguards_before,
                    "S": record.S,
                    "F": record.F,
                    "recommendations": record.recommendations,
                    "evidence": [],
                    "confidence": "inferred",
                }
            )
        body = {"guideword": guideword, "cells": cells}
        return ConverseResponse(content=json.dumps(body, ensure_ascii=False))

    return make


def run_live(node_meta_json: str, replay: Result, environ: Mapping[str, str] = os.environ) -> Result:
    """노드 1건 생성. mock 모드면 재생 레코드를 돌려주는 모의 클라이언트로 끝까지 돈다(H-02 ⑦)."""
    node_meta = NodeMeta.model_validate_json(node_meta_json)
    mock = is_mock(environ)
    client: AbstractBedrockClient = (
        MockBedrockClient(response_factory=_mock_factory(replay)) if mock else get_bedrock_client()
    )
    generator = HazopGenerator(client, load_generator_config())
    started = time.perf_counter()
    records = generator.generate(node_meta)
    latency = time.perf_counter() - started
    meta = {
        "source": "mock" if mock else "live-run",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "node": node_meta.node,
        "node_meta": node_meta.model_dump(),
        "latency_s": round(latency, 1),
        "cost_usd": round(generator.total_cost_usd, 4),
        "expected_cells": generator.expected_cells,
        "judged_cells": generator.judged_cells,
        "review_guidewords": list(generator.review_guidewords),
        "recall": None,
    }
    return Result(meta=meta, records=records)


def _observe_calls(client: AbstractBedrockClient) -> list[dict[str, Any]]:
    """재시도까지 포함한 원시 호출을 기록한다(`tools/capture_replay.py` 와 같은 관측 훅)."""
    calls: list[dict[str, Any]] = []
    do_converse = client._do_converse  # noqa: SLF001

    def _observed(*args: Any, **kwargs: Any) -> ConverseResponse:
        response = do_converse(*args, **kwargs)
        calls.append({"tokens_out": response.usage.output, "stop_reason": response.stop_reason})
        return response

    client._do_converse = _observed  # type: ignore[method-assign]  # noqa: SLF001
    return calls


def run_quick(
    node_meta_json: str, guideword: str, replay: Result, environ: Mapping[str, str] = os.environ
) -> Result:
    """직접 입력 빠른 실호출(J-03): 파라미터 열거 1회 + 가이드워드 1종 판정 1회 = `converse` 2회.

    노드 전체(가이드워드 7~10종, 약 8분)를 돌지 않고 한 행만 채운다. mock 모드면 `replay` 레코드를
    돌려주는 모의 클라이언트로 같은 경로를 돈다. 입력이 스키마를 어기면 API 를 부르기 전에 `ValueError`.
    """
    if guideword not in GUIDEWORD_DEFINITIONS:
        raise ValueError(f"알 수 없는 가이드워드: {guideword}")
    node_meta = validate_node_meta(json.loads(node_meta_json))
    mock = is_mock(environ)
    client: AbstractBedrockClient = (
        MockBedrockClient(response_factory=_mock_factory(replay)) if mock else get_bedrock_client()
    )
    raw_calls = _observe_calls(client)
    provider: str | None = None
    model_id: str | None = None
    max_tokens: int | None = None
    with contextlib.suppress(ConfigValidationError):
        config = load_model_config()
        provider, model_id, max_tokens = (
            config.provider, config.generation.model_id, config.generation.max_tokens
        )
    generator = HazopGenerator(client, load_generator_config())
    started = time.perf_counter()
    # 비공개 메서드 의존 3곳(_enumerate_parameters·_generate_batch·_assemble) — core/ 무수정을 위해
    # 지시문 J 에 한해 허용. 본선에서 HazopGenerator.generate_quick() 공개 API 로 승격(docs/backlog.md).
    parameters = generator._enumerate_parameters(node_meta)  # noqa: SLF001
    if not parameters:
        raise RuntimeError("파라미터 열거 실패(응답 스키마 2회 위반) — 가이드워드 판정을 건너뛰었습니다.")
    batch = generator._generate_batch(node_meta, parameters, guideword)  # noqa: SLF001
    records = generator._assemble(node_meta, [batch] if batch else [])  # noqa: SLF001
    latency = time.perf_counter() - started
    meta = {
        "source": "quick",
        "mock": mock,
        "provider": "mock" if mock else provider,
        "model_id": None if mock else model_id,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "node": node_meta.node or "직접입력",
        "split": "none",
        "node_meta": node_meta.model_dump(),
        "guidewords": [guideword],
        "parameters": [p["name"] for p in parameters],
        "latency_s": round(latency, 1),
        "cost_usd": round(generator.total_cost_usd, 4),
        "expected_cells": len(parameters),
        "judged_cells": generator.judged_cells,
        "review_guidewords": list(generator.review_guidewords),
        "recall": None,
        "raw_calls": raw_calls,
        "truncated_calls": sum(
            c["stop_reason"] == "max_tokens" or (max_tokens is not None and c["tokens_out"] >= max_tokens)
            for c in raw_calls
        ),
    }
    return Result(meta=meta, records=records)


# ── 표시 ─────────────────────────────────────────────────────────────────────
def verified(result: Result) -> tuple[list[DeviationRecord], VerifySummary]:
    """규칙 verifier(FR-06) 결과를 `result.verified` 에 1회 계산해 둔다. 재생 파일은 바꾸지 않는다.

    골드 재생은 사람 작성 레코드라 모델 주장 검증 대상이 아니다 — 원본 그대로, 플래그 0.
    """
    if result.verified is None:
        m = result.meta
        if result.is_gold:
            result.verified = (list(result.records), verify([])[1])
        else:
            result.verified = verify(
                result.records, expected_cells=m.get("expected_cells"), judged_cells=m.get("judged_cells")
            )
    return result.verified


def _display_records(result: Result) -> list[dict[str, Any]]:
    """verifier 가 격하한 레코드. 골드 재생이면 confidence 를 지운다 — 사람 작성 레코드에 '모델 추론' 을
    붙이지 않기 위해서다.

    `DeviationRecord` 기본값이 `inferred` 이고 스키마가 null 을 허용하지 않아 파일에는 inferred 로
    저장돼 있다. 화면·내보내기에서는 `export/xlsx.py` 의 '미부여(사람 작성)' 표기로 바꾼다.
    """
    dumps = [r.model_dump() for r in verified(result)[0]]
    if result.is_gold:
        for d in dumps:
            d["confidence"] = None
    return dumps


def worksheet_table(result: Result) -> list[dict[str, object]]:
    """워크시트 12열(`core/export/rows.py::HEADERS` 순서) + 신뢰도 배지 열 + 검증 플래그 열."""
    records, summary = verified(result)
    flags: dict[str, list[str]] = {}
    for f in summary.flags:
        flags.setdefault(f.record_id, []).append(f"{f.rule}: {f.matched}")
    table: list[dict[str, object]] = []
    for record, row in zip(records, normalize_rows(_display_records(result)), strict=True):
        values = row.cells()
        values[HEADERS.index("위험도")] = row.risk_score  # 파일은 수식, 화면은 값
        label, _ = confidence_label(row.confidence)
        entry: dict[str, object] = dict(zip(HEADERS, values, strict=True))
        entry[CONFIDENCE_COLUMN] = f"{BADGES.get(row.confidence, '⚪')} {label}"
        entry[FLAG_COLUMN] = "; ".join(flags.get(record.id, []))
        table.append(entry)
    return table


def summary_line(result: Result) -> str:
    """요약 줄. 불리한 숫자도 그대로(NFR-03) — 값이 없으면 없다고 적는다."""
    m = result.meta
    parts = [f"레코드 {len(result.records)}건"]
    if m.get("expected_cells") is not None:
        parts.append(f"판정 셀 {m.get('judged_cells')}/{m['expected_cells']}")
    review = m.get("review_guidewords") or []
    parts.append(f"review 가이드워드 {', '.join(review) if review else '없음'}")
    if result.is_gold:
        parts.append("검증 해당 없음(골드 재생)")
    else:
        by_rule = verified(result)[1].by_rule
        n_review = sum(r.confidence == "review" for r in verified(result)[0])
        parts.append(
            f"review {n_review}건 (규격 {by_rule['unverified_standard']}·수치 {by_rule['unsupported_number']})"
        )
    latency = m.get("latency_s")
    parts.append(f"지연 {latency:.0f}초" if latency is not None else "지연 해당 없음")
    cost = m.get("cost_usd")
    parts.append(f"비용 ${cost:.3f}" if cost is not None else "비용 해당 없음")
    recall = m.get("recall")
    node, split = m.get("node", "N1"), m.get("split", "—")
    if recall:
        parts.append(
            f"{node}({split}) recall {recall['recall']:.3f} ({recall['matched']}/{recall['total']})"
        )
    else:
        parts.append(f"{node}({split}) recall 해당 없음")
    return " · ".join(parts)


# ── 평가 요약 표 (H-06 / FR-08 축소 실행) ─────────────────────────────────────
def _fmt(value: object, spec: str = "") -> str:
    return "—" if value is None else format(value, spec)


def evaluation_table(results: Mapping[str, Result]) -> list[dict[str, str]]:
    """노드별 1행 + 홀드아웃 합계 1행. 골드 재생 노드는 recall 을 내지 않고 합계에서도 뺀다.

    합계 recall = Σmatched / Σ(측정된 노드의 골드 수). 세 노드가 다 측정됐으면 분모는 26 이고,
    일부만이면 실제 분모와 어느 노드인지를 표기한다 — 26 으로 나눠 낮추지도, 빠진 노드를 채우지도 않는다.
    """
    rows: list[dict[str, str]] = []
    matched = gold = records = truncated = judged_sum = expected_sum = 0
    cost = latency = 0.0
    measured: list[str] = []
    # 골드셋이 없는 예시 공정(split "none")은 recall 표 대상이 아니다(J-01).
    results = {n: r for n, r in results.items() if r.meta.get("split") != "none"}
    for node in sorted(results, key=lambda n: (n not in PRESETS, n)):
        m = results[node].meta
        recall = m.get("recall")
        expected, judged = m.get("expected_cells"), m.get("judged_cells")
        rows.append(
            {
                "노드": f"{node} {PRESETS.get(node, '')}".strip(),
                "split": str(m.get("split", "—")),
                "레코드": str(len(results[node].records)),
                "judged/expected": "—" if expected is None else f"{judged}/{expected}",
                "절단": _fmt(m.get("truncated_calls")),
                "지연(s)": _fmt(m.get("latency_s"), ".1f"),
                "비용($)": _fmt(m.get("cost_usd"), ".3f"),
                "recall(m/n)": (
                    f"{recall['recall']:.3f} ({recall['matched']}/{recall['total']})"
                    if recall
                    else ("골드 재생 — 해당 없음" if results[node].is_gold else "—")
                ),
            }
        )
        if m.get("split") == "holdout" and recall:
            measured.append(node)
            matched += recall["matched"]
            gold += recall["total"]
            records += len(results[node].records)
            truncated += m.get("truncated_calls") or 0
            judged_sum += judged or 0
            expected_sum += expected or 0
            cost += m.get("cost_usd") or 0.0
            latency += m.get("latency_s") or 0.0
    if gold == HOLDOUT_GOLD_TOTAL:
        label = "홀드아웃 합계"
    else:
        scope = f"{'·'.join(measured)} 만" if measured else "측정 노드 없음"
        label = f"홀드아웃 합계 ({scope} — 골드 {gold}/{HOLDOUT_GOLD_TOTAL}건)"
    rows.append(
        {
            "노드": label,
            "split": "holdout",
            "레코드": str(records) if measured else "—",
            "judged/expected": f"{judged_sum}/{expected_sum}" if measured else "—",
            "절단": str(truncated) if measured else "—",
            "지연(s)": f"{latency:.1f}" if measured else "—",
            "비용($)": f"{cost:.3f}" if measured else "—",
            "recall(m/n)": f"{matched / gold:.3f} ({matched}/{gold})" if gold else "—",
        }
    )
    return rows


def evaluation_markdown(results: Mapping[str, Result]) -> str:
    """`evaluation_table` 을 README §6 에 그대로 붙일 마크다운 표로."""
    lines = ["| " + " | ".join(EVAL_HEADERS) + " |", "|" + "---|" * len(EVAL_HEADERS)]
    for row in evaluation_table(results):
        lines.append("| " + " | ".join(row[h] for h in EVAL_HEADERS) + " |")
    return "\n".join(lines) + "\n"


def export_files(result: Result) -> dict[str, tuple[str, bytes]]:
    """`export_all` 을 임시 디렉터리에 쓰고 바이트로 돌려준다(`results/` 에 쓰지 않는다)."""
    meta = result.meta
    expected, judged = meta.get("expected_cells"), meta.get("judged_cells")
    coverage = (expected, judged) if expected is not None and judged is not None else None
    tmp = Path(tempfile.mkdtemp(prefix="hazop_demo_"))
    try:
        paths = export_all(
            _display_records(result), tmp, generated_at=meta.get("captured_at"), coverage=coverage
        )
        return {key: (path.name, path.read_bytes()) for key, path in paths.items()}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
