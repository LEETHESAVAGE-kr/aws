"""데모 UI 의 시험 가능한 로직 — FR-10 H-02 (지시문 H) · J-01·J-03 (지시문 J).

모드 판정·실호출 상한·실행(노드 전체 / 빠른 실호출)·결과표·내보내기. `app.py` 는 위젯 배선만 하고
여기를 부른다. `core/` 는 호출만 한다(PRD §4).
"""

from __future__ import annotations

import contextlib
import dataclasses
import html
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from core import ipl
from core.agent import HazopGenerator, NodeMeta, VerifySummary, verify
from core.agent.generate import (
    GUIDEWORD_DEFINITIONS,
    INSUFFICIENT,
    PROCEDURAL_GUIDEWORDS,
    STANDARD_GUIDEWORDS,
    load_generator_config,
    prompt_version,
)
from core.criteria import (  # all_criteria 는 app.py 안내 탭이 service.all_criteria 로 쓴다
    GOLD_CRITERIA,
    OFFICIAL_CRITERIA,
    Criteria,
    all_criteria,  # noqa: F401
    load_criteria,
)
from core.export import export_all, normalize_rows
from core.export.rows import HEADERS, consensus_detail, consensus_summary
from core.export.xlsx import confidence_label
from core.llm import (
    AnthropicClient,
    BedrockClient,
    ConfigValidationError,
    ConverseResponse,
    Message,
    MockBedrockClient,
    effective_provider,
    get_bedrock_client,
    load_model_config,
)
from core.llm.gateway_client import GatewayClient, gateway_key

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
LIVE_BUTTON: Final[str] = "HAZOP 초안 생성 (가이드워드 전체 · 약 1.5~2분)"
QUICK_NOTE: Final[str] = "약 1분 · API 호출 3회(입력 해석 1 + 파라미터 도출 1 + 가이드워드 1, JSON 입력이면 2회)"
#: 보조 실행 "가이드워드 하나만 빠르게"(지시문 X-1b) 문구 — 실무 기능이다. 이 묶음에 '부스'·'관람객' 을 쓰지 않는다(시험).
#: §8 C 생성 방식(10/9 사용자: "지금처럼 한 AI 의 답을 고르는 버튼도 남기기"). 10/10 공통 답(교집합) → 합치기(합집합):
#: 교집합은 한 번만 나온 타당한 원인을 버린다. 값 = 가이드워드 판정 반복 횟수. 기본은 첫 항목(지금 방식).
GENERATION_MODES: Final[dict[str, int]] = {
    "한 번 생성 (기본)": 1,
    "3번 생성해 합치기": 3,
}
#: 생성 방식 설명(10/15 사용자 교열본) — 라디오 아래 작은 글씨.
GENERATION_MODE_HELP: Final[dict[str, str]] = {
    "한 번 생성 (기본)": "표준 HAZOP 초안을 생성합니다.",
    "3번 생성해 합치기": "누락되는 원인을 최소화하기 위해 3회 반복 생성 후 병합합니다. (시간 및 비용 약 3배 소요)",
}
GENERATION_MODE_LABEL: Final[str] = "생성 방식"
QUICK_EXPANDER: Final[str] = "특정 가이드워드만 빠르게 보기 — 하나의 이탈 방향만 집중적으로 먼저 확인할 때 사용합니다. (약 1분 소요)"
QUICK_QUESTION: Final[str] = "어떤 가이드워드만 볼까요?"
QUICK_BUTTON: Final[str] = "이 가이드워드만 생성 (약 1분 · 약 $0.15)"
QUICK_SCOPE: Final[str] = "가이드워드 1종({guideword})만 생성 — 전체 표가 아님"
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
    # PRD 추론경계·Kiro K-1~K-4: 대회 AI 모델 게이트웨이(OpenAI 호환) 선택과 그 키
    "HAZOP_PROVIDER", "KIRO_API_KEY", "HAZOP_GATEWAY_KEY",
    # 질문봉쇄 Q-01 되돌리기 — 이 날짜 이전 재생만 보인다(예: 2026-10-14 → 9/29 재생)
    "HAZOP_REPLAY_BEFORE",
)
GATEWAY_LABEL: Final[str] = "대회 제공 API"
#: `ANTHROPIC_BASE_URL` 이 있을 때 출처 줄에 붙는 경유 표시. Bedrock 경유는 운영사 확인 뒤에만
#: Secrets `HAZOP_ENDPOINT_LABEL` 로 바꾼다(PRD 본선 F-01-5) — 코드 기본값은 확인 전 문구.
DEFAULT_ENDPOINT_LABEL: Final[str] = "대회 제공 API"
DIRECT_BASE_URL: Final[str] = "https://api.anthropic.com"
LIVE_SCOPES: Final[tuple[str, ...]] = ("quick", "full")
#: 신뢰도 4단계(Y-4) — 판정은 core/agent/verify.py `confidence_tier`(코드 규칙, 모델 자기평가 아님).
BADGES: Final[dict[str | None, str]] = {"grounded": "🟢", "single_source": "🔵", "inferred": "🟡", "review": "🔴"}
CONFIDENCE_COLUMN: Final[str] = "신뢰도"
FLAG_COLUMN: Final[str] = "자동 검사"
#: 10/9 사용자: '근거' 빈칸이 "근거 없음"으로 읽힌다 → 무엇을 붙이는 칸인지 이름으로. 빈칸은 EVIDENCE_NONE.
EVIDENCE_COLUMN: Final[str] = "관련 법령·MSDS"
EVIDENCE_NONE: Final[str] = "인용 없음 (AI 추론)"
#: §8 C 합의 생성 — 같은 입력으로 판정을 3번 돌려 몇 번 같은 판단이 나왔나. 신뢰도 단계와 별개(C-6). 합의 결과에만 생긴다.
REPEAT_COLUMN: Final[str] = "반복 일치"
#: 질문봉쇄 Q-03 — 어떤 기존 안전장치를 반영해 이 빈도인지(판정 프롬프트 `frequency_basis`).
BASIS_COLUMN: Final[str] = "빈도 근거"
#: 지시문 S-4 — IPL 크레딧 결과의 빈도 표시 `기본→반영`(인정 IPL 이 없으면 값 하나). 읽기 전용, 편집은 F 열(반영 후)만.
FREQ_SHIFT_COLUMN: Final[str] = "빈도 (안전장치 반영 전→후)"
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


def provider_problem(environ: Mapping[str, str] = os.environ) -> str | None:
    """대회 게이트웨이를 고른 상태(`HAZOP_PROVIDER=gateway|kiro`)인데 키가 없으면 사유 — 직결로 넘어가지 않는다(K-4)."""
    if _provider(environ) != "gateway":
        return None
    key = gateway_key(environ)
    if not key:
        return "실호출 비활성 — HAZOP_PROVIDER=gateway 인데 게이트웨이 키(KIRO_API_KEY)가 없습니다."
    if not key.isascii() or any(c.isspace() for c in key):
        # 10/11 배포: 안내문 "대회에서 받은 sk- 로 시작하는 키"가 그대로 Secrets 에 들어가 'latin-1' 인코딩 오류로 죽었다
        return ("실호출 비활성 — 게이트웨이 키(KIRO_API_KEY)에 한글·공백 등 키가 아닌 글자가 있습니다. "
                "Streamlit Secrets 에 실제 키(sk- 로 시작)를 넣으세요.")
    return None


def _provider(environ: Mapping[str, str]) -> str:
    with contextlib.suppress(ConfigValidationError):
        return effective_provider(load_model_config(), environ)
    return "anthropic"


_KEY_CHARS: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)


def is_auth_error(exc: BaseException) -> bool:
    """API 키 인증 실패(401)인가 — 공급자 SDK 를 import 하지 않고 이름·상태 코드로 본다."""
    return type(exc).__name__ == "AuthenticationError" or getattr(exc, "status_code", None) == 401


def failure_hint(exc: BaseException) -> str:
    """재시도 소진(`BedrockCallError`)이 감춘 원인 상태코드를 사람 말로. 키 문자는 드러내지 않는다.

    429 는 둘이다 — 분당 한도(잠시 뒤 풀림)와 게이트웨이 키 누적 예산 소진(`budget_exceeded`, 10/14 실측 —
    기다려도 안 풀린다). 본문으로 가른다.
    """
    cause = exc.__cause__ or exc
    code = getattr(cause, "status_code", None)
    if code == 429 and "budget" in str(cause).lower():
        return (
            "원인: 대회에서 받은 API 사용 예산을 모두 썼습니다(오류 429, 기다려도 풀리지 않음). "
            "'완성된 사례 보기'에서 실제로 생성해 저장한 결과를 확인해 주세요. (이번 오류로 남은 생성 횟수가 차감되지 않았습니다.)"
        )
    if code == 429:
        return (
            "원인: 짧은 시간에 요청이 몰려 분당 사용 한도를 넘었습니다(오류 429). "
            "1분쯤 뒤 다시 시도하거나, 기다리는 동안 '완성된 사례 보기'를 확인해 주세요. (이번 오류로 남은 생성 횟수가 차감되지 않았습니다.)"
        )
    if code == 529 or (isinstance(code, int) and code >= 500):
        return (
            f"원인: AI 서버에 일시적으로 요청이 몰렸습니다(오류 {code}). 잠시 후 다시 시도해 주세요. "
            "(이번 오류로 남은 생성 횟수가 차감되지 않았습니다.)"
        )
    return (
        f"원인: {type(cause).__name__}"
        + (f" (HTTP {code})" if code else "")
        + " (이번 오류로 남은 생성 횟수가 차감되지 않았습니다.)"
    )


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
    if _provider(environ) == "gateway":
        return GATEWAY_LABEL
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
        return "지금은 새로 생성할 수 없습니다. '완성된 사례 보기'에서 저장된 결과를 확인해 주세요."
    if not is_mock(environ) and (problem := provider_problem(environ)):
        return problem
    if _provider(environ) != "gateway" and not environ.get(_key_name(environ), "").strip() and not is_mock(environ):
        return "지금은 새로 생성할 수 없습니다(AI 연결 설정 없음). '완성된 사례 보기'에서 저장된 결과를 확인해 주세요."
    return None


# ── 상한 (H-02 ⑥) ────────────────────────────────────────────────────────────
def quota_block_reason(session_runs: int, today: date | None = None) -> str | None:
    """세션·일 상한(`SESSION_LIMIT`·`DAILY_LIMIT`). 초과면 사유 문자열."""
    if session_runs >= SESSION_LIMIT:
        return f"이 창에서 생성할 수 있는 {SESSION_LIMIT}회를 모두 썼습니다."
    used = _daily_runs.get(today or date.today(), 0)
    if used >= DAILY_LIMIT:
        return f"오늘 생성할 수 있는 {DAILY_LIMIT}회를 모두 썼습니다({used}/{DAILY_LIMIT})."
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
        required = (kwargs.get("response_schema") or {}).get("properties", {}).get("cells", {}).get("items", {}).get(
            "required", [])
        if "frequency_basis" in required:  # Q-03 — 재생 레코드에 근거가 없으면 mock 이라고 적는다
            for cell in cells:
                record = by_key.get((guideword, cell["parameter"]))
                cell["frequency_basis"] = "" if record is None else (record.frequency_basis or "mock: 재생 기록에 빈도 근거 없음")
        if "ipl_credited" in required:  # S-2 — 재생 레코드에 크레딧 칸이 없으면 기본=반영 후, 인정 0(산수가 맞는 값)
            for cell in cells:
                record = by_key.get((guideword, cell["parameter"]))
                credited = (record.ipl_credited if record is not None else None) or []
                cell["ipl_credited"] = credited
                cell["frequency_base"] = (record.frequency_base if record is not None else None) or cell.get("F", 1)
        body = {"guideword": guideword, "cells": cells}
        return ConverseResponse(content=json.dumps(body, ensure_ascii=False))

    return make


# ── 자연어 입력 → NodeMeta (사용자 결정 9/29, PRD FR-10 밖) ─────────────────────
#: 압력 단위 → kPa 배수. 모델은 숫자·단위를 적힌 그대로 옮기고 환산은 여기서 한다 —
#: 9/29 실측에서 모델에게 환산을 맡기자 "90 MPa" 가 9,000 kPag(10배 오류)로 나왔다. 게이지압으로 간주한다.
PRESSURE_TO_KPA: Final[dict[str, float]] = {"kPa": 1.0, "bar": 100.0, "MPa": 1000.0, "kgf/cm2": 98.0665}


def _parse_schema() -> dict[str, Any]:
    """입력 해석 호출의 응답 스키마 — 산출물 스키마의 `node_meta` 에서 압력 칸(`P_kPag`·`design_P_kPag`)만 {value, unit} 으로 바꾼다."""
    schema = node_meta_schema()
    properties = {
        name: {k: v for k, v in spec.items() if k != "$comment"}
        for name, spec in schema["properties"].items()
        if name not in _PRESSURE_FIELDS
    }
    for name in _PRESSURE_FIELDS.values():
        properties[name] = {
            "type": ["object", "null"],
            "required": ["value", "unit"],
            "properties": {"value": {"type": "number"}, "unit": {"type": "string", "enum": list(PRESSURE_TO_KPA)}},
            "additionalProperties": False,
        }
    # 설계압력·용량은 산출물 스키마에선 선택이지만 해석에서는 매번 답하게 한다(없으면 null)
    required = ["node", *(_PRESSURE_FIELDS.get(f, f) for f in schema["required"]), "design_pressure", "capacity"]
    return {"type": "object", "required": required, "properties": properties, "additionalProperties": False}


#: 산출물 필드 → 해석 응답의 {value, unit} 필드.
_PRESSURE_FIELDS: Final[dict[str, str]] = {"P_kPag": "pressure", "design_P_kPag": "design_pressure"}


def _to_node_meta_payload(reply: dict[str, Any]) -> dict[str, Any]:
    """해석 응답의 `pressure`·`design_pressure` {value, unit} → `P_kPag`·`design_P_kPag`(kPa 게이지)."""
    payload = dict(reply)
    for field, name in _PRESSURE_FIELDS.items():
        pressure = payload.pop(name, None)
        if pressure is None and field != "P_kPag":
            continue  # 선택 속성은 비어 있으면 넣지 않는다(옛 레코드와 같은 모양)
        payload[field] = (
            None if pressure is None else round(pressure["value"] * PRESSURE_TO_KPA[pressure["unit"]], 3)
        )
    if not payload.get("capacity"):
        payload.pop("capacity", None)
    return payload


def _guard_pressure(reply: dict[str, Any], text: str) -> tuple[dict[str, Any], list[str]]:
    """해석 응답의 압력 칸 보정(Q-04). 설명에 '설계'라는 말이 없는데 압력이 설계압력 칸에만 들어왔으면 운전압력으로 옮긴다.

    10/14 배포 실측: "약 90 MPa 까지 올려" 가 design_pressure 로 가서 '입력에 없는 정보: 운전압력' 이 떴다.
    프롬프트에도 규칙을 넣었지만 모델이 다시 어겨도 화면이 틀리지 않게 코드가 한 번 더 본다. 고친 내역은 돌려준다.
    """
    fixes: list[str] = []
    if reply.get("pressure") is None and reply.get("design_pressure") is not None and "설계" not in text:
        reply = {**reply, "pressure": reply["design_pressure"], "design_pressure": None}
        fixes.append("설계압력 칸의 압력을 운전압력으로 옮김(설명에 '설계' 없음)")
    return reply, fixes


def parsed_values_line(meta: NodeMeta, info: Mapping[str, Any]) -> str:
    """입력 확인 상자의 '해석된 값' 줄(Q-04-4) — 적힌 단위 그대로와 환산값을 함께. 비어 있는 칸은 빼고 아래 목록이 맡는다."""
    written = info.get("pressure_as_written") or {}
    parts: list[str] = [f"물질 {meta.substance}"]
    for field, name, label in (("P_kPag", "pressure", "운전압력"), ("design_P_kPag", "design_pressure", "설계압력")):
        kpa = getattr(meta, field)
        if kpa is None:
            continue
        raw = written.get(name)
        as_written = f"{raw['value']:g} {raw['unit']}" if raw else f"{kpa:,.0f} kPag"
        parts.append(f"{label} {as_written}" + (f"(={kpa:,.0f} kPag)" if raw and raw["unit"] != "kPa" else ""))
    if meta.T_degC is not None:
        parts.append(f"온도 {meta.T_degC:g} ℃")
    if meta.capacity:
        parts.append(f"용량 {meta.capacity}")
    parts.append(f"상 {meta.phase}")
    parts.append(f"설비 {len(meta.equipment)}개")
    if meta.safeguards:
        parts.append(f"안전장치 {len(meta.safeguards)}개")
    return "해석된 값: " + " · ".join(parts)


def _mock_parse_factory(**_: Any) -> ConverseResponse:
    """mock 모드의 입력 해석 — 네트워크 없이 스키마를 통과하는 고정 응답."""
    payload = {
        "node": "X1", "substance": "수소", "phase": "gas", "pressure": None, "T_degC": None,
        "design_pressure": None, "capacity": None,
        "equipment": ["수소 저장용기", "디스펜서"], "safeguards": ["긴급차단밸브"],
    }
    return ConverseResponse(content=json.dumps(payload, ensure_ascii=False))


def _parser_client() -> AbstractBedrockClient:
    """입력 해석은 저비용 `verifier` 프로필(config/models.yaml)로 부른다 — 필드 추출일 뿐이라서다."""
    config = load_model_config()
    provider = effective_provider(config)
    if provider == "gateway":
        return GatewayClient(config=config, profile="verifier")
    client_cls = AnthropicClient if provider == "anthropic" else BedrockClient
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
            "공정 설명을 분석할 수 없습니다(AI 응답 형식 오류). 대상 물질과 설비 정보를 명확히 적어 다시 시도해 주세요."
        )
    reply, fixes = _guard_pressure(json.loads(response.content), stripped)
    written = {name: reply.get(name) for name in _PRESSURE_FIELDS.values() if reply.get(name)}
    node_meta = validate_node_meta(_to_node_meta_payload(reply))
    return node_meta, {
        "parsed_by": "llm",
        "node_text": stripped,
        "pressure_as_written": written,
        "parse_fixes": fixes,
        "parse_model": client.model_short,
        "raw_calls": [{**c, "stage": "parse"} for c in calls],
        "cost_usd": response.cost_usd,
    }


#: 생성 전 '입력 확인'(10/10 사용자 요청) — 문장 해석 뒤 비어 있는 정보를 사람이 채우게 한다.
#: (NodeMeta 필드, 화면 라벨). 비어 있으면 생성은 되지만 그 정보가 필요한 칸은 '정보 부족'으로 보류된다.
INPUT_CHECK_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("P_kPag", "운전압력 (kPag)"),
    ("T_degC", "운전온도 (℃)"),
    ("design_P_kPag", "설계압력 (kPag)"),
    ("capacity", "용량 (예: 50 m³)"),
    ("safeguards", "안전장치 (쉼표로 구분, 없으면 '없음')"),
)


def missing_inputs(meta: NodeMeta) -> list[str]:
    """해석 결과에서 비어 있는 확인 대상 필드. 안전장치는 '없음'이 명시됐으면(safeguards_known) 빈 것이 아니다."""
    missing = []
    for field, _ in INPUT_CHECK_FIELDS:
        value = getattr(meta, field)
        if field == "safeguards":
            if not value and not meta.safeguards_known:
                missing.append(field)
        elif value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def fill_node_meta(meta: NodeMeta, values: Mapping[str, Any]) -> tuple[NodeMeta, list[str]]:
    """'입력 확인'에서 사람이 채운 값을 덧붙인다 → (보완된 NodeMeta, 채운 필드). 빈 값은 그대로 둔다."""
    update: dict[str, Any] = {}
    for field in ("P_kPag", "T_degC", "design_P_kPag"):
        if values.get(field) is not None:
            update[field] = float(values[field])
    capacity = str(values.get("capacity") or "").strip()
    if capacity:
        update["capacity"] = capacity
    guards = str(values.get("safeguards") or "").strip()
    if guards in ("없음", "없다", "none"):
        update.update(safeguards=[], safeguards_known=True)
    elif guards:
        update["safeguards"] = [g.strip() for g in guards.replace("·", ",").split(",") if g.strip()]
    return validate_node_meta({**meta.model_dump(), **update}), list(update.keys() - {"safeguards_known"})


#: 단계별 대기 문구(R-11 T-12). 소요 시간은 실측 2회 — J-03(열거 22·판정 41초), 10/8(해석 5·열거 14·판정 53초).
STAGE_PENDING: Final[tuple[str, str]] = (
    "⏳ 1/3 공정 설명 해석 중 (약 3초)",
    "⏳ 2/3 점검할 파라미터 도출 중 (약 20초)",
)


def progress_text(
    event: str, payload: Mapping[str, Any], quick_guideword: str | None
) -> tuple[int, str, str | None]:
    """진행 알림 → (줄 번호, 완료 문구, 다음 줄 대기 문구). 빠른 실호출이면 `quick_guideword` 를 준다."""
    if event == "parsed":
        if payload.get("parsed_by") == "json":  # 항목 선택(또는 JSON) — 해석 호출 없음(U-6)
            meta = payload.get("node_meta")
            what = f" — {meta.substance} · 설비 {len(meta.equipment)}개" if meta is not None else ""
            return 0, f"✅ 1/3 입력한 항목 확인{what} (해석 생략)", STAGE_PENDING[1]
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
    node_text: str,
    environ: Mapping[str, str],
    on_progress: ProgressCallback | None,
    pre_parsed: tuple[NodeMeta, dict[str, Any]] | None = None,
) -> tuple[NodeMeta, dict[str, Any]]:
    """입력 해석 + `"parsed"` 알림. 해석은 웹 소관이라 생성기 대신 여기서 알린다(design §10).

    `pre_parsed` 는 화면 '입력 확인' 단계에서 이미 해석·보완한 값 — 다시 해석하지 않는다.
    """
    node_meta, parsed = pre_parsed if pre_parsed is not None else parse_node_text(node_text, environ)
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
        provider = effective_provider(config)
        model_id = config.gateway.get("generation_model_id") if provider == "gateway" else config.generation.model_id
        return provider, model_id, config.generation.max_tokens
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
        "prompt_version": prompt_version(),
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
        "inference_boundary": generator.inference_boundary,
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
    consensus_runs: int | None = None,
    consensus_union: bool = False,
    pre_parsed: tuple[NodeMeta, dict[str, Any]] | None = None,
) -> Result:
    """노드 1건 전체 생성(가이드워드 7~10종) — 직접 입력의 기본 실행(지시문 X-1).

    `consensus_runs` 는 화면 '생성 방식'(§8 C) — None 이면 models.yaml 값, 1 = 한 번 생성, 3 = 3번 생성.
    `consensus_union` 이 참이면 3번을 합친다(합집합), 거짓이면 공통 답(교집합).

    `node_text` 는 NodeMeta JSON 또는 자연어 공정 설명(`parse_node_text`). mock 모드면 재생 레코드를
    돌려주는 모의 클라이언트로 끝까지 돈다(H-02 ⑦). 가이드워드 판정이 끝날 때마다 `on_progress` 로
    부분 레코드가 온다(R-11).
    """
    started = time.perf_counter()
    node_meta, parsed = _parse_and_notify(node_text, environ, on_progress, pre_parsed)
    mock = is_mock(environ)
    client: AbstractBedrockClient = (
        MockBedrockClient(response_factory=_mock_factory(replay)) if mock else get_bedrock_client()
    )
    raw_calls = _observe_calls(client)
    gen_config = load_generator_config()
    if consensus_runs is not None:
        gen_config = dataclasses.replace(gen_config, consensus_runs=consensus_runs)
    gen_config = dataclasses.replace(gen_config, consensus_union=consensus_union)
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
        raise RuntimeError("파라미터를 도출하지 못해(AI 응답 형식이 두 번 연속 맞지 않음) 가이드워드 판정을 하지 않았습니다.")
    meta = _run_meta("mock" if mock else "live-run", environ, node_meta, parsed, generator, raw_calls, started)
    meta["guidewords"] = [g for g in STANDARD_GUIDEWORDS + PROCEDURAL_GUIDEWORDS if g in judged]
    meta["criteria_id"] = generator.criteria.id
    meta["parallel_calls"] = gen_config.parallel_calls
    meta["consensus_runs"] = gen_config.consensus_runs
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
    pre_parsed: tuple[NodeMeta, dict[str, Any]] | None = None,
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
    node_meta, parsed = _parse_and_notify(node_text, environ, on_progress, pre_parsed)
    mock = is_mock(environ)
    client: AbstractBedrockClient = (
        MockBedrockClient(response_factory=_mock_factory(replay)) if mock else get_bedrock_client()
    )
    raw_calls = _observe_calls(client)
    generator = HazopGenerator(client, load_generator_config(), criteria_id=OFFICIAL_CRITERIA)
    records = generator.generate_quick(node_meta, guideword, on_progress)  # R-11 AC-11-5 공개 API
    if not generator.parameters:
        raise RuntimeError("파라미터를 도출하지 못해(AI 응답 형식이 두 번 연속 맞지 않음) 가이드워드 판정을 하지 않았습니다.")
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
DEMO_TOGGLE_LABEL: Final[str] = "검사 기능 시연 — 일부러 틀린 규격 번호 1개 넣어 보기"
#: Q-06-2 검증기가 보는 범위 — 형식 검사이지 내용 진위 판단이 아니다.
VERIFIER_SCOPE: Final[str] = (
    "자동 검사 — 근거 없는 규격 번호, 입력이나 인용 원문에 없는 수치, 원문과 다른 인용, 빠진 필수 칸을 찾습니다 "
    "(내용의 옳고 그름은 판단하지 않음)"
)
#: Q-02-5 '판정 셀' 타일 — 빠짐없음(완전성)이지 맞음(정확도)이 아니다.
CELLS_TILE: Final[str] = "판정한 칸"
CELLS_TILE_SUB: Final[str] = "빠짐없이 판정했는가"
DEMO_SUFFIX: Final[str] = " (KOSHA GUIDE P-999 참조)"
DEMO_BANNER: Final[str] = (
    ":red-background[시연] 아래 표의 한 행에 넣은 규격 번호는 시연용이며, 저장된 원래 결과에는 없습니다."
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


def evidence_label(evidence: list[Any]) -> str:
    """'근거' 열(Y-3) — "문서 2건 · 산업안전보건기준에 관한 규칙 제261조(…) 외 1". 인용이 없으면 빈칸."""
    items = [e for e in evidence if isinstance(e, dict)]
    if not items:
        return ""
    docs = {str(e.get("source_id", "")).split("#")[0] for e in items}
    first = f"{items[0].get('doc_title', '')} {items[0].get('locator', '')}".strip()
    more = f" 외 {len(items) - 1}" if len(items) > 1 else ""
    return f"문서 {len(docs)}건 · {first}{more}"


def evidence_rows(result: Result) -> list[dict[str, object]]:
    """근거 발췌 원문 표(Y-3) — 워크시트 No·문서·위치·인용 구절. 화면 접힘 영역과 Excel '근거' 시트가 같은 내용."""
    records, _ = verified(result)
    return [
        {"No": no, "문서": e.get("doc_title", ""), "위치": e.get("locator", ""), "인용 구절(원문 그대로)": e.get("quote", "")}
        for no, r in enumerate(records, start=1)
        for e in r.evidence
        if isinstance(e, dict)
    ]


def confidence_counts(result: Result) -> str:
    """신뢰도 단계 분포 한 줄(Y-G4 — 한 단계로 몰려도 그대로 적는다). ⚪ 정보 부족은 보류 행이 있을 때만(Z-3)."""
    counts = Counter(r.confidence for r in verified(result)[0])
    line = " · ".join(f"{BADGES[k]} {confidence_label(k)[0]} {counts.get(k, 0)}" for k in BADGES)
    if counts.get(INSUFFICIENT):
        line += f" · {HELD_BADGE} {confidence_label(INSUFFICIENT)[0]} {counts[INSUFFICIENT]}"
    return line


#: Z-3 보류 행 배지. 보류 행의 신뢰도 칸은 "⚪ 정보 부족 — 〈없는 정보〉 미상".
HELD_BADGE: Final[str] = "⚪"
#: Q-Z2 (a)(PRD 추천안 — 사용자 미결정): 안전장치를 모르면 F 는 매기되 '안전조치 미반영'을 알린다.
SAFEGUARDS_UNKNOWN_NOTICE: Final[str] = (
    "기존 안전장치가 입력에 없어 '없음'이 아니라 '모름'으로 다뤘습니다 — 빈도는 현재 안전조치를 반영하지 못한 값입니다. 안전장치가 있으면 입력에 적고 다시 생성해 주세요."
)


def held_label(record: DeviationRecord) -> str:
    return f"{HELD_BADGE} {confidence_label(INSUFFICIENT)[0]} — {' · '.join(record.missing)} 미상"


def held_rows(result: Result) -> list[dict[str, object]]:
    """정보 부족으로 보류한 셀(Z-3) — 워크시트 No·가이드워드·이탈 초안·필요한 정보. Excel '확인 필요' 시트와 같은 내용."""
    return [
        {"No": no, "가이드워드": f"{r.guideword} ({r.parameter})", "이탈": r.deviation, "필요한 정보": " · ".join(r.missing)}
        for no, r in enumerate(verified(result)[0], start=1)
        if r.status == INSUFFICIENT
    ]


def reference_rows(result: Result) -> list[dict[str, object]]:
    """합의 생성(§8 C-4)에서 3번 중 한 번만 나와 워크시트 칸에서 뺀 문장 — 버리지 않고 '참고'로 보인다.

    Excel '반복 일치' 시트의 '참고(한 번만 나옴)' 행과 같은 내용.
    """
    rows: list[dict[str, object]] = []
    for no, r in enumerate(verified(result)[0], start=1):
        if r.status == INSUFFICIENT:
            continue
        for kind, text, agree, used in consensus_detail(r.consensus):
            if used.startswith("참고"):
                rows.append({"No": no, "가이드워드": f"{r.guideword} ({r.parameter})", "구분": kind,
                             "문장": text, "일치": agree})
    return rows


def repeat_counts(result: Result) -> str | None:
    """합의 결과 한 줄 — "같은 입력으로 판정 3번 · 원인 문장 41개 중 3/3 20 · 2/3 9 · 참고(1/3) 12". 단일 실행이면 None."""
    records = [r for r in verified(result)[0] if r.consensus and r.status != INSUFFICIENT]
    if not records:
        return None
    runs = int(records[0].consensus["runs"])
    agrees = Counter(c["agree"] for r in records for c in r.consensus.get("causes") or [])
    total = sum(agrees.values())
    parts = [f"{k}/{runs} {agrees.get(k, 0)}" for k in range(runs, 0, -1)]
    return f"같은 입력으로 판정 {runs}번 · 원인 문장 {total}개 중 " + " · ".join(parts)


def safeguards_notice(result: Result) -> str | None:
    """추론 경계를 켠 실행에서 안전장치가 '모름'이었으면 F 가 안전조치 미반영이라는 알림(Q-Z2 a)."""
    m = result.meta
    node_meta = m.get("node_meta") or {}
    if not m.get("inference_boundary") or node_meta.get("safeguards") or node_meta.get("safeguards_known"):
        return None
    return SAFEGUARDS_UNKNOWN_NOTICE


def cell_breakdown(result: Result) -> str | None:
    """판정 셀 내역(Z-6 예시) — 추론 경계를 켠 실행만. "판정 84셀 = 해당 41 · 해당 없음 30 · 정보 부족 13(보류)"."""
    m = result.meta
    if not m.get("inference_boundary") or m.get("judged_cells") is None:
        return None
    held = sum(r.status == INSUFFICIENT for r in result.records)
    shown = len(result.records)
    return (f"판정 {m['judged_cells']}칸 = 해당 {shown - held} · 해당 없음 {m['judged_cells'] - shown} · "
            f"정보 부족 {held}(보류)")


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
        entry[CONFIDENCE_COLUMN] = (
            held_label(record) if row.confidence == INSUFFICIENT else f"{BADGES.get(row.confidence, '⚪')} {label}"
        )
        entry[FLAG_COLUMN] = "; ".join(flags.get(record.id, []))
        entry[EVIDENCE_COLUMN] = (
            "" if record.status == INSUFFICIENT else evidence_label(record.evidence) or EVIDENCE_NONE
        )
        if any(r.consensus for r in records):  # 단일 실행 결과의 표는 지금과 같은 열
            entry[REPEAT_COLUMN] = consensus_summary(record.consensus, record.status == INSUFFICIENT)
        if any(r.ipl_credited is not None for r in records):  # S-4-1 크레딧 결과에만
            entry[FREQ_SHIFT_COLUMN] = freq_shift(record)
        if any(r.frequency_basis for r in records):  # Q-03 — 맨 뒤 열(기본으로 눈에 덜 띄게), 편집 불가
            entry[BASIS_COLUMN] = ipl_prefix(record) + (record.frequency_basis or "")
        table.append(entry)
    return table


def freq_shift(record: DeviationRecord) -> str:
    """S-4-1 `기본→반영` — 인정한 IPL 이 있으면 `3→1`, 없으면 반영 후 값만. 보류 행은 빈칸."""
    if record.F is None:
        return ""
    if record.ipl_credited and record.frequency_base is not None:
        return f"{record.frequency_base}→{record.F}"
    return str(record.F)


def ipl_prefix(record: DeviationRecord) -> str:
    """S-4-2 빈도 근거 앞 접두어 — 인정한 IPL `✓ 이름(예방)`, 인정하지 않은 입력 안전장치 `– 이름(감지만)`.

    크레딧 칸이 없는 결과(이 기능 이전·보류 행)는 빈 문자열 — 근거 문장만 그대로.
    """
    if record.ipl_credited is None:
        return ""
    parts = [f"✓ {i['name']}({ipl.CLASS_LABELS.get(str(i.get('class')), i.get('class'))})" for i in record.ipl_credited]
    for name in record.node_meta.safeguards:
        if not any(ipl.same_device(str(i["name"]), [name]) for i in record.ipl_credited):
            parts.append(f"– {name}({ipl.CLASS_LABELS[ipl.classify(name).cls]})")
    return " · ".join(parts) + " — " if parts else ""


def ipl_line(result: Result) -> str | None:
    """S-4-3 요약 줄 `IPL 인정 n행 / 검토 m행` — n 은 IPL 을 1개 이상 인정한 행, m 은 V-IPL 플래그가 붙은 행.

    크레딧 칸이 있는 결과에만(이전 재생·골드는 None).
    """
    records, summary = verified(result)
    if result.is_gold or not any(r.ipl_credited is not None for r in records):
        return None
    flagged = {f.record_id for f in summary.flags if f.rule.startswith("ipl_")}
    return f"IPL 인정 {sum(bool(r.ipl_credited) for r in records)}행 / 검토 {len(flagged)}행"


#: 골드셋 없는 공정에 NH3 기준이 쓰인 결과(10/9 이전 캡처)에 붙는 불일치 배지(지시문 M-03, 실무자평가 P-3).
CRITERIA_NOTICE = (
    "이 결과의 심각도·빈도 등급은 NH3 선박 벙커링 기준(선내·항만 피해 기준)으로 매긴 것이어서, 이 공정에는 참고로만 보세요. "
    "위험도는 심각도×빈도(곱)로 계산했으며, 새로 만드는 결과에 쓰는 KOSHA <표 2> 대조표와 계산법이 다릅니다."
)
#: 공식 기준으로 매긴 결과의 배지(Y-2). 〈이름〉·〈위치〉는 기준 파일에서.
OFFICIAL_NOTICE = (
    "이 결과의 심각도·빈도·위험도는 {name} 기준으로 매겼습니다({locator}). {how} · {short} ({published}, 확인 {retrieved}) · "
    "[원문 목록]({url}). 공식 문서의 예시 기준이므로, 사업장 자체 기준이 있으면 그 기준을 따르세요."
)
#: 위험도 산정 방식 한 줄(Q-03-1) — 같은 앱 안에서 곱과 대조표가 섞여 보이지 않게 결과마다 적는다.
RISK_HOW: Final[dict[str, str]] = {
    "lookup": "위험도 = <표 2> 대조표(곱이 아님)",
    "product": "위험도 = 심각도 × 빈도(곱)",
}


def criteria_label(criteria: Criteria) -> str:
    """화면에 쓰는 기준 이름 — 공식 기준은 약칭, NH3 기준은 팀 사업장 기준임을 밝힌다(Q-02: 내부 워크시트 이름을 화면에 쓰지 않는다)."""
    return NH3_CRITERIA_LABEL if criteria.id == GOLD_CRITERIA else criteria.short


#: NH3 벙커링 기준의 화면 이름 — 공식 기준이 아니고 산식이 곱이라는 것까지 이름에 싣는다.
NH3_CRITERIA_LABEL: Final[str] = "NH3 벙커링 사업장 기준(심각도×빈도)"


def result_criteria(result: Result) -> Criteria:
    """결과의 평가기준 — 메타 `criteria_id`, 없으면 레코드, 둘 다 없으면 골드셋 NH3(옛 캡처는 그 기준으로 생성됐다)."""
    cid = result.meta.get("criteria_id") or next((r.criteria_id for r in result.records if r.criteria_id), None)
    return load_criteria(cid)


def criteria_notice(result: Result) -> str | None:
    """어떤 기준으로 매겼는지(Y-2). NH3 골드 공정이면 None, NH3 기준이 다른 공정에 쓰였으면 '참고용' 배지."""
    criteria = result_criteria(result)
    if criteria.id != GOLD_CRITERIA:
        d = criteria.data
        published = d.get("doc", "").rpartition("(")[2].rstrip(")") if "(" in d.get("doc", "") else "공표일 미상"
        return OFFICIAL_NOTICE.format(
            name=criteria.name, locator=d.get("locator", ""), how=RISK_HOW[criteria.method], short=criteria.short,
            published=published, retrieved=d.get("retrieved_at", "미상"), url=d.get("url", ""),
        )
    return CRITERIA_NOTICE if result.meta.get("split") in ("none", "external") else None


#: Q-03-4 — 빈도가 한 값에 이 비율보다 많이 몰리면 자동 문구를 붙인다.
CONCENTRATION_LIMIT: Final[float] = 0.70
CONCENTRATION_WARNING: Final[str] = (
    "⚠ 빈도가 한 값에 몰려 있습니다. 안전장치 정보가 없으면 빈도를 보수적으로 높게 매기도록 만들었기 때문입니다. "
    "편집 표에서 사업장 기준에 맞게 고쳐 주세요."
)


CONCENTRATION_WARNING_IPL: Final[str] = (
    "⚠ 빈도가 한 값에 몰려 있습니다. 입력한 안전장치 가운데 IPL로 인정되는 장치가 적기 때문입니다 "
    "(감지기는 차단과 연동돼야 인정)."
)


def grade_counts(result: Result) -> dict[str, dict[int, int]]:
    """심각도·빈도·위험도 등급별 행 수(보류 행 제외). 등급 축은 결과의 평가기준 단계 수 전부(0 인 등급도 보인다)."""
    criteria = result_criteria(result)
    rated = [r for r in result.records if r.S is not None and r.F is not None]
    axes = {"심각도": range(1, criteria.s_max + 1), "빈도": range(1, criteria.f_max + 1),
            "위험도": sorted({criteria.risk(si, fi) for si in range(1, criteria.s_max + 1)
                            for fi in range(1, criteria.f_max + 1)})}
    values = {"심각도": [r.S for r in rated], "빈도": [r.F for r in rated], "위험도": [r.risk_score for r in rated]}
    return {name: {g: values[name].count(g) for g in axis} for name, axis in axes.items()}


def f_concentration(result: Result) -> float | None:
    """가장 많은 빈도 값의 비율(0~1). 등급을 매긴 행이 없으면 None."""
    counts = grade_counts(result)["빈도"]
    total = sum(counts.values())
    return max(counts.values()) / total if total else None


#: 위험도 판정 구간 색 — 높은 판정부터(빨강·주황·초록). 구간이 2개면 빨강·초록.
_BAND_COLORS: Final[dict[int, tuple[str, ...]]] = {
    2: ("#e5484d", "#30a46c"), 3: ("#e5484d", "#f5a524", "#30a46c"),
}


def risk_band_counts(result: Result) -> list[tuple[str, str, int]]:
    """(판정, 위험도 범위, 행 수) — 높은 판정부터. 등급을 매긴 행만(보류 행 제외)."""
    criteria = result_criteria(result)
    bands = sorted(criteria.data["risk_bands"], key=lambda b: -int(str(b["range"]).split("~")[0]))
    scores = [r.risk_score for r in result.records if r.S is not None and r.F is not None]
    return [(str(b["judgement"]), str(b["range"]),
             sum(1 for s in scores if s is not None and criteria.band(s) == b["judgement"])) for b in bands]


@dataclasses.dataclass(frozen=True)
class RiskCard:
    """'위험도 판정 한눈에 보기' 카드 조각 — 화면은 막대를 누를 수 있는 버튼으로 그린다(10/15). `html()` 은 막대까지 HTML."""

    head: str  # 제목 + 한 문장 메시지
    bands: tuple[tuple[str, str, int, str], ...]  # (판정, 위험도 범위, 행 수, 색) — 높은 판정부터
    tail: str  # 범례 + 심각도·빈도 분포

    def bar_html(self) -> str:
        return "<div style='display:flex;gap:2px;border-radius:6px;overflow:hidden'>" + "".join(
            f"<span title='{name} (위험도 {rng}): {n}행' style='flex:{n};background:{color};color:#fff;font-size:12px;"
            f"padding:4px 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>{name} {n}</span>"
            for name, rng, n, color in self.bands if n
        ) + "</div>"

    def html(self) -> str:
        return (f"<div class='hz-info' style='height:auto;padding:12px 16px'>{self.head}{self.bar_html()}"
                f"{self.tail}</div>")


def distribution_html(result: Result) -> str | None:
    """요약 줄 아래 '위험도 판정' 카드 전체 HTML. 등급을 매긴 행이 없으면 None."""
    card = risk_card(result)
    return card.html() if card else None


def risk_card(result: Result) -> RiskCard | None:
    """요약 줄 아래 '위험도 판정' 카드(Q-03-4, 10/15 개편) — 몇 행이 어느 판정인지 한 막대로 먼저 말하고,
    그 아래에 심각도·빈도 분포를 등급 이름과 함께 적는다. 등급을 매긴 행이 없으면 None."""
    counts = grade_counts(result)
    total = sum(counts["빈도"].values())
    if not total:
        return None
    criteria = result_criteria(result)
    bands = risk_band_counts(result)
    colors = _BAND_COLORS.get(len(bands), ("var(--accent)",) * len(bands))
    held = sum(1 for r in result.records if r.S is None or r.F is None)
    top_name, top_range, top_n = bands[0]
    if top_n:
        head = (f"등급을 매긴 {total}행 중 <b>{top_n}행({top_n / total:.0%})이 '{top_name}'</b>"
                f"(위험도 {top_range})입니다 — 아래 막대에서 그 칸을 누르면 그 행만 표에 남습니다.")
    else:
        busiest = max(bands, key=lambda b: b[2])
        head = (f"'{top_name}'(위험도 {top_range}) 행은 없습니다. "
                f"가장 많은 판정은 '{busiest[0]}' {busiest[2]}행입니다. 막대의 칸을 누르면 그 행만 표에 남습니다.")
    legend = " · ".join(
        f"<span style='color:{color}'>■</span> {name}(위험도 {rng}) {n}행"
        for (name, rng, n), color in zip(bands, colors, strict=True)
    )
    labels = grade_labels(criteria)

    def spread(name: str, what: str) -> str:
        by_grade = sorted(counts[name].items(), reverse=True)  # 높은 등급부터
        items = " · ".join(f"{labels[name].get(g) or f'{g}등급'}({g}) {n}" for g, n in by_grade)
        return f"<div class='hz-info-r'><span style='width:52px'>{name}</span><b style='flex:1;font-weight:400'>{items}행 <small style='color:var(--muted)'>— {what}</small></b></div>"

    note = f" 정보 부족으로 보류한 {held}행은 등급이 없어 빼고 셌습니다." if held else ""
    return RiskCard(
        # 위험도 설명은 제목 바로 밑(10/15 사용자 요청) — 막대를 읽기 전에 '위험도'가 무엇인지 먼저 말한다.
        head=(f"<p class='hz-info-t'>위험도 판정 한눈에 보기</p>"
              f"<small style='display:block;color:var(--muted);margin-top:2px'>위험도는 심각도와 빈도 등급을 "
              f"{criteria_label(criteria)} 기준표로 조합한 값입니다(두 등급의 분포는 맨 아래).</small>"
              f"<p style='margin:6px 0 10px'>{head}</p>"),
        bands=tuple((name, rng, n, color) for (name, rng, n), color in zip(bands, colors, strict=True)),
        tail=(
            f"<small style='display:block;color:var(--muted);margin:6px 0 10px'>{legend}.{note}</small>"
            f"{spread('심각도', '사고가 나면 피해가 얼마나 큰가')}{spread('빈도', '얼마나 자주 일어날 수 있나')}"
        ),
    )


#: '표에서 볼 행'(10/15) — 판정 카드에서 바로 그 행만 표에 남긴다.
ROW_FILTER_ALL: Final[str] = "전체"
ROW_FILTER_HELD: Final[str] = "정보 부족(보류)"


def row_filters(result: Result, table: list[dict[str, object]]) -> dict[str, list[int]]:
    """{선택지 이름: 표 행 인덱스} — 전체 · 판정 구간(높은 판정부터) · 정보 부족. 0행인 구간은 뺀다.

    표(`worksheet_table`) 행의 위험도 값으로 가른다 — 화면에 보이는 위험도와 같은 값이다.
    """
    criteria = result_criteria(result)
    out: dict[str, list[int]] = {ROW_FILTER_ALL: list(range(len(table)))}
    for name, _rng, _n in risk_band_counts(result):
        idx = [i for i, row in enumerate(table)
               if isinstance(row.get("위험도"), int | float) and row["위험도"] == row["위험도"]
               and criteria.band(int(row["위험도"])) == name]  # type: ignore[arg-type]
        if idx:
            out[name] = idx
    held = [i for i, row in enumerate(table) if row.get("위험도") is None]
    if held:
        out[ROW_FILTER_HELD] = held
    return out


def remap_edits(edited_rows: Mapping[Any, Mapping[str, Any]], indices: list[int]) -> dict[int, dict[str, Any]]:
    """걸러 낸 편집 표의 행 번호(0부터) → 전체 표의 행 번호. 편집 기록은 언제나 전체 표 기준으로 둔다."""
    return {indices[int(k)]: dict(v) for k, v in edited_rows.items() if int(k) < len(indices)}


def grade_labels(criteria: Criteria) -> dict[str, dict[int, str]]:
    """등급 → 이름(예: 4 → '치명적'). 기준표에 이름이 없으면 빈 문자열."""
    def named(items: list[dict[str, Any]]) -> dict[int, str]:
        return {int(i["grade"]): str(i.get("label") or "") for i in items}

    return {"심각도": named(criteria.data["severity"]), "빈도": named(criteria.data["frequency"])}


def concentration_warning(result: Result) -> str | None:
    """빈도 단일값 비율이 기준을 넘으면 자동 문구(Q-03-4). 사람이 쓴 워크시트에는 붙이지 않는다.

    S-4-4: 입력에 안전장치가 있는데도 몰렸으면 '없어서'가 아니다 — IPL 적격 장치가 적다는 문구로 바꾼다.
    """
    share = f_concentration(result)
    if result.is_gold or share is None or share <= CONCENTRATION_LIMIT:
        return None
    if any(r.node_meta.safeguards for r in result.records):
        return CONCENTRATION_WARNING_IPL
    return CONCENTRATION_WARNING


def evidence_line(result: Result) -> str | None:
    """'법령·MSDS 인용 n/m행'(Q-08) — 보류 행을 뺀 판정 행 중 원문 인용이 붙은 행. 사람이 쓴 워크시트는 None."""
    if result.is_gold:
        return None
    rated = [r for r in verified(result)[0] if r.status != INSUFFICIENT]
    return f"법령·MSDS 인용 {sum(bool(r.evidence) for r in rated)}/{len(rated)}행"


def f_distribution(result: Result) -> str:
    """가장 많은 F 값과 그 비율(실무자평가 P-2 공개). 동률이면 작은 F. 레코드가 없으면 해당 없음."""
    counts = Counter(r.F for r in result.records if r.F is not None)  # 보류 행(Z-3)은 F 가 없다
    if not counts:
        return "빈도 분포 해당 없음"
    value, count = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))
    return f"빈도 {value}인 행 {count / sum(counts.values()):.0%}"


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
            line += " — 외부 공개 워크시트의 공정변수 점검표와 대조한 후한 기준입니다."
        elif len(parts) > 1:
            line += " — 튜닝 노드(프롬프트를 맞춘 노드)와 처음 보는 홀드아웃 노드를 한 숫자로 합치지 않았습니다."
        return line or "대조 기준 없음"
    if result.meta.get("split") == "external" and recall:
        return (
            f"외부 공개 HAZOP 대비 **{recall['recall']:.1%}** ({recall['matched']}/{recall['total']}, 1회 실행) — "
            "인도 IOCL 충전소 워크시트(2014, 외부 팀 작성)의 공정변수 점검표 11행과 대조. 모델이 기본으로 내는 축과 겹쳐 "
            "후하게 나오는 기준입니다."
        )
    if not recall:
        return "사람이 작성한 워크시트 화면이라 정확도는 해당 없음."
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


# ── 다른 팀의 HAZOP 과 대조(PRD_본선_질문봉쇄 Q-02) ─────────────────────────────
_REFERENCE_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "data" / "reference"
#: 10/10 외부 평가 요약(`results/exteval_20261010/summary.json` 사본) — 패널 숫자의 단일 출처. 재측정하지 않는다.
EXTERNAL_SUMMARY_PATH: Final[Path] = _REFERENCE_DIR / "external_eval_summary.json"
#: 평가셋 본체 — 출처 이름·공정·평가 전용 문구·오염 고지를 여기서 읽는다.
EXTERNAL_SET_PATH: Final[Path] = _REFERENCE_DIR / "external_eval_202610.json"
EXTERNAL_PANEL_TITLE: Final[str] = "이 앱을 다른 팀의 HAZOP과 대조하면"
#: 출처 id → 짧은 이름(표의 첫 칸). 값이 아니라 이름이라 여기 둔다.
EXTERNAL_SHORT: Final[dict[str, str]] = {
    "ornl2023": "ORNL 2023", "ioclv2016": "IOCL 2016", "assam2010": "Assam 2010",
    "kais2019": "KAIS 2019", "ijerph2017": "IJERPH 2017",
}
#: 최저 출처가 낮은 이유 — docs/결과_외부평가_20261010.md '범위 밖 출처' 절과 같은 사실(README §6 같은 문장).
EXTERNAL_LOW_REASON: Final[str] = (
    "IJERPH가 낮은 이유 — 항만 터미널 작업 절차(하역·적재 순서)를 다룬 HAZOP이라 정전기·부식·속도·계류 같은 작업 고유의 "
    "파라미터를 씁니다. 이 앱은 이런 설비·절차형 파라미터를 적게 도출합니다(부식·속도는 아예 나오지 않음). "
    "알려진 약점이며, 편집 표에서 사람이 보완해야 하는 부분입니다."
)


def external_eval() -> dict[str, Any]:
    """패널 값 — 요약 파일과 평가셋 파일에서만 읽는다(하드코딩 금지). 출처 순서는 평가셋 파일 순서, 낮은 출처도 그대로."""
    summary = json.loads(EXTERNAL_SUMMARY_PATH.read_text(encoding="utf-8"))
    dataset = json.loads(EXTERNAL_SET_PATH.read_text(encoding="utf-8"))
    by_source = summary["by_source"]
    rows = []
    for src in sorted(dataset["sources"], key=lambda x: -by_source[x["id"]]["coverage"]):
        got = by_source[src["id"]]
        rows.append({
            "출처": EXTERNAL_SHORT.get(src["id"], src["id"]),
            "공정": src["process"],
            "다시 찾아낸 쌍": f"{got['matched']}/{got['total']}",
            "coverage": f"{got['coverage']:.2f}",
        })
    kept = [v["coverage"] for k, v in by_source.items() if k != summary["min_source"]]
    total = sum(v["total"] for v in by_source.values())
    return {
        "head": (
            f"외부 공개 HAZOP 워크시트 {len(by_source)}건 · {summary['nodes']}노드 · (가이드워드, 파라미터) 쌍 {total}개 · "
            f"{summary['measured_at']} 측정 · 비용 ${summary['cost_usd']:.1f}"
        ),
        "question": "다른 팀이 쓴 표의 (가이드워드, 파라미터) 쌍을 이 앱이 얼마나 다시 찾아내는지 잰 값입니다. 원인·결과 문장이 맞는지는 재지 않습니다.",
        "rows": rows,
        "total": (
            f"출처별 평균 {summary['macro_mean']:.2f} · 전체 합산 {summary['pooled']:.2f} · "
            f"{EXTERNAL_SHORT.get(summary['min_source'], summary['min_source'])} 제외 출처 {len(kept)}곳 평균 "
            f"{sum(kept) / len(kept):.2f}"
        ),
        "low_reason": EXTERNAL_LOW_REASON,
        "fine_print": (
            "평가에만 쓰는 자료 — " + dataset["display_eval_only"],
            "평가 자료 사용 이력 — " + dataset["display_contamination"],
        ),
    }


def reference_line(result: Result) -> str | None:
    """외부 공개 HAZOP 대조 공정(지시문 W)의 노드 재생에만 붙는 한 줄 — 'IOCL 2014 대조 n/11'. 다른 공정은 None."""
    m = result.meta
    recall = m.get("recall")
    if m.get("split") != "external" or m.get("combined") or not recall:
        return None
    return (f"IOCL 2014 대조 {recall['matched']}/{recall['total']} — 인도 IOCL 충전소 공개 워크시트(외부 팀 작성)의 "
            "공정변수 점검표와 (가이드워드, 파라미터) 쌍을 맞춘 수. 쉬운 기준이라 위 패널 값과 나란히 읽지 않습니다.")


def system_note(result: Result) -> str:
    """푸터의 시스템 정보 줄. 결과 출처는 화면 위 출처 줄과 같은 함수(`provenance_line`)로 쓴다(Q-01-4)."""
    font = "화면 글꼴: 에스코어 드림(S-Core 제공)."
    if result.is_gold or not result.meta.get("model_id"):
        return font
    return f"{font} 결과 출처: {provenance_line(result)}"


def summary_line(result: Result) -> str:
    """요약 줄. 불리한 숫자도 그대로(NFR-03) — 값이 없으면 없다고 적는다."""
    m = result.meta
    parts = [f"행 {len(result.records)}개", f_distribution(result)]
    cited = evidence_line(result)
    if cited:
        parts.insert(1, cited)
    credit = ipl_line(result)
    if credit:  # S-4-3 빈도 분포 바로 뒤
        parts.insert(parts.index(f_distribution(result)) + 1, credit)
    if m.get("source") == "quick":
        parts.insert(0, QUICK_SCOPE.format(guideword=", ".join(m.get("guidewords") or [])))
    if m.get("combined"):
        parts.insert(0, f"{m['process']} 공정 전체(노드 {len(m['nodes'])}개)")
    if m.get("expected_cells") is not None:
        parts.append(f"판정한 칸 {m.get('judged_cells')}/{m['expected_cells']}")
    breakdown = cell_breakdown(result)
    if breakdown:
        parts.append(breakdown)
    review = m.get("review_guidewords") or []
    parts.append(f"판정에 실패한 가이드워드 {', '.join(review) if review else '없음'}")
    if result.is_gold:
        parts.append("검증 해당 없음(전문가 작성 결과)")
    else:
        by_rule = verified(result)[1].by_rule
        n_review = sum(r.confidence == "review" for r in verified(result)[0])
        parts.append(
            f"검토 필요 {n_review}건 (근거 없는 규격 {by_rule['unverified_standard']}·수치 {by_rule['unsupported_number']})"
        )
    latency = m.get("latency_s")
    parts.append(f"소요 {latency:.0f}초" if latency is not None else "소요 시간 해당 없음")
    cost = m.get("cost_usd")
    parts.append(f"비용 ${cost:.3f}" if cost is not None else "비용 해당 없음")
    # 정확도(recall)는 화면에 싣지 않는다(10/9 사용자 결정) — 재생 메타·README §6 에만 남는다.
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


#: 공급자 → 출처 줄의 경유 표기(Q-01-3). 재생·라이브가 같은 함수를 쓴다 — 재생만 다르게 적히는 일이 없게.
VIA_LABELS: Final[dict[str, str]] = {
    "gateway": "Amazon Bedrock 경유(대회 제공 게이트웨이)",
    "bedrock": "Amazon Bedrock",
    "anthropic": "Anthropic API 직접 호출",
}


def origin_parts(result: Result) -> list[str]:
    """출처 줄의 꼬리 — 경유 · 모델 · 프롬프트 판본 · 평가기준 · 병렬 · 비용. 값은 결과 메타에서만 읽는다."""
    m = result.meta
    parts: list[str] = []
    provider = m.get("provider")
    if provider == "anthropic" and m.get("endpoint"):  # ANTHROPIC_BASE_URL 로 다른 곳을 거친 직결 SDK 호출
        parts.append(f"{m['endpoint']} 경유")
    elif provider in VIA_LABELS:
        parts.append(VIA_LABELS[provider])
    parts.append(m.get("model_id") or "모델 미상")
    version = m.get("prompt_version")
    if version:
        parts.append("프롬프트 현행 판" if version == prompt_version() else "프롬프트 이전 판")
    elif m.get("source") == "live" and _before_m01(m):
        parts.append("**초기 프롬프트**(판정 단계에 기존 안전장치·운전조건을 넘기지 않던 판)")
    if result.records or m.get("criteria_id"):
        parts.append(f"평가기준 {criteria_label(result_criteria(result))}")
    if (m.get("parallel_calls") or 1) > 1:
        parts.append(f"동시 호출 {m['parallel_calls']}개")
    cost = m.get("cost_usd")
    if cost is not None:
        parts.append(f"비용 ${cost:.3f}")
    return parts


#: 교열 10/15 — 재생 결과에 표기 대응표(`data/replay_notation.json`)를 적용했을 때 출처 안내에 붙는 말.
NOTATION_NOTE: Final[str] = "문장 교열(끝맺음·기호·번역투·영어 괄호·어색한 낱말과 조사)을 {n}곳 적용해 표시함 — 뜻은 저장본 그대로"


def notation_part(meta: Mapping[str, Any]) -> str:
    """교열 대응표를 적용한 문장 수가 있으면 ' · 문장 교열 …' 한 토막, 없으면 빈 문자열."""
    n = meta.get("notation_applied") or 0
    return " · " + NOTATION_NOTE.format(n=n) if n else ""


def provenance_line(result: Result) -> str:
    """이 결과가 어디서 왔는지 한 줄(J-04 ③ · Q-01-3). 재생이어도 실호출 캡처 일시·경유·모델·프롬프트·기준·비용을 적는다."""
    m = result.meta
    source = m.get("source")
    if m.get("combined"):
        cost = m.get("cost_usd")
        cost_part = f" · 합계 비용 ${cost:.3f}" if cost is not None else ""
        vias = sorted({VIA_LABELS.get(str(p), "") for p in m.get("providers") or []} - {""})
        via_part = f" · {' / '.join(vias)}" if vias else ""
        return (
            f"{m['process']} — 노드 {len(m['nodes'])}개를 하나씩 실제로 생성해 저장한 결과를 노드 순서대로 이어 붙여 보여 줌"
            f"{via_part}{cost_part}{notation_part(m)} · 노드별 저장 시각과 프롬프트는 아래 '노드별 출처'에 있음"
        )
    if result.is_gold:
        return f"사람이 직접 작성한 HAZOP 워크시트 — AI 생성 결과 아님 ({_kst(m.get('captured_at'))} 저장)"
    if m.get("mock"):
        scope = " · " + QUICK_SCOPE.format(guideword=", ".join(m.get("guidewords") or [])) if source == "quick" else ""
        return f"mock 실행 — 네트워크 없이 재생 레코드로 생성 경로를 돈 결과 ({_kst(m.get('captured_at'))}){scope}"
    when = f"{_kst(m.get('captured_at'))} " + ("저장된 생성 결과" if source == "live" else "방금 생성")
    tail = " · ".join([when, *origin_parts(result)]) + notation_part(m)
    if source == "quick":
        tail += " · " + QUICK_SCOPE.format(guideword=", ".join(m.get("guidewords") or []))
    return tail


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


def param_range(replays: Mapping[str, Result]) -> tuple[int, int] | None:
    """저장된 실호출 결과의 노드당 파라미터 수 (최소, 최대) — '회의와 비교' 표가 쓴다(Q-05-2). 열거 기록이 없으면 None."""
    counts = [len(r.meta["parameters"]) for r in replays.values() if not r.is_gold and r.meta.get("parameters")]
    return (min(counts), max(counts)) if counts else None


def guideword_count(guidewords: list[str]) -> str:
    """'가이드워드 10종(표준 7 + 절차형 3)' — 결과에 실제로 쓰인 가이드워드를 상수 축으로 나눠 센다(Q-05-1)."""
    standard = sum(g in STANDARD_GUIDEWORDS for g in guidewords)
    procedural = sum(g in PROCEDURAL_GUIDEWORDS for g in guidewords)
    if procedural:
        return f"가이드워드 {len(guidewords)}종(표준 {standard} + 절차형 {procedural})"
    return f"가이드워드 {len(guidewords)}종"


def calls_line(result: Result) -> str:
    """'AI 가 한 일' 첫 줄 — 호출 수는 저장된 원시 호출 기록에서. 기록이 없으면 '—' 대신 없다고 적는다(Q-05-3)."""
    m = result.meta
    raw = m.get("raw_calls")
    if raw is None:
        return "API 호출 기록 없음 — 사람이 작성한 워크시트" if result.is_gold else "API 호출 기록 없음"
    scope = f" (노드 {len(m['nodes'])}개 합계)" if m.get("combined") else ""
    parsed = sum(c.get("stage") == "parse" for c in raw)
    tail = f" — 문장 해석 {parsed}회 포함" if parsed else ""
    return f"API 호출 {len(raw)}회{scope}{tail}(재시도 포함)"


def given_lines(result: Result) -> list[str]:
    """'사용자가 준 것' — 노드 입력. 공정 전체는 노드마다 한 줄(빈 `{}` 를 보이지 않는다, Q-05-3)."""
    m = result.meta
    metas = m.get("node_metas") or [m.get("node_meta") or {}]
    lines = []
    for meta in metas:
        if not meta:
            continue
        values = [f"물질 {meta.get('substance') or '—'}", f"설비 {', '.join(meta.get('equipment') or []) or '—'}"]
        if meta.get("P_kPag") is not None:
            values.append(f"운전압력 {meta['P_kPag']:g} kPag")
        if meta.get("T_degC") is not None:
            values.append(f"온도 {meta['T_degC']:g} ℃")
        guards = meta.get("safeguards") or []
        values.append(f"안전장치 {len(guards)}개" if guards else ("안전장치 없음(입력에 명시)" if meta.get("safeguards_known")
                                                               else "안전장치 정보 없음"))
        lines.append(f"**{meta.get('node') or '노드'}** — " + " · ".join(values))
    return lines or ["노드 입력 기록 없음"]


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
    return f"가이드워드 {', '.join(failed)} 판정 실패{tail}. 판정에 실패한 가이드워드의 칸은 결과에 없습니다."


def partial_rows(records: list[DeviationRecord]) -> list[dict[str, object]]:
    """생성 중 부분 표(X-1c) — 가볍게 6열. 레코드는 생성기가 공정 순서(Y-1)로 준다."""
    return [
        {"가이드워드": r.guideword, "파라미터": r.parameter, "이탈": r.deviation, "심각도": r.S, "빈도": r.F, "위험도": r.risk_score}
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
            head = f"{name} — 판정 실패"
        else:
            head = f"{name} — {len(indices)}건"
            if key == "guideword" and parameters and not result.meta.get("combined"):
                skipped = len(parameters) - len({records[i].parameter for i in indices})
                head += f" (해당 없음 {skipped}칸)" if skipped > 0 else ""
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
        "providers": sorted({str(m.get("provider")) for m in metas if m.get("provider")}),
        # Q-05-3: 'AI 가 한 일' 탭이 공정 전체에서도 호출 수·노드 입력을 보인다 — 노드별 값을 이어 붙인다
        "raw_calls": None if any(m.get("raw_calls") is None for m in metas)
        else [c for m in metas for c in m["raw_calls"]],
        "node_metas": [m.get("node_meta") or {} for m in metas],
        "parameters": list(dict.fromkeys(p for m in metas for p in m.get("parameters") or [])),
        "captured_at": max(str(m.get("captured_at", "")) for m in metas),
        "latency_s": None,
        "cost_usd": None if cost is None else round(cost, 4),
        "expected_cells": _sum([m.get("expected_cells") for m in metas]),
        "judged_cells": _sum([m.get("judged_cells") for m in metas]),
        "review_guidewords": sorted({g for m in metas for g in m.get("review_guidewords") or []}),
        "recall": None,
        "recall_parts": recall_parts,
        "notation_applied": sum(m.get("notation_applied") or 0 for m in metas),
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
                    else ("사람 작성 — 해당 없음" if results[node].is_gold else "—")
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
        label = f"홀드아웃 합계 ({scope} — 정답 {gold}/{HOLDOUT_GOLD_TOTAL}건)"
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
REVIEW_FRONT: Final[tuple[str, ...]] = (
    "이탈", "위험도", "S(1-5)", FREQ_SHIFT_COLUMN, "F(1-5)", CONFIDENCE_COLUMN, REPEAT_COLUMN, EVIDENCE_COLUMN,
)
#: 글 열 너비(px) — 'large' 는 열 4개가 화면을 다 먹어 숫자 열이 밀려난다(10/8 1440px 캡처).
REVIEW_WIDTHS: Final[dict[str, int]] = {
    "가이드워드": 130, "이탈": 300, "원인": 300, "결과": 300, "기존 안전장치(Before)": 220, "권고": 300,
}
#: 화면 열 머리글(교열 10/15 — 한국어 뒤 영어 괄호를 뺀다). 데이터 열 이름과 Excel 머리글은 원본 양식 그대로(R-02).
COLUMN_LABELS: Final[dict[str, str]] = {"기존 안전장치(Before)": "기존 안전장치"}
REVIEW_ROW_HEIGHT: Final[int] = 84
#: 결과 읽는 순서(PRD 첫화면 U-7).
READING_ORDER: Final[str] = (
    "읽는 순서: ① 표를 읽고 → ② 🔴 검토 필요·⚪ 정보 부족 행을 먼저 확인 → ③ '편집 표'에서 채택·기각·수정 → ④ 위에서 내려받기"
)
#: 표 모양(10/9 사용자 피드백 "항목이 잘려 늘려서 봐야 한다"). 펼쳐 보기 = 글 전체 줄바꿈(읽기), 편집 표 = 기존 격자(검토·수정).
TABLE_STYLES: Final[tuple[str, ...]] = ("펼쳐 보기 — 글 전체", "편집 표 — 채택·기각·수정")
#: 펼쳐 보기 열 너비(px). 없는 열은 내용 길이대로.
FULL_WIDTHS: Final[dict[str, int]] = {
    "No": 40, "검토": 64, "가이드워드": 120, "이탈": 240, "위험도": 60, "S(1-5)": 92, "F(1-5)": 80,
    "신뢰도": 170, "반복 일치": 220, "관련 법령·MSDS": 200, "원인": 260, "결과": 260, "기존 안전장치(Before)": 180, "권고": 260,
    "노드": 160, "시나리오 연계": 120, FLAG_COLUMN: 180, "빈도 근거": 220, FREQ_SHIFT_COLUMN: 120,
}  # 10/15 머리글이 옆 열로 넘쳐 '심각도(' 로 잘려 보였다 — 머리글은 줄바꿈 허용, 숫자 열은 머리글 한 줄 너비로.
#: 편집 표에서 목록 항목 사이 구분(10/15). 데이터·파일은 줄바꿈(`LIST_JOINER`).
EDIT_JOINER: Final[str] = " | "
_LIST_COLUMNS: Final[tuple[str, ...]] = ("원인", "결과", "기존 안전장치(Before)", "권고")
_HIDE_IF_UNIFORM: Final[tuple[str, ...]] = ("노드", "시나리오 연계", FLAG_COLUMN, EVIDENCE_COLUMN)


_KOREAN: Final[dict[str, str]] = {"S": "심각도", "F": "빈도"}


def _blank(value: object) -> bool:
    """data_editor 의 빈 숫자 칸 — None 또는 NaN."""
    return value is None or (isinstance(value, float) and value != value)


def _split_list(value: object) -> list[str]:
    """한 칸의 목록 문자열 → 항목. 구분은 줄바꿈(`LIST_JOINER`, 파일·펼쳐 보기)과 `|`(편집 표 — 격자는 줄바꿈을 못 보여 준다).
    항목 문장 속 "·"는 자르지 않는다(10/15 — 항목의 45%가 "배관·펌프"처럼 "·"를 품는다). 두 구분 문자는 항목 문장에 나오지 않는다."""
    return [part.strip() for part in re.split(r"[\n|]", str(value or "")) if part.strip()]


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
    """화면 표 사본에 검토 편집(검토 판정·수정 값)을 넣는다 — 다른 보기의 읽기 전용 표와 편집 표 재생성용.

    S-4-1: 반영 후 빈도(F)를 고치면 `기본→반영` 표시의 뒤쪽도 따라 바꾼다(기본값은 AI 판정 그대로).
    """
    out = [dict(row) for row in table]
    for i, edit in edits.items():
        if 0 <= int(i) < len(out):
            row = out[int(i)]
            row.update({k: v for k, v in edit.items() if k in row})
            if FREQ_SHIFT_COLUMN in row and "F(1-5)" in edit and not _blank(edit["F(1-5)"]):
                base, arrow, _ = str(row[FREQ_SHIFT_COLUMN]).partition("→")
                row[FREQ_SHIFT_COLUMN] = f"{base}→{int(edit['F(1-5)'])}" if arrow else str(int(edit["F(1-5)"]))
    return out


def read_only_order(order: list[str]) -> list[str]:
    """S-4-1 읽기 보기(펼쳐 보기·묶음 보기)의 열 — 크레딧 결과면 F 숫자 열 대신 `기본→반영` 한 열만."""
    if FREQ_SHIFT_COLUMN not in order:
        return order
    return [c for c in order if c != "F(1-5)"]


def full_table_html(rows: list[dict[str, object]], columns: list[str], criteria: Criteria) -> str:
    """펼쳐 보기 표 — 글을 자르지 않고 줄바꿈. 목록 열(원인·결과·안전장치·권고)은 항목마다 한 줄. 값은 전부 이스케이프."""
    labels = {"S(1-5)": f"심각도(1-{criteria.s_max})", "F(1-5)": f"빈도(1-{criteria.f_max})", **COLUMN_LABELS}

    def cell(column: str, value: object) -> str:
        if value is None or (isinstance(value, float) and value != value):
            return ""
        if column in _LIST_COLUMNS:
            items = _split_list(value)
            return "<br>".join(f"• {html.escape(i)}" for i in items) if len(items) > 1 else html.escape(" ".join(items))
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return html.escape(str(value))

    def width(column: str) -> str:
        return f' style="min-width:{FULL_WIDTHS[column]}px;max-width:{FULL_WIDTHS[column]}px"' if column in FULL_WIDTHS else ""

    head = "".join(f"<th{width(c)}>{html.escape(labels.get(c, c))}</th>" for c in columns)
    body = "".join(
        "<tr>" + "".join(f"<td{width(c)}>{cell(c, row.get(c))}</td>" for c in columns) + "</tr>" for row in rows
    )
    return f'<div class="hz-full"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def readable_rows(table: list[dict[str, object]]) -> list[dict[str, object]]:
    """편집 표용 사본 — 목록 열은 ` | ` 로 잇는다(격자는 줄바꿈을 보여 주지 않는다). `apply_review` 는 구분 문자·공백 차이를 수정으로 치지 않는다."""
    return [
        {k: (EDIT_JOINER.join(_split_list(v)) if k in _LIST_COLUMNS else v) for k, v in row.items()} for row in table
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
                if value == shown[column] or (_blank(value) and _blank(shown[column])):
                    continue
            elif _split_list(value) == _split_list(shown[column]):
                continue  # 화면은 ' · ' 로 띄워 보여 준다 — 띄어쓰기만 다르면 같은 값
            if field in ("S", "F"):
                if _blank(value):  # 보류 행(Z-3)만 빈칸을 허용 — 판정한 행의 등급은 지울 수 없다
                    if record.get("status") != INSUFFICIENT:
                        raise ValueError(f"{_KOREAN[field]}는 비울 수 없습니다(빈칸은 정보 부족으로 보류한 행에만 허용)")
                    record[field] = None
                    changed.append(column)
                    continue
                grade = int(value)
                if grade != value or not 1 <= grade <= limits[field]:
                    raise ValueError(f"{_KOREAN[field]}는 1~{limits[field]} 사이의 정수여야 합니다({criteria.short}): {value!r}")
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


#: Q-06-1 LOPA 명칭 — 화면 버튼·파일명·문서 첫 줄.
LOPA_LABEL: Final[str] = "LOPA 후보 시나리오 (Word)"
LOPA_DOCX_NAME: Final[str] = "lopa_candidates.docx"
LOPA_FIRST_LINE: Final[str] = "심각도×빈도로 고른 후보 목록 — IPL·PFD·SIL은 계산하지 않았으며, LOPA 본 분석은 전문가가 합니다"
LOPA_MD_TITLE: Final[str] = "# LOPA 초안"
LOPA_TITLE: Final[str] = "# LOPA 후보 시나리오"


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
    # LOPA 는 Word 로 내려받는다(사용자 결정 9/29). 내용은 core/export/lopa.py 의 Markdown 에 이름·첫 줄만 바꾼다 —
    # IPL·PFD 가 없는 S×F 목록을 'LOPA 초안'이라 부르지 않는다(Q-06-1).
    markdown = files["lopa"][1].decode("utf-8").replace(LOPA_MD_TITLE, LOPA_TITLE, 1)
    files["lopa"] = (LOPA_DOCX_NAME, lopa_markdown_to_docx(f"{LOPA_FIRST_LINE}\n\n{markdown}"))
    return files

