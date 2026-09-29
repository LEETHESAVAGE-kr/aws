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
        background-color: #f3ecff; border: 1px solid #c59eff; font-weight: 600; min-height: 52px;
    }
    .st-key-process_name input { font-size: 21px; }  /* 기본 14px 의 1.5배 */
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
st.title("HAZOP 위험성평가 AI 코파일럿")
st.markdown("#### 복잡한 HAZOP 워크시트 초안, 이제 AI가 작성합니다. 전문가는 검토에만 집중하세요.")
st.markdown(
    "사용자가 공정의 기본 정보(물질, 온도, 설비 등)만 입력하면, AI가 스스로 점검 항목(파라미터)을 세우고 "
    "가이드워드마다 발생 가능한 이탈 시나리오를 빠짐없이 판정합니다. 원인과 결과부터 위험도(S×F), "
    "개선 권고사항까지 채워진 HAZOP 워크시트 초안을 자동으로 생성합니다."
)

# ── 2. 공정 선택 ─────────────────────────────────────────────────────────────
st.subheader("① 시나리오 및 공정 선택")
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
    if process["gold"]:
        st.markdown(
            f"{badge} 자체 구축한 전문가 검증 데이터(골드셋)를 기반으로 AI의 분석 정확도를 평가합니다.\n"
            "- **대상 공정**: 액체 암모니아(NH3) 이송 공정 (공급선 → 이송 호스 → 수급선)\n"
            "- **비교 검증**: 전문가가 직접 수행한 34건의 HAZOP 데이터를 기준으로 AI 결과물의 정확도(Recall)를 측정합니다."
        )
    else:
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
    st.subheader("② 최소한의 입력, 압도적인 AI 분석")
    st.markdown("AI는 좌측에 입력된 단편적인 노드 정보만으로도 전문가처럼 사고하고 분석을 확장합니다.")
    if result.is_gold:
        st.warning(service.provenance_line(result))
    else:
        st.caption(service.provenance_line(result))
    view = service.process_view(result)
    node_meta = result.meta.get("node_meta", {})
    left, right = st.columns(2)
    with left:
        kind = "문장" if result.meta.get("node_text") else "JSON"
        st.markdown(
            f"**사용자 입력 ({kind})** — 노드({node_meta.get('node') or '—'}), "
            f"취급 물질({node_meta.get('substance') or '—'}), "
            f"대상 설비({', '.join(node_meta.get('equipment') or []) or '—'}) 등 필수 정보만 입력"
        )
        if result.meta.get("node_text"):
            st.code(result.meta["node_text"], language=None, wrap_lines=True)
            st.markdown(f"→ 해석된 NodeMeta ({result.meta.get('parse_model')} 1회 — 설명에 없는 수치는 비워 둠)")
        st.json(node_meta)
    with right:
        cells = (
            f"{view['judged_cells']}/{view['expected_cells']}" if view["expected_cells"] is not None else "—"
        )
        st.markdown(
            "**AI 자동 분석 과정**\n"
            f"1. **파라미터 자동 도출**: {' · '.join(view['parameters'])} 등 "
            f"**{len(view['parameters'])}개**의 주요 점검 항목을 AI가 스스로 식별합니다.\n"
            f"2. **가이드워드 매핑**: 식별된 항목에 가이드워드 {len(view['guidewords'])}종"
            f"({' · '.join(view['guidewords'])})을 교차 적용해 매트릭스 셀 **{cells}** 을 빠짐없이 판정합니다."
        )

    # ── 4. HAZOP 워크시트 ────────────────────────────────────────────────────
    st.subheader("③ HAZOP 워크시트 초안 완성")
    st.markdown("도출된 위험 시나리오를 바탕으로 검토용 워크시트 초안이 완성됩니다.")
    notice = service.criteria_notice(result)
    if notice:
        st.markdown(f":orange-background[평가기준] {notice}")
    latency = "—" if view["latency_s"] is None else f"{view['latency_s']:.0f}초"
    calls = "—" if view["api_calls"] is None else f"{view['api_calls']}회"
    st.markdown(
        f"- **분석 결과**: 총 {len(result.records)}건의 위험성 평가 레코드 도출\n"
        f"- **정확도(Recall)**: {service.accuracy_line(result, replays)}\n"
        f"- **운영 지표**: 총 {cells} 셀 판정 완료 (소요 시간: {latency} / API 호출 {calls})"
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

    st.markdown(
        "💡 **참고사항 (데이터 보안 및 운영 환경)**\n"
        "- **데이터 보안**: 고객사의 실제 데이터는 일체 사용하지 않으며, 팀이 자체 보유한 데이터로만 작동합니다.\n"
        f"- **시스템 정보**: {service.system_note(result)}"
    )

# ── 5. 평가 결과 (기본 접힘) ─────────────────────────────────────────────────
with st.expander("평가 결과 — 골드셋 대비 recall (n=1)", expanded=False):
    st.caption(
        "NH3 벙커링 4노드만 해당(예시 공정은 골드셋 없음). 하네스 미구현 — `tools/capture_replay.py` 로 "
        f"노드별 1회 실측. 규칙·해석은 [README §6]({README_EVAL})."
    )
    st.table(service.evaluation_table(replays))
