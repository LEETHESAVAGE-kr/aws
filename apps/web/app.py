"""HAZOP 코파일럿 데모 화면 — FR-10 UX v3.1 (docs/PRD_UX_v3.md + 사용자 피드백 9/29 22:40 "문서 같다, 앱 같지 않다").

흐름: 상단바 → [왼쪽: 한 줄 정의·3단계 흐름 | 오른쪽: 작업 카드(모드·입력·실행)] → 결과(지표 타일 → 내보내기 → 탭) →
HAZOP 이 처음이라면(짧은 3카드·절차 비교) → 푸터. 정확도(recall) 화면은 10/9 사용자 결정으로 뺐다 — 수치는 README §6.
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

from apps.web import form, guide, nudge, service  # noqa: E402
from apps.web.replay import load_replays  # noqa: E402
from core.agent.generate import PROCEDURAL_GUIDEWORDS, STANDARD_GUIDEWORDS  # noqa: E402

#: 모드·입력 방식 이름(PRD_본선_첫화면_사용흐름 Q-U2·Q-U3, 10/9 결정). 첫 화면 흐름 카드·안내 탭이 같은 말을 쓴다.
MODE_NL = "새로 만들기"
MODE_CASES = "완성된 사례 보기"
#: 항목 선택은 JSON 으로 넘어가 문장 해석 호출이 없다.
INPUT_TEXT = "문장으로 설명"
INPUT_FORM = "항목 선택"
#: 예시 칩 안내 — 문장으로 설명에만 예시가 있다(10/9 사용자: "항목 선택일 때는 예시가 없어졌으면").
CHIP_HINT = "공정 예시 — 버튼을 누르면 아래 입력창에 예시 문장이 입력됩니다. 그대로 사용하거나 상황에 맞게 수정해 보세요."
GUIDEWORDS = STANDARD_GUIDEWORDS + PROCEDURAL_GUIDEWORDS
REPO = "https://github.com/LEETHESAVAGE-kr/aws"
README_EVAL = f"{REPO}/blob/main/README.md#-6-평가-결과"
#: 입력 칸 placeholder — 예시 문장은 칩이 맡고, 여기엔 쓰는 요령만.
DIRECT_PLACEHOLDER = (
    "예시를 누르거나 공정을 직접 적어 보세요.\n"
    "물질, 설비(흐름 순서), 운전압력, 온도 등 공정 정보를 상세히 적을수록 분석 결과가 구체적입니다. 정확히 모르는 값은 비워두셔도 됩니다.\n"
    '(JSON 형식으로도 넣을 수 있습니다: {"node": "X1", "substance": "프로판", "P_kPag": 800, ...})'
)
#: 예시 칩 (라벨, 문장) — PRD §4-4.
EXAMPLES: tuple[tuple[str, str], ...] = (
    (
        "수소충전소",
        "수소충전소에서 튜브트레일러의 압축 수소를 압축기로 약 90 MPa 까지 올려 저장용기에 모았다가 "
        "디스펜서로 차량에 충전한다. 안전장치는 안전밸브, 긴급차단밸브, 수소누출감지기.",
    ),
    (
        "메탄올 저장탱크",
        "메탄올을 이송 펌프로 상압 저장탱크(약 30 ℃)에 보낸다. 탱크에는 질소 블랭킷과 "
        "브리더밸브가 있고, 탱크 주변에는 가스감지기와 긴급차단밸브가 있다.",
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
    "No: 흐르지 않음 · More: 정량적 증가 · Less: 정량적 감소 · Reverse: 역류 · Part of: 조성 일부(묽음) · "
    "As well as: 이물 혼입(섞임) · Other than: 다른 물질 유입"
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
    /* 10/15 사용자 요청 — 한글을 글자가 아니라 어절 단위로 줄바꿈. 한 줄보다 긴 덩어리(URL 등)만 중간에서 끊는다(넘침 방지).
       Streamlit 요소가 자체 값을 갖기도 해 하위 요소에도 명시한다. 코드 블록은 원래대로. */
    .stApp, .stApp *:not(pre):not(code) { word-break: keep-all; overflow-wrap: anywhere; }
    .hz-full { max-height: 760px; overflow: auto; border: 1px solid var(--line); border-radius: 12px; }
    .hz-full table { border-collapse: collapse; font-size: 13px; line-height: 1.5; width: max-content; min-width: 100%; }
    .stApp .hz-full th { position: sticky; top: 0; z-index: 1; background: var(--card2); color: var(--muted); font-weight: 600;
        text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); white-space: normal; overflow-wrap: normal; vertical-align: bottom; }
    .hz-full td { vertical-align: top; padding: 8px 10px; border-bottom: 1px solid var(--line); color: var(--text);
        white-space: normal; word-break: keep-all; overflow-wrap: anywhere; }
    .hz-full tr:hover td { background: rgba(255,255,255,.03); }
    /* 결과 위 알림 상자(10/15) — 본문보다 한 단계 작게, 이름만 강조색 */
    .st-key-notices { padding: 10px 14px !important; gap: 6px !important; }
    .st-key-notices p, .st-key-notices summary { font-size: 14px !important; line-height: 1.6; color: var(--muted); }
    .st-key-notices strong { color: #f0a648; font-weight: 600; }
    .st-key-notices [data-testid="stExpander"] details { border: 0; }
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
    /* 입력 조각 안의 화면 이동 스크립트(높이 0 iframe) — 흐름에서 빼서 카드 높이·간격을 바꾸지 않는다.
       키 상자를 감싼 Streamlit 상자가 카드의 flex 항목이라 그 상자째 뺀다 */
    div:has(> .st-key-panel_nudge) { position: absolute; width: 0; height: 0; overflow: hidden; }
    </style>"""
)

with contextlib.suppress(Exception):  # secrets.toml 이 없으면 Streamlit 이 예외를 던진다
    service.sync_secrets(dict(st.secrets))

replays = st.cache_resource(load_replays)()
live_reason = service.live_block_reason()
state = st.session_state
state.setdefault("live_runs", 0)
state.setdefault("nudge_n", 0)  # 모바일 화면 이동 번호(nudge.py) — 같은 버튼을 다시 눌러도 스크립트가 돈다
state.setdefault("quick_result", None)
state.setdefault("node", None)
state.setdefault("quick_text", "")
state.setdefault("input_style", INPUT_TEXT)
state.setdefault("parse_pending", None)
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
    st.caption("물질과 설비 항목만 필수입니다. 나머지 항목은 모를 경우 비워주세요. (빈칸은 '정보 부족'으로 처리됩니다.)")
    left, right = st.columns([3, 2])
    left.selectbox("물질 (필수)", form.SUBSTANCES, key=form.KEYS["substance"],
                   placeholder="고르거나 직접 입력", accept_new_options=True)
    right.selectbox("상태", list(form.PHASES), key=form.KEYS["phase"])
    st.multiselect("설비 (필수) — 유체가 흐르는 순서대로", form.EQUIPMENT, key=form.KEYS["equipment"],
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
    no_safeguards = st.checkbox("안전장치 없음(확인함)", key=form.KEYS["no_safeguards"],
                                help="모르면 체크하지 말고 아래를 비워 두세요 — '없음'과 '모름'은 다르게 다룹니다.")
    st.multiselect("기존 안전장치 — 설정값은 직접 입력(예: 고압 경보 설정 95 MPa)", form.SAFEGUARDS,
                   key=form.KEYS["safeguards"], disabled=no_safeguards, accept_new_options=True,
                   placeholder="비워 두면 '모름'으로 다룹니다")


@st.cache_resource
def _combined(process_id: str) -> service.Result | None:
    return service.combine_replays(next(p for p in service.CATALOG if p["id"] == process_id), replays)


def _nudge(target: str) -> None:
    """모바일에서 바뀐 곳으로 이동시킨다 — 스크립트는 맨 끝에서 한 번 낸다(PC 는 스크립트가 아무것도 안 한다)."""
    state.nudge_to = target
    state.nudge_n += 1


def _fill(text: str, guideword: str | None = None) -> None:
    """예시 칩 — 문장 칸을 채운다. 칩은 '문장으로 설명'에서만 보인다."""
    state.quick_text = text
    _nudge("input")  # 모바일은 칩이 세로로 쌓여 채워진 칸이 아래에 있다
    if guideword:  # 칩이 지정한 가이드워드(V-6 · X-4) — 결과는 가이드워드별 보기에서 그 묶음을 펼친다
        state.guideword = guideword
        state.view_pref = service.VIEWS[1]
        state.view_gen += 1  # 새 위젯 키 — 상태로 정한 값을 radio 가 선택 표시하게(아래 view_choice)
        state.focus_guideword = guideword


def _emit_nudge(*, in_panel: bool = False) -> None:
    """`_nudge` 로 예약한 화면 이동을 낸다 — 앱 끝, 그리고 입력 조각만 다시 돌 때는 조각 끝에서.

    조각 안에서는 흐름 밖 상자(`panel_nudge`, CSS)에 넣는다 — 높이 0 iframe 도 간격 한 칸을 먹어 카드가 16px 커졌다.
    """
    target = state.pop("nudge_to", None)
    if target and not state.get("scroll_result"):
        script = nudge.script(target, state.nudge_n)
        if in_panel:
            with st.container(key="panel_nudge"):
                components.html(script, height=0)
        else:
            components.html(script, height=0)


def _to_cases() -> None:
    state.mode = MODE_CASES


# ── 상단바 ───────────────────────────────────────────────────────────────────
st.html(
    """<div class="hz-bar"><span class="hz-logo"><i></i>HAZOP Copilot</span>
    <span class="hz-nav"><a href="#result">결과</a><a href="#intro">HAZOP이란</a>
    <a href="https://github.com/LEETHESAVAGE-kr/aws" target="_blank">GitHub</a></span></div>"""
)

# ── 작업 영역: 왼쪽 소개 · 오른쪽 도구 ───────────────────────────────────────
intro, tool = st.columns([5, 7], gap="large")
intro.html(
    """<div class="hz-eyebrow">AI 위험성평가 초안 도우미</div>
    <div class="hz-h1">HAZOP Copilot</div>
    <p class="hz-sub"><b>"이 배관에 압력이 너무 많이 걸리면 어떻게 될까?"</b> HAZOP(위험과 운전 분석)은 이런 질문을 압력·온도·유량마다,
    설비마다 끝까지 던져 설계에서 벗어날 때의 위험을 찾는 기법입니다. 설비 하나에도 따져야 할 질문이 수십 개라, 공정 전체를
    보려면 시간이 오래 걸립니다. AI에게 맡기면 빠르지만, 그럴듯한 거짓말을 섞을까 봐 믿고 쓰기 어렵습니다.</p>
    <p class="hz-sub">그래서 AI가 질문을 대신 던지되, 답마다 법령과 MSDS 원문을 근거로 붙이게 했습니다. 공정 정보를 넣으면
    워크시트 초안이 나오고, 근거가 없는 부분은 지어내지 않고 '정보 부족'으로 남겨 사람이 채우게 합니다. 전문가는 빈 표를 채우는
    대신, 초안을 검토하고 현장 경험이 필요한 판단에 시간을 쓸 수 있습니다.</p>
    <div class="hz-steps">
      <div class="hz-step"><b>1</b><div><strong>공정 정보 입력 (두 가지 방식 지원)</strong>
        <ul>
          <li><em>문장으로 설명</em> 분석할 공정을 하나의 문단으로 자유롭게 적습니다.</li>
          <li><em>항목 선택</em> 물질, 설비, 압력, 안전장치 등을 목록에서 고릅니다. (목록에 없으면 직접 입력)</li>
        </ul>
        <span>Tip: 무엇을 적을지 막막하다면 <em>공정 예시</em> 버튼을 누르거나, <em>완성된 사례 보기</em>에서
        실제 분석 결과를 먼저 확인해 보세요.</span></div></div>
      <div class="hz-step"><b>2</b><div><strong>AI 초안 생성 (약 1.5~2분 소요)</strong>
        <span>AI가 스스로 점검 파라미터를 도출하고, 설계에서 벗어나는 모든 경우의 수에 대해 원인·결과·심각도·빈도·권고사항을 작성합니다.</span></div></div>
      <div class="hz-step"><b>3</b><div><strong>전문가 검토 및 다운로드</strong>
        <ul>
          <li>생성된 표를 확인하고 행마다 채택, 기각, 수정 등 최종 검토를 진행합니다.</li>
          <li>완성된 결과는 Excel 워크시트, LOPA 후보 시나리오(Word), 신뢰도 리포트 형식으로 내려받을 수 있습니다.</li>
        </ul></div></div>
    </div>"""
)

# ── 입력 패널 — 조각(fragment) ────────────────────────────────────────────────
# 칩·입력 방식·폼처럼 패널 안에서만 바뀌는 조작은 이 조각만 다시 실행한다(10/15 1-C, 예전엔 앱 전체를 다시 보냈다).
# 결과를 바꾸는 일(생성 완료)은 안에서 st.rerun() 으로 앱 전체를 다시 그린다.
@st.fragment
def _nl_panel() -> None:
    if state.mode != MODE_NL:  # 패널 안 버튼(사례 보기)이 모드를 바꿨다 — 모드 선택은 조각 밖이라 앱 전체를 다시 그린다
        st.rerun()
    done = 3 if state.quick_result is not None else (2 if state.quick_text.strip() or state[form.KEYS["substance"]] else 1)
    st.html(
        f'<div class="hz-progress"><div style="width:{done * 33.4:.0f}%"></div></div>'
        '<p class="hz-q">어떤 공정을 분석할까요?</p>'
        '<p class="hz-q-help">물질, 설비, 압력, 온도, 설계압력, 용량, 기존 안전장치 등을 구체적으로 입력할수록 결과가 정교해집니다.</p>'
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
    # §8 C: 한 번 생성(지금 방식)과 3번 생성해 합치기 중 고른다 — 사용자 요청(10/9·10/10).
    gen_mode = st.radio(service.GENERATION_MODE_LABEL, list(service.GENERATION_MODES), key="gen_mode", horizontal=True,
                        captions=[service.GENERATION_MODE_HELP[m] for m in service.GENERATION_MODES])
    runs = service.GENERATION_MODES[gen_mode]
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
    # 생성 전 '입력 확인'(10/10 사용자 요청): 문장 입력은 먼저 해석만 하고, 비어 있는 정보를 사람이 채운 뒤 생성한다.
    # 질문 누락은 매트릭스가 막지만 입력 누락은 사람만 메울 수 있다 — 그 빈칸을 생성 전에 보여 준다.
    pre_parsed = None
    if (clicked_quick or clicked_full) and input_style == INPUT_TEXT:
        state.parse_pending = None
        try:
            parsed_meta, parse_info = service.parse_node_text(run_text)
        except Exception:  # noqa: BLE001 — 해석 실패는 아래 생성 경로가 같은 사유로 다시 보여 준다
            parsed_meta = None
        if parsed_meta is not None:
            if service.missing_inputs(parsed_meta):
                state.parse_pending = {"meta": parsed_meta, "info": parse_info, "text": run_text,
                                       "quick": bool(clicked_quick)}
                clicked_quick = clicked_full = False
            else:
                pre_parsed = (parsed_meta, parse_info)
    pending = state.get("parse_pending")
    if pending is not None and (input_style != INPUT_TEXT or pending["text"] != run_text):
        state.parse_pending = pending = None  # 입력을 바꾸면 확인 단계를 버린다
    if pending is not None:
        meta = pending["meta"]
        missing = service.missing_inputs(meta)
        labels = dict(service.INPUT_CHECK_FIELDS)
        # 누르면 이 카드를 지운다(10/15) — 남겨 두면 흐려진 카드 밑으로 진행 상자가 밀려나 "작업이 들어갔나?"가 안 보인다.
        check_slot = st.empty()
        with check_slot.container(border=True, key="input_check"):
            st.markdown("**입력 확인 — 생성 전에 빠진 정보를 채우세요**")
            st.markdown(service.parsed_values_line(meta, pending["info"]))  # Q-04-4 해석된 값이 먼저
            st.caption(
                f"해석 결과: 물질 {meta.substance} · 상태 {meta.phase} · "
                f"설비 {', '.join(meta.equipment) or '—'}"
                + (f" · 안전장치 {', '.join(meta.safeguards)}" if meta.safeguards else "")
            )
            st.markdown("입력에 없는 정보: " + " · ".join(labels[f].split(" (")[0] for f in missing))
            values: dict[str, Any] = {}
            for column, field in zip(st.columns(len(missing)), missing, strict=True):
                if field in ("P_kPag", "T_degC", "design_P_kPag"):
                    values[field] = column.number_input(labels[field], value=None, key=f"check_{field}")
                else:
                    values[field] = column.text_input(labels[field], key=f"check_{field}")
            st.caption("비워 두면 그 정보가 필요한 칸은 지어내지 않고 '⚪ 정보 부족'으로 남겨 둡니다.")
            fill_col, skip_col = st.columns(2)
            go_fill = fill_col.button("채운 값으로 생성", type="primary", key="check_fill", width="stretch")
            go_skip = skip_col.button("이대로 생성", key="check_skip", width="stretch")
        if go_fill or go_skip:
            check_slot.empty()
            filled_meta, filled = service.fill_node_meta(meta, values if go_fill else {})
            pre_parsed = (filled_meta, {**pending["info"], "filled_after_parse": filled})
            clicked_quick, clicked_full = pending["quick"], not pending["quick"]
            state.parse_pending = None
    if clicked_quick or clicked_full:
        reason = service.reserve_live_run(session_runs)
        if reason:
            st.error(reason)
        else:
            state.live_runs += 1
            mock_source = replays.get("N1") or next(iter(replays.values()))
            # 진행 표시는 버튼 바로 아래 — 결과 영역은 첫 화면 밖이라 거기 두면 "아무 일도 없다"로 보인다(9/29 23:05).
            expected = "약 1분" if clicked_quick else ("약 4분 · 3번 생성" if runs > 1 else "약 1.5~2분")
            with st.status(
                f"HAZOP 초안 생성 중 · {expected} — 이 화면에서 기다려 주세요", expanded=True
            ) as status:
                # R-11: 단계가 끝나는 즉시 그 산출물을 쓴다(예전엔 끝난 뒤 2/3·3/3 을 한꺼번에 찍었다).
                lines = [st.empty() for _ in range(3)]
                lines[0].write(service.STAGE_PENDING[0])
                st.caption("분석 결과를 생성하는 동안 다른 버튼을 누르면 작업이 취소될 수 있습니다.")
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
                            run_text, guideword, mock_source, on_progress=on_progress, pre_parsed=pre_parsed
                        )
                    else:
                        state.quick_result = service.run_live(
                            run_text, mock_source, on_progress=on_progress, consensus_runs=runs,
                            consensus_union=True, pre_parsed=pre_parsed,
                        )
                except Exception as exc:  # noqa: BLE001 — 사유를 보이고 앱은 계속 산다
                    state.live_runs -= 1  # 실패한 실행은 세션 횟수에서 빼지 않는다
                    status.update(label="생성 실패", state="error", expanded=True)
                    st.error(f"생성 실패: {type(exc).__name__}: {exc}")
                    st.caption(service.failure_hint(exc))
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
        scope = "이 창에서" if "이 창" in quota else "오늘"
        st.caption(
            f"이 창에서 남은 생성 횟수 {left_runs}/{service.SESSION_LIMIT} · {scope} 생성할 수 있는 횟수를 모두 썼습니다. "
            "'완성된 사례 보기'에서 같은 화면을 볼 수 있습니다."
        )
        st.button("완성된 사례 보기", on_click=_to_cases, width="stretch")
    elif BOOTH:
        st.caption(
            f"현장 시연 모드 · 오늘 남은 {service.daily_left()}회 · 생성 약 1.5~2분 — "
            "가이드워드 판정이 끝날 때마다 표가 채워집니다."
        )
    else:
        st.caption(
            f"남은 생성 횟수: {left_runs}/{service.SESSION_LIMIT}  \n"
            f"진행 과정: 문장 해석 → 파라미터 도출 → 가이드워드 {guide.GUIDEWORD_COUNT} 동시 판정  \n"
            f"예상 소요 시간/비용: {service.LIVE_NOTE.split(' · ', 1)[1].replace(' · ', ' / ')}"
            + (
                " · mock 모드 — 네트워크 없이 재생 레코드로 생성 경로를 돕니다."
                if service.is_mock()
                else ""
            )
        )
    _emit_nudge(in_panel=True)  # 조각만 다시 돌 때는 스크립트 끝(아래)이 실행되지 않는다 — 칩의 모바일 이동을 여기서 낸다


result = None
with tool.container(border=True, key="tool"):
    mode = st.radio(
        "모드", [MODE_NL, MODE_CASES], horizontal=True, label_visibility="collapsed", key="mode"
    )
    if mode == MODE_NL:
        _nl_panel()
    else:
        st.html(
            '<p class="hz-card-sub">실제로 생성해 저장해 둔 결과를 보여 줍니다(새로 생성하지 않음). 문장 표현만 다듬어 표시하고 뜻은 저장본 그대로입니다. '
            "언제, 어떤 경로와 프롬프트로 만들었는지는 결과 위 출처 안내에 있습니다.</p>"
        )
        names = [p["name"] for p in service.CATALOG]
        choice = st.selectbox("공정", names, key="process_name", label_visibility="collapsed",
                              on_change=_nudge, args=("result",))
        process = next(p for p in service.CATALOG if p["name"] == choice)
        if process.get("reference"):  # 지시문 W — 외부 공개 HAZOP 대조
            st.markdown(f":blue-background[공개 HAZOP 대조 · 외부 팀 작성] {process['description']}")
        elif process["gold"]:  # Q-02: 내부 워크시트는 화면에서 가리키지 않는다 — `gold` 플래그는 코드만 쓴다
            st.markdown(f":violet-background[실제 생성 결과 저장본] {process['description']}")
        else:
            st.markdown(f":orange-background[예시 공정 · 정성 검토용] {process['description']}")
        node_ids = [n["id"] for n in process["nodes"]]
        if state.node not in (*node_ids, service.ALL_NODES):  # 공정을 바꾸면 그 공정의 첫 캡처 노드를 연다
            state.node = next((n for n in node_ids if n in replays), node_ids[0])
        # X-3: 공정 전체를 노드 순서로 이어 본다(재생만 — 공정 전체 실호출은 비목표). 노드 버튼 줄에 넣으면
        # 노드 이름이 "① 공급…" 으로 잘려 따로 한 줄(10/8 캡처).
        if st.button(
            f"공정 전체 보기 — 노드 {len(node_ids)}개를 순서대로",
            key="preset_all",
            disabled=not any(n in replays for n in node_ids),
            type="primary" if state.node == service.ALL_NODES else "secondary",
            width="stretch",
        ):
            state.node = service.ALL_NODES
            _nudge("result")
            st.rerun()
        for column, node in zip(st.columns(len(node_ids)), process["nodes"], strict=True):
            captured = node["id"] in replays
            if column.button(
                node["label"] + ("" if captured else " (저장된 결과 없음)"),
                key=f"preset_{node['id']}",
                disabled=not captured,
                type="primary" if state.node == node["id"] else "secondary",
                width="stretch",
            ):
                state.node = node["id"]
                _nudge("result")  # 모바일은 노드 버튼이 세로로 쌓여 결과가 화면 밖 아래에 있다
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
        '위에서 입력 방식과 예시를 선택하고 "HAZOP 초안 생성"을 누르면, 판정이 끝나는 대로 이곳에 워크시트가 채워집니다.<br>'
        "기다리지 않고 즉시 결과를 보려면 '완성된 사례 보기'를 클릭하세요.</div>"
    )
else:
    if result.is_gold:
        st.warning(service.provenance_line(result))
    else:
        st.caption(service.provenance_short(result))  # 전문은 푸터
    if result.meta.get("node_provenance"):  # X-3 공정 전체 — 노드마다 캡처 시각·프롬프트가 다르다
        with st.expander("노드별 출처", expanded=False):
            st.markdown("\n".join(f"- **{n}** {line}" for n, line in result.meta["node_provenance"]))
    failed = service.failed_guidewords_line(result)
    if failed:
        st.warning(failed)
    notices = service.notice_items(result)
    if notices:  # U-7 결과 위 알림을 한 상자에 — 한 줄 요약만 보이고 전문은 접는다(10/15 "너무 크고 안 읽힌다")
        with st.container(border=True, key="notices"):
            st.markdown("  \n".join(f"**{label}** · {short}" for label, short, _ in notices))
            with st.expander("기준 출처·자세히", expanded=False):
                for label, _, text in notices:
                    st.markdown(f"**{label}** — {text}")
    if not result.is_gold:
        st.caption(service.READING_ORDER)
    view = service.process_view(result)
    cells = service.cells_label(result)
    tiles = [
        ("이탈 시나리오", f"{len(result.records)}건"),
        (service.CELLS_TILE, cells),
        ("소요 시간", "—" if view["latency_s"] is None else f"{view['latency_s']:.0f}초"),
        ("비용", "—" if view["cost_usd"] is None else f"${view['cost_usd']:.2f}"),
    ]
    if result.meta.get("combined"):  # 공정 전체는 노드별 실행이라 지연 합이 의미 없다 — 타일 6개면 값이 잘린다
        tiles = [t for t in tiles if t[0] != "소요 시간"]
    for column, (label, value) in zip(st.columns(len(tiles)), tiles, strict=True):
        column.metric(label, value)
        if label == service.CELLS_TILE:  # Q-02-5 — 완전성이지 정확도가 아니다. 정확도는 아래 패널
            column.caption(service.CELLS_TILE_SUB)
    ref_line = service.reference_line(result)
    if ref_line:
        st.caption(ref_line)
    ext = service.external_eval()
    with st.expander(service.EXTERNAL_PANEL_TITLE, expanded=False):  # Q-02 — 앱 전체 성능(이 노드 성능 아님)
        st.markdown(f"**{ext['head']}**  \n{ext['question']}")
        st.table(ext["rows"], hide_index=True, border="horizontal")  # 고정 표 — 편집·정렬할 것이 없다
        st.markdown(ext["total"])
        st.caption(ext["low_reason"])
        for line in ext["fine_print"]:
            st.caption(line)

    # 검토 표(export-formats R-10): 편집 상태를 표보다 먼저 읽어 다운로드에 반영한다. 키에 결과 식별을 넣어
    # 새 결과가 오면 이전 편집이 엉뚱한 행에 붙지 않게 한다. 골드 재생은 사람 작성이라 검토 대상이 아니다.
    # 다른 보기로 가면 data_editor 가 그려지지 않아 Streamlit 이 그 위젯 상태를 지운다 — 편집은 위젯 밖
    # (`review_saved`)에도 두고, 표를 다시 그릴 때는 저장된 편집(`review_base`)을 데이터에 넣어 그린다(X-2b).
    review_key = service.review_key(result)
    review_base: dict[str, dict[int, dict[str, Any]]] = state.setdefault("review_base", {})
    review_saved: dict[str, dict[int, dict[str, Any]]] = state.setdefault("review_saved", {})
    # '표에서 볼 행'(10/15): 판정으로 거른 편집 표는 키가 따로다 — 그 표의 행 번호를 전체 표 번호로 되돌려 합친다.
    # 선택은 위젯 밖(`rowpref_…`)에 두고, 판정 막대를 누르면 새 키로 다시 만든다 — 위젯 키에 값을 넣으면
    # 화면 선택 표시가 따라오지 않는다(10/8 view_pref 와 같은 이유).
    pref_key = f"rowpref_{review_key}"
    filter_key = f"rowfilter_{review_key}_{state.get('rowfilter_gen', 0)}"
    row_filters = service.row_filters(result, service.worksheet_table(result))
    row_choice = state.get(pref_key) if state.get(pref_key) in row_filters else service.ROW_FILTER_ALL
    row_idx = row_filters.get(row_choice, row_filters[service.ROW_FILTER_ALL])
    editor_key = review_key if row_choice == service.ROW_FILTER_ALL else f"{review_key}__{row_choice}"
    if result.is_gold:
        edits: dict[int, dict[str, Any]] = {}
    elif editor_key in state:
        edits = service.merge_edits(
            review_base.get(review_key, {}), service.remap_edits(state[editor_key].get("edited_rows", {}), row_idx)
        )
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
        "lopa": service.LOPA_LABEL,
        "report": "신뢰도 리포트 (JSON)",
    }
    for column, key in zip(st.columns(3), ("xlsx", "lopa", "report"), strict=True):
        name, data = files[key]
        column.download_button(
            f"⬇ {labels[key]} · {name}", data, file_name=name, mime=mimes[key], width="stretch"
        )

    sheet_tab, process_tab = st.tabs(["HAZOP 워크시트", "AI가 한 일"])
    with sheet_tab:
        # verifier 시연(O-3): 표·요약 줄만 삽입 사본으로. 다운로드는 위에서 원본 `result` 로 만들었다.
        shown = result
        if not result.is_gold and st.checkbox(service.DEMO_TOGGLE_LABEL, key="verifier_demo",
                                              help=service.VERIFIER_SCOPE):
            shown = service.demo_injected(result)
            st.markdown(service.DEMO_BANNER)
        if not result.is_gold:
            st.caption(service.VERIFIER_SCOPE)
        st.caption(service.summary_line(shown))
        def _switch_rows() -> None:
            # 걸러 낸 편집 표를 바꾸기 전에 지금까지의 편집을 저장본에 넣고, 이전 편집 표 상태는 버린다(이중 적용 방지)
            review_base[review_key] = review_saved.get(review_key, {})
            for k in [k for k in state if str(k) == review_key or str(k).startswith(f"{review_key}__")]:
                del state[k]

        def _pick_rows(name: str) -> None:
            """판정 막대의 칸을 누름 — 그 판정만 표에 남기고 표로 이동한다(10/15 사용자 요청)."""
            _switch_rows()
            state[pref_key] = name
            state.rowfilter_gen = state.get("rowfilter_gen", 0) + 1
            _nudge("rows")

        def _keep_rows() -> None:
            _switch_rows()
            state[pref_key] = state[filter_key] or service.ROW_FILTER_ALL

        card = service.risk_card(shown)  # Q-03-4 위험도 판정 — 막대 칸이 곧 버튼
        if card:
            with st.container(border=True, key="risk_card"):
                st.html(card.head)
                present = [(i, b) for i, b in enumerate(card.bands) if b[2] and b[0] in row_filters]
                total_rated = sum(b[2] for _, b in present) or 1
                # 칸 너비 = 행 수 비례, 다만 글자가 들어가게 최소 너비를 둔다
                weights = [max(b[2], 0.18 * total_rated) for _, b in present]
                st.html("<style>" + "".join(
                    f".st-key-band_{i} button{{background:{b[3]};color:#fff;border:0;font-weight:600}}"
                    f".st-key-band_{i} button:hover{{filter:brightness(1.12);color:#fff}}"
                    for i, b in present
                ) + "</style>")
                for column, (i, (name, rng, n, _color)) in zip(st.columns(weights, gap="small"), present, strict=True):
                    with column.container(key=f"band_{i}"):
                        st.button(f"{name} {n}행", key=f"band_btn_{i}", on_click=_pick_rows, args=(name,),
                                  width="stretch", help=f"위험도 {rng} — 누르면 이 {n}행만 아래 표에 남기고 표로 이동합니다")
                st.html(card.tail)
        crowded = service.concentration_warning(shown)
        if crowded:
            st.caption(crowded)

        st.segmented_control(
            "표에서 볼 행",
            list(row_filters),
            format_func=lambda o: f"{o} {len(row_filters[o])}행",
            default=row_choice,
            key=filter_key,
            on_change=_keep_rows,
        )
        row_set = set(row_idx)
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
            c: st.column_config.Column(service.COLUMN_LABELS.get(c), width=w, pinned=c in service.REVIEW_PINNED or None)
            for c, w in service.REVIEW_WIDTHS.items()
            if c in order
        }
        column_config["No"] = st.column_config.Column(width=44, pinned=True)
        crit = service.result_criteria(result)
        # 머리글은 우리말(10/9 사용자 요청 — 'S·F' 대신 '심각도·빈도'). 열 키는 Excel 표준 12열 그대로.
        column_config["S(1-5)"] = st.column_config.NumberColumn(f"심각도(1-{crit.s_max})", width=96)
        column_config["F(1-5)"] = st.column_config.NumberColumn(f"빈도(1-{crit.f_max})", width=84)
        column_config[service.REVIEW_COLUMN] = st.column_config.Column(width=120, pinned=True)  # "기각(근거 부족)"이 들어가게
        if view_choice == service.VIEWS[0] and editable and not full_text:
            st.caption(
                "검토: 행마다 채택·기각을 고르고 원인·결과·권고·심각도·빈도를 고칠 수 있습니다(여러 항목은 | 로 구분). "
                "기각은 사유와 함께 고를 수 있습니다(예: 기각(중복)). "
                "고친 내용은 위 내려받기 파일 3종에 바로 반영됩니다. 기각한 행은 빠지고, Excel에는 '검토 기록' 시트가 붙습니다. "
                "화면에서는 위험도·심각도·빈도를 이탈 옆에 두었고, Excel은 표준 양식의 12열 순서를 따릅니다."
            )
            pending = sum(
                service.split_verdict(edits.get(i, {}).get(service.REVIEW_COLUMN))[0] == service.REVIEW_CHOICES[0]
                for i in row_idx
            )

            def _accept_visible() -> None:
                """보이는 행 일괄 채택(10/16) — 미검토 행만. 편집 표 위젯을 지우고 저장본으로 다시 그린다(필터 전환과 같은 길)."""
                current = (
                    service.merge_edits(review_base.get(review_key, {}),
                                        service.remap_edits(state[editor_key].get("edited_rows", {}), row_idx))
                    if editor_key in state else review_saved.get(review_key, review_base.get(review_key, {}))
                )
                accepted, n = service.bulk_accept(current, row_idx)
                review_base[review_key] = review_saved[review_key] = accepted
                for k in [k for k in state if str(k) == review_key or str(k).startswith(f"{review_key}__")]:
                    del state[k]
                st.toast(f"{n}행 채택 — 바꾸려면 표의 검토 칸에서 다시 고르세요")

            st.button(
                f"✓ 보이는 미검토 {pending}행 모두 채택", key="accept_visible", on_click=_accept_visible,
                disabled=pending == 0,
                help="지금 표에 보이는 행 중 '미검토'만 채택으로 바꿉니다. 이미 기각·채택한 행은 그대로 둡니다. 되돌리기는 없습니다.",
            )
            with_base = service.with_edits(table, review_base.get(review_key, {}))
            st.data_editor(
                [with_base[i] for i in row_idx],
                key=editor_key,
                hide_index=True,
                column_order=order,
                row_height=service.REVIEW_ROW_HEIGHT,
                disabled=[c for c in table[0] if c != service.REVIEW_COLUMN and c not in service.EDITABLE_COLUMNS]
                if table else True,
                column_config={
                    **column_config,
                    service.REVIEW_COLUMN: st.column_config.SelectboxColumn(
                        options=list(service.REVIEW_OPTIONS), required=True, width=120, pinned=True
                    ),
                    # Y-2: 단계 수는 결과의 평가기준대로(C-C-37 은 심각도 1~4 · 빈도 1~3). 열 키는 그대로, 머리글만 바꾼다.
                    "S(1-5)": st.column_config.NumberColumn(
                        f"심각도(1-{crit.s_max})", min_value=1, max_value=crit.s_max, step=1, width=96
                    ),
                    "F(1-5)": st.column_config.NumberColumn(
                        f"빈도 반영 후(1-{crit.f_max})" if table and service.FREQ_SHIFT_COLUMN in table[0] else f"빈도(1-{crit.f_max})",
                        min_value=1, max_value=crit.f_max, step=1, width=130,
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
            order = service.read_only_order(order)  # S-4-1 읽기 보기는 `기본→반영` 한 열
            for name, head, indices in service.view_groups(shown, view_choice):
                rows = [table[i] for i in indices if i in row_set]
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
                if not rows and row_choice != service.ROW_FILTER_ALL:
                    continue  # 판정으로 거르면 해당 행이 없는 묶음은 접어 두지 않고 뺀다
                focus = state.focus_guideword
                with st.expander(head, expanded=focus is None or name == focus):
                    if rows:
                        draw(rows)
                    else:
                        st.caption("이 묶음에는 결과 행이 없습니다.")
        if not result.is_gold and row_idx:
            # 근거 창(10/16, Elicit 준용) — 편집 표(data_editor)는 행 선택을 못 받아 고르기 칸으로 연다. 키에 필터를 넣어
            # 보이는 행이 바뀌면 이전 선택이 남지 않게 한다.
            plain_table = service.worksheet_table(shown)
            pick = st.selectbox(
                "근거 보기 — 행을 고르면 인용 원문·빈도 근거·검증 표시를 한곳에 보여 줍니다",
                row_idx,
                index=None,
                format_func=lambda i: service.evidence_choice_label(plain_table, i),
                placeholder="근거를 볼 행을 고르세요",
                key=f"evpick_{editor_key}",
            )
            if pick is not None:
                ev = service.row_evidence(shown, pick)
                with st.container(border=True, key="evidence_panel"):
                    st.markdown(f"**{ev.title}**  \n신뢰도: {ev.confidence}")
                    if ev.quotes:
                        # 같은 문서의 구절이 여럿일 수 있다 — 문서 수는 표의 '문서 n건'과 같은 셈
                        st.markdown(f"**인용 구절 {len(ev.quotes)}개 · 공식 문서 {ev.doc_count}건** (원문 그대로, 인용 검사 통과분만)")
                        st.dataframe(ev.quotes, hide_index=True, row_height=60)
                    else:
                        st.caption("이 행은 인용한 공식 문서가 없습니다 — 모델의 일반 지식으로 쓴 초안입니다.")
                    if ev.basis:
                        st.markdown(f"**빈도 근거**  \n{ev.basis}")
                    if ev.missing:
                        st.markdown("**보류 — 필요한 정보**  \n" + " · ".join(ev.missing))
                    if ev.flags:
                        st.markdown("**🔴 검증 표시**  \n" + "\n".join(f"- {f}" for f in ev.flags))
                    st.caption("인용은 '공식 문서가 같은 위험을 다룬다'는 뜻이지 내용이 맞다는 보증이 아닙니다.")
        if not result.is_gold:
            st.caption("신뢰도 " + service.confidence_counts(shown)
                       + " — 문서가 인용됐다는 것은 '공식 문서가 같은 위험을 다룬다'는 뜻이지 내용이 맞다는 보증이 아닙니다.")
        cited = service.evidence_rows(shown)
        if cited:
            with st.expander(f"인용한 법령·MSDS 원문 — {len(cited)}건 (원문 그대로, 인용 검사 통과분만)", expanded=False):
                st.dataframe(cited, hide_index=True, row_height=60)
        repeat = service.repeat_counts(shown)
        if repeat:
            st.caption("반복 일치 — " + repeat + ". 3번 생성한 결과를 합쳤고, 한 번만 나온 판단(●○○)도 남겼습니다. "
                       "●●●는 세 번 모두 나온 판단입니다. 심각도·빈도는 세 번 중 가장 높은 값을 썼습니다. "
                       "여러 번 나왔다고 해서 내용이 맞다는 보증은 아닙니다.")
        reference = service.reference_rows(shown)
        if reference:
            with st.expander(f"참고 — 3번 중 한 번만 나온 문장 {len(reference)}개 (워크시트 칸에서 뺌)", expanded=False):
                st.caption("드문 시나리오일 수도 있어 버리지 않았습니다. 필요하면 '편집 표'에서 해당 행에 옮겨 적어 주세요. "
                           "Excel '반복 일치' 시트에 같은 내용이 있습니다.")
                st.dataframe(reference, hide_index=True)
        held = service.held_rows(shown)
        if held:
            with st.expander(f"확인 필요 — 정보 부족으로 보류한 {len(held)}칸 (심각도·빈도·위험도를 매기지 않음)", expanded=False):
                st.caption("입력에도 공식 문서에도 없는 사업장 정보가 있어야 판단할 수 있는 칸입니다. "
                           "정보를 확인해 심각도·빈도를 채우거나 기각해 주세요. Excel '확인 필요' 시트와 같은 내용입니다.")
                st.dataframe(held, hide_index=True)
        if review_log:
            counts = {v: sum(e[1] == v for e in review_log) for v in ("채택", "수정", "기각")}
            reasons = service.reject_reason_counts(review_log)
            st.caption(" · ".join(f"{k} {n}건" for k, n in counts.items())
                       + (f" (기각 사유: {reasons})" if reasons else "") + " — 다운로드에 반영됨")
    with process_tab:
        st.markdown(service.calls_line(result))  # Q-05-3 저장된 원시 호출 기록에서 — '—' 를 보이지 않는다
        combined = bool(result.meta.get("combined"))
        left, right = st.columns(2)
        with left, st.container(border=True):
            kind = "문장" if result.meta.get("node_text") else ("노드별 입력" if combined else "항목 선택")
            st.markdown(f"**사용자가 넣은 정보 ({kind})**\n" + "\n".join(f"- {line}" for line in service.given_lines(result)))
            if result.meta.get("node_text"):
                st.code(result.meta["node_text"], language=None, wrap_lines=True)
                st.caption(
                    f"→ {result.meta.get('parse_model')} 1회로 해석 — 설명에 없는 수치는 비워 둠"
                )
            if result.meta.get("node_meta"):
                st.json(result.meta["node_meta"], expanded=False)
        with right, st.container(border=True):
            params = view["parameters"]
            param_text = (f"**파라미터 {len(params)}개**(노드 {len(result.meta['nodes'])}개의 파라미터를 모두 합침)" if combined
                          else f"**파라미터 {len(params)}개**")
            st.markdown(
                "**AI가 만든 것**\n"
                f"1. {param_text}: {' · '.join(params)}\n"
                f"2. 파라미터마다 **{service.guideword_count(view['guidewords'])}**({' · '.join(view['guidewords'])})을 하나씩 대입해 "
                f"**{cells}칸**을 빠짐없이 판정\n"
                "3. 칸마다 원인·결과·기존 안전장치·심각도·빈도·위험도·권고 초안을 쓰고, 근거 없는 규격 번호·수치는 🔴로 표시"
            )

# ── HAZOP 이 처음이라면 ──────────────────────────────────────────────────────
st.html(
    '<div id="intro" class="hz-section">HAZOP 및 앱 활용 가이드</div>'
    '<p class="hz-sub" style="margin-bottom:18px">HAZOP(위험과 운전 분석)은 화학 공장 및 가스 설비가 '
    "<b>“원래 설계된 목적에서 벗어날 경우 어떤 위험이 발생하는지”</b>를 체계적으로 분석하는 기법입니다. "
    "아래 카드는 HAZOP과 이 앱의 역할 요약이고, 그 아래 탭에서 기능별 상세 가이드를 볼 수 있습니다.</p>"
)
#: [요약] HAZOP과 이 앱의 역할 — (제목, 핵심 한 줄, 설명). 마크다운을 거치지 않는다(`~` 가 취소선이 된다).
INTRO_CARDS: tuple[tuple[str, str, str | tuple[tuple[str, str], ...]], ...] = (
    (
        "HAZOP이란",
        "설계 의도에서 벗어나는 경우를 빠짐없이 찾는 위험성평가",
        (
            ("방법", "설비를 구간(노드)으로 나누고, 구간마다 유량·압력·온도 같은 변수에 No(없음), More(많음), Less(적음), "
                    "Reverse(역류) 같은 가이드워드를 하나씩 대입해 '설계에서 벗어난 상태(이탈)'를 모두 만들어 봅니다."),
            ("예", "압력 + More → 배관 압력이 설계 압력을 넘음 → 원인: 압축기 토출 제어 고장 → 결과: 배관 파열·가스 누출 "
                  "→ 권고: 고압 연동 정지 인터록 추가"),
            ("결과물", "이탈마다 원인·결과·기존 안전장치·위험도(심각도×빈도)·권고를 적은 표(HAZOP 워크시트)"),
            ("근거", "공정안전보고서(PSM)의 대표 위험성평가 기법 · 절차는 KOSHA C-C-37-2026(연속공정 HAZOP 기술지원규정) 기준"),
        ),
    ),
    (
        "기존 방식의 고충",
        "노드 1개에 6~8명이 수 시간 회의",
        "공장 하나에 노드가 수십~수백 개에 달하며, 노드 1개 분석에 공정·계장·운전·안전 담당자 6~8명이 모여 "
        "수 시간을 회의해야 합니다. 지치면 시나리오가 누락될 위험이 큽니다.",
    ),
    (
        "앱의 효과",
        "초안은 AI, 검토와 승인은 사람",
        "회의 자체를 없애는 것이 아닙니다. 빈 표가 아닌 AI가 빠짐없이 채운 초안에서 시작하여, "
        "사람은 검토와 최종 승인에만 집중하게 해줍니다.",
    ),
)
#: 2·3열 카드 아래 빈자리(10/15 "너무 붕 뜬다") — 열 번호 → 덧붙이는 카드. 화면에 실제로 있는 기능만 적는다.
INTRO_EXTRA: dict[int, tuple[str, str, tuple[tuple[str, str], ...]]] = {
    1: (
        "AI가 하지 않는 것",
        "모르는 값은 지어내지 않습니다",
        (
            ("보류", "입력에 없는 압력·온도·안전장치가 필요한 칸은 채우지 않고 '⚪ 정보 부족'으로 남깁니다."),
            ("표시", "근거 없이 나온 규격 번호·수치는 🔴 검토 필요로 표시해 먼저 확인하게 합니다."),
            ("판단", "채택·기각과 최종 승인은 사람이 합니다. AI 결과는 초안입니다."),
        ),
    ),
    2: (
        "결과물 내려받기",
        "검토한 내용이 그대로 문서가 됩니다",
        (
            ("Excel", "HAZOP 워크시트 — 12열 표준 양식에 검토 내용을 반영하고 '검토 기록' 시트를 붙입니다."),
            ("Word", "LOPA 후보 시나리오 — 위험도가 높은 상위 5개 행을 다음 단계 분석용으로 모읍니다."),
            ("JSON", "신뢰도 리포트 — AI 신뢰도·위험도 분포와 근거 인용 비율을 한 파일로 모읍니다."),
        ),
    ),
}


def _card_rows(body: str | tuple[tuple[str, str], ...]) -> str:
    if isinstance(body, str):
        return f"<div class='hz-info-r'><b style='font-weight:400'>{body}</b></div>"
    return "".join(f"<div class='hz-info-r'><span style='flex-shrink:0;white-space:nowrap'>{k}</span>"
                   f"<b style='font-weight:400'>{v}</b></div>" for k, v in body)


for i, (column, (title, headline, body)) in enumerate(zip(st.columns(3), INTRO_CARDS, strict=True)):
    extra = INTRO_EXTRA.get(i)
    style = ' style="height:auto"' if extra else ""
    html_ = (f'<div class="hz-info"{style}><p class="hz-info-t">{title}</p>'
             f'<p class="hz-info-h">{headline}</p>{_card_rows(body)}</div>')
    if extra:
        html_ += (f'<div class="hz-info" style="height:auto;margin-top:16px"><p class="hz-info-t">{extra[0]}</p>'
                  f'<p class="hz-info-h">{extra[1]}</p>{_card_rows(extra[2])}</div>')
    column.html(html_)
st.html('<div style="height:14px"></div>')


@st.fragment
def _guide_tabs() -> None:
    """안내 탭 — 탭을 바꾸면 이 조각만 다시 실행하고, 열린 탭 하나만 그린다(모양은 예전 st.tabs 그대로)."""
    howto_tab, example_tab, gw_tab, risk_tab, read_tab, compare_tab, psm_tab = st.tabs(
        list(guide.GUIDE_TABS),
        key=guide.GUIDE_TAB_KEY,
        on_change="rerun",  # 선택한 탭만 그린다 — 숨은 탭의 표를 매번 보내지 않는다(10/15 1-B)
    )
    if howto_tab.open:
        with howto_tab:
            howto_tab.html(
                '<div class="hz-info">'
                + "".join(
                    f"<div class='hz-info-r'><span style='width:120px'>[{name}]</span><b style='flex:1;font-weight:400'>{text}</b></div>"
                    for name, text in guide.HOW_TO
                )
                + "</div>"
            )
    if example_tab.open:
        with example_tab:
            st.caption(
                "AI는 2단계를 스스로 도출하며, 4~9단계를 모두 자동 판정합니다. 의미가 성립하지 않는 칸은 '해당 없음'과 사유를 남깁니다. "
                "값은 이해를 돕는 설명용 예시입니다(실제 생성 결과 아님)."
            )
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
                "칸마다 해당하는지, 해당하면 원인·결과가 무엇인지 정하는 이 일을 '판정'이라고 부릅니다. "
                "예: 온도 + Reverse — 온도에는 '거꾸로'가 없어 '해당 없음'."
            )
    if gw_tab.open:
        with gw_tab:
            st.caption("가이드워드(Guide Word)를 조합하면 공정 내에서 발생할 수 있는 비정상적인 상태(이탈)를 쉽게 도출할 수 있습니다. "
                       "파라미터와 붙여 읽습니다(More + 압력 = 압력 과다).")
            st.table(guide.guideword_rows(), hide_index=True, border="horizontal")
            st.caption(f"절차(기동/정지/운전) 노드에는 {', '.join(PROCEDURAL_GUIDEWORDS)} "
                       f"{len(PROCEDURAL_GUIDEWORDS)}종이 추가됩니다.")
    if risk_tab.open:
        with risk_tab:
            st.caption(
                "기본적으로 'KOSHA C-C-37-2026'을 따르며, 위험도는 단순 곱셈이 아닌 대조표로 산출합니다. "
                "(단, 사업장 자체 기준이 있다면 그것이 최우선입니다.) 심각도는 안전조치를 고려하지 않은 기준, "
                "빈도는 안전조치를 고려한 기준입니다. 기준마다 단계 수와 계산법이 달라 섞거나 평균 내지 않습니다."
            )
            st.caption(
                "과거 데이터 기준: 2026년 10월 14일 이전 저장 사례 중 일부는 NH3 벙커링 사업장 기준이 적용되어 있으며, 결과 상단 출처에 명시됩니다."
            )
            crit_by_name = {service.criteria_label(c): c for c in service.all_criteria()}
            shown = crit_by_name[st.radio("평가기준", list(crit_by_name), horizontal=True, key="guide_criteria")]
            st.caption(guide.md_safe(guide.criteria_caption(shown)))
            st.table(guide.criteria_rating_rows(shown), hide_index=True, border="horizontal")
            st.table(guide.criteria_matrix_rows(shown), hide_index=True, border="horizontal")
            st.table(guide.criteria_band_rows(shown), hide_index=True, border="horizontal")
            for note in shown.data.get("notes") or []:
                st.caption(guide.md_safe("· " + note))
            st.markdown("**빈도와 독립방호계층(IPL)**")
            for line in guide.IPL_LINES:
                st.caption("· " + line)
    if read_tab.open:
        with read_tab:
            read_tab.html(
                '<div class="hz-info">'
                + "".join(
                    f"<div class='hz-info-r'><span style='width:170px'>{k}</span><b style='flex:1'>{v}</b></div>"
                    for k, v in guide.READING_GUIDE
                )
                + "</div>"
            )
            st.markdown("**근거 표시(G/S/I/U)의 상세 — AI가 쓰는 정보의 4단계** · AI에게 주는 프롬프트에 들어가는 문구와 같습니다")
            st.table(guide.information_level_rows(), hide_index=True, border="horizontal")
    if compare_tab.open:
        with compare_tab:
            st.markdown(guide.process_table(service.param_range(replays)))
            st.caption(guide.md_safe(
                "도입 효과: 기존에는 회의 중 서기가 기록하고 문서화에 수일이 걸렸으나, 이 앱은 노드 1개당 약 1.5~2분"
                "(측정: 2026-10-08, 3회 79~126초, 약 $0.75) 만에 초안을 자동 완성합니다. 신뢰도 지표가 포함된 Excel, Word 파일을 "
                "즉시 다운로드하여 전문가(회의 참석자) 검토 단계로 바로 넘어갈 수 있습니다. "
                "회의 시간이 얼마나 줄어드는지는 재지 않았습니다."
            ))

    if psm_tab.open:
        with psm_tab:
            st.caption("HAZOP은 산업안전보건법에 따라 설비 가동 전 정부 심사를 받아야 하는 공정안전보고서의 핵심 기법입니다.")
            psm_tab.html(
                '<div class="hz-info">'
                + "".join(f"<div class='hz-info-r'><span style='width:110px'>{k}</span><b style='flex:1'>{v}</b></div>" for k, v in guide.PSM_WHY)
                + "</div>"
            )
            st.caption(guide.SCOPE_NOTE)  # Q-06-4 선박·항만 규칙은 범위 밖
            st.markdown("**보고서가 쓰이는 흐름**")
            st.table(guide.psm_flow_rows(), hide_index=True, border="horizontal")
            st.caption(
                "실무 흐름: 공정 변경 시 지체 없이 보고서를 보완해야 하므로 HAZOP은 반복 작업입니다. 여기서 도출된 권고 사항은 "
                "'안전운전계획' 및 '비상조치계획'으로 이어지는 것이 실무의 기본 흐름입니다(조문 문구는 아님). 본 앱은 이 반복적인 실무 과정을 지원합니다. "
                "출처: [산업안전보건법 제44~46조](https://www.law.go.kr/법령/산업안전보건법) · "
                "[시행령 제43조](https://www.law.go.kr/법령/산업안전보건법시행령) · "
                "[시행규칙 제50조](https://www.law.go.kr/법령/산업안전보건법시행규칙) (2026-10-10 확인)"
            )


_guide_tabs()

# ── 푸터 ─────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "데이터 처리 안내: 실제 고객사 및 사업장 자료는 사용하지 않습니다. 공개된 법령, MSDS, HAZOP 워크시트 및 자체 구축 자료만 활용하며, "
    "신규 생성 시 입력한 공정 설명만 AI 추론을 위해 외부 API로 전송됩니다. · "
    f"{service.system_note(result) if result is not None else ''} · [리포지토리 확인]({REPO})"
)

_emit_nudge()

if state.pop("scroll_result", False):
    st.toast("HAZOP 초안이 완성됐습니다 — 결과로 이동합니다.")
    components.html(
        "<script>const go = () => window.parent.document.getElementById('result')"
        "?.scrollIntoView({block: 'start'}); setTimeout(go, 600); setTimeout(go, 1500);</script>",
        height=0,
    )
