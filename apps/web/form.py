"""'골라서 입력' 양식(10/9 사용자 요청 — 서술형 말고 클릭으로도). 화면 배선은 `app.py`.

양식 값 → NodeMeta JSON 문자열. JSON 은 `service.parse_node_text` 가 API 를 부르지 않고 스키마로만 검증하므로
문장 해석 호출(1회)이 빠지고, 해석 모델이 값을 잘못 옮길 일도 없다. 압력 환산은 문장 경로와 같은 표(`PRESSURE_TO_KPA`).
"""

from __future__ import annotations

import json
from typing import Any, Final

from .service import PRESSURE_TO_KPA

#: 물질 — 근거 코퍼스에 MSDS 가 있는 20종(`data/kb/msds/`)을 쓰는 이름으로. 목록에 없으면 직접 적는다.
SUBSTANCES: Final[tuple[str, ...]] = (
    "수소", "LPG(프로판)", "부탄", "메탄(LNG)", "메탄올", "암모니아", "염소", "실란", "염화수소", "황화수소",
    "황산", "차아염소산나트륨", "톨루엔", "벤젠", "에틸렌", "아세틸렌", "일산화탄소", "산소", "질소",
)
PHASES: Final[dict[str, str]] = {"기체": "gas", "액체": "liquid", "기체·액체 함께": "liquid/gas", "모름": "unknown"}
EQUIPMENT: Final[tuple[str, ...]] = (
    "저장탱크", "고압 저장용기", "튜브트레일러", "탱크로리", "실린더", "가스 캐비닛",
    "압축기", "펌프", "하역 펌프", "기화기", "열교환기", "감압밸브", "반응기",
    "배관", "호스", "로딩암", "디스펜서", "충전 작업 절차", "하역 작업 절차",
)
SAFEGUARDS: Final[tuple[str, ...]] = (
    "안전밸브", "긴급차단밸브", "가스누출감지기", "가스누출경보기", "압력계", "고압 경보", "압력 고고 인터록",
    "과류차단밸브", "체크밸브", "브레이크어웨이 커플링", "방유제", "질소 블랭킷", "브리더밸브", "캐비닛 배기",
    "살수설비", "접지",
)
UNITS: Final[tuple[str, ...]] = tuple(PRESSURE_TO_KPA)

#: 양식 위젯 키 — 예시 버튼이 같은 키에 값을 넣는다.
KEYS: Final[dict[str, str]] = {
    "substance": "f_substance", "phase": "f_phase", "equipment": "f_equipment",
    "pressure": "f_pressure", "pressure_unit": "f_pressure_unit", "temperature": "f_temperature",
    "design_pressure": "f_design_pressure", "design_unit": "f_design_unit", "capacity": "f_capacity",
    "safeguards": "f_safeguards", "no_safeguards": "f_no_safeguards",
}
EMPTY: Final[dict[str, Any]] = {
    "substance": None, "phase": "모름", "equipment": [], "pressure": None, "pressure_unit": "MPa",
    "temperature": None, "design_pressure": None, "design_unit": "MPa", "capacity": "",
    "safeguards": [], "no_safeguards": False,
}

#: 예시 버튼이 채우는 값 — 문장 예시(`app.EXAMPLES`)와 같은 공정. 문장에 없던 설계압력·용량·설정값을 더 채웠다
#: (골라서 입력의 장점: 추론 경계가 '미상'으로 보류하던 정보를 칸으로 받는다). 값은 설명용 예시다(실제 설비 아님).
EXAMPLES: Final[dict[str, dict[str, Any]]] = {
    "수소충전소": {
        "substance": "수소", "phase": "기체", "equipment": ["튜브트레일러", "압축기", "고압 저장용기", "디스펜서"],
        "pressure": 90.0, "pressure_unit": "MPa", "design_pressure": 100.0, "design_unit": "MPa", "capacity": "200 kg",
        "safeguards": ["안전밸브", "긴급차단밸브", "가스누출감지기", "고압 경보(설정 95 MPa)"],
    },
    "메탄올 하역": {
        "substance": "메탄올", "phase": "액체", "equipment": ["탱크로리", "하역 펌프", "저장탱크"],
        "pressure_unit": "kPa", "temperature": 30.0, "capacity": "50 m³",
        "safeguards": ["질소 블랭킷", "브리더밸브", "가스누출감지기", "긴급차단밸브", "방유제"],
    },
    "실란 가스 캐비닛": {
        "substance": "실란", "phase": "기체", "equipment": ["실린더", "가스 캐비닛", "감압밸브", "배관"],
        "pressure": 0.5, "pressure_unit": "MPa", "capacity": "47 L 실린더",
        "safeguards": ["캐비닛 배기", "가스누출감지기", "과류차단밸브", "긴급차단밸브"],
    },
}


def example_state(name: str) -> dict[str, Any]:
    """예시 → 위젯 키별 값(빈 양식 위에 덮는다 — 이전 예시 값이 남지 않게)."""
    values = {**EMPTY, **EXAMPLES[name]}
    return {KEYS[k]: v for k, v in values.items()}


def _kpa(value: float | None, unit: str) -> float | None:
    return None if value is None else round(float(value) * PRESSURE_TO_KPA[unit], 3)


def missing_fields(values: dict[str, Any]) -> list[str]:
    """생성 버튼을 막는 빈 칸 — 물질과 설비 1개 이상은 있어야 노드가 된다."""
    out = []
    if not (values.get("substance") or "").strip():
        out.append("물질")
    if not values.get("equipment"):
        out.append("설비")
    return out


def to_node_json(values: dict[str, Any]) -> str:
    """양식 값(EMPTY 와 같은 키) → NodeMeta JSON. '안전장치 없음'을 고르면 '없음'(G)으로, 비워 두면 '모름'(U)으로 간다."""
    no_safeguards = bool(values.get("no_safeguards"))
    payload: dict[str, Any] = {
        "node": "X1",
        "substance": (values.get("substance") or "").strip() or "미상",
        "phase": PHASES.get(values.get("phase") or "모름", "unknown"),
        "P_kPag": _kpa(values.get("pressure"), values.get("pressure_unit") or "MPa"),
        "T_degC": values.get("temperature"),
        "equipment": [str(e).strip() for e in values.get("equipment") or [] if str(e).strip()],
        "safeguards": [] if no_safeguards else [str(s).strip() for s in values.get("safeguards") or [] if str(s).strip()],
    }
    design = _kpa(values.get("design_pressure"), values.get("design_unit") or "MPa")
    if design is not None:
        payload["design_P_kPag"] = design
    if (values.get("capacity") or "").strip():
        payload["capacity"] = values["capacity"].strip()
    if no_safeguards:
        payload["safeguards_known"] = True
    return json.dumps(payload, ensure_ascii=False)


__all__ = ["EMPTY", "EQUIPMENT", "EXAMPLES", "KEYS", "PHASES", "SAFEGUARDS", "SUBSTANCES", "UNITS",
           "example_state", "missing_fields", "to_node_json"]
