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

from apps.web import service  # noqa: E402
from apps.web.replay import load_replays  # noqa: E402
from core.agent.generate import PROCEDURAL_GUIDEWORDS, STANDARD_GUIDEWORDS  # noqa: E402

MODE_NL = "문장으로 새 공정 분석"
MODE_CASES = "실측 사례 재생"
GUIDEWORDS = STANDARD_GUIDEWORDS + PROCEDURAL_GUIDEWORDS
REPO = "https://github.com/LEETHESAVAGE-kr/aws"
README_EVAL = f"{REPO}/blob/main/README.md#-6-평가-결과"
#: 입력 칸 placeholder — 예시 문장은 칩이 맡고, 여기엔 쓰는 요령만.
DIRECT_PLACEHOLDER = (
    "예시를 누르거나 공정을 직접 적어 보세요.\n"
    "물질 · 설비(흐름 순서) · 압력 · 온도 · 안전장치를 적을수록 구체적입니다. 모르는 값은 빼도 됩니다.\n"
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
GUIDEWORD_HELP = (
    "No: 흐름 없음 · More: 과다(압력·온도·유량↑) · Less: 과소 · Reverse: 역류 · Part of: 조성 일부 · "
    "As well as: 이물 혼입 · Other than: 다른 물질/상태"
)

#: 가이드워드 → 뜻 (선택 칸에 함께 보여 준다). "No: 흐름 없음" → {"No": "흐름 없음"}
GUIDEWORD_MEANING: dict[str, str] = dict(
    part.split(": ", 1) for part in GUIDEWORD_HELP.split(" · ")
)

st.set_page_config(page_title="HAZOP Copilot", layout="wide")
# DESIGN.md 토큰: primary #9046ff · primary-tint #f3ecff · primary-soft #c59eff · rounded.md 14px.
# 회색 캔버스 위 흰 카드 = "앱" 의 기본 문법. 셀렉터가 버전과 달라도 기능은 같다 — 모양만 잃는다(U-R6).
st.html(
    """<style>
    :root { --bg: #141417; --card: #1e1e23; --card2: #26262d; --line: #32323b; --text: #f3f3f6;
        --muted: #9b9ba8; --accent: #9046ff; --accent-text: #b996ff; --accent-soft: rgba(144,70,255,.16); }
    header[data-testid="stHeader"], #MainMenu, footer { display: none !important; }
    .stApp { background: var(--bg); }
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
    .hz-h1 { font-size: 28px; letter-spacing: -0.4px; font-weight: 700; line-height: 1.4; margin: 0 0 12px;
        color: var(--text); }
    .hz-sub { font-size: 15px; color: var(--muted); margin: 0 0 26px; line-height: 1.65; }
    .hz-steps { display: flex; flex-direction: column; gap: 10px; margin-bottom: 22px; }
    .hz-step { display: flex; gap: 14px; align-items: center; background: var(--card); border: 1px solid var(--line);
        border-radius: 12px; padding: 12px 14px; }
    .hz-step b { flex: none; width: 28px; height: 28px; border-radius: 8px; background: var(--accent-soft);
        color: var(--accent-text); font-size: 14px; display: flex; align-items: center; justify-content: center; }
    .hz-step strong { display: block; font-size: 15px; color: var(--text); }
    .hz-step span { font-size: 13px; color: var(--muted); }
    .hz-trust { display: flex; gap: 8px; flex-wrap: wrap; }
    .hz-trust span { font-size: 12px; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--line);
        color: var(--muted); }
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
state.setdefault("mode", MODE_NL)


def _fill(text: str) -> None:
    state.quick_text = text


def _to_cases() -> None:
    state.mode = MODE_CASES


def _failure_hint(exc: BaseException) -> str:
    """재시도 소진(`BedrockCallError`)이 감춘 원인 상태코드를 사람 말로. 키 문자는 드러내지 않는다."""
    cause = exc.__cause__ or exc
    code = getattr(cause, "status_code", None)
    if code == 429:
        return (
            "원인: 429 — API 키의 분당 사용량 한도에 걸렸습니다(여러 명이 연달아 누른 경우). "
            '1분쯤 뒤 다시 누르거나, 기다리는 동안 "실측 사례 재생"을 보세요. 이번 실패는 횟수에 넣지 않았습니다.'
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
    """<div class="hz-eyebrow">AI 위험성평가 코파일럿</div>
    <div class="hz-h1">공정을 한 문단으로 쓰면,<br>HAZOP 워크시트 초안이 나옵니다.</div>
    <p class="hz-sub">며칠짜리 HAZOP 회의의 첫 초안을 AI 가 2분 안에 채웁니다. 전문가는 검토와 승인만 하세요.</p>
    <div class="hz-steps">
      <div class="hz-step"><b>1</b><div><strong>공정을 문장으로 설명</strong>
        <span>예시 버튼 하나로 바로 시작</span></div></div>
      <div class="hz-step"><b>2</b><div><strong>AI 가 가이드워드 전 셀 판정</strong>
        <span>파라미터를 스스로 세우고 이탈·원인·결과·S×F 위험도·권고까지</span></div></div>
      <div class="hz-step"><b>3</b><div><strong>검토하고 내려받기</strong>
        <span>PSM 양식 Excel · LOPA 초안 Word · 신뢰도 리포트</span></div></div>
    </div>
    <div class="hz-trust"><span>실제 LLM 생성 (Claude)</span><span>전문가 골드셋 34건 대비 정확도 공개</span>
    <span>근거 없는 규격 번호 자동 표시</span></div>"""
)

result = None
with tool.container(border=True, key="tool"):
    mode = st.radio(
        "모드", [MODE_NL, MODE_CASES], horizontal=True, label_visibility="collapsed", key="mode"
    )
    if mode == MODE_NL:
        done = 3 if state.quick_result is not None else (2 if state.quick_text.strip() else 1)
        st.html(
            f'<div class="hz-progress"><div style="width:{done * 33.4:.0f}%"></div></div>'
            '<p class="hz-q-step">STEP 1 / 2</p><p class="hz-q">어떤 공정을 분석할까요?</p>'
            '<p class="hz-q-help">물질·설비·압력·온도·안전장치를 적을수록 정확해집니다. 예시를 눌러도 됩니다.</p>'
        )
        for i, (column, (label, text)) in enumerate(
            zip(st.columns(len(EXAMPLES)), EXAMPLES, strict=True)
        ):
            column.button(label, key=f"chip_{i}", on_click=_fill, args=(text,), width="stretch")
        st.text_area(
            "공정 설명",
            key="quick_text",
            height=130,
            max_chars=service.NODE_TEXT_LIMIT,
            placeholder=DIRECT_PLACEHOLDER,
            label_visibility="collapsed",
        )
        st.html(
            '<p class="hz-q-step" style="margin-top:8px">STEP 2 / 2</p>'
            '<p class="hz-q">어떤 이탈부터 볼까요?</p>'
        )
        guideword = st.selectbox(
            "가이드워드",
            GUIDEWORDS,
            index=GUIDEWORDS.index("More"),
            format_func=lambda g: f"{g} — {GUIDEWORD_MEANING[g]}" if g in GUIDEWORD_MEANING else g,
            label_visibility="collapsed",
        )
        quota = service.quota_block_reason(state.live_runs)
        blocked = live_reason is not None or quota is not None or not state.quick_text.strip()
        with st.container(key="cta"):
            clicked_quick = st.button(
                "HAZOP 초안 생성 (약 1분)", type="primary", disabled=blocked, width="stretch"
            )
        clicked_full = False
        if service.live_scope() == "full":
            clicked_full = st.button(
                f"노드 전체 초안 생성 ({service.LIVE_NOTE.replace('~', '–')})",
                disabled=blocked,
                width="stretch",
            )
        if clicked_quick or clicked_full:
            reason = service.reserve_live_run(state.live_runs)
            if reason:
                st.error(reason)
            else:
                state.live_runs += 1
                mock_source = replays.get("N1") or next(iter(replays.values()))
                # 진행 표시는 버튼 바로 아래 — 결과 영역은 첫 화면 밖이라 거기 두면 "아무 일도 없다"로 보인다(9/29 23:05).
                with st.status(
                    "HAZOP 초안 생성 중 · 약 1분 — 이 화면에서 기다려 주세요", expanded=True
                ) as status:
                    # R-11: 단계가 끝나는 즉시 그 산출물을 쓴다(예전엔 끝난 뒤 2/3·3/3 을 한꺼번에 찍었다).
                    lines = [st.empty() for _ in range(3)]
                    lines[0].write(service.STAGE_PENDING[0])
                    st.caption("생성 중에 다른 버튼을 누르면 이번 생성이 취소됩니다.")

                    def on_progress(event: str, payload: dict[str, Any]) -> None:
                        step, text, pending = service.progress_text(event, payload, guideword if clicked_quick else None)
                        lines[step].write(text)
                        if pending is not None and step + 1 < len(lines):
                            lines[step + 1].write(pending)
                        # expanded 를 다시 주지 않으면 라벨 갱신이 상자를 접는다(10/8 브라우저 확인).
                        status.update(label=f"HAZOP 초안 생성 중 · {text.split(' — ')[0]}", expanded=True)

                    try:
                        if clicked_quick:
                            state.quick_result = service.run_quick(
                                state.quick_text, guideword, mock_source, on_progress=on_progress
                            )
                        else:
                            state.quick_result = service.run_live(
                                state.quick_text, mock_source, on_progress=on_progress
                            )
                    except Exception as exc:  # noqa: BLE001 — 사유를 보이고 앱은 계속 산다
                        state.live_runs -= 1  # 실패한 실행은 세션 횟수에서 빼지 않는다
                        status.update(label="생성 실패", state="error", expanded=True)
                        st.error(f"생성 실패: {type(exc).__name__}: {exc}")
                        st.caption(_failure_hint(exc))
                        st.button(
                            "실측 사례 보기 — 완성된 결과를 바로 확인",
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
                "실측 사례에서 같은 화면을 볼 수 있습니다."
            )
            st.button("실측 사례 보기", on_click=_to_cases, width="stretch")
        else:
            st.caption(
                f"이 세션 남은 횟수 {left_runs}/{service.SESSION_LIMIT} · "
                "호출 3회(문장 해석 → 파라미터 열거 → 가이드워드 판정) · 약 $0.15"
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
        if process["gold"]:
            st.markdown(
                ":green-background[골드셋 34건 · recall 실측] 액체 암모니아(NH3) 이송 — "
                "전문가가 직접 수행한 HAZOP 34건과 대조합니다."
            )
        else:
            st.markdown(f":orange-background[예시 공정 · 골드셋 없음] {process['description']}")
        node_ids = [n["id"] for n in process["nodes"]]
        if state.node not in node_ids:  # 공정을 바꾸면 그 공정의 첫 캡처 노드를 연다
            state.node = next((n for n in node_ids if n in replays), node_ids[0])
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

result = state.quick_result if mode == MODE_NL else replays.get(state.node)

# ── 결과 ─────────────────────────────────────────────────────────────────────
st.html('<div id="result" class="hz-section">분석 결과</div>')
if result is None:
    st.html(
        '<div class="hz-empty"><strong>아직 결과가 없습니다</strong>'
        '위에서 예시를 누르고 "HAZOP 초안 생성"을 누르면 1분 안에 여기에 워크시트가 나타납니다.<br>'
        '기다리기 싫다면 "실측 사례 재생"에서 완성된 결과를 바로 볼 수 있습니다.</div>'
    )
else:
    if result.is_gold:
        st.warning(service.provenance_line(result))
    else:
        st.caption(service.provenance_line(result))
    notice = service.criteria_notice(result)
    if notice:
        st.markdown(f":orange-background[평가기준] {notice}")
    view = service.process_view(result)
    cells = (
        f"{view['judged_cells']}/{view['expected_cells']}"
        if view["expected_cells"] is not None
        else "—"
    )
    recall = result.meta.get("recall")
    tiles = [
        ("이탈 시나리오", f"{len(result.records)}건"),
        ("판정 셀 (누락 0)", cells),
        ("소요 시간", "—" if view["latency_s"] is None else f"{view['latency_s']:.0f}초"),
        ("비용", "—" if view["cost_usd"] is None else f"${view['cost_usd']:.2f}"),
    ]
    if recall:
        tiles.append(("전문가 대비 recall", f"{recall['recall']:.3f}"))
    for column, (label, value) in zip(st.columns(len(tiles)), tiles, strict=True):
        column.metric(label, value)

    files = service.export_files(result)
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
        st.dataframe(service.worksheet_table(shown), hide_index=True)
    with process_tab:
        calls = "—" if view["api_calls"] is None else f"{view['api_calls']}회"
        st.markdown(f"**정확도** {service.accuracy_line(result, replays)} · API 호출 {calls}")
        node_meta = result.meta.get("node_meta", {})
        left, right = st.columns(2)
        with left, st.container(border=True):
            kind = "문장" if result.meta.get("node_text") else "JSON"
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
                "3. 셀마다 원인·결과·기존 안전장치·S×F 위험도·권고 초안, 근거 없는 규격 번호·수치는 🔴 표시"
            )

# ── HAZOP 이 처음이라면 ──────────────────────────────────────────────────────
st.html('<div id="intro" class="hz-section">HAZOP 이 처음이라면</div>')
#: (제목, 핵심 한 줄, [(항목, 내용)...]) — 줄글 대신 한눈에 읽히는 행. 마크다운을 거치지 않는다(`~` 가 취소선이 된다).
INTRO_CARDS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "HAZOP 이란",
        "설계 의도에서 벗어나는 경우를 빠짐없이 찾는 위험성평가",
        (
            ("대상", "공정 구간(노드) — 배관·설비"),
            ("방법", "유량·압력·온도 × No·More·Less·Reverse…"),
            ("근거", "PSM 표준 기법 · KOSHA GUIDE P-82"),
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
            ("AI", "전 셀 판정 · 원인·결과·S×F·권고 초안"),
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
with st.expander("현장 절차와 한눈에 비교", expanded=False):
    st.markdown(
        "| 단계 | 기존 HAZOP 회의 | 이 앱 |\n|---|---|---|\n"
        "| 노드 정의 | 사람 (P&ID) | 사람 — 문장 한 문단 또는 JSON |\n"
        "| 파라미터 도출 | 팀 브레인스토밍 | AI 1회 호출, 노드당 8–12개 |\n"
        "| 가이드워드 전 셀 판정 | 셀마다 토론, 누락 위험 | AI 가이드워드별 병렬 호출, 셀 누락 0 |\n"
        "| 원인·결과·안전장치·S×F·권고 | 서기가 회의 중 기록 | 초안 자동, 신뢰도 배지 + 규칙 verifier |\n"
        "| 워크시트·LOPA 문서화 | 회의 후 수일 | 즉시 xlsx(5시트)·LOPA docx·신뢰도 JSON |"
    )
    st.caption("실측: 노드 1건 약 2–2.5분 · 약 $0.8 (2026-09-29, 병렬 4).")

# ── 정확도 (기본 접힘) ───────────────────────────────────────────────────────
st.html('<div id="eval"></div>')
with st.expander("정확도 — 골드셋 대비 recall (n=1), 불리한 값까지 공개", expanded=False):
    st.caption(
        "NH3 벙커링 4노드만 해당(예시 공정은 골드셋 없음). 하네스 미구현 — `tools/capture_replay.py` 로 "
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
