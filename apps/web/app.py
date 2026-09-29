"""HAZOP 코파일럿 데모 화면 — FR-10 H-02 (지시문 H) · J-04 (지시문 J).

흐름(위→아래): 공정 선택 → LLM 에 보낸 입력 / 생성 과정 → HAZOP 워크시트 → 평가 결과(접힘).
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

DIRECT = "직접 입력 (빠른 실호출)"
GUIDEWORDS = STANDARD_GUIDEWORDS + PROCEDURAL_GUIDEWORDS
README_EVAL = "https://github.com/LEETHESAVAGE-kr/aws/blob/main/README.md#-6-평가-결과"
#: 직접 입력 칸의 placeholder — 입력 방식을 보여주는 예시(값으로 채우지 않는다).
DIRECT_PLACEHOLDER = (
    "예시) 수소충전소에서 튜브트레일러의 압축 수소를 압축기로 약 90 MPa 까지 올려 저장용기에 모았다가 "
    "디스펜서로 차량에 충전한다. 안전장치는 안전밸브, 긴급차단밸브, 수소누출감지기.\n\n"
    "· 물질 · 설비(흐름 순서) · 압력 · 온도 · 안전장치를 적을수록 결과가 구체적입니다. 모르는 값은 빼도 됩니다.\n"
    '· NodeMeta JSON 도 그대로 받습니다: {"node": "X1", "substance": "프로판", "phase": "liquid", '
    '"P_kPag": 800, "T_degC": 30, "equipment": ["프로판 저장탱크"], "safeguards": ["안전밸브"]}'
)

st.set_page_config(page_title="HAZOP 코파일럿", layout="wide")
# 공정 선택 칸만 옅은 보라(DESIGN.md primary-tint·primary-soft) — 화면 바탕은 흰색 그대로.
st.html(
    """<style>
    .st-key-process_name [role="group"],
    .st-key-process_name [data-baseweb="select"] > div {
        background-color: #f3ecff; border: 1px solid #c59eff; font-weight: 600;
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

# ── 1. 제목 ──────────────────────────────────────────────────────────────────
st.title("HAZOP 위험성평가 코파일럿")
st.markdown(
    "공정 노드 설명(물질·상·압력·온도·설비·안전장치)을 넣으면 LLM 이 **파라미터 축을 스스로 열거**하고 "
    "가이드워드(No·More·Less·Reverse·Other than·Part of·As well as)마다 매트릭스 셀을 판정해 "
    "원인·결과·기존 안전장치·S×F 위험도·권고가 채워진 **HAZOP 워크시트 초안**을 만듭니다. "
    "아래 결과는 전부 LLM 이 **왼쪽 입력만 보고** 생성한 것입니다(캡처 일시·모델·비용 표기). "
    "사람은 검토에 집중합니다."
)
st.caption("고객사 실데이터는 쓰지 않았습니다. NH3 골드셋은 팀 보유 전문가 HAZOP 34건입니다.")

# ── 2. 공정 선택 ─────────────────────────────────────────────────────────────
st.subheader("① 공정 선택")
names = [p["name"] for p in service.CATALOG] + [DIRECT]
choice = st.selectbox("공정", names, key="process_name", label_visibility="collapsed")
process = next((p for p in service.CATALOG if p["name"] == choice), None)

result = None
if process is not None:
    badge = (
        ":green-background[골드셋 34건 · recall 실측]"
        if process["gold"]
        else ":orange-background[예시 공정 · 골드셋 없음(정성 검토)]"
    )
    st.markdown(f"{badge} {process['description']}")
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
else:
    st.markdown(
        ":blue-background[직접 입력] 공정을 문장으로 설명하고 가이드워드 1개를 고르면 실제로 생성합니다 — "
        "문장을 노드 입력으로 해석(저비용 모델 1회) → 파라미터 열거 1회 → 가이드워드 판정 1회."
    )
    left, right = st.columns([2, 1])
    left.text_area(
        "공정 설명 — 자연어 문장 또는 NodeMeta JSON",
        key="quick_text",
        height=230,
        max_chars=service.NODE_TEXT_LIMIT,
        placeholder=DIRECT_PLACEHOLDER,
    )
    guideword = right.selectbox("가이드워드", GUIDEWORDS, index=GUIDEWORDS.index("More"))
    if live_reason:
        right.caption(live_reason)
    elif service.is_mock():
        right.info("mock 모드 — 네트워크 없이 재생 레코드로 생성 경로를 돕니다.")
    quota = service.quota_block_reason(state.live_runs)
    blocked = live_reason is not None or quota is not None
    blocked = blocked or not state.quick_text.strip()
    clicked_quick = right.button("빠른 실호출(약 1분)", type="primary", disabled=blocked)
    right.caption(quota or service.QUICK_NOTE)
    clicked_full = False
    if service.live_scope() == "full":
        clicked_full = right.button(f"노드 전체 실호출({service.LIVE_NOTE})", disabled=blocked)
    if clicked_quick or clicked_full:
        reason = service.reserve_live_run(state.live_runs)
        if reason:
            st.error(reason)
        else:
            state.live_runs += 1
            mock_source = replays.get("N1") or next(iter(replays.values()))
            with st.spinner("생성 중… " + (service.QUICK_NOTE if clicked_quick else service.LIVE_NOTE)):
                try:
                    if clicked_quick:
                        state.quick_result = service.run_quick(state.quick_text, guideword, mock_source)
                    else:
                        state.quick_result = service.run_live(state.quick_text, mock_source)
                except Exception as exc:  # noqa: BLE001 — 사유를 보이고 앱은 계속 산다
                    st.error(f"생성 실패: {type(exc).__name__}: {exc}")
                    if service.is_auth_error(exc):
                        st.caption(service.key_hint())
                else:
                    st.rerun()  # 버튼을 상한 사유와 함께 즉시 비활성으로 다시 그린다
    result = state.quick_result

# ── 3. LLM 에 보낸 입력 / 생성 과정 ──────────────────────────────────────────
if result is None:
    st.info("직접 입력한 노드로 '빠른 실호출' 을 누르면 여기에 생성 과정과 워크시트가 나타납니다.")
else:
    st.subheader("② LLM 에 보낸 입력 → 생성 과정")
    if result.is_gold:
        st.warning(service.provenance_line(result))
    else:
        st.caption(service.provenance_line(result))
    view = service.process_view(result)
    left, right = st.columns(2)
    with left:
        st.markdown("**LLM 에 보낸 입력** — 프롬프트에 채워지는 노드 정보는 이것뿐입니다")
        if result.meta.get("node_text"):
            st.markdown("입력 문장")
            st.code(result.meta["node_text"], language=None, wrap_lines=True)
            st.markdown(f"→ 해석된 NodeMeta ({result.meta.get('parse_model')} 1회 — 설명에 없는 수치는 비워 둠)")
        st.json(result.meta.get("node_meta", {}))
    with right:
        st.markdown("**생성 과정**")
        cells = (
            f"{view['judged_cells']}/{view['expected_cells']}" if view["expected_cells"] is not None else "—"
        )
        st.markdown(
            f"1. **파라미터 열거** ({len(view['parameters'])}개, LLM 이 노드에서 도출): "
            + " · ".join(view["parameters"])
            + f"\n2. **가이드워드 판정** {len(view['guidewords'])}종: {' · '.join(view['guidewords'])}"
            + f"\n3. 판정 셀 **{cells}** · API 호출 "
            + ("—" if view["api_calls"] is None else f"{view['api_calls']}회(재시도 포함)")
            + f" · 절단 {'—' if view['truncated_calls'] is None else view['truncated_calls']}회"
            + f"\n4. 지연 {'—' if view['latency_s'] is None else f'{view["latency_s"]:.0f}초'}"
            + f" · 비용 {'—' if view['cost_usd'] is None else f'${view["cost_usd"]:.3f}'}"
            + f" · verifier review {view['review']}건"
        )

    # ── 4. HAZOP 워크시트 ────────────────────────────────────────────────────
    st.subheader("③ HAZOP 워크시트")
    notice = service.criteria_notice(result)
    if notice:
        st.markdown(f":orange-background[평가기준] {notice}")
    st.markdown(f"**{service.summary_line(result)}**")
    st.dataframe(service.worksheet_table(result), hide_index=True)
    files = service.export_files(result)
    mimes = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "lopa": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "report": "application/json",
    }
    for column, key in zip(st.columns(3), ("xlsx", "lopa", "report"), strict=True):
        name, data = files[key]
        column.download_button(f"⬇ {name}", data, file_name=name, mime=mimes[key])

# ── 5. 평가 결과 (기본 접힘) ─────────────────────────────────────────────────
with st.expander("평가 결과 — 골드셋 대비 recall (n=1)", expanded=False):
    st.caption(
        "NH3 벙커링 4노드만 해당(예시 공정은 골드셋 없음). 하네스 미구현 — `tools/capture_replay.py` 로 "
        f"노드별 1회 실측. 규칙·해석은 [README §6]({README_EVAL})."
    )
    st.table(service.evaluation_table(replays))
