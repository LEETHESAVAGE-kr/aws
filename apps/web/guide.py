"""'HAZOP 이 처음이라면' 안내 내용(10/8 사용자 요청 — 처음 보는 사람도 이해하게). 화면 배선은 `app.py`.

정의는 새로 쓰지 않고 이미 쓰는 것을 읽는다(가이드워드 뜻만 예외 — 10/15 교열로 화면 문구를 따로 둔다. 프롬프트는 `GUIDEWORD_DEFINITIONS`),
S·F 등급과 위험도는 평가기준 라이브러리(`core.criteria`, `data/kb/criteria/` — Y-2), 신뢰도 배지는 내보내기의 사유 표.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from core.agent.generate import PROCEDURAL_GUIDEWORDS, STANDARD_GUIDEWORDS
from core.criteria import GOLD_CRITERIA
from core.policy import load_policy

if TYPE_CHECKING:
    from core.criteria import Criteria

#: 워크시트 한 줄이 만들어지는 과정 — (단계, 설명, 예시 값). 예시는 설명용이다(실제 생성 결과 아님). 문구는 10/15 사용자 교열본.
WORKED_EXAMPLE: Final[tuple[tuple[str, str, str], ...]] = (
    ("노드", "분석 구간 한 토막", "압축기 → 고압 저장용기 배관"),
    ("파라미터", "변수", "압력"),
    ("가이드워드", "이탈 방향", "More"),
    ("이탈 상태", "파라미터 × 가이드워드", "압력이 설계 압력을 넘는다"),
    ("원인", "왜 그렇게 되나", "압축기 토출 제어 고장"),
    ("결과", "그러면 무슨 일이 생기나", "배관 파열 → 폭발"),
    ("기존 안전장치", "지금 이미 있는 대책", "안전밸브"),
    ("위험도", "심각도와 빈도를 KOSHA C-C-37 대조표로 조합",
     "심각도 4(치명적) · 빈도 2(중) → 위험도 5 → 위험작업 불허"),
    ("권고 사항", "무엇을 더 해야 하나", "인터록 추가"),
)

#: 가이드워드 뜻(화면용, 10/15 사용자 교열본)과 쉬운 예. 생성 프롬프트는 `GUIDEWORD_DEFINITIONS` 그대로 쓴다 —
#: 프롬프트 문구를 바꾸면 생성 결과가 달라지므로 화면 설명만 실무 표현으로 다듬었다.
GUIDEWORD_MEANINGS: Final[dict[str, str]] = {
    "No": "유량이나 압력 등이 완전히 상실됨 (예: 흐름 차단)",
    "More": "유량, 압력, 온도 등이 설계 기준을 초과하여 증가함",
    "Less": "유량, 압력, 온도 등이 설계 기준에 미치지 못하고 감소함",
    "Reverse": "유체의 흐름 방향이 역전됨 (역류)",
    "Other than": "완전히 다른 물질 유입이나 잘못된 상태 발생",
    "Part of": "조성 비율 저하 또는 불완전한 충족 (예: 성분 누락)",
    "As well as": "불순물 혼입 등 의도치 않은 현상 추가 발생",
}
GUIDEWORD_EXAMPLES: Final[dict[str, str]] = {
    "No": "유량 없음 (닫혀서 흐르지 않음)",
    "More": "압력 과다 (설계 초과)",
    "Less": "온도 과소 (얼거나 취성 파괴)",
    "Reverse": "역류 (거꾸로 밀려옴)",
    "Other than": "다른 물질 (질소 대신 공기 유입)",
    "Part of": "조성 일부 (정해진 농도보다 묽음)",
    "As well as": "이물 혼입 (수분, 산 섞임)",
}

#: ⓪ 입력 방식별 사용법 — (이름, 순서). 이름은 app.py 의 INPUT_* · MODE_CASES 와 같다. 버튼 이름은 화면 그대로.
HOW_TO: Final[tuple[tuple[str, str], ...]] = (
    ("문장으로 설명", "새로 만들기 → '문장으로 설명' → 공정 예시(수소충전소 등) 클릭 후 내용 수정 → 'HAZOP 초안 생성' → "
     "부족한 정보(압력, 설정값 등)를 묻는 '입력 확인' 상자에 아는 값을 채워 최종 생성."),
    ("항목 선택", "새로 만들기 → '항목 선택' → 물질·설비(필수) 및 아는 값 입력 → 'HAZOP 초안 생성' (문장 해석 단계가 없어 더 빠름)."),
    ("사례 보기", "'완성된 사례 보기'에서 저장된 결과를 열람. 하단 'AI가 한 일' 탭에서 분석 로직, 호출 수, 비용 등을 확인할 수 있습니다."),
)

#: ④ 화면 읽는 법 (검토 기능 및 AI 신뢰도) — (표시, 뜻). 10/15 사용자 교열본.
READING_GUIDE: Final[tuple[tuple[str, str], ...]] = (
    ("판정한 칸 84/84", f"파라미터(12개) × 가이드워드({len(STANDARD_GUIDEWORDS)}종) = 84칸을 빈틈없이 검토했다는 뜻입니다. "
     "(내용이 100% 맞다는 의미가 아니므로, 정확도는 '이 앱을 다른 팀의 HAZOP과 대조하면' 패널에서 확인 필요)"),
    ("근거 표시 (G/S/I/U)", "G(입력 그대로), S(문헌 원문 인용), I(일반 물리적 추론), U(확인 필요/추론 금지)"),
    ("🟢 문서 2건 이상 인용 / 🔵 문서 1건 인용", "서로 다른 공식 문서 2건 이상 / 공식 문서 1건의 원문과 일치"),
    ("🟡 추론 / ⚪ 정보 부족", "인용 없이 AI가 논리적으로 추론한 항목 / 현장 데이터가 없어 판단을 보류함"),
    ("🔴 검토 필요", "문서 수치, 규격 번호 검증 실패로 사람의 직접 확인 필수"),
    ("검토 열", "행마다 채택/기각을 고르고 내용을 수정할 수 있습니다. 수정한 내역은 다운로드 시 Excel의 '검토 기록' 시트에 모두 남습니다."),
    ("보기 전환", "워크시트 기본 순서, 가이드워드별, 파라미터별로 뷰를 전환해 볼 수 있습니다. (다운로드 파일 내용은 동일)"),
)

#: 공정안전보고서 — 왜 중요한가(10/10 법령 원문 확인, law.go.kr). 숫자 통계는 원자료 미확인이라 넣지 않는다.
PSM_WHY: Final[tuple[tuple[str, str], ...]] = (
    ("가동의 전제", "유해·위험 설비는 정부로부터 '적합' 통보를 받기 전에는 가동할 수 없다(산업안전보건법 제44조)."),
    ("대상", "원유 정제·석유화학 등 7개 업종, 또는 지정 유해·위험물질을 규정량 이상 다루는 사업장(시행령 제43조)."),
    ("목적", "화재·폭발·독성물질 누출처럼 한 번에 여러 사람과 주변 지역까지 피해가 번지는 중대산업사고 예방."),
)
#: Q-06-4 법령 KB 범위 — 선박·항만 공정에는 별도 규칙이 적용된다.
SCOPE_NOTE: Final[str] = (
    "예외 적용: 선박 및 항만 공정(암모니아 벙커링 등)의 경우 산업안전보건법 외에 IMO IGF Code와 선급 규칙이 별도로 적용됩니다. 이 앱이 참조하는 자료는 "
    "산업안전보건법·고압가스 안전관리법·액화석유가스의 안전관리 및 사업법과 MSDS까지입니다."
)
#: 보고서가 쓰이는 흐름 — (단계, 내용, 조문).
PSM_FLOW: Final[tuple[tuple[str, str, str], ...]] = (
    ("① 작성", "설비를 가동하기 전에 사업주가 작성 — 산업안전보건위원회 심의(없으면 근로자대표 의견)", "법 제44조"),
    ("② 제출·심사", "고용노동부에 제출 → 기준에 따라 심사, 필요하면 변경 명령", "법 제45조"),
    ("③ 가동", "적합 통보를 받아야 설비를 가동할 수 있다", "법 제44조"),
    ("④ 비치·준수", "심사받은 보고서를 사업장에 두고 사업주·근로자가 그 내용을 지킨다", "법 제45·46조"),
    ("⑤ 변경·평가", "공정이 바뀌면 지체 없이 보완 · 정부가 이행 상태를 정기 평가, 미이행 시 재제출 명령", "법 제46조"),
)


def psm_flow_rows() -> list[dict[str, str]]:
    return [{"단계": s, "내용": c, "근거": law} for s, c, law in PSM_FLOW]


#: 가이드워드 수 — 화면 어디서나 이 상수에서(Q-05-1). 7 인지 10 인지는 코드가 답한다.
GUIDEWORD_COUNT: Final[str] = f"표준 {len(STANDARD_GUIDEWORDS)}종(절차 노드는 {len(PROCEDURAL_GUIDEWORDS)}종 추가)"
GUIDEWORD_TAB: Final[str] = f"② 가이드워드 ({len(STANDARD_GUIDEWORDS)}+{len(PROCEDURAL_GUIDEWORDS)}종)"
#: 첫 화면 아래 안내 탭 — 순서대로. 열린 탭만 그리므로(1-B) 시험은 이 이름으로 탭을 하나씩 연다.
GUIDE_TABS: Final[tuple[str, ...]] = (
    "⓪ 입력 방식별 사용법", "① 워크시트 한 줄이 만들어지는 과정", GUIDEWORD_TAB, "③ 위험도 산정 기준 (심각도 × 빈도)",
    "④ 화면 읽는 법 (검토 기능 및 AI 신뢰도)", "⑤ 기존 회의 vs 앱 도입 후 비교", "⑥ 공정안전보고서(PSM)와 HAZOP",
)
#: 안내 탭의 위젯 키 — 열린 탭 이름이 이 키의 상태에 있다.
GUIDE_TAB_KEY: Final[str] = "guide_tab"


def process_table(param_range: tuple[int, int] | None) -> str:
    """'회의와 비교' 표 — 노드당 파라미터 수는 저장된 실호출 결과의 최소~최대(Q-05-2). 없으면 범위를 적지 않는다."""
    params = f"노드당 {param_range[0]}~{param_range[1]}개(저장된 생성 결과 기준)" if param_range else "노드마다 다름"
    return PROCESS_TABLE.replace("{params}", params)


PROCESS_TABLE: Final[str] = (
    "| 단계 | 기존 회의 | 앱 도입 후 |\n|---|---|---|\n"
    "| 노드 정의 | 사람 (P&ID 도면을 보고 구간을 나눔) | 사람 (입력 — 문장 한 문단 또는 JSON) |\n"
    "| 파라미터 도출 | 브레인스토밍 | AI 자동 도출 — 1회 호출, {params} |\n"
    "| 모든 칸 판정 | 수기 토론, 누락 발생 | AI 가이드워드 동시 판정 (누락 0) |\n"
    "| 초안 및 문서화 | 서기가 회의 중 기록 후 수일 소요 | 신뢰도 지표 포함 즉시 다운로드 (Excel, Word 등 — LOPA 본 분석은 전문가) |\n"
    "| 최종 검토/승인 | 회의 참석자 | **사람** (본 앱은 사람의 최종 결정을 대체하지 않습니다.) |"
)


#: 지시문 S-4-5 — ③ 위험도 탭 끝 3줄. 규칙·분류는 data/kb/criteria/ipl_credit.json(KOSHA C-C-62-2026 독립방호계층 정의).
IPL_LINES: Final[tuple[str, ...]] = (
    "빈도 (1~3단계, 안전조치 고려 기준): 독립방호계층(IPL)으로 인정되는 장치 1개당 빈도 1등급 하향 (최대 2등급까지, "
    "가장 낮은 등급은 1 — 방호계층분석(LOPA) 원칙, KOSHA C-C-62-2026).",
    "단순 감지기나 완화 장치(방류벽·살수), 절차·교육은 빈도 완화에 불인정 (감지기라도 차단과 연동되면 인정). "
    "심각도에는 안전장치를 반영하지 않습니다.",
    "AI는 장치 인정 조건 및 빈도 계산(기본 빈도 − 인정 장치 수)이 맞는지 자동 검사하며, 오류 시 🔴로 표시합니다.",
)


def md_safe(text: str) -> str:
    """마크다운(st.caption·markdown)에서 '~' 두 개가 취소선이 되지 않게 이스케이프한다(10/15 '75~76쪽 (인쇄 61~62쪽)')."""
    return text.replace("~", "\\~")


def criteria_caption(criteria: Criteria) -> str:
    """기준 한 줄 설명 — 단계 수·산정 방식·출처(Y-2). 단계 수는 원문 그대로라 기준마다 다르다. 마크다운으로 그리면 `md_safe`."""
    how = "곱한 값" if criteria.method == "product" else "대조표에서 찾은 값(곱이 아님)"
    src = criteria.data.get("locator") or ""
    if criteria.id == GOLD_CRITERIA:  # 팀 사업장 기준 — 내부 워크시트 이름은 화면에 쓰지 않는다(Q-02)
        return (f"심각도 {criteria.s_max}단계 · 빈도 {criteria.f_max}단계 — 위험도는 심각도·빈도를 {how}. "
                "출처: 팀이 NH3 선박 벙커링 사업장을 평가할 때 쓴 기준표(공식 기준 아님). 2026년 10월 14일 이전에 저장한 사례 일부가 이 기준을 따릅니다.")
    return (f"심각도 {criteria.s_max}단계 · 빈도 {criteria.f_max}단계 — 위험도는 심각도·빈도를 {how}. "
            f"출처: {criteria.data.get('issuer')} {criteria.data.get('doc')} {src}".strip())


def criteria_rating_rows(criteria: Criteria) -> list[dict[str, object]]:
    """S·F 등급을 한 표로 — 단계 수가 다르면 짧은 쪽은 빈칸."""
    sev = {int(i["grade"]): i for i in criteria.data["severity"]}
    freq = {int(i["grade"]): i for i in criteria.data["frequency"]}

    def text(item: dict[str, Any] | None) -> str:
        if item is None:
            return ""
        return f"{item['label']} — {item['definition']}" if item.get("label") else str(item["definition"])

    return [
        {"등급": g, "심각도 — 사고가 나면 피해가 얼마나 큰가": text(sev.get(g)),
         "빈도 — 얼마나 자주 일어날 수 있나": text(freq.get(g))}
        for g in range(max(criteria.s_max, criteria.f_max), 0, -1)
    ]


def criteria_matrix_rows(criteria: Criteria) -> list[dict[str, object]]:
    """위험도 대조표(행 S 높은 순, 열 F) — 곱 기준도 같은 모양으로 보여 준다."""
    return [
        {"심각도＼빈도": f"심각도 {s}", **{f"빈도 {f}": criteria.risk(s, f) for f in range(1, criteria.f_max + 1)}}
        for s in range(criteria.s_max, 0, -1)
    ]


def criteria_band_rows(criteria: Criteria) -> list[dict[str, str]]:
    return [
        {"위험도": b["range"], "판정": b["judgement"], "조치": str(b["action"]).split(" — ")[0]}
        for b in criteria.data["risk_bands"]
    ]


def information_level_rows() -> list[dict[str, str]]:
    """정보 4단계(Z-1) — `data/kb/inference_policy.json` 문구 그대로(프롬프트와 같은 말)."""
    return [
        {"단계": f"{lv['code']} {lv['name']}", "표시": lv["badge"], "뜻": lv["definition"], "AI 는": lv["rule"], "예": lv["example"]}
        for lv in load_policy()["levels"]
    ]


def guideword_rows() -> list[dict[str, str]]:
    return [
        {"가이드워드": g, "뜻": GUIDEWORD_MEANINGS[g], "예 (파라미터와 붙였을 때)": GUIDEWORD_EXAMPLES[g]}
        for g in STANDARD_GUIDEWORDS
    ]
