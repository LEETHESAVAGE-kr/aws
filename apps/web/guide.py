"""'HAZOP 이 처음이라면' 안내 내용(10/8 사용자 요청 — 처음 보는 사람도 이해하게). 화면 배선은 `app.py`.

정의는 새로 쓰지 않고 이미 쓰는 것을 읽는다: 가이드워드 뜻은 생성 프롬프트가 쓰는 `GUIDEWORD_DEFINITIONS`,
S·F 등급과 위험도는 평가기준 라이브러리(`core.criteria`, `data/kb/criteria/` — Y-2), 신뢰도 배지는 내보내기의 사유 표.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from core.agent.generate import GUIDEWORD_DEFINITIONS, STANDARD_GUIDEWORDS
from core.policy import load_policy

if TYPE_CHECKING:
    from core.criteria import Criteria

#: 한 줄이 만들어지는 순서 — (단계, 무엇을 묻나, 예시 값). 예시는 설명용이다(실제 생성 결과 아님).
WORKED_EXAMPLE: Final[tuple[tuple[str, str, str], ...]] = (
    ("노드", "어느 구간을 보나 — 배관·설비를 몇 구간으로 나눈 한 토막", "수소충전소: 압축기 → 고압 저장용기 배관"),
    ("파라미터", "그 구간에서 무엇이 변할 수 있나 — 유량·압력·온도·준위·조성…", "압력"),
    ("가이드워드", "어느 방향으로 벗어나나 — No·More·Less… (아래 탭)", "More (정량적 증가)"),
    ("이탈", "파라미터 × 가이드워드 = '설계 의도에서 벗어난 상태'", "배관·용기 압력이 설계 압력을 넘는다"),
    ("원인", "왜 그렇게 되나", "압축기 토출 제어 고장 · 저장용기 출구 밸브 닫힘"),
    ("결과", "그러면 무슨 일이 생기나", "용기·배관 파열 → 수소 누출 · 화재·폭발"),
    ("기존 안전장치", "지금 이미 있는 대책은", "안전밸브 · 긴급차단밸브"),
    ("심각도 · 빈도 → 위험도", "얼마나 심각하고(심각도) 얼마나 자주(빈도) — 공식 대조표(KOSHA C-C-37)로 조합해 우선순위",
     "심각도 4(치명적) · 빈도 2(중) → 위험도 5 → 위험작업 불허"),
    ("권고", "무엇을 더 해야 하나", "고압 연동 정지(인터록) 추가 · 안전밸브 정기 시험"),
)

#: 가이드워드별 쉬운 예 — 뜻은 GUIDEWORD_DEFINITIONS(생성 프롬프트와 같은 문구).
GUIDEWORD_EXAMPLES: Final[dict[str, str]] = {
    "No": "유량 없음 — 밸브가 닫혀 흐르지 않음",
    "More": "압력 과다 — 설계 압력 초과",
    "Less": "온도 과소 — 너무 차가워져 배관이 얼거나 취성 파괴",
    "Reverse": "역류 — 받는 쪽에서 거꾸로 밀려 들어옴",
    "Other than": "다른 물질 — 질소 대신 공기가 들어감",
    "Part of": "조성 일부 — 정해진 농도보다 묽음",
    "As well as": "이물 혼입 — 수분·산이 함께 섞임",
}

#: 앱 사용법 — 정보 넣기 두 방법 + 모르겠으면 예시 보기(PRD 첫화면 U-8, 10/9 사용자 정정). 이름은 app.py 의 MODE_* · INPUT_* 와 같다.
HOW_TO: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("문장으로 설명", (
        "'새로 만들기' → 입력 방식 '문장으로 설명'",
        "공정 예시(수소충전소 등)를 누르면 예시 문장이 채워집니다 — 물질·설비·압력·안전장치를 고쳐 쓰세요",
        "'HAZOP 초안 생성' → 약 1.5–2분 뒤 아래 '분석 결과'에 표가 나옵니다",
    )),
    ("항목 선택", (
        "'새로 만들기' → 입력 방식 '항목 선택'",
        "물질·설비(필수)를 고르고, 아는 값(압력·온도·설계압력·용량·안전장치)만 채웁니다 — 목록에 없으면 직접 입력",
        "'HAZOP 초안 생성' — 문장 해석 단계가 없어 몇 초 빠릅니다",
    )),
    ("무엇을 넣을지 모르겠다면 — 완성된 사례 보기", (
        "'완성된 사례 보기' → 공정을 고릅니다",
        "'공정 전체 보기' 또는 노드 버튼을 누르면 저장된 실제 결과가 바로 열립니다(새로 생성하지 않음)",
        "결과 아래 'AI 가 한 일' 탭에서 AI 가 세운 점검 항목·호출 수·시간·비용을 봅니다",
    )),
)

#: 결과 화면 읽는 법 — (표시, 뜻).
READING_GUIDE: Final[tuple[tuple[str, str], ...]] = (
    ("판정 셀 84/84 (누락 0)", "파라미터 12개 × 가이드워드 7종 = 84칸을 모두 판정했다는 뜻. '해당 없음'으로 판정한 칸도 "
     "센다 — 표에는 해당하는 칸만 행으로 나온다. 회의에서는 지쳐서 칸을 건너뛰는 일이 생기는데, 여기서는 빈칸이 있으면 숫자가 어긋난다."),
    ("🟢 문서 2건 이상 인용", "서로 다른 공식 문서(법령·고시·MSDS) 2건 이상의 원문 구절을 인용했고 규칙 검증을 통과한 행"),
    ("🔵 문서 1건 인용", "공식 문서 1건의 원문 구절을 인용했고 규칙 검증을 통과한 행"),
    ("🟡 추론", "인용 없이 모델이 추론한 행"),
    ("🔴 검토 필요", "형식 검증 실패, 근거 없는 규격 번호·수치, 또는 원문과 한 글자라도 다른 인용이 있어 사람이 꼭 봐야 하는 행. "
     "문서가 인용됐다는 것은 '공식 문서가 같은 위험을 다룬다'는 뜻이지 내용이 맞다는 보증이 아니다"),
    ("⚪ 정보 부족", "입력에도 공식 문서에도 없는 사업장 정보(인터록 설정값, 입력에 없는 안전장치의 유무 등)가 있어야 판단할 수 있어 "
     "심각도·빈도를 매기지 않고 보류한 행. 무엇이 없는지 함께 적는다 — 모르는 것을 메우느니 덜 쓰는 편이 낫다는 원칙(추론 경계를 켠 실행에서만)"),
    ("검토 열", "행마다 채택·기각을 고르고 원인·결과·권고·심각도·빈도를 고친다. 다운로드 Excel 에 그대로 반영되고 '검토 기록' 시트가 붙는다"),
    ("보기 전환", "워크시트 순서(공정 순서 — 파라미터마다 No·More·Less… 가 붙어 나온다, Excel No 와 같다) · 가이드워드별(예: More 만 모아 보기) · 파라미터별(예: 압력만 모아 보기). "
     "보는 순서만 바뀌고 내용·다운로드는 같다"),
)

PROCESS_TABLE: Final[str] = (
    "| 단계 | 기존 HAZOP 회의 | 이 앱 |\n|---|---|---|\n"
    "| 노드 정의 | 사람 (P&ID 도면을 보고 구간을 나눔) | 사람 — 문장 한 문단 또는 JSON |\n"
    "| 파라미터 도출 | 팀 브레인스토밍 | AI 1회 호출, 노드당 8–12개 |\n"
    "| 가이드워드 전 셀 판정 | 셀마다 토론, 지치면 건너뛰는 칸이 생김 | AI 가 가이드워드별로 동시에 판정, 셀 누락 0 |\n"
    "| 원인·결과·안전장치·심각도·빈도·권고 | 서기가 회의 중 기록 | 초안 자동, 신뢰도 배지 + 규칙 검증기 |\n"
    "| 워크시트·LOPA 문서화 | 회의 후 수일 | 즉시 xlsx(5시트)·LOPA docx·신뢰도 JSON |\n"
    "| 검토·승인 | 회의 참석자 | **사람** — 이 앱은 이 단계를 대신하지 않는다 |"
)


def criteria_caption(criteria: Criteria) -> str:
    """기준 한 줄 설명 — 단계 수·산정 방식·출처(Y-2). 단계 수는 원문 그대로라 기준마다 다르다."""
    how = "곱한 값" if criteria.method == "product" else "대조표에서 찾은 값(곱이 아님)"
    src = criteria.data.get("locator") or ""
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
        {"등급": g, "심각도 — 사고가 나면 얼마나 나쁜가": text(sev.get(g)),
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
        {"가이드워드": g, "뜻": GUIDEWORD_DEFINITIONS[g], "예 (파라미터와 붙였을 때)": GUIDEWORD_EXAMPLES[g]}
        for g in STANDARD_GUIDEWORDS
    ]
