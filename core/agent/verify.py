"""규칙 기반 자기 검증 — spec:self-verification T-01 (PRD v2.0 §5 FR-06).

LLM 을 호출하지 않는 순수 함수다(`core/llm` 임포트 금지). 근거(`evidence[]`) 없이 본문에 적힌
규격·문헌 번호(R-01)와 단위 붙은 수치(R-02)를 플래그하고, 플래그가 있는 레코드만
`confidence="review"` 로 격하한 **사본**을 돌려준다(R-03). `grounded` 는 부여하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from .generate import DeviationRecord

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from .generate import NodeMeta

Rule = Literal["unverified_standard", "unsupported_number"]

#: R-01 규격·문헌 번호. 대소문자 무시·공백 유연. 각 줄 주석은 매치 예시.
STANDARD_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"KOSHA\s*(GUIDE)?\s*[A-Z]-\d+",  # KOSHA GUIDE P-140
        r"KS\s*[A-Z]\s*(IEC|ISO)?\s*\d+",  # KS B 6750, KS C IEC 60079
        r"API\s*(RP|STD|Std)?\s*\d+",  # API 520, API RP 521
        r"NFPA\s*\d+",  # NFPA 55
        r"IEC\s*\d+",  # IEC 61511
        r"ISO\s*\d+",  # ISO 13709
        r"ASME\s*[A-Z]?\d*(\.\d+)?",  # ASME B31.3
        r"OSHA\s*\d+",  # OSHA 1910
        r"산업안전보건기준에\s*관한\s*규칙\s*제?\s*\d+조",  # 산업안전보건기준에 관한 규칙 제261조
        r"고압가스안전관리법\s*(시행규칙)?\s*제?\s*\d+조",  # 고압가스안전관리법 시행규칙 제8조
    )
)
# 한 정규식으로 합쳐 겹치는 매치를 막는다("KS C IEC 60079" 가 KS·IEC 로 두 번 잡히지 않게).
# 앞이 영문자면 단어 중간이므로 제외(한글 뒤에는 \b 가 안 서므로 lookbehind 로).
_STANDARD_RE: Final = re.compile(
    r"(?<![A-Za-z])(?:" + "|".join(p.pattern for p in STANDARD_PATTERNS) + ")", re.IGNORECASE
)

#: R-02 단위 붙은 수치. 단위는 긴 것부터 — "10 min" 이 "10 m" 로, "5 kPag" 가 "5 kPa" 로 잘리지 않게.
_UNITS: Final[tuple[str, ...]] = (
    "vol%", "kPag", "barg", "kPa", "MPa", "bar", "ppm", "m/s", "min", "시간",
    "°C", "m³", "m3", "kg", "℃", "톤", "초", "분", "%", "K", "t", "L", "m", "h", "s",
)
NUMBER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9.])(-?\d+(?:\.\d+)?)\s*(?:" + "|".join(map(re.escape, _UNITS)) + r")(?![A-Za-z0-9])"
)

_STANDARD_FIELDS: Final = ("deviation", "causes", "consequences", "safeguards_before", "recommendations", "scenario")
_NUMBER_FIELDS: Final = ("causes", "consequences", "safeguards_before", "recommendations")  # AC-02-2·3


@dataclass(frozen=True)
class Flag:
    record_id: str
    rule: Rule
    field: str  # "causes[1]" 처럼 인덱스 포함
    matched: str


@dataclass(frozen=True)
class VerifySummary:
    total: int
    flagged: int
    by_rule: dict[str, int]
    missing_cells: int | None
    flags: tuple[Flag, ...]


def _iter_text_fields(record: DeviationRecord, fields: Sequence[str]) -> Iterator[tuple[str, str]]:
    for name in fields:
        value = getattr(record, name)
        if isinstance(value, str):
            yield name, value
        else:
            for i, text in enumerate(value):
                yield f"{name}[{i}]", str(text)


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _num(text: str) -> str:
    return f"{float(text):g}"


def _allowed_numbers(node_meta: NodeMeta) -> set[str]:
    """`P_kPag`·`T_degC` 를 정규화한 문자열(350 과 350.0 은 같은 "350")."""
    return {_num(str(v)) for v in (node_meta.P_kPag, node_meta.T_degC) if v is not None}


def _record_flags(record: DeviationRecord) -> list[Flag]:
    flags: list[Flag] = []
    seen: set[tuple[str, str]] = set()  # AC-01-2 같은 레코드·같은 매치는 1회

    def add(rule: Rule, field: str, matched: str) -> None:
        if (rule, _norm(matched)) not in seen:
            seen.add((rule, _norm(matched)))
            flags.append(Flag(record.id, rule, field, matched))

    evidence = _norm(" ".join(map(str, record.evidence)))
    for field, text in _iter_text_fields(record, _STANDARD_FIELDS):
        for m in _STANDARD_RE.finditer(text):
            if _norm(m.group(0)) not in evidence:
                add("unverified_standard", field, m.group(0))
    allowed = _allowed_numbers(record.node_meta)
    for field, text in _iter_text_fields(record, _NUMBER_FIELDS):
        for m in NUMBER_PATTERN.finditer(text):
            if _num(m.group(1)) not in allowed:
                add("unsupported_number", field, m.group(0))
    return flags


def verify(
    records: Sequence[DeviationRecord | Mapping[str, object]],
    *,
    expected_cells: int | None = None,
    judged_cells: int | None = None,
) -> tuple[list[DeviationRecord], VerifySummary]:
    """R-01~R-04. 입력 순서·개수 보존, 원본 불변(`model_copy`)."""
    out: list[DeviationRecord] = []
    all_flags: list[Flag] = []
    flagged = 0
    for raw in records:
        record = raw if isinstance(raw, DeviationRecord) else DeviationRecord.model_validate(raw)
        flags = _record_flags(record)
        if flags:
            flagged += 1
            record = record.model_copy(update={"confidence": "review"})
        out.append(record)
        all_flags.extend(flags)
    by_rule = {rule: sum(f.rule == rule for f in all_flags) for rule in ("unverified_standard", "unsupported_number")}
    missing = expected_cells - judged_cells if expected_cells is not None and judged_cells is not None else None
    return out, VerifySummary(len(out), flagged, by_rule, missing, tuple(all_flags))
