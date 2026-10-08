"""S·F 평가기준 라이브러리 — 지시문 Y-2 (평가기준 다변화).

`data/kb/criteria/<id>.json` 하나가 기준 하나다. 기준마다 단계 수(S 1~4, F 1~3 등)와 위험도 산정
방식(곱 `product` / 대조표 `lookup`)이 다르다 — 원문 단계 수를 5 로 바꾸지 않는다(PRD Y-2).
LLM·내보내기 어느 쪽도 임포트하지 않는다(`core/export` 가 이 모듈을 쓴다).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final

_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
CRITERIA_DIR: Final[Path] = _ROOT / "data" / "kb" / "criteria"
#: 골드셋 노드(NH3 N1~N4)와 `criteria_id` 가 없는 옛 레코드의 기준 — 그 레코드들은 이 기준으로 생성됐다.
GOLD_CRITERIA: Final[str] = "nh3_sts_bunkering"
#: 그 밖의 공정(직접 입력 등)의 기본 기준 — 공식 HAZOP 기술지원규정(steering domain.md §4 적용 범위).
OFFICIAL_CRITERIA: Final[str] = "kosha_cc37_2026"


@dataclass(frozen=True)
class Criteria:
    id: str
    data: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.data["name"])

    @property
    def short(self) -> str:
        return str(self.data.get("short") or self.name)

    @property
    def s_max(self) -> int:
        return max(int(i["grade"]) for i in self.data["severity"])

    @property
    def f_max(self) -> int:
        return max(int(i["grade"]) for i in self.data["frequency"])

    @property
    def method(self) -> str:
        return str(self.data["risk"]["method"])

    @property
    def risk_max(self) -> int:
        return self.risk(self.s_max, self.f_max) if self.method == "product" else max(
            v for row in self.data["risk"]["table"].values() for v in row.values()
        )

    def check(self, s: int, f: int) -> None:
        if not (1 <= s <= self.s_max and 1 <= f <= self.f_max):
            raise ValueError(f"{self.short}: S 는 1~{self.s_max}, F 는 1~{self.f_max} 정수여야 합니다 (S={s}, F={f})")

    def risk(self, s: int, f: int) -> int:
        """위험도. 곱 기준은 S×F, 대조표 기준은 표 값. 범위 밖이면 ValueError."""
        self.check(s, f)
        if self.method == "product":
            return s * f
        return int(self.data["risk"]["table"][str(s)][str(f)])

    def bands(self) -> list[tuple[int, int, str, str]]:
        """[(하한, 상한, 판정, 조치)] — 원문 순서(높은 구간 먼저)."""
        out = []
        for b in self.data["risk_bands"]:
            low, _, high = str(b["range"]).partition("~")
            out.append((int(low), int(high or low), str(b["judgement"]), str(b["action"])))
        return out

    def band(self, score: int) -> str:
        for low, high, judgement, _ in self.bands():
            if low <= score <= high:
                return judgement
        raise ValueError(f"{self.short}: 위험도 {score} 는 구간 밖이다")

    def excel_formula(self, row: int) -> str:
        """위험도 열 수식(값을 넣지 않는다 — 검토에서 S·F 를 고치면 다시 계산된다)."""
        if self.method == "product":
            return f"=H{row}*I{row}"
        table = self.data["risk"]["table"]
        matrix = ";".join(
            ",".join(str(table[str(s)][str(f)]) for f in range(1, self.f_max + 1))
            for s in range(1, self.s_max + 1)
        )
        return f"=INDEX({{{matrix}}},H{row},I{row})"

    def method_text(self) -> str:
        return "S×F" if self.method == "product" else "대조표(S·F 조합)"

    def prompt_text(self) -> str:
        """판정 프롬프트 `{rating_scale}` 자리. 골드셋 기준은 예전과 바이트 동일(원본 파일 그대로)."""
        if "scale_file" in self.data:
            return (_ROOT / self.data["scale_file"]).read_text(encoding="utf-8").strip()
        lines = [f"기준: {self.name}", f"S 는 1~{self.s_max} 정수, F 는 1~{self.f_max} 정수만 쓴다.", "", "S(강도):"]
        lines += [f"- {i['grade']}({i['label']}): {i['definition']}" for i in self.data["severity"]]
        lines += ["", "F(발생빈도):"]
        lines += [f"- {i['grade']}({i['label']}): {i['definition']}" for i in self.data["frequency"]]
        notes = self.data.get("notes") or []
        if notes:
            lines += ["", "주:"] + [f"- {n}" for n in notes]
        return "\n".join(lines)


@cache
def load_criteria(criteria_id: str | None = None) -> Criteria:
    """기준 1개. `None` 이면 골드셋 기준(옛 레코드 호환). `scale_file` 이 있으면 등급표를 그 파일에서 합친다."""
    cid = criteria_id or GOLD_CRITERIA
    path = CRITERIA_DIR / f"{cid}.json"
    if not path.exists():
        raise ValueError(f"알 수 없는 평가기준: {cid} ({path} 없음)")
    data = json.loads(path.read_text(encoding="utf-8"))
    if "scale_file" in data:
        scale = json.loads((_ROOT / data["scale_file"]).read_text(encoding="utf-8"))
        data = {**scale, **data}
    return Criteria(id=cid, data=data)


def all_criteria() -> list[Criteria]:
    """라이브러리의 기준 전부 — 공식 기준 먼저, 골드셋 기준 마지막."""
    ids = sorted(p.stem for p in CRITERIA_DIR.glob("*.json"))
    ids.sort(key=lambda i: (i == GOLD_CRITERIA, i != OFFICIAL_CRITERIA))
    return [load_criteria(i) for i in ids]


__all__ = ["CRITERIA_DIR", "GOLD_CRITERIA", "OFFICIAL_CRITERIA", "Criteria", "all_criteria", "load_criteria"]
