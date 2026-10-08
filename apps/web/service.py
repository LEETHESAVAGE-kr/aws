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
from core.criteria import (  # all_criteria 는 app.py 안내 탭이 service.all_criteria 로 쓴다
    GOLD_CRITERIA,
    OFFICIAL_CRITERIA,
    Criteria,
    all_criteria,  # noqa: F401
    load_criteria,
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

#: 기본 실행(지시문 X-1) 안내 — 노드 전체, 병렬 7. X-G7 실측 3회 79~126초 · $0.73~0.78 (results/xg7_20261008_2350).
LIVE_NOTE: Final[str] = "가이드워드 전체 · 약 1.5~2분 · 약 $0.75"
LIVE_BUTTON: Final[str] = "HAZOP 초안 생성 (가이드워드 전체 · 약 1.5–2분)"
QUICK_NOTE: Final[str] = "약 1분 · API 호출 3회(입력 해석 1 + 파라미터 열거 1 + 가이드워드 1, JSON 입력이면 2회)"
#: 보조 실행 "가이드워드 하나만 빠르게"(지시문 X-1b) 문구 — 실무 기능이다. 이 묶음에 '부스'·'관람객' 을 쓰지 않는다(시험).
QUICK_EXPANDER: Final[str] = "가이드워드 하나만 빠르게 보기 — 특정 이탈 방향만 먼저 확인할 때 (약 1분)"
QUICK_QUESTION: Final[str] = "어떤 가이드워드만 볼까요?"
QUICK_BUTTON: Final[str] = "이 가이드워드만 생성 (약 1분 · 약 $0.15)"
QUICK_SCOPE: Final[str] = "가이드워드 1종({guideword})만 생성 — 전체 매트릭스 아님"
#: 결과 보기(지시문 X-2). 보기는 표시 순서만 바꾼다 — 레코드·다운로드는 그대로.
VIEWS: Final[tuple[str, ...]] = ("워크시트 순서", "가이드워드별", "파라미터별")
#: 재생에서 공정 전체를 노드 순서로 이어 보는 선택(지시문 X-3).
ALL_NODES: Final[str] = "__all__"
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


def daily_left(today: date | None = None) -> int:
    """오늘 남은 실호출 횟수(일 상한 기준) — 부스 모드 안내 줄(지시문 V-5)."""
    return max(DAILY_LIMIT - _daily_runs.get(today or date.today(), 0), 0)


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

    def make(system: str, messages: list[Message], **kwargs: Any) -> ConverseResponse:
        # Y-2: 재생 레코드는 NH3 기준(S·F 1~5)이다. 공식 기준(S 1~4, F 1~3) 스키마로 부르면 상한에 맞춰 자른다 — mock 전용.
        props = ((kwargs.get("response_schema") or {}).get("properties", {}).get("cells", {})
                 .get("items", {}).get("properties", {}))
        s_max, f_max = props.get("S", {}).get("maximum", 5), props.get("F", {}).get("maximum", 5)
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
                    "S": min(record.S, s_max),
                    "F": min(record.F, f_max),
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


#: 단계별 대기 문구(R-11 T-12). 소요 시간은 실측 2회 — J-03(열거 22·판정 41초), 10/8(해석 5·열거 14·판정 53초).
STAGE_PENDING: Final[tuple[str, str]] = (
    "⏳ 1/3 문장을 노드 입력으로 해석 중 (약 3초)",
    "⏳ 2/3 점검 파라미터 열거 중 (약 20초)",
)


def progress_text(
    event: str, payload: Mapping[str, Any], quick_guideword: str | None
) -> tuple[int, str, str | None]:
    """진행 알림 → (줄 번호, 완료 문구, 다음 줄 대기 문구). 빠른 실호출이면 `quick_guideword` 를 준다."""
    if event == "parsed":
        if payload.get("parsed_by") == "json":
            return 0, "✅ 1/3 JSON 입력 — 해석 생략", STAGE_PENDING[1]
        m = payload["node_meta"]
        equipment = ", ".join(m.equipment[:3]) or "미상"
        return 0, f"✅ 1/3 입력 해석 — {m.substance} · {m.phase} · 설비 {equipment}", STAGE_PENDING[1]
    if event == "parameters":
        names = list(payload["parameters"])
        more = f" 외 {len(names) - 6}개" if len(names) > 6 else ""
        pending = (
            f"⏳ 3/3 가이드워드 '{quick_guideword}' 판정 중 (약 40~50초)"
            if quick_guideword
            else "⏳ 3/3 가이드워드 판정 중 (병렬)"
        )
        return 1, f"✅ 2/3 파라미터 {len(names)}개 — {', '.join(names[:6])}{more}", pending
    n = len(payload["records"])
    if quick_guideword:
        return 2, f"✅ 3/3 가이드워드 '{quick_guideword}' 판정 — 이탈 {n}건", None
    done, total = payload["done"], payload["total"]
    mark = "✅" if done == total else "⏳"
    return 2, f"{mark} 3/3 가이드워드 {done}/{total} 판정 완료 — 방금 {payload['guideword']} · 이탈 {n}건", None


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


def _model_info() -> tuple[str | None, str | None, int | None]:
    """(provider, 생성 모델 ID, max_tokens) — 설정을 못 읽으면 None."""
    with contextlib.suppress(ConfigValidationError):
        config = load_model_config()
        return config.provider, config.generation.model_id, config.generation.max_tokens
    return None, None, None


def _run_meta(
    source: str,
    environ: Mapping[str, str],
    node_meta: NodeMeta,
    parsed: dict[str, Any],
    generator: HazopGenerator,
    raw_calls: list[dict[str, Any]],
    started: float,
) -> dict[str, Any]:
    """실행 결과 메타 — 기본 실행·빠른 실행 공통(출처 줄·요약 줄·'AI 가 한 일' 패널이 읽는다)."""
    mock = is_mock(environ)
    provider, model_id, max_tokens = _model_info()
    calls = parsed["raw_calls"] + raw_calls
    return {
        "source": source,
        "mock": mock,
        "provider": "mock" if mock else provider,
        "model_id": None if mock else model_id,
        "endpoint": None if mock else endpoint_label(environ),
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "node": node_meta.node or "직접입력",
        "split": "none",
        "node_meta": node_meta.model_dump(),
        **{k: parsed[k] for k in ("parsed_by", "node_text", "parse_model") if k in parsed},
        "parameters": list(generator.parameters),
        "latency_s": round(time.perf_counter() - started, 1),
        "cost_usd": round(generator.total_cost_usd + parsed["cost_usd"], 4),
        "expected_cells": generator.expected_cells,
        "judged_cells": generator.judged_cells,
        "review_guidewords": list(generator.review_guidewords),
        "recall": None,
        "raw_calls": calls,
        "truncated_calls": sum(
            c["stop_reason"] == "max_tokens" or (max_tokens is not None and c["tokens_out"] >= max_tokens)
            for c in calls
        ),
    }


def run_live(
    node_text: str,
    replay: Result,
    environ: Mapping[str, str] = os.environ,
    on_progress: ProgressCallback | None = None,
) -> Result:
    """노드 1건 전체 생성(가이드워드 7~10종) — 직접 입력의 기본 실행(지시문 X-1).

    `node_text` 는 NodeMeta JSON 또는 자연어 공정 설명(`parse_node_text`). mock 모드면 재생 레코드를
    돌려주는 모의 클라이언트로 끝까지 돈다(H-02 ⑦). 가이드워드 판정이 끝날 때마다 `on_progress` 로
    부분 레코드가 온다(R-11).
    """
    started = time.perf_counter()
    node_meta, parsed = _parse_and_notify(node_text, environ, on_progress)
    mock = is_mock(environ)
    client: AbstractBedrockClient = (
        MockBedrockClient(response_factory=_mock_factory(replay)) if mock else get_bedrock_client()
    )
    raw_calls = _observe_calls(client)
    gen_config = load_generator_config()
    # Y-2: 직접 입력은 골드셋 공정이 아니다 — 공식 HAZOP 기준(steering domain.md §4 적용 범위)
    generator = HazopGenerator(client, gen_config, criteria_id=OFFICIAL_CRITERIA)
    judged: list[str] = []  # 판정한 가이드워드(완료 순서) — 결과 묶음 보기의 축

    def relay(event: str, payload: dict[str, Any]) -> None:
        if event == "guideword":
            judged.append(payload["guideword"])
        if on_progress is not None:
            on_progress(event, payload)

    records = generator.generate(node_meta, relay)
    if not generator.parameters:
        raise RuntimeError("파라미터 열거 실패(응답 스키마 2회 위반) — 가이드워드 판정을 건너뛰었습니다.")
    meta = _run_meta("mock" if mock else "live-run", environ, node_meta, parsed, generator, raw_calls, started)
    meta["guidewords"] = [g for g in STANDARD_GUIDEWORDS + PROCEDURAL_GUIDEWORDS if g in judged]
    meta["criteria_id"] = generator.criteria.id
    meta["parallel_calls"] = gen_config.parallel_calls
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
    generator = HazopGenerator(client, load_generator_config(), criteria_id=OFFICIAL_CRITERIA)
    records = generator.generate_quick(node_meta, guideword, on_progress)  # R-11 AC-11-5 공개 API
    if not generator.parameters:
        raise RuntimeError("파라미터 열거 실패(응답 스키마 2회 위반) — 가이드워드 판정을 건너뛰었습니다.")
    meta = _run_meta("quick", environ, node_meta, parsed, generator, raw_calls, started)
    meta["guidewords"] = [guideword]
    meta["criteria_id"] = generator.criteria.id
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


#: 골드셋 없는 공정에 NH3 기준이 쓰인 결과(10/9 이전 캡처)에 붙는 불일치 배지(지시문 M-03, 실무자평가 P-3).
CRITERIA_NOTICE = "S·F 등급 정의는 NH3 선박 벙커링 기준(선내·항만 영향)입니다 — 이 공정에는 참고용."
#: 공식 기준으로 매긴 결과의 배지(Y-2). 〈이름〉·〈위치〉는 기준 파일에서.
OFFICIAL_NOTICE = "이 결과의 S·F·위험도는 {name} 기준으로 매겼습니다({locator}). 공식 예시 기준이라 사업장 자체 기준이 있으면 그것이 우선합니다."


def result_criteria(result: Result) -> Criteria:
    """결과의 평가기준 — 메타 `criteria_id`, 없으면 레코드, 둘 다 없으면 골드셋 NH3(옛 캡처는 그 기준으로 생성됐다)."""
    cid = result.meta.get("criteria_id") or next((r.criteria_id for r in result.records if r.criteria_id), None)
    return load_criteria(cid)


def criteria_notice(result: Result) -> str | None:
    """어떤 기준으로 매겼는지(Y-2). NH3 골드 공정이면 None, NH3 기준이 다른 공정에 쓰였으면 '참고용' 배지."""
    criteria = result_criteria(result)
    if criteria.id != GOLD_CRITERIA:
        return OFFICIAL_NOTICE.format(name=criteria.name, locator=criteria.data.get("locator", ""))
    return CRITERIA_NOTICE if result.meta.get("split") in ("none", "external") else None


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
        return "정성 검토용 예시라 대조할 기준이 없어 정확도는 측정하지 않았습니다."
    if result.meta.get("combined"):
        parts = result.meta.get("recall_parts") or []
        line = " · ".join(f"{label} **{a / b:.1%}** ({a}/{b})" for label, a, b in parts)
        if any(label == "외부 대조" for label, _, _ in parts):
            line += " — 외부 공개 워크시트의 공정변수 점검표와 대조한 후한 기준이며 NH3 골드셋과 같은 난이도가 아닙니다."
        elif len(parts) > 1:
            line += " — 튜닝 노드(프롬프트를 맞춘 노드)와 처음 보는 홀드아웃 노드를 한 숫자로 합치지 않았습니다."
        return line or "대조 기준 없음"
    if result.meta.get("split") == "external" and recall:
        return (
            f"외부 공개 HAZOP 대비 **{recall['recall']:.1%}** ({recall['matched']}/{recall['total']}, 1회 실행) — "
            "인도 IOCL 충전소 워크시트(2014, 외부 팀 작성)의 공정변수 점검표 11행과 대조. 모델이 기본으로 내는 축과 겹쳐 "
            "후하게 나오는 기준이며, NH3 골드셋과 같은 난이도가 아닙니다."
        )
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
    if m.get("source") == "quick":
        parts.insert(0, QUICK_SCOPE.format(guideword=", ".join(m.get("guidewords") or [])))
    if m.get("combined"):
        parts.insert(0, f"{m['process']} 공정 전체 {len(m['nodes'])}노드 ({m['node']})")
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
    if m.get("combined"):
        recalls = [f"{label} recall {a / b:.3f} ({a}/{b})" for label, a, b in m.get("recall_parts") or []]
        parts.append(" · ".join(recalls) if recalls else "정성 검토용 — 대조 기준 없음")
    elif recall and split == "external":
        parts.append(
            f"{node} 외부 공개 HAZOP 대비 recall {recall['recall']:.3f} ({recall['matched']}/{recall['total']})"
        )
    elif recall:
        parts.append(
            f"{node}({split}) recall {recall['recall']:.3f} ({recall['matched']}/{recall['total']})"
        )
    elif split == "none":
        parts.append(f"{node} 정성 검토용 — 대조 기준 없음")
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
    if m.get("combined"):
        cost_part = f" · 합계 비용 ${cost:.3f}" if cost is not None else ""
        return (
            f"{m['process']} — 노드 {len(m['nodes'])}개의 실호출 캡처를 노드 순서({m['node']})로 이어 본 재생"
            f"{cost_part} · 노드마다 캡처 시각·프롬프트가 다릅니다(아래 '노드별 출처')"
        )
    if result.is_gold:
        return f"전문가 골드셋 재생 — LLM 생성 결과 아님 ({_kst(m.get('captured_at'))} 저장)"
    if source == "live":
        stale = " · **M-01 이전 프롬프트**(판정 단계에 기존 안전장치·운전조건 미전달)" if _before_m01(m) else ""
        return f"{_kst(m.get('captured_at'))} 실호출 캡처를 재생{tail}{stale}"
    scope = (
        " · " + QUICK_SCOPE.format(guideword=", ".join(m.get("guidewords") or [])) if source == "quick" else ""
    )
    if m.get("mock"):
        return f"mock 실행 — 네트워크 없이 재생 레코드로 생성 경로를 돈 결과 ({_kst(m.get('captured_at'))}){scope}"
    return f"{_kst(m.get('captured_at'))} 방금 실호출{tail}{scope}"


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


# ── 보기 전환 · 공정 전체 (지시문 X-2·X-3) ────────────────────────────────────
def cells_label(result: Result) -> str:
    """'판정 셀' 타일 값. 빠른 실행은 1종만 돌았다는 것을 값에 붙인다(X-1b)."""
    m = result.meta
    if m.get("expected_cells") is None:
        return "—"
    cells = f"{m.get('judged_cells')}/{m['expected_cells']}"
    return cells + " (1종)" if m.get("source") == "quick" else cells


def failed_guidewords_line(result: Result) -> str | None:
    """판정에 실패해 review 로 격하된 가이드워드가 있으면 경고 문구(X-1d). 없거나 빠른 실행이면 None."""
    m = result.meta
    failed = m.get("review_guidewords") or []
    if not failed or m.get("source") == "quick" or result.is_gold:
        return None
    ok = len(m.get("guidewords") or []) - len(failed)
    tail = f" — 나머지 {ok}종은 정상" if ok > 0 else ""
    return f"가이드워드 {', '.join(failed)} 판정 실패(review){tail}. 실패한 가이드워드의 셀은 결과에 없습니다."


def partial_rows(records: list[DeviationRecord]) -> list[dict[str, object]]:
    """생성 중 부분 표(X-1c) — 가볍게 6열. 레코드는 생성기가 공정 순서(Y-1)로 준다."""
    return [
        {"가이드워드": r.guideword, "파라미터": r.parameter, "이탈": r.deviation, "S": r.S, "F": r.F, "위험도": r.S * r.F}
        for r in records
    ]


def _guideword_axis(result: Result, records: list[DeviationRecord]) -> list[str]:
    known = list(result.meta.get("guidewords") or [])
    seen = {r.guideword for r in records} | set(known) | set(result.meta.get("review_guidewords") or [])
    return [g for g in STANDARD_GUIDEWORDS + PROCEDURAL_GUIDEWORDS if g in seen] + sorted(
        seen - set(STANDARD_GUIDEWORDS + PROCEDURAL_GUIDEWORDS)
    )


def view_groups(result: Result, view: str) -> list[tuple[str, str, list[int]]]:
    """보기별 묶음 [(묶음 이름, 머리줄, 워크시트 행 인덱스)]. 인덱스는 `worksheet_table` 순서 — 보기는 순서만 바꾼다.

    가이드워드별 머리줄 "More — 9건 (해당 없음 1셀)" 의 해당 없음 셀 수는 열거된 파라미터를 아는 단일 노드
    결과에서만 계산한다(공정 전체·옛 재생은 건수만).
    """
    records = verified(result)[0]
    review = set(result.meta.get("review_guidewords") or [])
    if view == VIEWS[1]:
        axis = _guideword_axis(result, records)
        key = "guideword"
    elif view == VIEWS[2]:
        axis = list(dict.fromkeys(list(result.meta.get("parameters") or []) + [r.parameter for r in records]))
        key = "parameter"
    else:
        return [("", "", list(range(len(records))))]
    rows: dict[str, list[int]] = {name: [] for name in axis}
    for index, record in enumerate(records):
        rows.setdefault(getattr(record, key), []).append(index)
    parameters = result.meta.get("parameters")
    groups: list[tuple[str, str, list[int]]] = []
    for name, indices in rows.items():
        if key == "guideword" and name in review:
            head = f"{name} — 판정 실패(review)"
        else:
            head = f"{name} — {len(indices)}건"
            if key == "guideword" and parameters and not result.meta.get("combined"):
                skipped = len(parameters) - len({records[i].parameter for i in indices})
                head += f" (해당 없음 {skipped}셀)" if skipped > 0 else ""
        groups.append((name, head, indices))
    return [g for g in groups if g[2] or "실패" in g[1]] if key == "parameter" else groups


def _sum(values: list[Any]) -> Any:
    return None if any(v is None for v in values) else sum(values)


def combine_replays(process: Mapping[str, Any], replays: Mapping[str, Result]) -> Result | None:
    """공정의 캡처된 노드 재생을 노드 순서로 이어 붙인 결과 1개(X-3). 캡처된 노드가 없으면 None.

    레코드 id 는 노드 접두사(n1-·n2-…)가 달라 겹치지 않는다. 지연은 노드별 실행을 더한 값이라 비운다.
    recall 은 split 별로 따로 합산한다 — NH3 튜닝 N1 과 홀드아웃 N2~N4 를 한 숫자로 섞지 않는다.
    """
    nodes = [n["id"] for n in process["nodes"] if n["id"] in replays]
    if not nodes:
        return None
    parts = [replays[n] for n in nodes]
    metas = [p.meta for p in parts]
    recall_parts: list[tuple[str, int, int]] = []
    for label, split in (("튜닝", "tune"), ("홀드아웃", "holdout"), ("외부 대조", "external")):
        pairs = [m["recall"] for m in metas if m.get("split") == split and m.get("recall")]
        if pairs:
            recall_parts.append((label, sum(p["matched"] for p in pairs), sum(p["total"] for p in pairs)))
    splits = {m.get("split") for m in metas}
    sources = {m.get("source") for m in metas}
    models = {m.get("model_id") for m in metas}
    cost = _sum([m.get("cost_usd") for m in metas])
    meta = {
        "combined": True,
        "process": process["name"],
        "nodes": nodes,
        "node": "→".join(nodes),
        "source": sources.pop() if len(sources) == 1 else "mixed",
        "split": splits.pop() if len(splits) == 1 else "mixed",
        "model_id": models.pop() if len(models) == 1 else None,
        "captured_at": max(str(m.get("captured_at", "")) for m in metas),
        "latency_s": None,
        "cost_usd": None if cost is None else round(cost, 4),
        "expected_cells": _sum([m.get("expected_cells") for m in metas]),
        "judged_cells": _sum([m.get("judged_cells") for m in metas]),
        "review_guidewords": sorted({g for m in metas for g in m.get("review_guidewords") or []}),
        "recall": None,
        "recall_parts": recall_parts,
        "node_provenance": [(n, provenance_line(p)) for n, p in zip(nodes, parts, strict=True)],
    }
    return Result(meta=meta, records=[r for p in parts for r in p.records])


def recall_tiles(result: Result) -> list[tuple[str, str]]:
    """recall 지표 타일. 공정 전체는 split 별로 타일을 따로(튜닝 · 홀드아웃 — 한 칸에 넣으면 값이 잘린다),
    단일 노드는 기존 1개."""
    m = result.meta
    if m.get("combined"):
        return [(f"{label} recall", f"{a / b:.3f}") for label, a, b in m.get("recall_parts") or []]
    recall = m.get("recall")
    if not recall:
        return []
    external = m.get("split") == "external"  # 지시문 W — 골드셋이 아니라 외부 공개 워크시트
    return [("외부 대조 recall" if external else "전문가 대비 recall", f"{recall['recall']:.3f}")]


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
    # NH3 골드셋 표다. 예시 공정(`none`)·외부 공개 HAZOP 대조(`external`, 지시문 W)는 섞지 않는다 — 기준이 다르다.
    results = {n: r for n, r in results.items() if r.meta.get("split") not in ("none", "external")}
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


#: 검토 표(export-formats R-10, T-08). 화면 열 이름 → 레코드 필드. 목록 필드는 화면처럼 `·` 로 잇고 가른다.
REVIEW_COLUMN: Final[str] = "검토"
REVIEW_CHOICES: Final[tuple[str, ...]] = ("미검토", "채택", "기각")
EDITABLE_COLUMNS: Final[dict[str, str]] = {
    "원인": "causes", "결과": "consequences", "권고": "recommendations", "S(1-5)": "S", "F(1-5)": "F",
}


#: 검토 표 가독성(10/8 사용자 피드백 — 검토자는 열을 눈으로 따라가며 채택·기각한다).
#: 왼쪽 고정 열 · 넓은 글 열 · 목록 구분자 띄어쓰기 · 모든 행이 같거나 빈 열 숨김.
REVIEW_PINNED: Final[tuple[str, ...]] = (REVIEW_COLUMN, "No", "가이드워드")
#: 고정 열 다음에 오는 판단 열 — 우선순위(위험도·S·F·신뢰도)가 가로 스크롤 없이 보이게 이탈 바로 뒤에 둔다.
#: 화면 순서일 뿐이다. 다운로드 xlsx 는 표준 12열 순서(R-02) 그대로.
REVIEW_FRONT: Final[tuple[str, ...]] = ("이탈", "위험도", "S(1-5)", "F(1-5)", CONFIDENCE_COLUMN)
#: 글 열 너비(px) — 'large' 는 열 4개가 화면을 다 먹어 숫자 열이 밀려난다(10/8 1440px 캡처).
REVIEW_WIDTHS: Final[dict[str, int]] = {
    "가이드워드": 130, "이탈": 300, "원인": 300, "결과": 300, "기존 안전장치(Before)": 220, "권고": 300,
}
REVIEW_ROW_HEIGHT: Final[int] = 84
_LIST_COLUMNS: Final[tuple[str, ...]] = ("원인", "결과", "기존 안전장치(Before)", "권고")
_HIDE_IF_UNIFORM: Final[tuple[str, ...]] = ("노드", "시나리오 연계", FLAG_COLUMN)


def _split_list(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").split("·") if part.strip()]


def review_key(result: Result) -> str:
    """검토 편집 상태의 키 — 결과 식별을 넣어 새 결과가 오면 이전 편집이 엉뚱한 행에 붙지 않게 한다."""
    m = result.meta
    return f"review_{m.get('node')}_{m.get('captured_at')}_{len(result.records)}"


def merge_edits(
    base: Mapping[int, Mapping[str, Any]], newer: Mapping[Any, Mapping[str, Any]]
) -> dict[int, dict[str, Any]]:
    """행별로 합친 편집. `data_editor` 의 `edited_rows` 는 행 인덱스가 str 로 올 수 있어 int 로 맞춘다."""
    merged = {int(i): dict(e) for i, e in base.items()}
    for i, e in newer.items():
        merged.setdefault(int(i), {}).update(e)
    return merged


def with_edits(table: list[dict[str, object]], edits: Mapping[int, Mapping[str, Any]]) -> list[dict[str, object]]:
    """화면 표 사본에 검토 편집(검토 판정·수정 값)을 넣는다 — 다른 보기의 읽기 전용 표와 편집 표 재생성용."""
    out = [dict(row) for row in table]
    for i, edit in edits.items():
        if 0 <= int(i) < len(out):
            out[int(i)].update({k: v for k, v in edit.items() if k in out[int(i)]})
    return out


def readable_rows(table: list[dict[str, object]]) -> list[dict[str, object]]:
    """화면용 사본 — 목록 열의 `·` 를 ` · ` 로 띄운다. `apply_review` 는 띄어쓰기 차이를 수정으로 치지 않는다."""
    return [
        {k: (" · ".join(_split_list(v)) if k in _LIST_COLUMNS else v) for k, v in row.items()} for row in table
    ]


def review_column_order(table: list[dict[str, object]]) -> list[str]:
    """보이는 열 순서. 판단에 쓰는 열을 앞에, 모든 행이 같은 값(노드)·빈 값(시나리오 연계·플래그)인 열은 뺀다.

    숨긴 노드 값은 요약 줄·'AI 가 한 일'에 이미 있고, 다운로드 파일에는 12열이 그대로 남는다.
    """
    if not table:
        return []
    columns = list(table[0])
    hidden = {c for c in _HIDE_IF_UNIFORM if c in columns and len({str(r[c]) for r in table}) == 1}
    front = [c for c in (*REVIEW_PINNED, *REVIEW_FRONT) if c in columns]
    return front + [c for c in columns if c not in front and c not in hidden]


def apply_review(
    result: Result, edits: Mapping[int, Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[tuple[object, ...]]]:
    """검토 표의 편집(`st.data_editor` 의 `edited_rows` — 행 인덱스 → {열: 값}) → (내보낼 레코드, 검토 기록).

    기각 행은 빼고, 수정 셀은 반영한다(위험도는 내보내기가 기준대로 다시 계산 — 곱 또는 대조표). 기록 행은
    `core/export` 의 `REVIEW_HEADERS` 순서. 값이 원래와 같으면 수정으로 치지 않는다. S·F 는 결과 기준의
    단계 안 정수만(골드셋 기준 1~5, C-C-37 S 1~4·F 1~3 — Y-2).
    """
    criteria = result_criteria(result)
    limits = {"S": criteria.s_max, "F": criteria.f_max}
    records = _display_records(result)
    table = worksheet_table(result)
    kept: list[dict[str, Any]] = []
    log: list[tuple[object, ...]] = []
    for index, (record, shown) in enumerate(zip(records, table, strict=True)):
        edit = edits.get(index) or edits.get(str(index)) or {}  # type: ignore[call-overload]
        record = dict(record)
        changed: list[str] = []
        for column, field in EDITABLE_COLUMNS.items():
            if column not in edit:
                continue
            value = edit[column]
            if field in ("S", "F"):
                if value == shown[column]:
                    continue
            elif _split_list(value) == _split_list(shown[column]):
                continue  # 화면은 ' · ' 로 띄워 보여 준다 — 띄어쓰기만 다르면 같은 값
            if field in ("S", "F"):
                grade = int(value)
                if grade != value or not 1 <= grade <= limits[field]:
                    raise ValueError(f"{column} 는 1~{limits[field]} 정수여야 합니다({criteria.short}): {value!r}")
                record[field] = grade
            else:
                record[field] = _split_list(value)
            changed.append(column)
        verdict = edit.get(REVIEW_COLUMN) or REVIEW_CHOICES[0]
        if verdict == "기각":
            log.append((shown["No"], "기각", shown["가이드워드"], shown["이탈"], ""))
            continue
        kept.append(record)
        if changed:
            log.append((shown["No"], "수정", shown["가이드워드"], shown["이탈"], ", ".join(changed)))
        elif verdict == "채택":
            log.append((shown["No"], "채택", shown["가이드워드"], shown["이탈"], ""))
    return kept, log


def export_files(
    result: Result, edits: Mapping[int, Mapping[str, Any]] | None = None
) -> dict[str, tuple[str, bytes]]:
    """`export_all` 을 임시 디렉터리에 쓰고 바이트로 돌려준다(`results/` 에 쓰지 않는다).

    `edits` 가 있으면 검토(R-10)를 반영한다 — 기각 행 제외·수정 값·`검토 기록` 시트.
    """
    meta = result.meta
    expected, judged = meta.get("expected_cells"), meta.get("judged_cells")
    coverage = (expected, judged) if expected is not None and judged is not None else None
    records, review_log = apply_review(result, edits) if edits else (_display_records(result), None)
    tmp = Path(tempfile.mkdtemp(prefix="hazop_demo_"))
    try:
        paths = export_all(
            records, tmp, generated_at=meta.get("captured_at"), coverage=coverage, review_log=review_log
        )
        files = {key: (path.name, path.read_bytes()) for key, path in paths.items()}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # LOPA 초안은 Word 로 내려받는다(사용자 결정 9/29). 내용은 core/export/lopa.py 의 Markdown 그대로.
    name, markdown = files["lopa"]
    files["lopa"] = (Path(name).with_suffix(".docx").name, lopa_markdown_to_docx(markdown.decode("utf-8")))
    return files

