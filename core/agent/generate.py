"""HAZOP 이탈 생성 루프 — R-01~R-08 (spec:hazop-generation, PRD §5 FR-03).

design.md 는 `NodeMeta` / `DeviationRecord` / `HazopGenerator` 3개 클래스를 요구하고
파일을 `core/agent/generate.py` 하나로 제한한다(지시문 C 범위 상한). 압축 구현 원칙에 따라
호출 단위 스키마(`DeviationBatch`)와 파라미터 목록 스키마는 클래스가 아니라 모듈 상수로 둔다
— 클래스 상한 3개를 지키기 위해서다.

매트릭스는 2단이다(R-03·R-04):
  1단 `_enumerate_parameters` — 노드 메타에서 파라미터 축을 도출한다. 고정 목록이 아니다.
       근거: 골드셋 파라미터 어휘가 표준 12종과 12/34 만 일치하며, 고정 열거 시 홀드아웃
       recall 상한이 0.192 다(docs/프롬프트초안_FR-03_20260908.md §2.3).
  2단 `_generate_batch` — 가이드워드 1종 × 파라미터 전체를 한 호출로 판정한다.

LLM 호출은 `core/llm` 래퍼만 경유한다. 이 파일에 boto3 임포트는 없다(NFR-B04).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, Field, model_validator

from core.llm import (
    AbstractBedrockClient,
    ConfigValidationError,
    Message,
    load_model_config,
)

logger = logging.getLogger(__name__)

_PROMPT_DIR: Final[Path] = Path(__file__).parent / "prompts"
_RATING_SCALE_PATH: Final[Path] = (
    Path(__file__).parent.parent.parent / "data" / "gold" / "rating_scale.json"
)
_USER_DELIMITER: Final[str] = "<!-- USER -->"
_PARAM_EXAMPLES_PATH: Final[Path] = (
    Path(__file__).parent.parent.parent / "data" / "kb" / "hazop_param_examples.json"
)

#: 진행 알림(R-11, design §10). `(event, payload)` — event 는 "parameters" | "guideword".
ProgressCallback = Callable[[str, dict[str, Any]], None]

# ── 가이드워드 축 (R-04, design.md §4) ────────────────────────────────────────
# 정본은 steering domain.md §1. 데이터가 아니라 방법론이 정의하는 축이므로 고정 상수다.
STANDARD_GUIDEWORDS: Final[list[str]] = [
    "No",
    "More",
    "Less",
    "Reverse",
    "Other than",
    "Part of",
    "As well as",
]
PROCEDURAL_GUIDEWORDS: Final[list[str]] = ["Too early", "Too late", "Wrong action"]
PROCEDURAL_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"절차", "운전", "조작", "순서", "작업", "procedure", "operation"}
)
GUIDEWORD_DEFINITIONS: Final[dict[str, str]] = {
    "No": "설계 의도가 전혀 달성되지 않음",
    "More": "정량적 증가",
    "Less": "정량적 감소",
    "Reverse": "방향 또는 흐름이 반대",
    "Other than": "설계 의도와 다른 물질·상태",
    "Part of": "설계 의도 중 일부만 달성",
    "As well as": "설계 의도에 더해 추가 사항 발생",
    "Too early": "정해진 시점보다 이르게 수행",
    "Too late": "정해진 시점보다 늦게 수행",
    "Wrong action": "정해진 것과 다른 조작 수행",
}

# ── 호출 단위 스키마 (R-06) ───────────────────────────────────────────────────
# 산출물 스키마가 아니라 프롬프트 계약이므로 schemas/ 가 아닌 코드 상수다.
# 최상위가 객체여야 한다 — core/llm 이 이 스키마를 structured_output tool 의
# inputSchema 로 넣고, Bedrock toolSpec 은 배열 최상위를 허용하지 않는다.
PARAMETER_LIST_SCHEMA: Final[dict[str, Any]] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["parameters"],
    "properties": {
        "parameters": {
            "type": "array",
            "minItems": 6,
            "maxItems": 12,
            "items": {
                "type": "object",
                "required": ["name", "rationale"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "rationale": {"type": "string"},
                },
                "additionalProperties": False,
            },
        }
    },
    "additionalProperties": False,
}

DEVIATION_BATCH_SCHEMA: Final[dict[str, Any]] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["guideword", "cells"],
    "properties": {
        "guideword": {"type": "string"},
        "cells": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["parameter", "applicable"],
                "properties": {
                    "parameter": {"type": "string", "minLength": 1},
                    "applicable": {"type": "boolean"},
                    "skip_reason": {"type": "string"},
                    "deviation": {"type": "string"},
                    "causes": {"type": "array", "items": {"type": "string"}},
                    "consequences": {"type": "array", "items": {"type": "string"}},
                    "safeguards_before": {"type": "array", "items": {"type": "string"}},
                    "S": {"type": "integer", "minimum": 1, "maximum": 5},
                    "F": {"type": "integer", "minimum": 1, "maximum": 5},
                    "recommendations": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": {}, "maxItems": 0},
                    "confidence": {"type": "string", "enum": ["inferred"]},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


# ── 프롬프트 로딩 (R-03·R-08, design.md §5) ───────────────────────────────────
def _load_prompt(name: str) -> str:
    """`core/agent/prompts/<name>` 전문을 읽는다. 프롬프트는 코드에 두지 않는다."""
    return (_PROMPT_DIR / name).read_text(encoding="utf-8")


def _split_prompt(text: str) -> tuple[str, str]:
    """프롬프트 파일을 (시스템, 사용자 턴 템플릿)으로 가른다.

    캐싱 경계이기도 하다(R-08): 노드마다 바뀌지 않는 부분만 시스템에 남기고, 노드·
    가이드워드에 따라 바뀌는 부분은 사용자 턴으로 보낸다. 이렇게 갈라야
    `deviation_generate` 시스템 블록이 노드 1건 안에서 7~10회 그대로 재사용된다.
    """
    system, _, user = text.partition(_USER_DELIMITER)
    return system.strip(), user.strip()


def _fill(template: str, values: dict[str, str]) -> str:
    """`{key}` 치환. `str.format` 을 쓰지 않는 이유는 등급표 JSON 의 중괄호 때문이다."""
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return out


def render_param_examples(path: Path = _PARAM_EXAMPLES_PATH) -> str:
    """R-12: 공개 HAZOP 예시 → 열거 시스템 프롬프트 꼬리. 머리말 문구는 `data/kb` 파일이 갖는다(코드에 프롬프트 금지)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = [data["preamble"]]
    for ex in data["examples"]:
        lines.append(f"- {ex['process']}: {' · '.join(ex['parameters'])}")
    return "\n".join(lines)


def _load_rating_scale() -> str:
    """S·F 등급 정의(`data/gold/rating_scale.json`) 원문. 읽기 전용 자산이다."""
    return _RATING_SCALE_PATH.read_text(encoding="utf-8").strip()


# ── 설정 (design.md §2.3 — 클래스 카운트 제외, ModelConfig 패턴 재사용) ────────
@dataclass
class GeneratorConfig:
    prompt_caching: bool = True
    cost_limit_usd: float = 0.30
    # 가이드워드 판정 동시 호출 수(R-10). 1 이면 순차 경로. 직접 생성한 설정의 기본값은 1 —
    # 응답 목록을 순서대로 소비하는 mock 시험이 흔들리지 않게. models.yaml 로더 기본은 4.
    parallel_calls: int = 1
    # R-12: 열거 시스템 프롬프트에 공개 HAZOP 예시를 덧붙인다. 기본 false — 프롬프트 바이트 불변(AC-12-1).
    enumerate_examples: bool = False


def load_generator_config() -> GeneratorConfig:
    """`config/models.yaml` 에서 읽되, G0 미완료(model_id=null)면 기본값으로 계속한다.

    모델 ID 를 추측해 채우지 않는다 — 이 함수는 모델 ID 를 읽지도 않는다. 오프라인
    (mock) 경로가 설정 파일 없이도 동작해야 하기 때문에 예외를 삼킨다.
    """
    try:
        cfg = load_model_config()
    except ConfigValidationError as exc:
        logger.warning("models.yaml 미완성 — 생성기 기본 설정으로 진행한다: %s", exc)
        return GeneratorConfig()
    return GeneratorConfig(
        prompt_caching=cfg.generation.prompt_caching,
        cost_limit_usd=cfg.cost_limit_usd,
        parallel_calls=cfg.parallel_calls,
        enumerate_examples=cfg.enumerate_examples,
    )


# ── 모델 (R-01·R-02, design.md §2.1·§2.2) ─────────────────────────────────────
class NodeMeta(BaseModel):
    """공정 노드 입력. 골드셋 `node_meta` 와 1:1 대응하며 `node` 만 추가된다."""

    node: str = ""
    substance: str
    phase: str
    P_kPag: float | None = None
    T_degC: float | None = None
    equipment: list[str] = Field(default_factory=list)
    safeguards: list[str] = Field(default_factory=list)


class DeviationRecord(BaseModel):
    """생성된 이탈 1건. `schemas/deviation.schema.json` 의 items 와 대응한다."""

    id: str
    node: str
    node_meta: NodeMeta
    guideword: str
    parameter: str
    deviation: str
    causes: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    safeguards_before: list[str] = Field(default_factory=list)
    S: int = Field(ge=1, le=5)
    F: int = Field(ge=1, le=5)
    risk_score: int = 0
    recommendations: list[str] = Field(default_factory=list)
    scenario: str = ""
    evidence: list[Any] = Field(default_factory=list)
    confidence: str = "inferred"

    @model_validator(mode="after")
    def _compute_risk_score(self) -> DeviationRecord:
        """위험도는 언제나 코드가 계산한다(R-05). 입력으로 들어온 값은 덮어쓴다."""
        object.__setattr__(self, "risk_score", self.S * self.F)
        return self


# ── 생성기 (R-03~R-06) ────────────────────────────────────────────────────────
class HazopGenerator:
    def __init__(
        self, client: AbstractBedrockClient, config: GeneratorConfig | None = None
    ) -> None:
        self._client = client
        self._config = config or GeneratorConfig()
        # 한 번의 generate() 실행 결과를 관측하기 위한 상태 (R-06 수용 기준·비용 집계)
        self.review_guidewords: list[str] = []
        self.total_cost_usd: float = 0.0
        self.expected_cells: int = 0
        self.judged_cells: int = 0
        self.parameters: list[str] = []  # 마지막 실행에서 열거된 파라미터 이름(R-11)

    # -- 공개 진입점 ---------------------------------------------------------
    def generate(
        self, node_meta: NodeMeta, on_progress: ProgressCallback | None = None
    ) -> list[DeviationRecord]:
        """노드 전체 생성. `on_progress` 는 단계가 끝날 때마다 이 스레드에서 불린다(R-11)."""
        parameters = self._start(node_meta, on_progress)
        guidewords = _select_guidewords(node_meta)
        self.expected_cells = len(parameters) * len(guidewords)

        # 가이드워드 판정은 서로 독립이다(R-10). 각 호출은 (batch, 비용) 을 **반환**만 하고
        # 공유 상태는 건드리지 않는다 — 합산·review 기록은 아래에서 목록 순서대로 단일 스레드로 한다.
        outcomes: list[tuple[dict[str, Any] | None, float] | None] = [None] * len(guidewords)
        partial: list[list[DeviationRecord]] = [[] for _ in guidewords]

        def collect(index: int, outcome: tuple[dict[str, Any] | None, float]) -> None:
            # 완료 순서로 알리고(R-11), 결과는 축 인덱스 자리에 둔다 — 최종 조립은 축 순서(AC-10-1).
            outcomes[index] = outcome
            if on_progress is None:
                return
            # 중간 표는 묶음별로 한 번만 만든다. id 는 묶음 안 임시 번호 — 최종 id 는 아래 _assemble 이 매긴다.
            if outcome[0] is not None:
                partial[index] = _build_records(node_meta, [outcome[0]])[0]
            self._notify(on_progress, "guideword", {
                "guideword": guidewords[index],
                "done": sum(o is not None for o in outcomes),
                "total": len(guidewords),
                "records": [r for rows in partial for r in rows],
            })

        workers = max(1, self._config.parallel_calls)
        if workers == 1:
            for index, gw in enumerate(guidewords):
                collect(index, self._generate_batch(node_meta, parameters, gw))
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(self._generate_batch, node_meta, parameters, gw): index
                    for index, gw in enumerate(guidewords)
                }
                for future in as_completed(futures):
                    collect(futures[future], future.result())

        batches: list[dict[str, Any]] = []
        for guideword, outcome in zip(guidewords, outcomes, strict=True):
            assert outcome is not None  # 모든 future 가 collect 를 거쳤다
            batch, cost = outcome
            self.total_cost_usd += cost
            if batch is None:
                if parameters:
                    self.review_guidewords.append(guideword)
                continue
            batches.append(batch)

        records = self._assemble(node_meta, batches)
        self._check_coverage(node_meta)
        self._check_node_cost(node_meta)
        return records

    def generate_quick(
        self, node_meta: NodeMeta, guideword: str, on_progress: ProgressCallback | None = None
    ) -> list[DeviationRecord]:
        """빠른 실호출(R-11 AC-11-5): 파라미터 열거 1회 + 가이드워드 1종 판정 1회.

        `generate()` 와 같은 관측 상태를 남긴다. 열거가 실패하면 판정을 부르지 않고 빈 목록.
        """
        parameters = self._start(node_meta, on_progress)
        self.expected_cells = len(parameters)
        if not parameters:
            return []
        batch, cost = self._generate_batch(node_meta, parameters, guideword)
        self.total_cost_usd += cost  # O-1 이후 _generate_batch 는 합산을 호출자에게 맡긴다
        if batch is None:
            self.review_guidewords.append(guideword)
        records = self._assemble(node_meta, [batch] if batch else [])
        self._notify(on_progress, "guideword", {
            "guideword": guideword, "done": 1, "total": 1, "records": records,
        })
        return records

    def _start(self, node_meta: NodeMeta, on_progress: ProgressCallback | None) -> list[dict[str, str]]:
        """관측 상태 초기화 → 파라미터 열거 → `parameters` 알림. 두 진입점 공통."""
        self.review_guidewords = []
        self.total_cost_usd = 0.0
        self.expected_cells = 0
        self.judged_cells = 0
        parameters = self._enumerate_parameters(node_meta)
        self.parameters = [p["name"] for p in parameters]
        self._notify(on_progress, "parameters", {"parameters": list(self.parameters)})
        return parameters

    @staticmethod
    def _notify(on_progress: ProgressCallback | None, event: str, payload: dict[str, Any]) -> None:
        """진행 알림 단일 지점. 화면 쪽 예외가 생성을 멈추지 않는다(AC-11-3)."""
        if on_progress is None:
            return
        try:
            on_progress(event, payload)
        except Exception:  # noqa: BLE001 — 표시 실패는 생성 실패가 아니다
            logger.warning("진행 알림 콜백 예외(event=%s) — 생성은 계속한다", event, exc_info=True)

    # -- 1단: 파라미터 축 도출 (R-03) ----------------------------------------
    def _enumerate_parameters(self, node_meta: NodeMeta) -> list[dict[str, str]]:
        system, user_template = _split_prompt(_load_prompt("matrix_enumerate.md"))
        if self._config.enumerate_examples:
            system = system + "\n\n" + render_param_examples()
        user = _fill(
            user_template,
            {
                "node": node_meta.node or "미상",
                "substance": node_meta.substance,
                "phase": node_meta.phase,
                "P_kPag": _fmt_number(node_meta.P_kPag),
                "T_degC": _fmt_number(node_meta.T_degC),
                "equipment": ", ".join(node_meta.equipment) or "미상",
                "safeguards": ", ".join(node_meta.safeguards) or "없음",
            },
        )
        response = self._client.converse(
            system=system,
            messages=[Message(role="user", content=user)],
            response_schema=PARAMETER_LIST_SCHEMA,
            context={"node": node_meta.node},
        )
        self.total_cost_usd += response.cost_usd
        if response.content is None:
            logger.warning("node=%s 파라미터 열거 실패 — 이탈 생성을 건너뛴다", node_meta.node)
            return []
        payload = json.loads(response.content)
        return [
            {"name": str(item["name"]), "rationale": str(item.get("rationale", ""))}
            for item in payload.get("parameters", [])
        ]

    # -- 2단: 가이드워드 행 판정 (R-04) --------------------------------------
    def _generate_batch(
        self, node_meta: NodeMeta, parameters: list[dict[str, str]], guideword: str
    ) -> tuple[dict[str, Any] | None, float]:
        """(batch, 비용). batch=None 이면 그 행은 review. 스레드에서 돌므로 `self` 를 쓰지 않는다."""
        if not parameters:
            return None, 0.0
        system_template, user_template = _split_prompt(_load_prompt("deviation_generate.md"))
        system = _fill(system_template, {"rating_scale": _load_rating_scale()})
        user = _fill(
            user_template,
            {
                "node": node_meta.node or "미상",
                "substance": node_meta.substance,
                "equipment": ", ".join(node_meta.equipment) or "미상",
                "phase": node_meta.phase or "미상",
                "P_kPag": _fmt_number(node_meta.P_kPag),
                "T_degC": _fmt_number(node_meta.T_degC),
                "safeguards": ", ".join(node_meta.safeguards) or "없음",
                "guideword": guideword,
                "guideword_definition": GUIDEWORD_DEFINITIONS.get(guideword, ""),
                "n": str(len(parameters)),
                "parameters": "\n".join(
                    f"- {p['name']}: {p['rationale']}" for p in parameters
                ),
            },
        )
        try:
            response = self._client.converse(
                system=system,
                messages=[Message(role="user", content=user)],
                response_schema=DEVIATION_BATCH_SCHEMA,
                context={"node": node_meta.node},
            )
        except Exception:
            if self._config.parallel_calls <= 1:
                raise  # 순차 경로는 기존 동작(예외 전파) 그대로
            # 병렬에서는 한 가이드워드의 예외가 나머지를 죽이지 않게 그 행만 review 로 격하한다.
            logger.exception("node=%s gw=%s 호출 예외 — 이 행을 review 로 기록한다", node_meta.node, guideword)
            return None, 0.0
        if response.content is None:
            # core/llm 이 이미 1회 재시도를 소진했다(R-06). 노드 전체를 중단하지 않는다.
            logger.warning(
                "node=%s gw=%s content=None — 이 행을 review 로 기록한다",
                node_meta.node,
                guideword,
            )
            return None, response.cost_usd
        batch: dict[str, Any] = json.loads(response.content)
        batch["guideword"] = guideword  # 모델이 다른 값을 넣어도 호출한 축을 정본으로 삼는다
        return batch, response.cost_usd

    # -- 결과 조립 (R-02·R-05) -----------------------------------------------
    def _assemble(
        self, node_meta: NodeMeta, batches: list[dict[str, Any]]
    ) -> list[DeviationRecord]:
        records, judged = _build_records(node_meta, batches)
        self.judged_cells += judged
        return records

    # -- 사후 점검 -----------------------------------------------------------
    def _check_coverage(self, node_meta: NodeMeta) -> None:
        """열거한 셀과 판정된 셀이 다르면 경고만 남긴다(R-04 — 예외를 던지지 않는다)."""
        if self.judged_cells != self.expected_cells:
            logger.warning(
                "node=%s 매트릭스 누락 — expected_cells=%d judged_cells=%d",
                node_meta.node,
                self.expected_cells,
                self.judged_cells,
            )

    def _check_node_cost(self, node_meta: NodeMeta) -> None:
        """`core/llm` 은 호출 1건씩만 검사하므로 노드 누적은 여기서 본다(design.md §8)."""
        if self.total_cost_usd > self._config.cost_limit_usd:
            logger.warning(
                "node=%s total_cost_usd=%.4f EXCEEDS LIMIT %.2f",
                node_meta.node,
                self.total_cost_usd,
                self._config.cost_limit_usd,
            )


# ── 보조 함수 ─────────────────────────────────────────────────────────────────
def _build_records(
    node_meta: NodeMeta, batches: list[dict[str, Any]]
) -> tuple[list[DeviationRecord], int]:
    """batch 목록 → (레코드, 판정 셀 수). 생성기 상태를 건드리지 않는다 — 진행 알림의 중간 표가 이걸 쓴다(AC-11-4)."""
    records: list[DeviationRecord] = []
    judged = 0
    prefix = (node_meta.node or "node").lower()
    for batch in batches:
        guideword = str(batch.get("guideword", ""))
        for cell in batch.get("cells", []):
            judged += 1
            if not cell.get("applicable", False):
                continue
            if not _cell_is_complete(cell):
                logger.warning(
                    "node=%s gw=%s param=%s 필수 필드 결측 — 이 셀을 버린다",
                    node_meta.node,
                    guideword,
                    cell.get("parameter"),
                )
                continue
            records.append(
                DeviationRecord(
                    id=f"{prefix}-{len(records) + 1:03d}",
                    node=node_meta.node,
                    node_meta=node_meta,
                    guideword=guideword,
                    parameter=str(cell["parameter"]),
                    deviation=str(cell["deviation"]),
                    causes=list(cell.get("causes", [])),
                    consequences=list(cell.get("consequences", [])),
                    safeguards_before=_normalize_safeguards(
                        node_meta, guideword, str(cell["parameter"]), cell.get("safeguards_before", [])
                    ),
                    S=int(cell["S"]),
                    F=int(cell["F"]),
                    recommendations=list(cell.get("recommendations", [])),
                    scenario="",
                    evidence=[],
                    confidence="inferred",
                )
            )
    return records, judged


def _select_guidewords(node_meta: NodeMeta) -> list[str]:
    """절차형 3종은 설비가 운전 절차를 가리킬 때만 축에 넣는다(R-04 조건부 포함)."""
    guidewords = list(STANDARD_GUIDEWORDS)
    equipment_text = " ".join(node_meta.equipment).lower()
    if any(keyword in equipment_text for keyword in PROCEDURAL_KEYWORDS):
        guidewords.extend(PROCEDURAL_GUIDEWORDS)
    return guidewords


_SAFEGUARD_SPLIT: Final[re.Pattern[str]] = re.compile(r"[()\s·/,]+")


def _safeguard_tokens(text: str) -> set[str]:
    """괄호·공백·`·`·`/`·`,` 로 쪼갠 2글자 이상 토큰(소문자). 부분문자열 비교로는
    "ESV(긴급차단밸브)" ↔ "긴급차단밸브(ESV)" 가 안 잡히므로 토큰 단위로 비교한다."""
    return {t for t in _SAFEGUARD_SPLIT.split(text.lower()) if len(t) >= 2}


def _normalize_safeguards(
    node_meta: NodeMeta, guideword: str, parameter: str, generated: list[Any]
) -> list[str]:
    """`safeguards_before` 를 입력 `node_meta.safeguards` 의 원문 문자열로만 남긴다(지시문 M-01, P-1·P-9).

    생성 항목과 토큰이 하나라도 겹치는 입력은 전부 채택(둘과 겹치면 둘 다), 어느 입력과도
    안 겹치면 버리고 WARNING. 결과는 중복 없이 입력 순서. 입력이 비면 항상 빈 배열.
    """
    inputs = node_meta.safeguards
    input_tokens = [_safeguard_tokens(s) for s in inputs]
    kept: set[int] = set()
    for item in generated:
        tokens = _safeguard_tokens(str(item))
        hits = {i for i, toks in enumerate(input_tokens) if toks & tokens}
        if not hits:
            logger.warning(
                "node=%s gw=%s param=%s safeguards_before 입력에 없는 항목을 버린다: %s",
                node_meta.node,
                guideword,
                parameter,
                item,
            )
        kept |= hits
    return [inputs[i] for i in sorted(kept)]


def _cell_is_complete(cell: dict[str, Any]) -> bool:
    """`applicable=true` 셀이 레코드가 되려면 이탈 서술과 S·F 가 모두 있어야 한다."""
    return bool(cell.get("deviation")) and cell.get("S") is not None and cell.get("F") is not None


def _fmt_number(value: float | None) -> str:
    return "미상" if value is None else f"{value:g}"
