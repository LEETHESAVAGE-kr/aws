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

from pydantic import BaseModel, Field, model_serializer, model_validator

from core import policy
from core.agent import consensus
from core.criteria import GOLD_CRITERIA, Criteria, load_criteria
from core.llm import (
    AbstractBedrockClient,
    ConfigValidationError,
    Message,
    load_model_config,
)
from core.retrieval import Passage, Retriever, check_citation, default_retriever

logger = logging.getLogger(__name__)

_PROMPT_DIR: Final[Path] = Path(__file__).parent / "prompts"
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


def batch_schema(criteria: Criteria, with_evidence: bool = False, boundary: bool = False) -> dict[str, Any]:
    """판정 호출 스키마 — S·F 상한을 기준의 단계 수로 좁힌다(Y-2). 골드셋 기준이면 `DEVIATION_BATCH_SCHEMA` 와 같다."""
    schema = json.loads(json.dumps(DEVIATION_BATCH_SCHEMA))
    cell = schema["properties"]["cells"]["items"]["properties"]
    cell["S"]["maximum"] = criteria.s_max
    cell["F"]["maximum"] = criteria.f_max
    if boundary:  # Z-3: 셀 보류 — 미상(U) 정보 없이는 정할 수 없는 셀. 원인·S·F 는 코드가 지운다
        cell["insufficient"] = {"type": "boolean"}
        cell["missing"] = {"type": "array", "maxItems": 3, "items": {"type": "string", "minLength": 1}}
    if with_evidence:  # Y-3: 발췌 id + 원문 구절만. 제목·위치는 코드가 코퍼스에서 채운다
        cell["evidence"] = {
            "type": "array", "maxItems": 3,
            "items": {
                "type": "object", "required": ["source_id", "quote"], "additionalProperties": False,
                "properties": {"source_id": {"type": "string"}, "quote": {"type": "string"}},
            },
        }
    return schema


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
    # Y-3: 파라미터당 공식 문서 발췌 검색 수. 0 이면 근거 인용 끔 — 판정 프롬프트·스키마가 Y-3 이전과 같다.
    evidence_k: int = 0
    # Z-1~Z-3: 추론 경계. false 면 판정·열거 프롬프트와 스키마가 Z 이전과 바이트 동일.
    inference_boundary: bool = False
    # §8 C 합의 생성: 가이드워드 판정 반복 횟수. 1 이면 지금 경로 그대로(프롬프트·스키마·레코드 바이트 동일).
    consensus_runs: int = 1
    # 합치기(합집합) — true 면 반복 중 한 번이라도 나온 판단을 모두 남긴다. 화면 '생성 방식'만 켠다.
    consensus_union: bool = False


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
        evidence_k=cfg.evidence_k,
        inference_boundary=cfg.inference_boundary,
        consensus_runs=cfg.consensus_runs,
    )


# ── 모델 (R-01·R-02, design.md §2.1·§2.2) ─────────────────────────────────────
class NodeMeta(BaseModel):
    """공정 노드 입력. 골드셋 `node_meta` 와 1:1 대응하며 `node` 만 추가된다."""

    node: str = ""
    substance: str
    phase: str
    P_kPag: float | None = None
    T_degC: float | None = None
    #: 10/9 사용자 결정(가): 추론 경계가 '용량·설계압력 미상'으로 보류하던 정보를 받을 칸. 없으면 미상.
    design_P_kPag: float | None = None  # noqa: N815 — P_kPag 와 같은 표기(골드셋 node_meta 관례)
    capacity: str | None = None  # 적힌 그대로("200 kg", "50 m³") — 단위가 설비마다 달라 환산하지 않는다
    equipment: list[str] = Field(default_factory=list)
    safeguards: list[str] = Field(default_factory=list)
    #: Z-1 "없음"과 "모름"의 구분. `safeguards` 가 비었을 때 true 면 사용자가 '안전장치 없음'을 명시(G),
    #: false 면 입력에 없을 뿐(U). 입력 해석은 "없음"이 명시된 경우에만 true 로 둔다.
    safeguards_known: bool = False


#: 셀 상태(Z-3). 판정한 셀 = 해당(레코드) · 해당 없음(레코드 아님) · 정보 부족(보류 레코드).
INSUFFICIENT: Final[str] = "insufficient"
#: 보류 셀에 모델이 이탈 초안을 적지 않았을 때의 표기 — 지어내지 않고 비었다고 쓴다.
HELD_NO_DRAFT: Final[str] = "(이탈 초안 없음 — 정보 부족으로 보류)"


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
    #: 보류(`status="insufficient"`) 행만 None — 미상 정보 없이 S·F 를 정하지 않는다(Z-3).
    S: int | None = Field(default=None, ge=1, le=5)
    F: int | None = Field(default=None, ge=1, le=5)
    risk_score: int | None = 0
    recommendations: list[str] = Field(default_factory=list)
    scenario: str = ""
    evidence: list[Any] = Field(default_factory=list)
    confidence: str = "inferred"
    #: S·F 를 매긴 평가기준(Y-2, `data/kb/criteria/<id>.json`). 없으면 골드셋 NH3 기준(옛 레코드).
    criteria_id: str | None = None
    #: Y-3 인용 검사에서 지운 인용(가짜·변형 구절). 비어 있지 않으면 검증기가 review 로 내린다.
    citation_flags: list[str] = Field(default_factory=list)
    #: Z-3 "applicable" | "insufficient"(정보 부족 보류). 보류 행의 `missing` 은 없어서 보류한 정보(1~3개).
    status: str = "applicable"
    missing: list[str] = Field(default_factory=list)
    #: §8 C 합의 생성 내역(셀 투표·문장별 agree·S/F 값). 단일 실행(consensus_runs=1)이면 None — 직렬화에서 빠진다.
    consensus: dict[str, Any] | None = None

    @model_serializer(mode="wrap")
    def _drop_empty_consensus(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if self.consensus is None:
            data.pop("consensus", None)  # 합의 이전 레코드·재생 파일과 바이트 동일하게
        return data

    @model_validator(mode="after")
    def _compute_risk_score(self) -> DeviationRecord:
        """위험도는 언제나 코드가 계산한다(R-05) — 기준이 곱이면 S×F, 대조표면 표 값. 입력값은 덮어쓴다.

        보류 행은 S·F 가 없으면 위험도도 없다(None). 보류가 아닌 행에 S·F 가 없으면 거부한다.
        """
        if self.S is None or self.F is None:
            if self.status != INSUFFICIENT:
                raise ValueError("S·F 는 보류(insufficient) 행에서만 비울 수 있다")
            object.__setattr__(self, "risk_score", None)
            return self
        object.__setattr__(self, "risk_score", load_criteria(self.criteria_id).risk(self.S, self.F))
        return self


# ── 생성기 (R-03~R-06) ────────────────────────────────────────────────────────
class HazopGenerator:
    def __init__(
        self,
        client: AbstractBedrockClient,
        config: GeneratorConfig | None = None,
        criteria_id: str = GOLD_CRITERIA,
        retriever: Retriever | None = None,
    ) -> None:
        self._client = client
        self._config = config or GeneratorConfig()
        self.criteria = load_criteria(criteria_id)  # Y-2: S·F 등급표·위험도 산정 기준
        self._retriever = retriever  # Y-3: evidence_k > 0 일 때만 쓴다(없으면 프로세스 공용 검색기)
        self.inference_boundary = self._config.inference_boundary  # Z: 결과 메타에 남긴다
        # 한 번의 generate() 실행 결과를 관측하기 위한 상태 (R-06 수용 기준·비용 집계)
        self.review_guidewords: list[str] = []
        self.total_cost_usd: float = 0.0
        self.expected_cells: int = 0
        self.judged_cells: int = 0
        self.parameters: list[str] = []  # 마지막 실행에서 열거된 파라미터 이름(R-11)
        self.parameter_items: list[dict[str, str]] = []  # 이름+근거(실측 도구가 같은 목록으로 재판정할 때)
        #: §8 C: 가이드워드 → 실행별 원시 판정 묶음(실패는 None). 단일 실행이면 비어 있다.
        self.consensus_raw: dict[str, list[dict[str, Any] | None]] = {}
        self.consensus_costs: dict[str, list[float]] = {}  # 같은 키, 실행별 판정 비용

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
        runs = max(1, self._config.consensus_runs)
        # 판정 작업 = (실행, 가이드워드). 실행 우선 순서로 넣어 첫 물결이 단일 실행 한 벌이 되게 한다(§8 C-1).
        jobs = [(run, gi) for run in range(runs) for gi in range(len(guidewords))]
        outcomes: list[tuple[dict[str, Any] | None, float] | None] = [None] * len(jobs)
        partial: list[list[DeviationRecord]] = [[] for _ in guidewords]

        def collect(index: int, outcome: tuple[dict[str, Any] | None, float]) -> None:
            # 완료 순서로 알리고(R-11), 결과는 작업 인덱스 자리에 둔다 — 최종 조립은 공정 순서(Y-1, process_order).
            outcomes[index] = outcome
            if on_progress is None:
                return
            gi = jobs[index][1]
            # 중간 표는 가이드워드별 처음 도착한 묶음으로 한 번만. id 는 임시 번호 — 최종 id 는 _assemble 이 매긴다.
            if outcome[0] is not None and not partial[gi]:
                partial[gi] = _build_records(node_meta, [outcome[0]], self.criteria.id)[0]
            self._notify(on_progress, "guideword", {
                "guideword": guidewords[gi],
                "done": sum(o is not None for o in outcomes),
                "total": len(jobs),
                "records": process_order([r for rows in partial for r in rows], self.parameters, renumber=False),
            })

        workers = max(1, self._config.parallel_calls)
        if workers == 1:
            for index, (_, gi) in enumerate(jobs):
                collect(index, self._generate_batch(node_meta, parameters, guidewords[gi]))
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(self._generate_batch, node_meta, parameters, guidewords[gi]): index
                    for index, (_, gi) in enumerate(jobs)
                }
                for future in as_completed(futures):
                    collect(futures[future], future.result())

        similarity = consensus.e5_similarity() if runs > 1 else None
        batches: list[dict[str, Any]] = []
        for gi, guideword in enumerate(guidewords):
            run_batches: list[dict[str, Any] | None] = []
            for run in range(runs):
                outcome = outcomes[run * len(guidewords) + gi]
                assert outcome is not None  # 모든 future 가 collect 를 거쳤다
                self.total_cost_usd += outcome[1]
                run_batches.append(outcome[0])
            if runs > 1:
                self.consensus_raw[guideword] = run_batches
                self.consensus_costs[guideword] = [
                    outcomes[run * len(guidewords) + gi][1] for run in range(runs)  # type: ignore[index]
                ]
                batch = consensus.merge_batches(
                    run_batches, self.parameters, similarity, union=self._config.consensus_union
                )
            else:
                batch = run_batches[0]
            if batch is None:
                if parameters:
                    self.review_guidewords.append(guideword)
                continue
            batch["guideword"] = guideword
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
        self.consensus_raw = {}
        self.consensus_costs = {}
        parameters = self._enumerate_parameters(node_meta)
        self.parameter_items = [dict(p) for p in parameters]
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
        if self._config.inference_boundary:
            system = policy.enumerate_rule(system)
        user = _fill(
            user_template,
            {
                "node": node_meta.node or "미상",
                "substance": node_meta.substance,
                "phase": node_meta.phase,
                "P_kPag": _fmt_number(node_meta.P_kPag),
                "T_degC": _fmt_number(node_meta.T_degC),
                "design_P_kPag": _fmt_number(node_meta.design_P_kPag),
                "capacity": node_meta.capacity or "미상",
                "equipment": ", ".join(node_meta.equipment) or "미상",
                "safeguards": self._safeguards_text(node_meta),
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
        system = _fill(system_template, {"rating_scale": self.criteria.prompt_text()})
        boundary = self._config.inference_boundary
        if boundary:  # Z-1: 노드와 무관한 고정 문구라 시스템 끝에 둔다(캐시 유지)
            system = system + "\n\n" + policy.judge_system_block()
        user = _fill(
            user_template,
            {
                "node": node_meta.node or "미상",
                "substance": node_meta.substance,
                "equipment": ", ".join(node_meta.equipment) or "미상",
                "phase": node_meta.phase or "미상",
                "P_kPag": _fmt_number(node_meta.P_kPag),
                "T_degC": _fmt_number(node_meta.T_degC),
                "design_P_kPag": _fmt_number(node_meta.design_P_kPag),
                "capacity": node_meta.capacity or "미상",
                "safeguards": self._safeguards_text(node_meta),
                "guideword": guideword,
                "guideword_definition": GUIDEWORD_DEFINITIONS.get(guideword, ""),
                "n": str(len(parameters)),
                "parameters": "\n".join(
                    f"- {p['name']}: {p['rationale']}" for p in parameters
                ),
            },
        )
        if boundary:  # Z-2: 이 노드에 걸린 유형의 경계표만
            user += "\n\n" + policy.node_block(node_meta.node, node_meta.equipment)
        passages = self._passages_for(node_meta, parameters, guideword)
        if passages:
            block = _split_prompt(_load_prompt("evidence_block.md"))[0]
            user += "\n\n" + _fill(block, {"passages": "\n\n".join(
                f"[{p.chunk_id}] {p.doc_title} {p.locator}\n{p.text}" for p in passages
            )})
        try:
            response = self._client.converse(
                system=system,
                messages=[Message(role="user", content=user)],
                response_schema=batch_schema(self.criteria, with_evidence=bool(passages), boundary=boundary),
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
        batch["_passages"] = {p.chunk_id: p for p in passages}  # 인용 검사의 허용 집합(이번 호출에 보낸 발췌)
        return batch, response.cost_usd

    def _safeguards_text(self, node_meta: NodeMeta) -> str:
        """'기존 안전장치' 칸. 추론 경계를 켜면 빈 칸을 '없음'이 아니라 '미상'으로 보낸다(Z-1)."""
        if self._config.inference_boundary:
            return policy.safeguards_text(node_meta.safeguards, node_meta.safeguards_known)
        return ", ".join(node_meta.safeguards) or "없음"

    def _passages_for(
        self, node_meta: NodeMeta, parameters: list[dict[str, str]], guideword: str
    ) -> list[Passage]:
        """Y-3: 파라미터마다 (물질·설비·파라미터·가이드워드 뜻) 질의로 상위 k, 중복 제거, 호출당 최대 10문단."""
        k = self._config.evidence_k
        if k <= 0:
            return []
        retriever = self._retriever or default_retriever()
        seen: dict[str, Passage] = {}
        for p in parameters:
            query = " ".join([
                node_meta.substance, " ".join(node_meta.equipment), p["name"], guideword,
                GUIDEWORD_DEFINITIONS.get(guideword, ""),
            ])
            for passage in retriever.search(query, k):
                seen.setdefault(passage.chunk_id, passage)
        return list(seen.values())[:10]

    # -- 결과 조립 (R-02·R-05) -----------------------------------------------
    def _assemble(
        self, node_meta: NodeMeta, batches: list[dict[str, Any]]
    ) -> list[DeviationRecord]:
        records, judged = _build_records(node_meta, batches, self.criteria.id)
        self.judged_cells += judged
        return process_order(records, self.parameters)

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
    node_meta: NodeMeta, batches: list[dict[str, Any]], criteria_id: str = GOLD_CRITERIA
) -> tuple[list[DeviationRecord], int]:
    """batch 목록 → (레코드, 판정 셀 수). 생성기 상태를 건드리지 않는다 — 진행 알림의 중간 표가 이걸 쓴다(AC-11-4)."""
    records: list[DeviationRecord] = []
    judged = 0
    prefix = (node_meta.node or "node").lower()
    for batch in batches:
        guideword = str(batch.get("guideword", ""))
        allowed: dict[str, Passage] = batch.get("_passages") or {}
        for cell in batch.get("cells", []):
            judged += 1  # 보류 셀도 판정한 셀이다 — 건너뛴 것이 아니라 판단의 결과(Z-3-5)
            if not cell.get("applicable", False):
                continue
            if cell.get(INSUFFICIENT) or (cell.get("missing") and not _cell_is_complete(cell)):
                # 보류 표시만 하고 이탈 초안을 비우거나, 보류 표시 없이 missing 만 적고 S·F 를 비운 셀도 보류로 받는다 —
                # 10/9 실호출에서 No 행 11셀이 '필수 필드 결측'으로 통째로 버려졌다.
                records.append(_held_record(node_meta, guideword, cell, len(records) + 1, criteria_id))
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
                    **_checked_evidence(cell.get("evidence") or [], allowed),
                    confidence="inferred",
                    criteria_id=criteria_id,
                    consensus=cell.get("_consensus"),
                )
            )
    return records, judged


def _held_record(
    node_meta: NodeMeta, guideword: str, cell: dict[str, Any], seq: int, criteria_id: str
) -> DeviationRecord:
    """정보 부족 보류 행(Z-3). 원인·S·F 는 모델이 적었어도 버린다 — 미상 정보에 달린 값이기 때문이다.

    이탈 초안·결과·권고(예: "~ 유무 확인")와 없어서 보류한 정보만 남긴다. 인용은 보류 행에 붙이지 않는다.
    """
    missing = [str(m).strip() for m in cell.get("missing") or [] if str(m).strip()][:3]
    return DeviationRecord(
        id=f"{(node_meta.node or 'node').lower()}-{seq:03d}",
        node=node_meta.node,
        node_meta=node_meta,
        guideword=guideword,
        parameter=str(cell["parameter"]),
        deviation=str(cell.get("deviation") or "") or HELD_NO_DRAFT,
        consequences=list(cell.get("consequences", [])),
        safeguards_before=_normalize_safeguards(
            node_meta, guideword, str(cell["parameter"]), cell.get("safeguards_before", [])
        ),
        recommendations=list(cell.get("recommendations", [])),
        criteria_id=criteria_id,
        status=INSUFFICIENT,
        missing=missing or ["(모델이 적지 않음)"],
        consensus=cell.get("_consensus"),
    )


def process_order(
    records: list[DeviationRecord], parameters: list[str], *, renumber: bool = True
) -> list[DeviationRecord]:
    """공정 순서(지시문 Y-1): 노드(등장 순서) → 파라미터(열거 순서) → 가이드워드 축 순서. 안정 정렬.

    같은 파라미터의 No·More·Less… 가 붙어 나온다. 열거 목록에 없는 파라미터는 뒤에 등장 순서로,
    축에 없는 가이드워드는 축 뒤에. `renumber` 면 노드별로 id 를 1번부터 다시 매긴다(새 생성 결과) —
    재생 파일을 불러올 때는 파일과 대조할 수 있게 id 를 그대로 둔다.
    """
    axis = STANDARD_GUIDEWORDS + PROCEDURAL_GUIDEWORDS
    nodes = list(dict.fromkeys(r.node for r in records))
    params = list(dict.fromkeys([*parameters, *(r.parameter for r in records)]))
    ordered = sorted(records, key=lambda r: (
        nodes.index(r.node),
        params.index(r.parameter),
        axis.index(r.guideword) if r.guideword in axis else len(axis),
    ))
    if not renumber:
        return ordered
    seq: dict[str, int] = {}
    out: list[DeviationRecord] = []
    for r in ordered:
        seq[r.node] = seq.get(r.node, 0) + 1
        out.append(r.model_copy(update={"id": f"{(r.node or 'node').lower()}-{seq[r.node]:03d}"}))
    return out


def _checked_evidence(raw: list[Any], allowed: dict[str, Passage]) -> dict[str, list[Any]]:
    """인용 계약(Y-3-3): 이번 호출에 보낸 발췌의 id 이고 구절이 그 원문의 부분 문자열인 것만 남긴다.

    어긋난 인용은 지우고 `citation_flags` 에 남긴다 — 검증기가 그 행을 review 로 내린다(조용히 통과 금지).
    """
    evidence: list[Any] = []
    flags: list[str] = []
    for item in raw:
        sid, quote = str(item.get("source_id", "")), str(item.get("quote", ""))
        passage = check_citation(sid, quote, allowed)
        if passage is None:
            flags.append(f"{sid}: {quote[:40]}")
        elif all(e["source_id"] != sid or e["quote"] != quote for e in evidence):
            evidence.append(passage.evidence(quote))
    return {"evidence": evidence, "citation_flags": flags}


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
