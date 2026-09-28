"""HAZOP 코파일럿 데모 화면 — FR-10 H-02 (PRD v2.0 §5 FR-10, 지시문 H).

위젯 배선만 한다. 로직은 `apps/web/service.py`·`apps/web/replay.py` 에 있다.
실행: `streamlit run apps/web/app.py`
"""

import sys
from pathlib import Path

# 리포 루트를 먼저 sys.path 에 넣는다 — pyproject 가 packages=[] 라 배포 환경엔 core 가 설치되지 않는다.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import contextlib  # noqa: E402
import json  # noqa: E402

import streamlit as st  # noqa: E402

from apps.web import service  # noqa: E402
from apps.web.replay import load_replays  # noqa: E402

MODE_LIVE = "실호출"

st.set_page_config(page_title="HAZOP 코파일럿", layout="wide")

with contextlib.suppress(Exception):  # secrets.toml 이 없으면 Streamlit 이 예외를 던진다
    service.sync_secrets(dict(st.secrets))

replays = st.cache_resource(load_replays)()
MODE_REPLAY = "재생 (캡처 결과)"
live_reason = service.live_block_reason()
state = st.session_state
state.setdefault("live_runs", 0)
state.setdefault("result", None)
state.setdefault("node_json", "")
state.setdefault("preset", "N1")

# ── 상단 ─────────────────────────────────────────────────────────────────────
st.title("HAZOP 위험성평가 코파일럿")
st.markdown(
    "HAZOP(위험과 운전성 분석)은 공정을 노드로 나누고, 각 노드의 파라미터(유량·압력·온도 등)에 "
    "가이드워드(No·More·Less·Reverse·Other than·Part of·As well as)를 붙여 설계 의도에서 벗어난 "
    "**이탈**을 빠짐없이 찾는 방법입니다. 이탈마다 원인·결과·기존 안전장치를 적고 강도(S)×빈도(F)로 "
    "위험도를 매긴 뒤 권고를 냅니다. 이 도구는 LLM 이 가이드워드×파라미터 매트릭스를 판정해 "
    "워크시트 초안을 만들고, 사람은 검토에 집중합니다."
)
st.caption(
    "데이터 출처: NH3 벙커링 QRA 전문가 HAZOP 34건 골드셋(팀 보유). 고객사 실데이터는 쓰지 않았습니다."
)
left, right = st.columns([1, 2])

# ── 좌측: 모드·프리셋·입력 ───────────────────────────────────────────────────
with left:
    mode = st.radio("모드", [MODE_REPLAY, MODE_LIVE], disabled=live_reason is not None)
    if live_reason:
        st.caption(live_reason)
    st.markdown("**NH3 벙커링 프리셋**")
    for node, equipment in service.PRESETS.items():
        captured = replays.get(node)
        clicked_preset = st.button(
            f"{node} {equipment}" + ("" if captured else " (미캡처)"),
            key=f"preset_{node}",
            disabled=captured is None,
            type="primary" if state.preset == node else "secondary",
        )
        if clicked_preset and captured is not None:
            state.preset = node
            state.node_json = json.dumps(captured.meta["node_meta"], ensure_ascii=False, indent=2)
            if mode == MODE_REPLAY:
                state.result = captured
            st.rerun()  # 선택 강조(primary)를 새 프리셋으로 다시 그린다
    replay = replays.get(state.preset) or replays["N1"]  # 실호출 mock 모드의 재생 원천
    st.text_area("NodeMeta (JSON)", key="node_json", height=220, disabled=mode == MODE_REPLAY)

    if mode == MODE_LIVE:
        if service.is_mock():
            st.info("mock 모드 — 네트워크를 쓰지 않고 재생 레코드로 생성 경로를 돕니다.")
        quota = service.quota_block_reason(state.live_runs)
        clicked = st.button(
            "생성 실행", disabled=quota is not None or not state.node_json.strip()
        )
        st.caption(quota or service.LIVE_NOTE)
        if clicked:
            reason = service.reserve_live_run(state.live_runs)
            if reason:
                st.error(reason)
            else:
                state.live_runs += 1
                with st.spinner(f"생성 중… {service.LIVE_NOTE}"):
                    try:
                        state.result = service.run_live(state.node_json, replay)
                    except Exception as exc:  # noqa: BLE001 — 사유를 보이고 앱은 계속 산다
                        st.error(f"생성 실패: {type(exc).__name__}: {exc}")
                    else:
                        st.rerun()  # 버튼을 상한 사유와 함께 즉시 비활성으로 다시 그린다

# ── 우측: 결과 ───────────────────────────────────────────────────────────────
with right:
    result = state.result
    if result is None:
        st.info("왼쪽의 프리셋 버튼을 누르면 결과표가 나타납니다.")
    else:
        source = result.meta.get("source")
        if result.is_gold:
            st.warning("전문가 골드셋 재생 — LLM 생성 결과 아님")
        st.caption(f"source={source} · captured_at={result.meta.get('captured_at')}")
        st.markdown(f"**{service.summary_line(result)}**")
        st.dataframe(service.worksheet_table(result), hide_index=True)
        files = service.export_files(result)
        mimes = {
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "lopa": "text/markdown",
            "report": "application/json",
        }
        for column, key in zip(st.columns(3), ("xlsx", "lopa", "report"), strict=True):
            name, data = files[key]
            column.download_button(f"⬇ {name}", data, file_name=name, mime=mimes[key])

    st.markdown("**평가 요약** — 하네스 미구현, `tools/capture_replay.py` 로 노드별 1회 실측(n=1)")
    st.table(service.evaluation_table(replays))
