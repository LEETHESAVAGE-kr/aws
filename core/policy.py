"""추론 경계 정책 — PRD_본선_추론경계_Kiro연동 Z-1(정보 4단계)·Z-2(노드 유형별 경계표).

정본은 `data/kb/inference_policy.json` 하나다. 판정·열거 프롬프트와 화면 안내가 모두 이 파일의 문구를
그대로 쓴다(같은 말 — Z-G1). 노드 유형은 설비 이름·노드 이름의 키워드로 고르고, 여러 유형에 걸리면
모두 적용한다. 공통 행은 항상 붙는다. LLM·내보내기 어느 쪽도 임포트하지 않는다.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
POLICY_PATH: Final[Path] = _ROOT / "data" / "kb" / "inference_policy.json"


@cache
def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def node_types(node: str, equipment: Iterable[str]) -> list[dict[str, Any]]:
    """키워드가 걸린 노드 유형(정책 파일 순서) + 공통 행(항상 마지막)."""
    policy = load_policy()
    text = " ".join([node, *equipment]).lower()
    hits = [t for t in policy["node_types"] if any(k.lower() in text for k in t["keywords"])]
    return [*hits, policy["common"]]


def levels_text() -> str:
    """정보 4단계 — 프롬프트·화면 공통 문구."""
    return "\n".join(
        f"- {lv['code']} {lv['name']}({lv['badge']}): {lv['definition']} — {lv['rule']}. 예: {lv['example']}"
        for lv in load_policy()["levels"]
    )


def judge_system_block() -> str:
    """판정 시스템 프롬프트 꼬리. 노드와 무관한 고정 문구라 시스템 블록 캐시를 깨지 않는다."""
    return "\n".join(load_policy()["prompt"]["judge_system"]).replace("{levels}", levels_text())


def node_block(node: str, equipment: Iterable[str]) -> str:
    """판정 사용자 턴에 붙는 이 노드의 경계표(Z-2) — 걸린 유형만."""
    types = node_types(node, equipment)
    lines = [load_policy()["prompt"]["node_block_header"].replace("{types}", ", ".join(t["label"] for t in types))]
    for t in types:
        lines += [
            "",
            f"[{t['label']}]",
            f"- 추론해도 되는 것(I): {' · '.join(t['infer'])}",
            f"- 추론 금지(U) — 입력에 없으면 보류하고 missing 에: {' · '.join(t['unknown'])}",
        ]
    return "\n".join(lines)


def safeguards_text(safeguards: list[str], known: bool) -> str:
    """'기존 안전장치' 칸. 비어 있으면 '없음'(사용자가 명시)과 '미상'(입력에 없음)을 가른다."""
    if safeguards:
        return ", ".join(safeguards)
    prompt = load_policy()["prompt"]
    return prompt["safeguards_none"] if known else prompt["safeguards_unknown"]


def enumerate_rule(system: str) -> str:
    """열거 프롬프트의 "부족하다고 적지도 마라" 줄을 보류 규칙으로 바꾼다(PRD §7 — Z 와 정면 충돌)."""
    prompt = load_policy()["prompt"]
    if prompt["enumerate_rule_original"] not in system:
        raise ValueError("열거 프롬프트에서 바꿀 줄을 찾지 못했다 — matrix_enumerate.md 와 정책 파일을 맞출 것")
    return system.replace(prompt["enumerate_rule_original"], prompt["enumerate_rule"])


__all__ = [
    "POLICY_PATH",
    "enumerate_rule",
    "judge_system_block",
    "levels_text",
    "load_policy",
    "node_block",
    "node_types",
    "safeguards_text",
]
