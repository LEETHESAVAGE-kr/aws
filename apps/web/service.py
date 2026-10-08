"""데모 UI 의 시험 가능한 로직 — FR-10 H-02 (지시문 H) · J-01·J-03 (지시문 J).

모드 판정·실호출 상한·실행(노드 전체 / 빠른 실호출)·결과표·내보내기. `app.py` 는 위젯 배선만 하고
여기를 부른다. `core/` 는 호출만 한다(PRD §4).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
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
    AnthropicClient,
    BedrockClient,
    ConfigValidationError,
    ConverseResponse,
    Message,
    MockBedrockClient,
    get_bedrock_client,
    load_model_config,
)

from .catalog import load_catalog, node_meta_schema, nodes_by_id, validate_node_meta
from .docx_export import lopa_markdown_to_docx
from .replay import Result

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, MutableMapping

    from core.agent import DeviationRecord
    from core.agent.generate import ProgressCallback
    from core.llm import AbstractBedrockClient

LIVE_NOTE: Final[str] = "약 7~9분 · 약 $0.75~1.01 소요(9/29 실측 4노드)"
QUICK_NOTE: Final[str] = "약 1분 · API 호출 3회(입력 해석 1 + 파라미터 열거 1 + 가이드워드 1, JSON 입력이면 2회)"
#: 자연어 입력 길이 상한 — 해석 호출 비용·남용 방지.
NODE_TEXT_LIMIT: Final[int] = 600
_PARSE_PROMPT: Final[Path] = Path(__file__).parent / "prompts" / "node_parse.md"
logger = logging.getLogger(__name__)

#: 실호출 상한 — Streamlit Cloud 는 최상위 Secrets 를 프로세스 환경변수로 넣은 뒤 스크립트를 import 하므로
#: import 시점에 읽어도 Secrets 값이 반영된다(U-1). 기본값은 세션 1회·일 5회.
SESSION_LIMIT: Final[int] = int(os.environ.get("HAZOP_SESSION_LIMIT", 1))
DAILY_LIMIT: Final[int] = int(os.environ.get("HAZOP_DAILY_LIMIT", 5))
SECRET_KEYS: Final[tuple[str, ...]] = (
    "HAZOP_ALLOW_LIVE", "HAZOP_LIVE_SCOPE", "ANTHROPIC_API_KEY", "HAZOP_SESSION_LIMIT", "HAZOP_DAILY_LIMIT",
    # 본선 F-01: 대회 게이트웨이가 Anthropic 형식이면 SDK 가 이 둘을 환경변수에서 읽는다(core/llm 무변경).
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "HAZOP_ENDPOINT_LABEL",
)
#: `ANTHROPIC_BASE_URL` 이 있을 때 출처 줄에 붙는 경유 표시. Bedrock 경유는 운영사 확인 뒤에만
#: Secrets `HAZOP_ENDPOINT_LABEL` 로 바꾼다(PRD 본선 F-01-5) — 코드 기본값은 확인 전 문구.
DEFAULT_ENDPOINT_LABEL: Final[str] = "대회 제공 API"
DIRECT_BASE_URL: Final[str] = "https://api.anthropic.com"
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
KST: Final[timezone] = timezone(timedelta(hours=9))
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

    이미 환경변수에 있는 값은 덮어쓰지 않는다. 값의 앞뒤 공백·줄바꿈은 떼어 낸다 — 붙여 넣기로 섞인
    공백이 키에 남으면 401 이 난다(9/29 배포). Streamlit Cloud 는 최상위 시크릿을 환경변수로도 직접 넣으므로
    이미 있는 값도 공백만은 정리한다.
    """
    for key in SECRET_KEYS:
        if key in secrets and not environ.get(key, "").strip():
            environ[key] = str(secrets[key]).strip()
        elif key in environ and environ[key] != environ[key].strip():
            environ[key] = environ[key].strip()


_KEY_CHARS: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)


def is_auth_error(exc: BaseException) -> bool:
    """API 키 인증 실패(401)인가 — 공급자 SDK 를 import 하지 않고 이름·상태 코드로 본다."""
    return type(exc).__name__ == "AuthenticationError" or getattr(exc, "status_code", None) == 401


def key_hint(environ: Mapping[str, str] = os.environ) -> str:
    """`ANTHROPIC_API_KEY` 형식 진단 — **키 문자는 한 글자도 드러내지 않는다**(접두사 일치 여부·길이·이상 문자 수만)."""
    name = _key_name(environ)
    raw = environ.get(name, "")
    key = raw.strip()
    if not key:
        return "키 진단: ANTHROPIC_API_KEY 가 비어 있습니다."
    odd = sum(ch not in _KEY_CHARS for ch in key)
    if endpoint_label(environ):
        # 게이트웨이 키는 형식을 모른다 — sk-ant- 접두사·길이로 오경보를 내지 않는다.
        parts = [f"{name} · 엔드포인트 ANTHROPIC_BASE_URL 설정됨", f"길이 {len(key)}자"]
    else:
        parts = [
            "sk-ant- 로 시작 ✅" if key.startswith("sk-ant-") else "sk-ant- 로 시작하지 않음 ❌",
            f"길이 {len(key)}자 (Anthropic 키는 보통 100자 안팎)",
        ]
    parts.append(
        "영문·숫자·-·_ 외 문자 없음 ✅" if odd == 0 else f"영문·숫자·-·_ 외 문자 {odd}개 ❌ (따옴표·공백·줄바꿈이 섞였을 수 있음)"
    )
    if key == "sk-ant-...":
        parts.append("예시 값 'sk-ant-...' 그대로입니다 ❌")
    if raw != key:
        parts.append("앞뒤 공백·줄바꿈 있음(자동 제거됨)")
    return "키 진단: " + " · ".join(parts) + ". Secrets 의 값이 로컬 .env 의 키와 같은지 확인하세요."


def _key_name(environ: Mapping[str, str]) -> str:
    """쓰이는 키 변수 이름 — `x-api-key` 형식이 우선, 없으면 `Bearer` 형식(`ANTHROPIC_AUTH_TOKEN`)."""
    if environ.get("ANTHROPIC_API_KEY", "").strip() or not environ.get("ANTHROPIC_AUTH_TOKEN", "").strip():
        return "ANTHROPIC_API_KEY"
    return "ANTHROPIC_AUTH_TOKEN"


def endpoint_label(environ: Mapping[str, str] = os.environ) -> str | None:
    """`ANTHROPIC_BASE_URL` 로 기본 엔드포인트가 아닌 곳에 보낼 때의 경유 표시. 직결이면 `None`.

    기본 엔드포인트를 명시한 경우(이 PC 셸에 `https://api.anthropic.com` 이 설정돼 있다)도 직결로 본다.
    """
    if environ.get("ANTHROPIC_BASE_URL", "").strip().rstrip("/") in ("", DIRECT_BASE_URL):
        return None
    return environ.get("HAZOP_ENDPOINT_LABEL", "").strip() or DEFAULT_ENDPOINT_LABEL


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

    `HAZOP_ALLOW_LIVE=true` 와 키(`ANTHROPIC_API_KEY` 또는 게이트웨이의 `ANTHROPIC_AUTH_TOKEN`)가
    **모두** 있어야 한다. mock 모드(`HAZOP_USE_MOCK=true`)는 네트워크를 쓰지 않으므로 키 없이 허용한다(오프라인 시험용).
    """
    if not _is_true(environ.get("HAZOP_ALLOW_LIVE", "false")):
        return "실호출 비활성 — 공개 데모는 재생 모드만 제공합니다(HAZOP_ALLOW_LIVE 미설정)."
    if not environ.get(_key_name(environ), "").strip() and not is_mock(environ):
        return "실호출 비활성 — ANTHROPIC_API_KEY 가 없습니다."
    return None


# ── 상한 (H-02 ⑥) ────────────────────────────────────────────────────────────
def quota_block_reason(session_runs: int, today: date | None = None) -> str | None:
    """세션·일 상한(`SESSION_LIMIT`·`DAILY_LIMIT`). 초과면 사유 문자열."""
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


# ── 자연어 입력 → NodeMeta (사용자 결정 9/29, PRD FR-10 밖) ─────────────────────
#: 압력 단위 → kPa 배수. 모델은 숫자·단위를 적힌 그대로 옮기고 환산은 여기서 한다 —
#: 9/29 실측에서 모델에게 환산을 맡기자 "90 MPa" 가 9,000 kPag(10배 오류)로 나왔다. 게이지압으로 간주한다.
PRESSURE_TO_KPA: Final[dict[str, float]] = {"kPa": 1.0, "bar": 100.0, "MPa": 1000.0, "kgf/cm2": 98.0665}


def _parse_schema() -> dict[str, Any]:
    """입력 해석 호출의 응답 스키마 — 산출물 스키마의 `node_meta` 에서 `P_kPag` 만 {value, unit} 으로 바꾼다."""
    schema = node_meta_schema()
    properties = {
        name: {k: v for k, v in spec.items() if k != "$comment"}
        for name, spec in schema["properties"].items()
        if name != "P_kPag"
    }
    properties["pressure"] = {
        "type": ["object", "null"],
        "required": ["value", "unit"],
        "properties": {"value": {"type": "number"}, "unit": {"type": "string", "enum": list(PRESSURE_TO_KPA)}},
        "additionalProperties": False,
    }
    required = ["node", *("pressure" if f == "P_kPag" else f for f in schema["required"])]
    return {"type": "object", "required": required, "properties": properties, "additionalProperties": False}


def _to_node_meta_payload(reply: dict[str, Any]) -> dict[str, Any]:
    """해석 응답의 `pressure` {value, unit} → `P_kPag`(kPa 게이지)."""
    payload = dict(reply)
    pressure = payload.pop("pressure", None)
    payload["P_kPag"] = (
        None if pressure is None else round(pressure["value"] * PRESSURE_TO_KPA[pressure["unit"]], 3)
    )
    return payload


def _mock_parse_factory(**_: Any) -> ConverseResponse:
    """mock 모드의 입력 해석 — 네트워크 없이 스키마를 통과하는 고정 응답."""
    payload = {
        "node": "X1", "substance": "수소", "phase": "gas", "pressure": None, "T_degC": None,
        "equipment": ["수소 저장용기", "디스펜서"], "safeguards": ["긴급차단밸브"],
    }
    return ConverseResponse(content=json.dumps(payload, ensure_ascii=False))


def _parser_client() -> AbstractBedrockClient:
    """입력 해석은 저비용 `verifier` 프로필(config/models.yaml)로 부른다 — 필드 추출일 뿐이라서다."""
    config = load_model_config()
    client_cls = AnthropicClient if config.provider == "anthropic" else BedrockClient
    return client_cls(config=config, profile="verifier")


def parse_node_text(
    text: str, environ: Mapping[str, str] = os.environ, client: AbstractBedrockClient | None = None
) -> tuple[NodeMeta, dict[str, Any]]:
    """자연어 공정 설명 또는 NodeMeta JSON → `NodeMeta`.

    `{` 로 시작하면 JSON 으로 보고 API 를 부르지 않는다. 문장이면 저비용 모델 1회로 구조화한 뒤
    JSON 입력과 같은 스키마 검증을 거친다(설명에 없는 수치는 null — 프롬프트 `prompts/node_parse.md`).
    """
    stripped = text.strip()
    if not stripped:
        raise ValueError("공정 설명이 비어 있습니다.")
    if stripped.startswith("{"):
        return validate_node_meta(json.loads(stripped)), {"parsed_by": "json", "raw_calls": [], "cost_usd": 0.0}
    if len(stripped) > NODE_TEXT_LIMIT:
        raise ValueError(f"공정 설명은 {NODE_TEXT_LIMIT}자 이내로 적어 주세요(지금 {len(stripped)}자).")
    if client is None:
        client = MockBedrockClient(response_factory=_mock_parse_factory) if is_mock(environ) else _parser_client()
    calls = _observe_calls(client)
    system, _, user = _PARSE_PROMPT.read_text(encoding="utf-8").partition("<!-- USER -->")
    response = client.converse(
        system=system.strip(),
        messages=[Message(role="user", content=user.strip().replace("{text}", stripped))],
        response_schema=_parse_schema(),
        context={"node": "parse"},
    )
    if response.content is None:
        raise ValueError(
            "공정 설명을 노드 입력으로 바꾸지 못했습니다(응답 스키마 2회 위반). 물질·설비를 넣어 다시 적어 주세요."
        )
    node_meta = validate_node_meta(_to_node_meta_payload(json.loads(response.content)))
    return node_meta, {
        "parsed_by": "llm",
        "node_text": stripped,
        "parse_model": client.model_short,
        "raw_calls": [{**c, "stage": "parse"} for c in calls],
        "cost_usd": response.cost_usd,
    }


def _parse_and_notify(
    node_text: str, environ: Mapping[str, str], on_progress: ProgressCallback | None
) -> tuple[NodeMeta, dict[str, Any]]:
    """입력 해석 + `"parsed"` 알림. 해석은 웹 소관이라 생성기 대신 여기서 알린다(design §10)."""
    node_meta, parsed = parse_node_text(node_text, environ)
    if on_progress is not None:
        try:
            on_progress("parsed", {"node_meta": node_meta, "parsed_by": parsed["parsed_by"]})
        except Exception:  # noqa: BLE001 — 표시 실패는 생성 실패가 아니다(AC-11-3)
            logger.warning("진행 알림 콜백 예외(event=parsed) — 생성은 계속한다", exc_info=True)
    return node_meta, parsed


def run_live(
    node_text: str,
    replay: Result,
    environ: Mapping[str, str] = os.environ,
    on_progress: ProgressCallback | None = None,
) -> Result:
    """노드 1건 생성. mock 모드면 재생 레코드를 돌려주는 모의 클라이언트로 끝까지 돈다(H-02 ⑦).

    `node_text` 는 NodeMeta JSON 또는 자연어 공정 설명(`parse_node_text`).
    """
    started = time.perf_counter()
    node_meta, parsed = _parse_and_notify(node_text, environ, on_progress)
    mock = is_mock(environ)
    client: AbstractBedrockClient = (
        MockBedrockClient(response_factory=_mock_factory(replay)) if mock else get_bedrock_client()
    )
    gen_config = load_generator_config()
    generator = HazopGenerator(client, gen_config)
    records = generator.generate(node_meta, on_progress)
    latency = time.perf_counter() - started
    meta = {
        "source": "mock" if mock else "live-run",
        "endpoint": None if mock else endpoint_label(environ),
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "node": node_meta.node,
        "node_meta": node_meta.model_dump(),
        **{k: parsed[k] for k in ("parsed_by", "node_text", "parse_model") if k in parsed},
        "latency_s": round(latency, 1),
        "cost_usd": round(generator.total_cost_usd + parsed["cost_usd"], 4),
        "expected_cells": generator.expected_cells,
        "judged_cells": generator.judged_cells,
        "review_guidewords": list(generator.review_guidewords),
        "recall": None,
        "parallel_calls": gen_config.parallel_calls,
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
    node_text: str,
    guideword: str,
    replay: Result,
    environ: Mapping[str, str] = os.environ,
    on_progress: ProgressCallback | None = None,
) -> Result:
    """직접 입력 빠른 실호출(J-03): 파라미터 열거 1회 + 가이드워드 1종 판정 1회 = `converse` 2회.

    `node_text` 가 자연어면 그 앞에 입력 해석 1회(저비용 모델)가 붙어 3회다. JSON 이면 2회.
    노드 전체(가이드워드 7~10종, 약 8분)를 돌지 않고 한 행만 채운다. mock 모드면 `replay` 레코드를
    돌려주는 모의 클라이언트로 같은 경로를 돈다. 입력이 스키마를 어기면 생성 호출 전에 `ValueError`.
    `on_progress` 는 해석(`"parsed"`)·열거·판정이 끝날 때마다 불린다(R-11).
    """
    if guideword not in GUIDEWORD_DEFINITIONS:
        raise ValueError(f"알 수 없는 가이드워드: {guideword}")
    started = time.perf_counter()
    node_meta, parsed = _parse_and_notify(node_text, environ, on_progress)
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
    records = generator.generate_quick(node_meta, guideword, on_progress)  # R-11 AC-11-5 공개 API
    if not generator.parameters:
        raise RuntimeError("파라미터 열거 실패(응답 스키마 2회 위반) — 가이드워드 판정을 건너뛰었습니다.")
    latency = time.perf_counter() - started
    meta = {
        "source": "quick",
        "mock": mock,
        "provider": "mock" if mock else provider,
        "model_id": None if mock else model_id,
        "endpoint": None if mock else endpoint_label(environ),
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "node": node_meta.node or "직접입력",
        "split": "none",
        "node_meta": node_meta.model_dump(),
        **{k: parsed[k] for k in ("parsed_by", "node_text", "parse_model") if k in parsed},
        "guidewords": [guideword],
        "parameters": list(generator.parameters),
        "latency_s": round(latency, 1),
        "cost_usd": round(generator.total_cost_usd + parsed["cost_usd"], 4),
        "expected_cells": generator.expected_cells,
        "judged_cells": generator.judged_cells,
        "review_guidewords": list(generator.review_guidewords),
        "recall": None,
        "raw_calls": parsed["raw_calls"] + raw_calls,
        "truncated_calls": sum(
            c["stop_reason"] == "max_tokens" or (max_tokens is not None and c["tokens_out"] >= max_tokens)
            for c in parsed["raw_calls"] + raw_calls
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


#: verifier 시연 토글(지시문 O-3). 실측 플래그가 0 이라 심사위원이 🔴 를 볼 수 없어서, **표시용 사본**에만
#: 근거 없는 규격 번호 1개를 붙인다. 재생 파일·`Result` 원본·다운로드 3개는 삽입 없는 원본 그대로다.
DEMO_TOGGLE_LABEL: Final[str] = "verifier 시연 — 결함 1건 삽입(근거 없는 규격 번호)"
DEMO_SUFFIX: Final[str] = " (KOSHA GUIDE P-999 참조)"
DEMO_BANNER: Final[str] = (
    ":red-background[시연] 아래 1행의 규격 번호는 시연용으로 삽입한 것입니다 — 원본 재생 데이터에는 없습니다."
)


def demo_injected(result: Result) -> Result:
    """첫 레코드 `recommendations[0]` 끝에 `DEMO_SUFFIX` 를 붙인 **새** `Result`(검증 캐시 없음).

    원본 레코드는 `model_copy` 로 건드리지 않는다. 권고가 비어 있으면 새 항목으로 넣는다. 골드·빈 결과는 원본 그대로.
    """
    if result.is_gold or not result.records:
        return result
    first = result.records[0]
    recs = list(first.recommendations) or [""]
    recs[0] = (recs[0] + DEMO_SUFFIX).strip()
    records = [first.model_copy(update={"recommendations": recs}), *result.records[1:]]
    return Result(meta=result.meta, records=records)


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


#: 골드셋 없는 공정 결과에 붙는 평가기준 불일치 배지(지시문 M-03, 실무자평가 P-3).
CRITERIA_NOTICE = "S·F 등급 정의는 NH3 선박 벙커링 기준(선내·항만 영향)입니다 — 이 공정에는 참고용."


def criteria_notice(result: Result) -> str | None:
    """예시 공정·직접 입력(`split == "none"`)이면 배지 문구, 골드 공정이면 None."""
    return CRITERIA_NOTICE if result.meta.get("split") == "none" else None


def f_distribution(result: Result) -> str:
    """가장 많은 F 값과 그 비율(실무자평가 P-2 공개). 동률이면 작은 F. 레코드가 없으면 해당 없음."""
    counts = Counter(r.F for r in result.records)
    if not counts:
        return "F 분포 해당 없음"
    value, count = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))
    return f"F={value} 비율 {count / len(result.records):.0%}"


def holdout_recall(replays: Mapping[str, Result]) -> tuple[int, int] | None:
    """홀드아웃 노드 recall 합계 (matched, total). 캡처가 없으면 None."""
    pairs = [
        (r.meta["recall"]["matched"], r.meta["recall"]["total"])
        for r in replays.values()
        if r.meta.get("split") == "holdout" and r.meta.get("recall")
    ]
    return (sum(m for m, _ in pairs), sum(n for _, n in pairs)) if pairs else None


def accuracy_line(result: Result, replays: Mapping[str, Result]) -> str:
    """화면 ③ '정확도' 한 줄. 튜닝 노드 수치만 내세우지 않도록 홀드아웃 합계를 같이 적는다(NFR-03)."""
    recall = result.meta.get("recall")
    if result.meta.get("split") == "none":
        return "골드셋이 없는 공정이라 정확도는 측정하지 않았습니다(정성 검토용)."
    if not recall:
        return "골드셋 재생 화면이라 정확도는 해당 없음."
    line = f"전문가 결과물 대비 **{recall['recall']:.1%}** ({recall['matched']}/{recall['total']}, 1회 실행)"
    held = holdout_recall(replays)
    if result.meta.get("split") == "tune" and held:
        line += (
            f" — {result.meta.get('node')} 은 프롬프트를 맞춘 튜닝 노드입니다. "
            f"처음 보는 홀드아웃 3노드 합계는 **{held[0] / held[1]:.1%}** ({held[0]}/{held[1]})"
        )
    elif result.meta.get("split") == "holdout":
        line += " — 프롬프트 개발에 쓰지 않은 홀드아웃 노드"
    return line


def system_note(result: Result) -> str:
    """💡 참고사항의 시스템 정보 줄. 모델·캡처 시각·비용은 결과 메타에서 읽는다."""
    font = "화면에는 S-Core에서 제공한 에스코어 드림 폰트가 적용되어 있습니다."
    m = result.meta
    if result.is_gold or not m.get("model_id"):
        return font
    cost = m.get("cost_usd")
    tail = f" / 1회 구동 비용 ${cost:.3f}" if cost is not None else ""
    return f"이 결과는 {m['model_id']} 모델로 생성했으며, {font} (실호출 기준: {_kst(m.get('captured_at'))}{tail})"


def summary_line(result: Result) -> str:
    """요약 줄. 불리한 숫자도 그대로(NFR-03) — 값이 없으면 없다고 적는다."""
    m = result.meta
    parts = [f"레코드 {len(result.records)}건", f_distribution(result)]
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
    elif split == "none":
        parts.append(f"{node} 골드셋 없음 — recall 해당 없음")
    else:
        parts.append(f"{node}({split}) recall 해당 없음")
    return " · ".join(parts)


def _kst(captured_at: str | None) -> str:
    """ISO 시각(UTC 저장)을 KST 로. 형식이 다르면 원문 그대로."""
    if not captured_at:
        return "시각 미상"
    try:
        stamp = datetime.fromisoformat(captured_at)
    except ValueError:
        return captured_at
    if stamp.tzinfo is None:
        return stamp.strftime("%Y-%m-%d %H:%M")
    return stamp.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")


#: 지시문 M-01(판정 프롬프트에 safeguards·P·T·phase 전달 + safeguards_before 정규화) 적용 시각.
#: 이보다 먼저 캡처된 재생은 옛 프롬프트 결과다 — 9/29 커밋된 재생 7파일 전부.
M01_APPLIED_AT: Final[datetime] = datetime(2026, 9, 29, 13, 0, tzinfo=KST)


def _before_m01(meta: Mapping[str, Any]) -> bool:
    try:
        stamp = datetime.fromisoformat(str(meta.get("captured_at")))
    except ValueError:
        return False
    return stamp.tzinfo is not None and stamp < M01_APPLIED_AT


def provenance_line(result: Result) -> str:
    """이 결과가 어디서 왔는지 한 줄(J-04 ③). 재생이어도 실호출 캡처 일시·모델·비용을 적는다."""
    m = result.meta
    cost = m.get("cost_usd")
    tail = f" · 모델 {m.get('model_id') or '미상'}" + (f" · 비용 ${cost:.3f}" if cost is not None else "")
    if (m.get("parallel_calls") or 1) > 1:
        tail += f" · 병렬 {m['parallel_calls']}"
    if m.get("endpoint"):
        tail += f" · {m['endpoint']} 경유"
    source = m.get("source")
    if result.is_gold:
        return f"전문가 골드셋 재생 — LLM 생성 결과 아님 ({_kst(m.get('captured_at'))} 저장)"
    if source == "live":
        stale = " · **M-01 이전 프롬프트**(판정 단계에 기존 안전장치·운전조건 미전달)" if _before_m01(m) else ""
        return f"{_kst(m.get('captured_at'))} 실호출 캡처를 재생{tail}{stale}"
    if m.get("mock"):
        return f"mock 실행 — 네트워크 없이 재생 레코드로 생성 경로를 돈 결과 ({_kst(m.get('captured_at'))})"
    return f"{_kst(m.get('captured_at'))} 방금 실호출{tail}"


def process_view(result: Result) -> dict[str, Any]:
    """'생성 과정' 패널 값(J-04 ③). 파라미터는 저장된 열거 결과가 있으면 그것, 없으면 레코드 등장 순서."""
    m = result.meta
    parameters = m.get("parameters") or list(dict.fromkeys(r.parameter for r in result.records))
    guidewords = m.get("guidewords") or list(dict.fromkeys(r.guideword for r in result.records))
    raw_calls = m.get("raw_calls")
    records, _ = verified(result)
    return {
        "parameters": parameters,
        "guidewords": guidewords,
        "api_calls": len(raw_calls) if raw_calls is not None else None,
        "judged_cells": m.get("judged_cells"),
        "expected_cells": m.get("expected_cells"),
        "latency_s": m.get("latency_s"),
        "cost_usd": m.get("cost_usd"),
        "truncated_calls": m.get("truncated_calls"),
        "review": sum(r.confidence == "review" for r in records),
    }


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
        files = {key: (path.name, path.read_bytes()) for key, path in paths.items()}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # LOPA 초안은 Word 로 내려받는다(사용자 결정 9/29). 내용은 core/export/lopa.py 의 Markdown 그대로.
    name, markdown = files["lopa"]
    files["lopa"] = (Path(name).with_suffix(".docx").name, lopa_markdown_to_docx(markdown.decode("utf-8")))
    return files
