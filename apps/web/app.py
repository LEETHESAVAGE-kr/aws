"""HAZOP 코파일럿 데모 화면 — FR-10 UX v3 (docs/PRD_UX_v3.md).

흐름(위→아래): 앱바 → 히어로 → HAZOP 60초 → 절차 비교 → 모드(문장으로 분석 | 실측 사례) → 결과 → 정확도(접힘) → 푸터.
위젯 배선만 한다. 로직은 `apps/web/service.py`·`apps/web/replay.py`·`apps/web/catalog.py` 에 있다.
실행: `streamlit run apps/web/app.py`
"""

import sys
from pathlib import Path

# 리포 루트를 먼저 sys.path 에 넣는다 — pyproject 가 packages=[] 라 배포 환경엔 core 가 설치되지 않는다.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import contextlib  # noqa: E402

import streamlit as st  # noqa: E402

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
    "위 예시를 누르거나 직접 적으세요.\n"
    "· 물질 · 설비(흐름 순서) · 압력 · 온도 · 안전장치를 적을수록 결과가 구체적입니다. 모르는 값은 빼도 됩니다.\n"
    '· NodeMeta JSON 도 그대로 받습니다: {"node": "X1", "substance": "프로판", "phase": "liquid", '
    '"P_kPag": 800, "T_degC": 30, "equipment": ["프로판 저장탱크"], "safeguards": ["안전밸브"]}'
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

st.set_page_config(page_title="HAZOP Copilot", layout="wide")
# DESIGN.md 토큰: primary #9046ff · primary-tint #f3ecff · primary-soft #c59eff · rounded.md 14px.
# 셀렉터가 Streamlit 버전과 달라도 기능은 같다 — 숨김·모서리만 잃는다(U-R6).
st.html(
    """<style>
    header[data-testid="stHeader"], #MainMenu, footer { display: none !important; }
    .block-container { padding-top: 0 !important; max-width: 1200px; }
    [data-testid="stVerticalBlockBorderWrapper"] { border-radius: 14px; box-shadow: 0 1px 3px rgba(20,20,40,.08); }
    [data-testid="stMetricValue"] { font-size: 32px; font-weight: 700; }
    .hz-bar { position: sticky; top: 0; z-index: 100; background: #fff; height: 56px; display: flex;
        align-items: center; justify-content: space-between; border-bottom: 1px solid #e6e6ee; margin: 0 0 12px; }
    .hz-logo { font-size: 20px; font-weight: 700; color: #1a1a2e; }
    .hz-nav a { margin-left: 20px; color: #555; text-decoration: none; font-size: 14px; }
    .hz-nav a:hover { color: #1a1a2e; }
    @media (max-width: 900px) { .hz-nav { display: none; } }
    .hz-h1 { font-size: 28px; font-weight: 700; line-height: 1.35; margin: 4px 0 6px; color: #1a1a2e; }
    .hz-sub { font-size: 16px; color: #444; margin: 0 0 10px; line-height: 1.6; }
    .hz-badge { display: inline-block; font-size: 13px; padding: 3px 10px; margin: 0 6px 4px 0;
        border-radius: 999px; background: #fff7e0; color: #7a5a00; border: 1px solid #f0dca0; }
    [class*="st-key-intro"] p, [class*="st-key-intro"] li { font-size: 14px; line-height: 1.5; margin-bottom: 2px; }
    [class*="st-key-intro"] ol { margin-bottom: 4px; }
    .hz-card-sub { font-size: 13px; color: #666; margin: 0 0 4px; }
    .hz-card-title { font-size: 20px; font-weight: 600; margin: 0 0 2px; }
    .st-key-mode [role="radiogroup"] { gap: 6px; }
    .st-key-mode label { border: 1px solid #ddd; border-radius: 10px; padding: 6px 14px; background: #fafafa; }
    .st-key-mode label:has(input:checked) { background: #f3ecff; border-color: #c59eff; color: #6a2fd6;
        font-weight: 600; }
    .st-key-process_name [data-baseweb="select"] > div {
        background-color: #f3ecff; border: 1px solid #c59eff; font-weight: 600; min-height: 48px;
    }
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


def _comparison() -> None:
    with st.expander("현장 절차와 비교", expanded=True):
        st.markdown(
            "| 단계 | 기존 HAZOP 회의 | 이 앱 |\n|---|---|---|\n"
            "| 노드 정의 | 사람 (P&ID) | 사람 — 문장 한 문단 또는 JSON |\n"
            "| 파라미터 도출 | 팀 브레인스토밍 | AI 1회 호출, 노드당 8~12개 |\n"
            "| 가이드워드 전 셀 판정 | 셀마다 토론, 누락 위험 | AI 가이드워드별 병렬 호출, 셀 누락 0 (판정 셀 n/n 표시) |\n"
            "| 원인·결과·안전장치·S×F·권고 | 서기가 회의 중 기록 | 초안 자동, 신뢰도 배지 + 규칙 verifier |\n"
            "| 워크시트·LOPA 문서화 | 회의 후 수일 | 즉시 xlsx(5시트)·LOPA docx·신뢰도 JSON |"
        )
        st.caption(
            "실측: 노드 1건 약 2~2.5분 · 약 $0.8 (2026-09-29, 병렬 4). "
            '정확도는 하단 "정확도" 절에 불리한 값까지 공개합니다.'
        )


# ── 앱바 + 히어로 ────────────────────────────────────────────────────────────
st.html(
    """<div class="hz-bar"><span class="hz-logo">⬡ HAZOP Copilot</span>
    <span class="hz-nav"><a href="#nl">문장으로 분석</a><a href="#cases">실측 사례</a><a href="#eval">정확도</a></span></div>
    <div class="hz-h1">공정을 한 문단으로 쓰면, HAZOP 워크시트 초안이 나옵니다.</div>
    <p class="hz-sub">물질·설비·압력·온도·안전장치를 문장으로 적으면, AI 가 점검 파라미터를 세우고 가이드워드마다
    이탈을 판정해 원인·결과·S×F 위험도·권고까지 채운 초안을 만듭니다. 전문가는 검토만 하면 됩니다.</p>
    <span class="hz-badge">실제 LLM 생성 (Claude)</span><span class="hz-badge">전문가 골드셋 34건 대비 recall 공개</span>
    <span class="hz-badge">PSM 양식 xlsx · LOPA 초안 내보내기</span>"""
)

# ── HAZOP 60초 ───────────────────────────────────────────────────────────────
what, why, split = st.columns(3)
with what.container(border=True, key="intro_what"):
    st.markdown(
        "**① HAZOP 이 뭔가**\n\n"
        "위험과 운전 분석(Hazard and Operability Study). 공정을 노드(배관·설비 구간)로 나누고, 각 노드의 "
        "파라미터(유량·압력·온도·조성…)에 가이드워드(No·More·Less·Reverse·Part of·As well as·Other than)를 "
        '하나씩 붙여 "설계 의도에서 벗어나는 경우(이탈)"를 빠짐없이 찾는 정성 위험성평가입니다. 국내에서는 '
        "공정안전보고서(PSM) 위험성평가의 표준 기법이고, KOSHA GUIDE P-82 가 절차를 정합니다."
    )
with why.container(border=True, key="intro_why"):
    st.markdown(
        "**② 왜 무거운가 — 현장 절차**\n"
        "1. P&ID 를 놓고 노드를 나눈다.\n"
        "2. 리더·서기·공정·계장·운전·안전 담당이 한 방에 모인다.\n"
        "3. 노드마다 파라미터×가이드워드 셀을 하나씩 짚으며 이탈·원인·결과를 토론한다.\n"
        "4. 기존 안전장치를 확인하고 심각도(S)×빈도(F)로 위험도를 매긴다.\n"
        "5. 권고사항을 정하고 워크시트·LOPA 로 문서화한다.\n\n"
        "노드 하나에 회의 수 시간, 공장 하나에 노드 수십~수백 개. 매트릭스 셀을 빠뜨리지 않는 것 자체가 일입니다."
    )
with split.container(border=True, key="intro_split"):
    st.markdown(
        "**③ 이 앱이 대신하는 것 / 사람이 하는 것**\n\n"
        "**대신하는 것**: 파라미터 도출(3) → 가이드워드 전 셀 판정(3) → 원인·결과·안전장치·S×F·권고 초안(4) → "
        "워크시트·LOPA 초안(5). 판정 셀은 100% 채우고, 근거 없는 규격 번호·수치는 verifier 가 🔴 로 표시합니다.\n\n"
        "**사람이 하는 것**: 노드 정의(1), 초안 검토·수정, 최종 승인. "
        "**초안은 회의를 없애지 않고 회의 시작점을 올립니다.**"
    )

# ── 모드 선택 ────────────────────────────────────────────────────────────────
# 비교 표는 입력 카드 옆에 펼친 채로 — 1440×900 첫 화면에 입력칸·버튼과 함께 들어가게(S1·S4).
work, compare = st.columns([3, 2])
with compare:
    _comparison()
work.html('<div id="nl"></div><div id="cases"></div>')
mode = work.radio(
    "모드", [MODE_NL, MODE_CASES], horizontal=True, label_visibility="collapsed", key="mode"
)

result = None
if mode == MODE_NL:
    with work.container(border=True):
        st.html(
            f'<div class="hz-card-title">{MODE_NL}</div><p class="hz-card-sub">처음 보는 공정도 됩니다. '
            "물질·설비(흐름 순서)·압력·온도·안전장치를 적을수록 구체적입니다.</p>"
        )
        for i, (column, (label, text)) in enumerate(
            zip(st.columns(len(EXAMPLES)), EXAMPLES, strict=True)
        ):
            column.button(
                f"예시 · {label}", key=f"chip_{i}", on_click=_fill, args=(text,), width="stretch"
            )
        left, right = st.columns([2, 1])
        left.text_area(
            "공정 설명",
            key="quick_text",
            height=160,
            max_chars=service.NODE_TEXT_LIMIT,
            placeholder=DIRECT_PLACEHOLDER,
            label_visibility="collapsed",
        )
        guideword = right.selectbox(
            "가이드워드",
            GUIDEWORDS,
            index=GUIDEWORDS.index("More"),
            format_func=lambda g: f"가이드워드 · {g}",
            label_visibility="collapsed",
        )
        quota = service.quota_block_reason(state.live_runs)
        blocked = live_reason is not None or quota is not None or not state.quick_text.strip()
        clicked_quick = right.button(
            "HAZOP 초안 생성 (약 1분)", type="primary", disabled=blocked, width="stretch"
        )
        clicked_full = False
        if service.live_scope() == "full":
            clicked_full = right.button(
                f"노드 전체 초안 생성 ({service.LIVE_NOTE})", disabled=blocked, width="stretch"
            )
        right.caption(f"이번 호출에서 판정할 가이드워드 1개 — {GUIDEWORD_HELP}")
        left_runs = max(service.SESSION_LIMIT - state.live_runs, 0)
        if live_reason:
            right.caption(live_reason)
        elif quota:
            scope = "이 세션에" if "세션" in quota else "오늘"
            right.caption(
                f"이 세션 남은 횟수 {left_runs}/{service.SESSION_LIMIT} · {scope} 준비된 실행 횟수를 모두 썼습니다. "
                '아래 "실측 사례 재생"에서 같은 화면을 볼 수 있습니다.'
            )
            right.button("실측 사례 보기", on_click=_to_cases, width="stretch")
        else:
            right.caption(
                f"이 세션 남은 횟수 {left_runs}/{service.SESSION_LIMIT} · "
                "호출 3회(문장 해석 → 파라미터 열거 → 가이드워드 판정) · 약 $0.15"
            )
            if service.is_mock():
                right.caption("mock 모드 — 네트워크 없이 재생 레코드로 생성 경로를 돕니다.")
    if clicked_quick or clicked_full:
        reason = service.reserve_live_run(state.live_runs)
        if reason:
            st.error(reason)
        else:
            state.live_runs += 1
            mock_source = replays.get("N1") or next(iter(replays.values()))
            with st.status("HAZOP 초안 생성 중", expanded=True) as status:
                st.write("1/3 문장을 노드 입력으로 해석")
                try:
                    if clicked_quick:
                        state.quick_result = service.run_quick(
                            state.quick_text, guideword, mock_source
                        )
                    else:
                        state.quick_result = service.run_live(state.quick_text, mock_source)
                except Exception as exc:  # noqa: BLE001 — 사유를 보이고 앱은 계속 산다
                    status.update(label="생성 실패", state="error")
                    st.error(f"생성 실패: {type(exc).__name__}: {exc}")
                    if service.is_auth_error(exc):
                        st.caption(service.key_hint())
                else:
                    st.write("2/3 점검 파라미터 열거")
                    st.write(f"3/3 가이드워드 '{guideword}' 판정")
                    latency = state.quick_result.meta.get("latency_s")
                    status.update(
                        label="완료" + ("" if latency is None else f" · {latency:.0f}초"),
                        state="complete",
                    )
                    st.rerun()  # 버튼을 상한 사유와 함께 즉시 비활성으로 다시 그린다
    result = state.quick_result
else:
    with work.container(border=True):
        st.html(f'<div class="hz-card-title">{MODE_CASES}</div>')
        st.caption(
            "9/29 에 실제로 생성한 결과를 그대로 다시 보여줍니다(재생성 아님). "
            "암모니아 STS 벙커링은 전문가 HAZOP 골드셋 34건과 대조해 recall 을 공개합니다."
        )
        names = [p["name"] for p in service.CATALOG]
        choice = st.selectbox("공정", names, key="process_name", label_visibility="collapsed")
        process = next(p for p in service.CATALOG if p["name"] == choice)
        if process["gold"]:
            st.markdown(
                ":green-background[골드셋 34건 · recall 실측] 액체 암모니아(NH3) 이송 공정"
                "(공급선 → 이송 호스 → 수급선) — 전문가가 직접 수행한 HAZOP 34건과 대조합니다."
            )
        else:
            st.markdown(
                f":orange-background[예시 공정 · 골드셋 없음(정성 검토)] {process['description']}"
            )
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
    result = replays.get(state.node)

# ── 결과 패널 ────────────────────────────────────────────────────────────────
if result is None:
    st.info('예시 칩을 누르거나 문장을 적고 "HAZOP 초안 생성"을 누르세요.')
else:
    if result.is_gold:
        st.warning(service.provenance_line(result))
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
        ("이탈 레코드", f"{len(result.records)}건"),
        ("판정 셀", cells),
        ("소요", "—" if view["latency_s"] is None else f"{view['latency_s']:.0f}초"),
        ("비용", "—" if view["cost_usd"] is None else f"${view['cost_usd']:.2f}"),
    ]
    if recall:
        tiles.append(("recall", f"{recall['recall']:.3f}"))
    for column, (label, value) in zip(st.columns(len(tiles)), tiles, strict=True):
        column.metric(label, value)
    calls = "—" if view["api_calls"] is None else f"{view['api_calls']}회"
    st.markdown(f"**정확도** {service.accuracy_line(result, replays)} · API 호출 {calls}")

    node_meta = result.meta.get("node_meta", {})
    left, right = st.columns(2)
    with left:
        kind = "문장" if result.meta.get("node_text") else "JSON"
        st.markdown(
            f"**사용자가 준 것 ({kind})** — 노드({node_meta.get('node') or '—'}), "
            f"취급 물질({node_meta.get('substance') or '—'}), "
            f"대상 설비({', '.join(node_meta.get('equipment') or []) or '—'})"
        )
        if result.meta.get("node_text"):
            st.code(result.meta["node_text"], language=None, wrap_lines=True)
        with st.expander(
            "해석된 NodeMeta"
            + (
                f" ({result.meta.get('parse_model')} 1회 — 설명에 없는 수치는 비워 둠)"
                if result.meta.get("node_text")
                else ""
            ),
            expanded=False,
        ):
            st.json(node_meta)
    with right:
        st.markdown(
            "**AI 가 만든 것**\n"
            f"1. **파라미터 {len(view['parameters'])}개**: {' · '.join(view['parameters'])}\n"
            f"2. **가이드워드 {len(view['guidewords'])}종**({' · '.join(view['guidewords'])})을 교차 적용해 "
            f"매트릭스 셀 **{cells}** 을 빠짐없이 판정"
        )

    # verifier 시연(O-3): 표·요약 줄만 삽입 사본으로. 다운로드는 아래에서 원본 `result` 로 만든다.
    shown = result
    if not result.is_gold and st.checkbox(service.DEMO_TOGGLE_LABEL, key="verifier_demo"):
        shown = service.demo_injected(result)
        st.markdown(service.DEMO_BANNER)
    st.caption(service.summary_line(shown))
    st.dataframe(service.worksheet_table(shown), hide_index=True)
    files = service.export_files(result)
    mimes = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "lopa": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "report": "application/json",
    }
    for column, key in zip(st.columns(3), ("xlsx", "lopa", "report"), strict=True):
        name, data = files[key]
        column.download_button(f"⬇ {name}", data, file_name=name, mime=mimes[key])
    if not result.is_gold:
        st.caption(service.provenance_line(result))

# ── 정확도 (기본 접힘) ───────────────────────────────────────────────────────
st.html('<div id="eval"></div>')
with st.expander("정확도 — 골드셋 대비 recall (n=1)", expanded=False):
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
