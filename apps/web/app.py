"""HAZOP 코파일럿 데모 화면 — FR-10 UX v3.1 (docs/PRD_UX_v3.md + 사용자 피드백 9/29 22:40 "문서 같다, 앱 같지 않다").

흐름: 상단바 → [왼쪽: 한 줄 정의·3단계 흐름 | 오른쪽: 작업 카드(모드·입력·실행)] → 결과(지표 타일 → 내보내기 → 탭) →
HAZOP 이 처음이라면(짧은 3카드·절차 비교) → 정확도(접힘) → 푸터.
위젯 배선만 한다. 로직은 `apps/web/service.py`·`apps/web/replay.py`·`apps/web/catalog.py` 에 있다.
실행: `streamlit run apps/web/app.py`
"""

import sys
from pathlib import Path

# 리포 루트를 먼저 sys.path 에 넣는다 — pyproject 가 packages=[] 라 배포 환경엔 core 가 설치되지 않는다.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import contextlib  # noqa: E402
from typing import Any  # noqa: E402

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

from apps.web import form, guide, service  # noqa: E402
from apps.web.replay import load_replays  # noqa: E402
from core.agent.generate import PROCEDURAL_GUIDEWORDS, STANDARD_GUIDEWORDS  # noqa: E402

#: 모드·입력 방식 이름(PRD_본선_첫화면_사용흐름 Q-U2·Q-U3, 10/9 결정). 첫 화면 흐름 카드·안내 탭이 같은 말을 쓴다.
MODE_NL = "새로 만들기"
MODE_CASES = "완성된 사례 보기"
#: 항목 선택은 JSON 으로 넘어가 문장 해석 호출이 없다.
INPUT_TEXT = "문장으로 설명"
INPUT_FORM = "항목 선택"
#: 예시 칩 안내 — 문장으로 설명에만 예시가 있다(10/9 사용자: "항목 선택일 때는 예시가 없어졌으면").
CHIP_HINT = "공정 예시 — 누르면 아래 칸에 예시 문장이 채워집니다. 그대로 써도, 고쳐 써도 됩니다."
GUIDEWORDS = STANDARD_GUIDEWORDS + PROCEDURAL_GUIDEWORDS
REPO = "https://github.com/LEETHESAVAGE-kr/aws"
README_EVAL = f"{REPO}/blob/main/README.md#-6-평가-결과"
#: 입력 칸 placeholder — 예시 문장은 칩이 맡고, 여기엔 쓰는 요령만.
DIRECT_PLACEHOLDER = (
    "예시를 누르거나 공정을 직접 적어 보세요.\n"
    "물질 · 설비(흐름 순서) · 운전압력 · 온도 · 설계압력 · 용량 · 안전장치(설정값 포함)를 적을수록 구체적입니다. 모르는 값은 빼도 됩니다.\n"
    '(NodeMeta JSON 도 받습니다: {"node": "X1", "substance": "프로판", "P_kPag": 800, ...})'
)
#: 예시 칩 (라벨, 문장) — PRD §4-4.
EXAMPLES: tuple[tuple[str, str], ...] = (
    (
        "수소충전소",
        "수소충전소에서 튜브트레일러의 압축 수소를 압축기로 약 90 MPa 까지 올려 저장용기에 모았다가 "
        "디스펜서로 차량에 충전한다. 안전장치는 안전밸브, 긴급차단밸브, 수소누출감지기.",
    ),
    (
        "메탄올 하역",
        "탱크로리의 메탄올을 하역 펌프로 상압 저장탱크(약 30 ℃)에 받는다. 탱크에는 질소 블랭킷과 "
        "브리더밸브가 있고, 하역장에는 가스감지기와 긴급차단밸브가 있다.",
    ),
    (
        "실란 가스 캐비닛",
        "반도체 라인의 가스 캐비닛에서 실란(SiH4) 실린더를 자동 절체하며 약 0.5 MPa 로 감압해 공정 장비에 "
        "공급한다. 안전장치는 캐비닛 배기, 가스감지기, 과류차단밸브, 긴급차단밸브.",
    ),
)
#: 부스 모드 예시 칩(지시문 V-2) — 관람객이 아는 장소의 공정. 물질·설비·안전장치를 넣어 해석이 비지 않게.
#: 세 번째 값은 칩이 함께 고르는 가이드워드(V-6). 수영장은 More 로는 산 혼입→염소가스가 안 나온다(10/8 실측,
#: As well as 에서 No.4·5 행으로 나옴).
BOOTH_EXAMPLES: tuple[tuple[str, str, str | None], ...] = (
    (
        "학교 실험실 수소",
        "학교 화학 실험실에서 수소 실린더(약 15 MPa)를 감압밸브로 낮춰 가스 분석기에 공급한다. "
        "다 쓴 실린더는 사람이 직접 교체한다. 안전장치는 가스누출감지기와 긴급차단밸브.",
        None,
    ),
    (
        "아파트 LPG 공급",
        "아파트 단지의 LPG 저장탱크에서 기화기를 거쳐 배관으로 각 세대 가스레인지에 공급한다. "
        "안전장치는 가스누출경보기, 긴급차단밸브, 안전밸브.",
        None,
    ),
    (
        "수영장 염소 소독",
        "수영장 기계실에서 차아염소산나트륨 용액을 정량펌프로 순환 배관에 주입해 소독한다. "
        "바로 옆에 pH 조정용 산 탱크가 있다. 안전장치는 유량 인터록과 누출 받침대.",
        "As well as",
    ),
)
GUIDEWORD_HELP = (
    "No: 흐름 없음 · More: 과다(압력·온도·유량↑) · Less: 과소 · Reverse: 역류 · Part of: 조성 일부 · "
    "As well as: 이물 혼입 · Other than: 다른 물질/상태"
)

#: 가이드워드 → 뜻 (선택 칸에 함께 보여 준다). "No: 흐름 없음" → {"No": "흐름 없음"}
GUIDEWORD_MEANING: dict[str, str] = dict(
    part.split(": ", 1) for part in GUIDEWORD_HELP.split(" · ")
)

st.set_page_config(page_title="HAZOP Copilot", layout="wide")
#: 부스 모드(지시문 V) — `?booth=1` 일 때만. 기본 화면은 그대로다.
BOOTH = st.query_params.get("booth") == "1"
if BOOTH:  # V-4 큰 글씨 — 43" 모니터를 2 m 밖에서 본다
    st.html("<style>.stApp { zoom: 1.2; }</style>")
# DESIGN.md 토큰: primary #9046ff · primary-tint #f3ecff · primary-soft #c59eff · rounded.md 14px.
# 회색 캔버스 위 흰 카드 = "앱" 의 기본 문법. 셀렉터가 버전과 달라도 기능은 같다 — 모양만 잃는다(U-R6).
st.html(
    """<style>
    :root { --bg: #141417; --card: #1e1e23; --card2: #26262d; --line: #32323b; --text: #f3f3f6;
        --muted: #9b9ba8; --accent: #9046ff; --accent-text: #b996ff; --accent-soft: rgba(144,70,255,.16); }
    header[data-testid="stHeader"], #MainMenu, footer { display: none !important; }
    .stApp { background: var(--bg); }
    .hz-full { max-height: 760px; overflow: auto; border: 1px solid var(--line); border-radius: 12px; }
    .hz-full table { border-collapse: collapse; font-size: 13px; line-height: 1.5; width: max-content; min-width: 100%; }
    .hz-full th { position: sticky; top: 0; z-index: 1; background: var(--card2); color: var(--muted); font-weight: 600;
        text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
    .hz-full td { vertical-align: top; padding: 8px 10px; border-bottom: 1px solid var(--line); color: var(--text);
        white-space: normal; word-break: keep-all; overflow-wrap: anywhere; }
    .hz-full tr:hover td { background: rgba(255,255,255,.03); }
    .block-container { padding-top: 0 !important; max-width: 1240px; }
    [data-testid="stVerticalBlockBorderWrapper"] { background: var(--card); border-radius: 16px !important;
        border-color: var(--line) !important; }
    [data-testid="stMetric"] { background: var(--card); border: 1px solid var(--line); border-radius: 14px;
        padding: 14px 18px; }
    [data-testid="stMetricLabel"] p { font-size: 13px; color: var(--muted); }
    [data-testid="stMetricValue"] { font-size: 30px; font-weight: 700; color: var(--text); }
    .hz-bar { position: sticky; top: 0; z-index: 100; background: var(--bg); height: 60px; display: flex;
        align-items: center; justify-content: space-between; border-bottom: 1px solid var(--line);
        margin: 0 -9999px 24px; padding: 0 9999px; }
    .hz-logo { font-size: 18px; font-weight: 700; color: var(--text); display: flex; align-items: center; gap: 10px; }
    .hz-logo i { width: 24px; height: 24px; border-radius: 7px; background: var(--accent); display: inline-block; }
    .hz-nav a { margin-left: 22px; color: var(--muted); text-decoration: none; font-size: 14px; }
    .hz-nav a:hover { color: var(--text); }
    @media (max-width: 900px) { .hz-nav { display: none; } }
    .hz-eyebrow { font-size: 13px; font-weight: 600; color: var(--accent-text); margin: 8px 0 8px; }
    .hz-h1 { font-size: 34px; letter-spacing: -0.4px; font-weight: 700; line-height: 1.4; margin: 0 0 12px;
        color: var(--text); }
    .hz-sub { font-size: 15px; color: var(--muted); margin: 0 0 26px; line-height: 1.65; }
    .hz-steps { display: flex; flex-direction: column; gap: 10px; margin-bottom: 22px; }
    .hz-step { display: flex; gap: 14px; align-items: center; background: var(--card); border: 1px solid var(--line);
        border-radius: 12px; padding: 12px 14px; }
    .hz-step b { flex: none; width: 28px; height: 28px; border-radius: 8px; background: var(--accent-soft);
        color: var(--accent-text); font-size: 14px; display: flex; align-items: center; justify-content: center; }
    .hz-step strong { display: block; font-size: 15px; color: var(--text); }
    .hz-step span { font-size: 13px; color: var(--muted); }
    .hz-step ul { margin: 4px 0 0; padding-left: 16px; }
    .hz-step li { font-size: 13px; color: var(--muted); margin: 2px 0; }
    .hz-step em { font-style: normal; color: var(--accent-text); font-weight: 600; margin-right: 4px; }
    .hz-sub b { color: var(--text); font-weight: 600; }
    .hz-progress { height: 4px; background: var(--card2); border-radius: 4px; overflow: hidden; margin: 4px 0 18px; }
    .hz-progress div { height: 100%; background: var(--accent); border-radius: 4px; }
    .hz-q-step { font-size: 12px; color: var(--muted); margin: 0 0 4px; letter-spacing: .3px; }
    .hz-q { font-size: 21px; font-weight: 700; color: var(--text); margin: 0 0 4px; letter-spacing: -0.3px; }
    .hz-q-help { font-size: 13px; color: var(--muted); margin: 0 0 4px; }
    .hz-card-sub { font-size: 13px; color: var(--muted); margin: 0; }
    .hz-section { font-size: 22px; font-weight: 700; margin: 36px 0 6px; color: var(--text); }
    .hz-empty { border: 1px dashed var(--line); border-radius: 16px; padding: 40px 24px; text-align: center;
        color: var(--muted); background: var(--card); }
    .hz-empty strong { display: block; font-size: 17px; color: var(--text); margin-bottom: 8px; }
    .hz-info { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 18px 20px;
        height: 100%; }
    .hz-info-t { font-size: 13px; font-weight: 600; color: var(--accent-text); margin: 0 0 6px; }
    .hz-info-h { font-size: 17px; font-weight: 700; color: var(--text); margin: 0 0 14px; line-height: 1.4; }
    .hz-info-r { display: flex; gap: 12px; padding: 9px 0; border-top: 1px solid var(--line); font-size: 14px; }
    .hz-info-r span { flex: none; width: 36px; color: var(--muted); }
    .hz-info-r b { font-weight: 500; color: var(--text); }
    .st-key-mode, .st-key-mode .stRadio, .st-key-mode [data-testid="stRadio"] > div { width: 100% !important; }
    [class*="st-key-view_"] [role="radiogroup"] { gap: 0; background: var(--card2); border-radius: 10px; padding: 3px;
        display: inline-flex; }
    [class*="st-key-view_"] [data-testid="stRadioOption"] { border-radius: 8px; padding: 5px 14px; margin: 0; cursor: pointer; }
    [class*="st-key-view_"] [data-testid="stRadioOption"] > div > div:first-child { display: none; }
    [class*="st-key-view_"] [data-testid="stRadioOption"] p { font-size: 13px; color: var(--muted); }
    [class*="st-key-view_"] [data-testid="stRadioOption"][data-selected="true"] { background: #3a3a44; }
    [class*="st-key-view_"] [data-testid="stRadioOption"][data-selected="true"] p { color: var(--text); font-weight: 600; }
    .st-key-mode [role="radiogroup"] { gap: 0; background: var(--card2); border-radius: 12px; padding: 4px;
        display: flex; flex-wrap: nowrap; width: 100%; }
    .st-key-mode [role="radiogroup"] > div { flex: 1; }
    .st-key-mode [data-testid="stRadioOption"] { width: 100%; justify-content: center; border-radius: 9px;
        padding: 8px 10px; margin: 0; cursor: pointer; }
    .st-key-mode [data-testid="stRadioOption"] > div > div:first-child { display: none; }
    .st-key-mode [data-testid="stRadioOption"] p { font-size: 14px; color: var(--muted); white-space: nowrap; }
    .st-key-mode [data-testid="stRadioOption"][data-selected="true"] { background: #3a3a44; }
    .st-key-mode [data-testid="stRadioOption"][data-selected="true"] p { color: var(--text); font-weight: 600; }
    [class*="st-key-chip_"] button { border-radius: 999px; min-height: 34px; padding: 2px 14px; font-size: 13px;
        background: var(--card2); border-color: var(--line); }
    [class*="st-key-chip_"] button:hover { border-color: var(--accent); color: var(--accent-text); }
    .st-key-cta button { min-height: 54px; font-size: 16px; font-weight: 700; border-radius: 12px; }
    .st-key-process_name [data-baseweb="select"] > div { background-color: var(--accent-soft);
        border: 1px solid var(--accent); font-weight: 600; min-height: 46px; }
    </style>"""
)

with contextlib.suppress(Exception):  # secrets.toml 이 없으면 Streamlit 이 예외를 던진다
    service.sync_secrets(dict(st.secrets))

replays = st.cache_resource(load_replays)()
live_reason = service.live_block_reason()
state = st.session_state
state.setdefault("live_runs", 0)
state.setdefault("quick_result", None)
state.setdefault("node", None)
state.setdefault("quick_text", "")
state.setdefault("input_style", INPUT_TEXT)
state.setdefault("table_style", service.TABLE_STYLES[0])
for _k, _v in form.EMPTY.items():
    state.setdefault(form.KEYS[_k], _v)
state.setdefault("mode", MODE_NL)
state.setdefault("guideword", "More")
state.setdefault("view_pref", service.VIEWS[0])  # 결과 보기(X-2) — 위젯 밖에 둔다
state.setdefault("view_gen", 0)
state.setdefault("focus_guideword", None)


def _node_form() -> None:
    """항목 선택 — 목록에서 고르고, 없으면 직접 적는다(accept_new_options). 값은 `form.KEYS` 상태에 있다."""
    st.caption("필수는 물질·설비 둘뿐입니다. 나머지는 모르면 비워 두세요 — 비운 정보는 ‘정보 부족’으로 다룹니다.")
    left, right = st.columns([3, 2])
    left.selectbox("물질 (필수)", form.SUBSTANCES, key=form.KEYS["substance"],
                   placeholder="고르거나 직접 입력", accept_new_options=True)
    right.selectbox("상태", list(form.PHASES), key=form.KEYS["phase"])
    st.multiselect("설비 (필수) — 흐름 순서대로: 받는 곳 → 내보내는 곳", form.EQUIPMENT, key=form.KEYS["equipment"],
                   placeholder="예: 압축기 → 저장용기 → 디스펜서", accept_new_options=True)
    # 10/9 화면 캡처: 한 줄 6칸이면 단위 칸이 좁아 'MPa' 가 'M' 으로 잘린다 → 두 줄, 단위 칸 넓게
    p, pu, t_ = st.columns([3, 2, 3])
    p.number_input("운전압력", key=form.KEYS["pressure"], min_value=0.0, placeholder="모름")
    pu.selectbox("압력 단위", form.UNITS, key=form.KEYS["pressure_unit"])
    t_.number_input("온도(℃)", key=form.KEYS["temperature"], placeholder="모름")
    d, du, c = st.columns([3, 2, 3])
    d.number_input("설계압력", key=form.KEYS["design_pressure"], min_value=0.0, placeholder="모름")
    du.selectbox("설계압력 단위", form.UNITS, key=form.KEYS["design_unit"])
    c.text_input("용량", key=form.KEYS["capacity"], placeholder="예: 200 kg")
    no_safeguards = st.checkbox("안전장치가 정말 없음", key=form.KEYS["no_safeguards"],
                                help="모르면 체크하지 말고 아래를 비워 두세요 — '없음'과 '모름'은 다르게 다룹니다.")
    st.multiselect("기존 안전장치 — 설정값은 직접 입력(예: 고압 경보(설정 95 MPa))", form.SAFEGUARDS,
                   key=form.KEYS["safeguards"], disabled=no_safeguards, accept_new_options=True,
                   placeholder="비워 두면 '모름'으로 다룹니다")


@st.cache_resource
def _combined(process_id: str) -> service.Result | None:
    return service.combine_replays(next(p for p in service.CATALOG if p["id"] == process_id), replays)


def _fill(text: str, guideword: str | None = None) -> None:
    """예시 칩 — 문장 칸을 채운다. 칩은 '문장으로 설명'에서만 보인다."""
    state.quick_text = text
    if guideword:  # 칩이 지정한 가이드워드(V-6 · X-4) — 결과는 가이드워드별 보기에서 그 묶음을 펼친다
        state.guideword = guideword
        state.view_pref = service.VIEWS[1]
        state.view_gen += 1  # 새 위젯 키 — 상태로 정한 값을 radio 가 선택 표시하게(아래 view_choice)
        state.focus_guideword = guideword


def _to_cases() -> None:
    state.mode = MODE_CASES


def _failure_hint(exc: BaseException) -> str:
    """재시도 소진(`BedrockCallError`)이 감춘 원인 상태코드를 사람 말로. 키 문자는 드러내지 않는다."""
    cause = exc.__cause__ or exc
    code = getattr(cause, "status_code", None)
    if code == 429:
        return (
            "원인: 429 — API 키의 분당 사용량 한도에 걸렸습니다(여러 명이 연달아 누른 경우). "
            '1분쯤 뒤 다시 누르거나, 기다리는 동안 "완성된 사례 보기"를 보세요. 이번 실패는 횟수에 넣지 않았습니다.'
        )
    if code == 529 or (isinstance(code, int) and code >= 500):
        return (
            f"원인: {code} — Anthropic 서버가 일시적으로 과부하입니다. 잠시 뒤 다시 누르세요. "
            "이번 실패는 횟수에 넣지 않았습니다."
        )
    return (
        f"원인: {type(cause).__name__}"
        + (f" (HTTP {code})" if code else "")
        + " — 이번 실패는 횟수에 넣지 않았습니다."
    )


# ── 상단바 ───────────────────────────────────────────────────────────────────
st.html(
    """<div class="hz-bar"><span class="hz-logo"><i></i>HAZOP Copilot</span>
    <span class="hz-nav"><a href="#result">결과</a><a href="#intro">HAZOP 이란</a><a href="#eval">정확도</a>
    <a href="https://github.com/LEETHESAVAGE-kr/aws" target="_blank">GitHub</a></span></div>"""
)

# ── 작업 영역: 왼쪽 소개 · 오른쪽 도구 ───────────────────────────────────────
intro, tool = st.columns([5, 7], gap="large")
intro.html(
    """<div class="hz-eyebrow">AI 위험성평가 초안 도우미</div>
    <div class="hz-h1">HAZOP Copilot</div>
    <p class="hz-sub">화학공장·가스설비의 공정 정보를 넣으면, AI 가 <b>“설비가 원래 하려던 일에서 벗어나면 무슨 일이
    생기나”</b>를 빠짐없이 따져 HAZOP(위험과 운전 분석) 표 초안을 만듭니다. 근거가 있는 내용에는 법령·MSDS 원문을
    붙이고, 모르는 정보는 지어내지 않고 ‘정보 부족’으로 남깁니다. 최종 판단은 전문가가 합니다.</p>
    <div class="hz-steps">
      <div class="hz-step"><b>1</b><div><strong>공정 정보 넣기 — 세 가지 중 하나</strong>
        <ul>
          <li><em>문장으로 설명</em> 예시 공정을 누르면 예시 문장이 채워지고, 고쳐 쓰면 됩니다</li>
          <li><em>항목 선택</em> 물질·설비·압력·안전장치를 목록에서 고릅니다(없으면 직접 입력)</li>
          <li><em>완성된 사례 보기</em> 기다리기 싫다면, 저장해 둔 실제 결과를 바로 엽니다 → 3번으로</li>
        </ul></div></div>
      <div class="hz-step"><b>2</b><div><strong>AI 가 HAZOP 표 만들기 · 약 1.5–2분</strong>
        <span>점검할 항목을 스스로 정하고, 벗어나는 경우마다 원인·결과·심각도·빈도·권고를 씁니다</span></div></div>
      <div class="hz-step"><b>3</b><div><strong>검토하고 내려받기</strong>
        <span>표를 읽고 채택·기각·수정 → Excel 워크시트 · LOPA 초안 Word · 신뢰도 리포트</span></div></div>
    </div>"""
)

result = None
with tool.container(border=True, key="tool"):
    mode = st.radio(
        "모드", [MODE_NL, MODE_CASES], horizontal=True, label_visibility="collapsed", key="mode"
    )
    if mode == MODE_NL:
        done = 3 if state.quick_result is not None else (2 if state.quick_text.strip() or state[form.KEYS["substance"]] else 1)
        st.html(
            f'<div class="hz-progress"><div style="width:{done * 33.4:.0f}%"></div></div>'
            '<p class="hz-q">어떤 공정을 분석할까요?</p>'
            '<p class="hz-q-help">물질·설비·압력·온도·설계압력·용량·안전장치를 넣을수록 정확해집니다. 먼저 입력 방식을 고르세요.</p>'
        )
        input_style = st.radio("입력 방식", [INPUT_TEXT, INPUT_FORM], key="input_style", horizontal=True)
        if input_style == INPUT_TEXT:
            st.html(f'<p class="hz-q-help">{CHIP_HINT}</p>')
            for i, (column, (label, text, *chip_guideword)) in enumerate(
                zip(st.columns(len(EXAMPLES)), BOOTH_EXAMPLES if BOOTH else EXAMPLES, strict=True)
            ):
                column.button(label, key=f"chip_{i}", on_click=_fill, args=(text, *chip_guideword), width="stretch")
            st.text_area(
                "공정 설명",
                key="quick_text",
                height=130,
                max_chars=service.NODE_TEXT_LIMIT,
                placeholder=DIRECT_PLACEHOLDER,
                label_visibility="collapsed",
            )
            run_text = state.quick_text
            form_missing: list[str] = []
        else:
            _node_form()
            values = {k: state[form.KEYS[k]] for k in form.EMPTY}
            form_missing = form.missing_fields(values)
            run_text = "" if form_missing else form.to_node_json(values)
            if form_missing:
                st.caption(f"{' · '.join(form_missing)}을(를) 고르면 생성할 수 있습니다.")
        # V-3 부스 PC 한 대 = 세션 하나 — 세션 상한은 빼고 일 상한(비용 상한)만 건다.
        session_runs = 0 if BOOTH else state.live_runs
        quota = service.quota_block_reason(session_runs)
        blocked = live_reason is not None or quota is not None or not run_text.strip()
        # 지시문 X-1: 기본 실행 = 가이드워드 전체. HAZOP 은 원래 전 가이드워드를 도는 방법이다.
        with st.container(key="cta"):
            clicked_full = st.button(
                service.LIVE_BUTTON,
                type="primary",
                disabled=blocked,
                width="stretch",
            )
        # X-1b 보조 실행 — 특정 가이드워드만 먼저 확인하고 싶을 때(실무 기능).
        with st.expander(service.QUICK_EXPANDER, expanded=False):
            guideword = st.selectbox(
                service.QUICK_QUESTION,
                GUIDEWORDS,
                key="guideword",  # 기본 More(state.setdefault) — 칩이 바꿀 수 있게 상태로 둔다(V-6)
                format_func=lambda g: f"{g} — {GUIDEWORD_MEANING[g]}" if g in GUIDEWORD_MEANING else g,
            )
            clicked_quick = st.button(service.QUICK_BUTTON, key="run_quick", disabled=blocked, width="stretch")
        if clicked_quick or clicked_full:
            reason = service.reserve_live_run(session_runs)
            if reason:
                st.error(reason)
            else:
                state.live_runs += 1
                mock_source = replays.get("N1") or next(iter(replays.values()))
                # 진행 표시는 버튼 바로 아래 — 결과 영역은 첫 화면 밖이라 거기 두면 "아무 일도 없다"로 보인다(9/29 23:05).
                expected = "약 1분" if clicked_quick else "약 1.5~2분"
                with st.status(
                    f"HAZOP 초안 생성 중 · {expected} — 이 화면에서 기다려 주세요", expanded=True
                ) as status:
                    # R-11: 단계가 끝나는 즉시 그 산출물을 쓴다(예전엔 끝난 뒤 2/3·3/3 을 한꺼번에 찍었다).
                    lines = [st.empty() for _ in range(3)]
                    lines[0].write(service.STAGE_PENDING[0])
                    st.caption("생성 중에 다른 버튼을 누르면 이번 생성이 취소됩니다.")
                    partial = st.empty()  # X-1c: 가이드워드 판정이 끝날 때마다 행이 늘어나는 부분 표

                    def on_progress(event: str, payload: dict[str, Any]) -> None:
                        step, text, pending = service.progress_text(event, payload, guideword if clicked_quick else None)
                        lines[step].write(text)
                        if pending is not None and step + 1 < len(lines):
                            lines[step + 1].write(pending)
                        if event == "guideword" and not clicked_quick:
                            partial.dataframe(service.partial_rows(payload["records"]), hide_index=True, height=240)
                        # expanded 를 다시 주지 않으면 라벨 갱신이 상자를 접는다(10/8 브라우저 확인).
                        status.update(label=f"HAZOP 초안 생성 중 · {text.split(' — ')[0]}", expanded=True)

                    try:
                        if clicked_quick:
                            state.quick_result = service.run_quick(
                                run_text, guideword, mock_source, on_progress=on_progress
                            )
                        else:
                            state.quick_result = service.run_live(
                                run_text, mock_source, on_progress=on_progress
                            )
                    except Exception as exc:  # noqa: BLE001 — 사유를 보이고 앱은 계속 산다
                        state.live_runs -= 1  # 실패한 실행은 세션 횟수에서 빼지 않는다
                        status.update(label="생성 실패", state="error", expanded=True)
                        st.error(f"생성 실패: {type(exc).__name__}: {exc}")
                        st.caption(_failure_hint(exc))
                        st.button(
                            "완성된 사례 보기 — 저장된 결과를 바로 확인",
                            key="fail_to_cases",
                            on_click=_to_cases,
                            width="stretch",
                        )
                        if service.is_auth_error(exc):
                            st.caption(service.key_hint())
                    else:
                        status.update(label="완료", state="complete")
                        state.scroll_result = True  # 다음 실행에서 결과로 스크롤
                        st.rerun()  # 버튼을 상한 사유와 함께 즉시 비활성으로 다시 그린다
        left_runs = max(service.SESSION_LIMIT - state.live_runs, 0)
        if live_reason:
            st.caption(live_reason)
        elif quota:
            scope = "이 세션에" if "세션" in quota else "오늘"
            st.caption(
                f"이 세션 남은 횟수 {left_runs}/{service.SESSION_LIMIT} · {scope} 준비된 실행 횟수를 모두 썼습니다. "
                "'완성된 사례 보기'에서 같은 화면을 볼 수 있습니다."
            )
            st.button("완성된 사례 보기", on_click=_to_cases, width="stretch")
        elif BOOTH:
            st.caption(
                f"부스 모드 · 오늘 남은 {service.daily_left()}회 · 생성 약 1.5~2분 — "
                "가이드워드 판정이 끝날 때마다 표가 채워집니다."
            )
        else:
            st.caption(
                f"이 세션 남은 횟수 {left_runs}/{service.SESSION_LIMIT} · "
                "문장 해석 → 파라미터 열거 → 가이드워드 7종 판정(병렬) · "
                f"{service.LIVE_NOTE.split(' · ', 1)[1]}"
                + (
                    " · mock 모드 — 네트워크 없이 재생 레코드로 생성 경로를 돕니다."
                    if service.is_mock()
                    else ""
                )
            )
    else:
        st.html(
            '<p class="hz-card-sub">9/29 에 실제로 생성한 결과를 그대로 다시 보여줍니다(재생성 아님).</p>'
        )
        names = [p["name"] for p in service.CATALOG]
        choice = st.selectbox("공정", names, key="process_name", label_visibility="collapsed")
        process = next(p for p in service.CATALOG if p["name"] == choice)
        if process.get("reference"):  # 지시문 W — 외부 공개 HAZOP 대조(골드셋 아님)
            st.markdown(f":blue-background[공개 HAZOP 대조 · 외부 팀 작성] {process['description']}")
        elif process["gold"]:
            st.markdown(
                ":green-background[전문가 정답지 34건 · 정확도 실측] 액체 암모니아(NH3) 이송 — "
                "전문가가 직접 수행한 HAZOP 34건과 대조합니다."
            )
        else:
            st.markdown(f":orange-background[예시 공정 · 정성 검토용] {process['description']}")
        node_ids = [n["id"] for n in process["nodes"]]
        if state.node not in (*node_ids, service.ALL_NODES):  # 공정을 바꾸면 그 공정의 첫 캡처 노드를 연다
            state.node = next((n for n in node_ids if n in replays), node_ids[0])
        # X-3: 공정 전체를 노드 순서로 이어 본다(재생만 — 공정 전체 실호출은 비목표). 노드 버튼 줄에 넣으면
        # 노드 이름이 "① 공급…" 으로 잘려 따로 한 줄(10/8 캡처).
        if st.button(
            f"공정 전체 보기 — 노드 순서대로 {' → '.join(node_ids)}",
            key="preset_all",
            disabled=not any(n in replays for n in node_ids),
            type="primary" if state.node == service.ALL_NODES else "secondary",
            width="stretch",
        ):
            state.node = service.ALL_NODES
            st.rerun()
        for column, node in zip(st.columns(len(node_ids)), process["nodes"], strict=True):
            captured = node["id"] in replays
            if column.button(
                node["label"] + ("" if captured else " (미캡처)"),
                key=f"preset_{node['id']}",
                disabled=not captured,
                type="primary" if state.node == node["id"] else "secondary",
                width="stretch",
            ):
                state.node = node["id"]
                st.rerun()  # 선택 강조(primary)를 새 노드로 다시 그린다

if mode == MODE_NL:
    result = state.quick_result
elif state.node == service.ALL_NODES:
    result = _combined(process["id"])  # 같은 Result 를 재사용해야 검증 캐시·검토 편집 키가 유지된다
else:
    result = replays.get(state.node)

# ── 결과 ─────────────────────────────────────────────────────────────────────
st.html('<div id="result" class="hz-section">분석 결과</div>')
if result is None:
    st.html(
        '<div class="hz-empty"><strong>아직 결과가 없습니다</strong>'
        '위에서 입력 방식과 예시를 고르고 "HAZOP 초안 생성"을 누르면, 판정이 끝나는 대로 여기에 표가 채워집니다(전체 약 1.5~2분).<br>'
        '기다리기 싫다면 "완성된 사례 보기"에서 저장된 결과를 바로 볼 수 있습니다.</div>'
    )
else:
    if result.is_gold:
        st.warning(service.provenance_line(result))
    else:
        st.caption(service.provenance_line(result))
    if result.meta.get("node_provenance"):  # X-3 공정 전체 — 노드마다 캡처 시각·프롬프트가 다르다
        with st.expander("노드별 출처", expanded=False):
            st.markdown("\n".join(f"- **{n}** {line}" for n, line in result.meta["node_provenance"]))
    failed = service.failed_guidewords_line(result)
    if failed:
        st.warning(failed)
    notices = [(label, text) for label, text in (("평가기준", service.criteria_notice(result)),
                                                 ("안전조치 미반영", service.safeguards_notice(result))) if text]
    if notices:  # U-7 결과 위 알림을 한 상자에
        with st.container(border=True):
            for label, text in notices:
                st.markdown(f":orange-background[{label}] {text}")
    if not result.is_gold:
        st.caption(service.READING_ORDER)
    view = service.process_view(result)
    cells = service.cells_label(result)
    tiles = [
        ("이탈 시나리오", f"{len(result.records)}건"),
        ("판정 셀 (누락 0)", cells),
        ("소요 시간", "—" if view["latency_s"] is None else f"{view['latency_s']:.0f}초"),
        ("비용", "—" if view["cost_usd"] is None else f"${view['cost_usd']:.2f}"),
        *service.recall_tiles(result),
    ]
    if result.meta.get("combined"):  # 공정 전체는 노드별 실행이라 지연 합이 의미 없다 — 타일 6개면 값이 잘린다
        tiles = [t for t in tiles if t[0] != "소요 시간"]
    for column, (label, value) in zip(st.columns(len(tiles)), tiles, strict=True):
        column.metric(label, value)

    # 검토 표(export-formats R-10): 편집 상태를 표보다 먼저 읽어 다운로드에 반영한다. 키에 결과 식별을 넣어
    # 새 결과가 오면 이전 편집이 엉뚱한 행에 붙지 않게 한다. 골드 재생은 사람 작성이라 검토 대상이 아니다.
    # 다른 보기로 가면 data_editor 가 그려지지 않아 Streamlit 이 그 위젯 상태를 지운다 — 편집은 위젯 밖
    # (`review_saved`)에도 두고, 표를 다시 그릴 때는 저장된 편집(`review_base`)을 데이터에 넣어 그린다(X-2b).
    review_key = service.review_key(result)
    review_base: dict[str, dict[int, dict[str, Any]]] = state.setdefault("review_base", {})
    review_saved: dict[str, dict[int, dict[str, Any]]] = state.setdefault("review_saved", {})
    if result.is_gold:
        edits: dict[int, dict[str, Any]] = {}
    elif review_key in state:
        edits = service.merge_edits(review_base.get(review_key, {}), state[review_key].get("edited_rows", {}))
    else:
        edits = review_saved.get(review_key, review_base.get(review_key, {}))
    review_saved[review_key] = edits
    try:
        files = service.export_files(result, edits)
        review_log = service.apply_review(result, edits)[1] if edits else []
    except ValueError as exc:  # S·F 범위 밖 값 — 표의 열 설정이 막지만 서비스가 한 번 더 막는다
        st.error(f"검토 값 오류: {exc}")
        files, review_log = service.export_files(result), []
    mimes = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "lopa": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "report": "application/json",
    }
    labels = {
        "xlsx": "Excel 워크시트",
        "lopa": "LOPA 초안 (Word)",
        "report": "신뢰도 리포트 (JSON)",
    }
    for column, key in zip(st.columns(3), ("xlsx", "lopa", "report"), strict=True):
        name, data = files[key]
        column.download_button(
            f"⬇ {labels[key]} · {name}", data, file_name=name, mime=mimes[key], width="stretch"
        )

    sheet_tab, process_tab = st.tabs(["HAZOP 워크시트", "AI 가 한 일"])
    with sheet_tab:
        # verifier 시연(O-3): 표·요약 줄만 삽입 사본으로. 다운로드는 위에서 원본 `result` 로 만들었다.
        shown = result
        if not result.is_gold and st.checkbox(service.DEMO_TOGGLE_LABEL, key="verifier_demo"):
            shown = service.demo_injected(result)
            st.markdown(service.DEMO_BANNER)
        st.caption(service.summary_line(shown))
        # X-2 보기 전환 — 표시 순서만 바꾼다. 검토 편집은 워크시트 순서에서만(편집 키가 행 인덱스라서).
        # 위젯 키에 상태로 값을 넣어 두면 처음 그릴 때 화면 선택 표시가 그 값을 따르지 않는다(10/8 브라우저 확인,
        # segmented_control·radio 둘 다). 값은 위젯 밖 `view_pref` 에 두고, 칩이 바꾸면 새 키 + index 로 다시 만든다.
        view_key = f"view_{state.view_gen}"

        def _keep_view() -> None:
            state.view_pref = state[view_key]

        view_choice = st.radio(
            "보기",
            service.VIEWS,
            index=service.VIEWS.index(state.view_pref),
            key=view_key,
            on_change=_keep_view,
            horizontal=True,
            label_visibility="collapsed",
        )
        table_style = st.radio("표 모양", service.TABLE_STYLES, key="table_style", horizontal=True,
                               label_visibility="collapsed")
        full_text = table_style == service.TABLE_STYLES[0]
        editable = not result.is_gold and shown is result
        table = service.readable_rows(service.worksheet_table(shown))
        if not result.is_gold:  # 검토 열 — 다른 보기에서는 편집 결과를 읽기 전용으로 보여 준다
            table = [{service.REVIEW_COLUMN: service.REVIEW_CHOICES[0], **row} for row in table]
        order = service.review_column_order(table)
        # 검토자는 열을 눈으로 따라가며 판단한다(10/8 피드백) — 왼쪽 고정·넓은 글 열·높은 행(줄바꿈).
        column_config: dict[str, Any] = {
            c: st.column_config.Column(width=w, pinned=c in service.REVIEW_PINNED or None)
            for c, w in service.REVIEW_WIDTHS.items()
            if c in order
        }
        column_config["No"] = st.column_config.Column(width=44, pinned=True)
        crit = service.result_criteria(result)
        # 머리글은 우리말(10/9 사용자 요청 — 'S·F' 대신 '심각도·빈도'). 열 키는 Excel 표준 12열 그대로.
        column_config["S(1-5)"] = st.column_config.NumberColumn(f"심각도(1-{crit.s_max})", width=76)
        column_config["F(1-5)"] = st.column_config.NumberColumn(f"빈도(1-{crit.f_max})", width=70)
        column_config[service.REVIEW_COLUMN] = st.column_config.Column(width=72, pinned=True)
        if view_choice == service.VIEWS[0] and editable and not full_text:
            st.caption(
                "검토: 행마다 채택·기각을 고르고 원인·결과·권고·심각도·빈도를 고칠 수 있습니다(목록은 · 로 구분). "
                "위 다운로드 3종에 바로 반영됩니다 — 기각 행은 빠지고, Excel 에 '검토 기록' 시트가 붙습니다. "
                "화면은 위험도·심각도·빈도를 이탈 옆에 두었고, Excel 은 표준 12열 순서입니다."
            )
            st.data_editor(
                service.with_edits(table, review_base.get(review_key, {})),
                key=review_key,
                hide_index=True,
                column_order=order,
                row_height=service.REVIEW_ROW_HEIGHT,
                disabled=[c for c in table[0] if c != service.REVIEW_COLUMN and c not in service.EDITABLE_COLUMNS]
                if table else True,
                column_config={
                    **column_config,
                    service.REVIEW_COLUMN: st.column_config.SelectboxColumn(
                        options=list(service.REVIEW_CHOICES), required=True, width="small", pinned=True
                    ),
                    # Y-2: 단계 수는 결과의 평가기준대로(C-C-37 은 심각도 1~4 · 빈도 1~3). 열 키는 그대로, 머리글만 바꾼다.
                    "S(1-5)": st.column_config.NumberColumn(
                        f"심각도(1-{crit.s_max})", min_value=1, max_value=crit.s_max, step=1, width=76
                    ),
                    "F(1-5)": st.column_config.NumberColumn(
                        f"빈도(1-{crit.f_max})", min_value=1, max_value=crit.f_max, step=1, width=70
                    ),
                },
            )
        else:
            if editable and full_text:
                st.caption("글 전체를 줄바꿈해 보여 줍니다. 채택·기각·심각도·빈도 수정은 '편집 표'에서 합니다.")
            elif editable:
                st.caption("검토 편집은 '워크시트 순서' 보기에서 합니다. 여기서는 검토 결과를 함께 보여 줍니다.")
            if not result.is_gold:  # 편집 표가 이번 실행에 안 그려진다 — 돌아오면 저장본을 데이터에 넣어 그린다
                review_base[review_key] = edits
            table = service.with_edits(table, edits)
            for name, head, indices in service.view_groups(shown, view_choice):
                rows = [table[i] for i in indices]
                kwargs = {"hide_index": True, "column_order": order, "column_config": column_config,
                          "row_height": service.REVIEW_ROW_HEIGHT}
                def draw(rows: list[dict[str, object]], kwargs: dict[str, Any] = kwargs) -> None:
                    if full_text:
                        st.html(service.full_table_html(rows, order, service.result_criteria(result)))
                    else:
                        st.dataframe(rows, **kwargs)

                if not head:  # 워크시트 순서(골드·시연 사본·펼쳐 보기) — 묶음 없이 표 하나
                    draw(rows)
                    continue
                focus = state.focus_guideword
                with st.expander(head, expanded=focus is None or name == focus):
                    if rows:
                        draw(rows)
                    else:
                        st.caption("이 묶음은 결과 행이 없습니다.")
        if not result.is_gold:
            st.caption("신뢰도 " + service.confidence_counts(shown)
                       + " — 근거가 붙었다는 것은 '공식 문서가 같은 위험을 다룬다'는 뜻이지 내용이 맞다는 보증이 아닙니다.")
        cited = service.evidence_rows(shown)
        if cited:
            with st.expander(f"근거 발췌 원문 — {len(cited)}건 (법령·고시 원문 그대로, 인용 검사 통과분만)", expanded=False):
                st.dataframe(cited, hide_index=True, row_height=60)
        held = service.held_rows(shown)
        if held:
            with st.expander(f"확인 필요 — 정보 부족으로 보류한 {len(held)}셀 (심각도·빈도·위험도를 매기지 않음)", expanded=False):
                st.caption("입력에도 공식 문서에도 없는 사업장 정보가 있어야 판단할 수 있는 셀입니다. "
                           "정보를 확인해 심각도·빈도를 채우거나 기각하세요. Excel '확인 필요' 시트와 같은 내용입니다.")
                st.dataframe(held, hide_index=True)
        if review_log:
            counts = {v: sum(e[1] == v for e in review_log) for v in ("채택", "수정", "기각")}
            st.caption(" · ".join(f"{k} {n}건" for k, n in counts.items()) + " — 다운로드에 반영됨")
    with process_tab:
        calls = "—" if view["api_calls"] is None else f"{view['api_calls']}회"
        st.markdown(f"**정확도** {service.accuracy_line(result, replays)} · API 호출 {calls}")
        node_meta = result.meta.get("node_meta", {})
        left, right = st.columns(2)
        with left, st.container(border=True):
            kind = "문장" if result.meta.get("node_text") else "항목 선택"
            st.markdown(
                f"**사용자가 준 것 ({kind})** — 노드({node_meta.get('node') or '—'}), "
                f"취급 물질({node_meta.get('substance') or '—'}), "
                f"대상 설비({', '.join(node_meta.get('equipment') or []) or '—'})"
            )
            if result.meta.get("node_text"):
                st.code(result.meta["node_text"], language=None, wrap_lines=True)
                st.caption(
                    f"→ {result.meta.get('parse_model')} 1회로 해석 — 설명에 없는 수치는 비워 둠"
                )
            st.json(node_meta, expanded=False)
        with right, st.container(border=True):
            st.markdown(
                "**AI 가 만든 것**\n"
                f"1. **파라미터 {len(view['parameters'])}개**: {' · '.join(view['parameters'])}\n"
                f"2. **가이드워드 {len(view['guidewords'])}종**({' · '.join(view['guidewords'])})을 교차 적용해 "
                f"매트릭스 셀 **{cells}** 을 빠짐없이 판정\n"
                "3. 셀마다 원인·결과·기존 안전장치·심각도·빈도·위험도·권고 초안, 근거 없는 규격 번호·수치는 🔴 표시"
            )

# ── HAZOP 이 처음이라면 ──────────────────────────────────────────────────────
st.html(
    '<div id="intro" class="hz-section">HAZOP 이 처음이라면</div>'
    '<p class="hz-sub" style="margin-bottom:18px">HAZOP(위험과 운전 분석)은 화학공장·가스설비에서 '
    "<b>“이 설비가 원래 하려던 일에서 벗어나면 무슨 일이 생기나?”</b>를 빠짐없이 묻는 방법입니다. "
    "설비를 구간으로 나누고, 구간마다 유량·압력·온도 같은 값에 ‘없음·많음·적음·거꾸로…’를 하나씩 대입해 "
    "생길 수 있는 사고를 표(워크시트)로 정리합니다. 아래 3장은 요약, 그 아래 탭은 한 줄이 만들어지는 과정과 용어 설명입니다.</p>"
)
#: (제목, 핵심 한 줄, [(항목, 내용)...]) — 줄글 대신 한눈에 읽히는 행. 마크다운을 거치지 않는다(`~` 가 취소선이 된다).
INTRO_CARDS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "HAZOP 이란",
        "설계 의도에서 벗어나는 경우를 빠짐없이 찾는 위험성평가",
        (
            ("대상", "공정 구간(노드) — 배관·설비를 나눈 한 토막"),
            ("방법", "유량·압력·온도 × No·More·Less·Reverse… 를 칸마다 대입"),
            ("근거", "공정안전관리(PSM) 표준 기법 · KOSHA C-C-37-2026(구 P-82)"),
        ),
    ),
    (
        "왜 힘든가",
        "노드 1개에 회의 수 시간",
        (
            ("참석", "공정·계장·운전·안전 담당 6–8명"),
            ("규모", "공장 하나에 노드 수십–수백 개"),
            ("위험", "셀 하나만 빠져도 시나리오 누락"),
        ),
    ),
    (
        "이 앱의 역할",
        "초안은 AI, 판단은 사람",
        (
            ("AI", "전 셀 판정 · 원인·결과·심각도·빈도·권고 초안"),
            ("사람", "검토 · 수정 · 최종 승인"),
            ("효과", "회의를 없애지 않고 시작점을 올림"),
        ),
    ),
)
for column, (title, headline, rows) in zip(st.columns(3), INTRO_CARDS, strict=True):
    column.html(
        f'<div class="hz-info"><p class="hz-info-t">{title}</p><p class="hz-info-h">{headline}</p>'
        + "".join(f"<div class='hz-info-r'><span>{k}</span><b>{v}</b></div>" for k, v in rows)
        + "</div>"
    )
st.html('<div style="height:14px"></div>')
howto_tab, example_tab, gw_tab, risk_tab, read_tab, compare_tab = st.tabs(
    ["⓪ 이렇게 쓰세요", "① 한 줄이 만들어지는 과정", "② 가이드워드 7종", "③ 위험도 (심각도·빈도)", "④ 결과 화면 읽는 법", "⑤ 회의와 비교"]
)
with howto_tab:
    for path_name, steps in guide.HOW_TO:
        st.markdown(f"**{path_name}**")
        st.markdown("\n".join(f"{i}. {s}" for i, s in enumerate(steps, start=1)))
with example_tab:
    st.caption("워크시트 한 줄은 아래 순서로 채워집니다. 값은 이해를 돕는 설명용 예시입니다(실제 생성 결과 아님).")
    example_tab.html(
        '<div class="hz-info">'
        + "".join(
            f"<div class='hz-info-r'><span style='width:110px'>{i}. {step}</span>"
            f"<b style='flex:1'>{value}<br><small style='color:var(--muted);font-weight:400'>{question}</small></b></div>"
            for i, (step, question, value) in enumerate(guide.WORKED_EXAMPLE, start=1)
        )
        + "</div>"
    )
    st.caption(
        "AI 는 2단계(파라미터)를 스스로 세우고, 파라미터 × 가이드워드의 모든 칸에 대해 4~9단계를 채웁니다. "
        "뜻이 성립하지 않는 칸(예: 온도 + Reverse — 온도에는 '거꾸로'가 없다)은 '해당 없음'과 그 이유를 남깁니다."
    )
with gw_tab:
    st.caption("가이드워드는 '어느 방향으로 벗어나는가'를 가리키는 정해진 단어입니다. 파라미터와 붙여 읽습니다(More + 압력 = 압력 과다).")
    st.table(guide.guideword_rows(), hide_index=True, border="horizontal")
    st.caption("절차(기동·정지·운전 순서)가 있는 노드에는 Too early · Too late · Wrong action 3종이 더 붙습니다.")
with risk_tab:
    st.caption(
        "심각도와 빈도를 등급으로 매기고, 둘을 조합한 값이 위험도입니다. 위험도가 높은 줄부터 대책을 세웁니다. "
        "기준은 결과마다 하나입니다 — 직접 입력은 KOSHA C-C-37(공식 HAZOP 기술지원규정), NH3 정답지 노드는 그 정답지의 평가기준. "
        "기준마다 단계 수와 계산법이 달라 섞거나 평균내지 않습니다."
    )
    crit_by_name = {c.short: c for c in service.all_criteria()}
    shown = crit_by_name[st.radio("평가기준", list(crit_by_name), horizontal=True, key="guide_criteria")]
    st.caption(guide.criteria_caption(shown))
    st.table(guide.criteria_rating_rows(shown), hide_index=True, border="horizontal")
    st.table(guide.criteria_matrix_rows(shown), hide_index=True, border="horizontal")
    st.table(guide.criteria_band_rows(shown), hide_index=True, border="horizontal")
    for note in shown.data.get("notes") or []:
        st.caption("· " + note)
with read_tab:
    st.markdown("**AI 가 쓰는 정보의 4단계** — 생성 프롬프트에 들어가는 문구와 같습니다")
    st.table(guide.information_level_rows(), hide_index=True, border="horizontal")
    read_tab.html(
        '<div class="hz-info">'
        + "".join(
            f"<div class='hz-info-r'><span style='width:170px'>{k}</span><b style='flex:1'>{v}</b></div>"
            for k, v in guide.READING_GUIDE
        )
        + "</div>"
    )
with compare_tab:
    st.markdown(guide.PROCESS_TABLE)
    st.caption(
        "실측: 노드 1건 약 1.5–2분 · 약 $0.75 (2026-10-08, 가이드워드 7종 동시 판정, 3회 79–126초). "
        "회의 시간 단축을 잰 것은 아닙니다 — 이 앱이 만드는 것은 회의에서 검토할 초안입니다."
    )

# ── 정확도 (기본 접힘) ───────────────────────────────────────────────────────
st.html('<div id="eval"></div>')
with st.expander("정확도 — 전문가 정답지 대비 재현율(recall, n=1), 불리한 값까지 공개", expanded=False):
    st.caption(
        "NH3 벙커링 4노드만 해당(공개 HAZOP 대조 LPG 공정은 기준이 달라 각 결과 화면에 따로 표시, 예시 공정은 대조 기준 없음). 하네스 미구현 — `tools/capture_replay.py` 로 "
        f"노드별 1회 실측. 규칙·해석은 [README §6]({README_EVAL})."
    )
    st.table(service.evaluation_table(replays))

# ── 푸터 ─────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "데이터 보안: 고객사의 실제 데이터는 일체 사용하지 않으며, 팀이 자체 보유한 데이터로만 작동합니다. · "
    f"{service.system_note(result) if result is not None else ''} · [리포지토리]({REPO})"
)

if state.pop("scroll_result", False):
    st.toast("HAZOP 초안이 완성됐습니다 — 결과로 이동합니다.")
    components.html(
        "<script>const go = () => window.parent.document.getElementById('result')"
        "?.scrollIntoView({block: 'start'}); setTimeout(go, 600); setTimeout(go, 1500);</script>",
        height=0,
    )
