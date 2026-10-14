"""IPL 빈도 크레딧 — 지시문 S-1~S-3 (10/14).

`data/kb/criteria/ipl_credit.json` 이 정본이다(규칙·분류표·출처). 이 모듈은 그 파일을 읽어
① 판정 프롬프트 블록을 만들고 ② 장치 이름을 분류하고 ③ 빈도 산수를 계산한다.
분류는 장치 이름의 낱말로만 한다 — 위에서부터 첫 일치, 없으면 unknown(인정 안 함).
LLM·내보내기 어느 쪽도 임포트하지 않는다(`core/agent/verify.py` 가 이 모듈을 쓴다).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from typing import Any, Final

from core.criteria import CRITERIA_DIR

IPL_PATH: Final = CRITERIA_DIR / "ipl_credit.json"
#: 화면 접두어용 짧은 이름(S-4-2).
CLASS_LABELS: Final[dict[str, str]] = {
    "prevention": "예방", "detection_only": "감지만", "mitigation": "완화", "procedural": "절차", "unknown": "미분류",
}


@dataclass(frozen=True)
class SafeguardClass:
    key: str
    cls: str
    eligible: bool
    reason: str
    applies_to: tuple[str, ...] = ()


@cache
def table() -> dict[str, Any]:
    return json.loads(IPL_PATH.read_text(encoding="utf-8"))


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def classify(name: str) -> SafeguardClass:
    """장치 이름 → 분류. 분류표에 없으면 unknown(ipl_eligible=false) — 자동 인정하지 않는다."""
    key = _norm(name)
    for item in table()["safeguard_classes"]:
        if any(_norm(word) in key for word in item["match"]):
            return SafeguardClass(item["key"], item["class"], bool(item["ipl_eligible"]), item["reason"],
                                  tuple(item.get("applies_to") or ()))
    unknown = table()["unknown"]
    return SafeguardClass("unknown", unknown["class"], bool(unknown["ipl_eligible"]), unknown["reason"])


def expected_frequency(frequency_base: int, credited: int) -> int:
    """frequency = max(min_frequency, frequency_base − min(max_credits, 인정 수))."""
    rules = table()["rules"]
    return max(int(rules["min_frequency"]), frequency_base - min(int(rules["max_credits"]), credited) * int(rules["credit_per_ipl"]))


def same_device(name: str, safeguards: list[str]) -> bool:
    """모델이 적은 장치 이름이 입력 안전장치 중 하나인가 — 공백·대소문자 무시, 한쪽이 다른 쪽을 품으면 같다."""
    key = _norm(name)
    return bool(key) and any(key in _norm(s) or _norm(s) in key for s in safeguards if _norm(s))


def prompt_block(template: str) -> str:
    """판정 시스템 끝에 붙는 IPL 블록 — 규칙 수치·분류표를 파일에서 채운다(하드코딩 금지, S-2-2)."""
    data = table()
    rules = data["rules"]
    lines = []
    for item in data["safeguard_classes"]:
        scope = f" · 적용 이탈: {', '.join(item['applies_to'])}" if item.get("applies_to") else ""
        verdict = "IPL 적격" if item["ipl_eligible"] else "IPL 아님"
        lines.append(f"- {item['label']} — class `{item['class']}` · {verdict}{scope} · {item['reason']}")
    unknown = data["unknown"]
    lines.append(f"- 위 표에 없는 장치 — class `{unknown['class']}` · IPL 아님 · {unknown['reason']}")
    return (
        template.replace("{max_credits}", str(rules["max_credits"]))
        .replace("{min_frequency}", str(rules["min_frequency"]))
        .replace("{credit_per_ipl}", str(rules["credit_per_ipl"]))
        .replace("{severity_note}", rules["severity_note"])
        .replace("{classes}", "\n".join(lines))
        .replace("{notes}", "\n".join(f"- {n}" for n in data["notes"]))
    )


def class_enum() -> list[str]:
    """스키마 `ipl_credited[].class` 허용값 — 분류표의 class 전부 + unknown."""
    data = table()
    return list(dict.fromkeys([*(i["class"] for i in data["safeguard_classes"]), data["unknown"]["class"]]))


__all__ = ["CLASS_LABELS", "IPL_PATH", "SafeguardClass", "class_enum", "classify", "expected_frequency",
           "prompt_block", "same_device", "table"]
