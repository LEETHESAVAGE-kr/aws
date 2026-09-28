"""노드 recall 규칙 — spec:hazop-generation T-08 / FR-10 H-01 (I-1 에서 노드 일반화).

`tests/test_generate.py` 와 `tools/capture_replay.py` 가 같은 함수를 쓰도록 여기로 옮겼다
(테스트 모듈은 배포본에 없으므로 도구가 시험 코드를 import 할 수 없다). 규칙은 T-08 문면 그대로다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

#: 파라미터 정규화에서 떼는 조사 (T-08 문면: "공백·조사 제거"). 긴 것부터 떼야 "으로"가 "로"로 잘리지 않는다.
PARTICLES = ("으로", "에서", "이나", "과", "와", "은", "는", "이", "가", "을", "를", "의", "에", "로")


def normalize_parameter(text: str) -> str:
    """공백 제거 후 말미 조사 1개 제거. T-08 이 정한 매칭 규칙 그대로 — 여기서 넓히지 않는다."""
    compact = "".join(text.split())
    for particle in PARTICLES:
        if len(compact) > len(particle) + 1 and compact.endswith(particle):
            return compact[: -len(particle)]
    return compact


def recall_for_node(generated: Iterable[Any], gold: list[Mapping[str, Any]]) -> dict[str, Any]:
    """가이드워드 정확 일치 + 파라미터 정규화 일치로 recall 을 잰다.

    recall = 매칭된 골드 레코드 수 / 그 노드의 전체 골드 레코드 수(N1 8·N2 9·N3 7·N4 10). 생성물이 골드보다 많아도
    분모는 골드다 — precision 은 T-08 의 판정 대상이 아니다. `generated` 는 `guideword`·
    `parameter` 속성을 가진 객체(`DeviationRecord`)다.
    """
    produced = {(r.guideword, normalize_parameter(r.parameter)) for r in generated}
    rows = [
        {
            "guideword": g["guideword"],
            "parameter": g["parameter"],
            "key": (g["guideword"], normalize_parameter(g["parameter"])),
        }
        for g in gold
    ]
    for row in rows:
        row["matched"] = row["key"] in produced
        row["guideword_seen"] = any(gw == row["guideword"] for gw, _ in produced)
        row["parameter_seen"] = any(pm == row["key"][1] for _, pm in produced)
    matched = sum(1 for row in rows if row["matched"])
    return {
        "recall": matched / len(rows),
        "matched": matched,
        "total": len(rows),
        "rows": rows,
        "produced": sorted(produced),
    }


#: 9/29 이전 이름 — 규칙은 노드 무관이다. 기존 시험·호출부 호환용 별칭.
recall_n1 = recall_for_node
