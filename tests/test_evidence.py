"""지시문 Y-3 근거 인용(RAG) · Y-4 신뢰도 4단계 — 오프라인(임베딩 없이 BM25 검색기로)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from core.agent import HazopGenerator, NodeMeta, verify
from core.agent.generate import GeneratorConfig
from core.criteria import OFFICIAL_CRITERIA
from core.llm import ConverseResponse, Message, MockBedrockClient
from core.retrieval import Passage, Retriever, check_citation, load_corpus, normalize

_ROOT = Path(__file__).parent.parent
_META = NodeMeta(node="X1", substance="수소", phase="gas", equipment=["압축기", "고압 저장용기"], safeguards=["안전밸브"])
_PARAMS = ["압력", "온도", "유량", "준위", "조성", "누출"]
_GW = ("No", "More", "Less", "Reverse", "Other than", "Part of", "As well as")


# ── 코퍼스 ────────────────────────────────────────────────────────────────────
def test_corpus_is_laws_and_notices_only_with_manifest() -> None:
    """이용 조건 확인된 문서만(불변 규칙 1·R1): 법령·고시(저작권법 제7조). KOSHA 지침은 넣지 않았다."""
    corpus = load_corpus()
    assert len(corpus) >= 150 and len({p.chunk_id for p in corpus}) == len(corpus)
    rows = list(csv.DictReader((_ROOT / "data" / "kb" / "manifest.csv").open(encoding="utf-8")))
    assert {r["code"] for r in rows} == {p.source_id for p in corpus}
    assert all("저작권법 제7조" in r["license"] for r in rows)
    for path in (_ROOT / "data" / "kb" / "law").glob("*.json"):
        for e in json.loads(path.read_text(encoding="utf-8")):
            assert e["url"].startswith("https://www.law.go.kr/") and e["locator"] and e["version"]
    assert not any("KOSHA" in p.source_id for p in corpus)


def test_retriever_finds_safety_valve_article_for_overpressure() -> None:
    hits = Retriever(use_embeddings=False).search("수소 압축기 압력 More 정량적 증가 안전밸브 과압", 3)
    assert any("안전밸브" in p.text for p in hits)


# ── 인용 계약 ─────────────────────────────────────────────────────────────────
_P = Passage("LAW-T#1", "LAW-T", "시험 규칙", "고용노동부", "제1조", normalize("사업주는 과압에 따른 폭발을  방지하기 위하여 안전밸브를 설치하여야 한다."), "")


@pytest.mark.parametrize(("sid", "quote", "ok"), [
    ("LAW-T#1", "과압에 따른 폭발을 방지하기 위하여", True),
    ("LAW-T#1", "과압에 따른  폭발을\n방지하기", True),  # 공백 차이는 같은 글
    ("LAW-T#1", "과압으로 인한 폭발을 방지하기 위하여", False),  # 바꿔 쓰기
    ("LAW-T#1", "안전밸브", False),  # 8자 미만 — 낱말 하나로는 근거가 아니다
    ("LAW-T#2", "과압에 따른 폭발을 방지하기 위하여", False),  # 이번 호출에 보내지 않은 id
])
def test_check_citation(sid: str, quote: str, ok: bool) -> None:
    assert (check_citation(sid, quote, {_P.chunk_id: _P}) is not None) == ok


def _factory(evidence_for: Any) -> Any:
    """판정 호출의 사용자 턴에서 발췌 id·원문을 읽어 `evidence_for(passages)` 가 정한 인용을 넣는다."""

    def make(system: str, messages: list[Message], **_: Any) -> ConverseResponse:
        if "파라미터 축" in system:
            return ConverseResponse(content=json.dumps({"parameters": [{"name": n, "rationale": "r"} for n in _PARAMS]}))
        user = str(messages[0].content)
        gw = next(g for g in _GW if f"\n{g} —" in user)
        ids = [line[1:line.index("]")] for line in user.splitlines() if line.startswith("[") and "]" in line]
        corpus = {p.chunk_id: p for p in load_corpus()}
        cells = [{"parameter": n, "applicable": True, "deviation": f"{n} 이탈", "causes": ["c"], "consequences": ["r"],
                  "safeguards_before": [], "S": 3, "F": 2, "recommendations": ["점검"],
                  "evidence": evidence_for([corpus[i] for i in ids]), "confidence": "inferred"} for n in _PARAMS]
        return ConverseResponse(content=json.dumps({"guideword": gw, "cells": cells}, ensure_ascii=False))

    return make


def _run(evidence_for: Any, k: int = 2) -> tuple[HazopGenerator, MockBedrockClient, list[Any]]:
    client = MockBedrockClient(response_factory=_factory(evidence_for))
    gen = HazopGenerator(client, GeneratorConfig(evidence_k=k), criteria_id=OFFICIAL_CRITERIA,
                         retriever=Retriever(use_embeddings=False))
    records = gen.generate(_META)
    return gen, client, verify(records)[0]


def _quote(p: Passage) -> str:
    return p.text[:30]


def test_evidence_off_keeps_prompt_and_schema() -> None:
    _, client, out = _run(lambda ps: [], k=0)
    judge = client.calls[1]
    assert "참고 발췌" not in judge["messages"][0].content
    assert judge["response_schema"]["properties"]["cells"]["items"]["properties"]["evidence"]["maxItems"] == 0
    assert {r.confidence for r in out} == {"inferred"}


def test_valid_quotes_become_evidence_with_corpus_metadata() -> None:
    _, client, out = _run(lambda ps: [{"source_id": ps[0].chunk_id, "quote": _quote(ps[0])}])
    user = client.calls[1]["messages"][0].content
    assert "참고 발췌" in user and "한 글자도 바꾸지 않은" in user
    e = out[0].evidence[0]
    assert e["doc_title"] and e["locator"] and e["quote"] == _quote(load_corpus_by_id()[e["source_id"]])
    assert {r.confidence for r in out} == {"single_source"}


def load_corpus_by_id() -> dict[str, Passage]:
    return {p.chunk_id: p for p in load_corpus()}


def test_two_documents_make_grounded() -> None:
    def pick(ps: list[Passage]) -> list[dict[str, str]]:
        by_doc: dict[str, Passage] = {}
        for p in ps:
            by_doc.setdefault(p.source_id, p)
        return [{"source_id": p.chunk_id, "quote": _quote(p)} for p in list(by_doc.values())[:2]]

    _, _, out = _run(pick)
    multi = [r for r in out if len({e["source_id"].split("#")[0] for e in r.evidence}) >= 2]
    assert multi and all(r.confidence == "grounded" for r in multi)


@pytest.mark.parametrize("fake", [
    lambda ps: [{"source_id": ps[0].chunk_id, "quote": _quote(ps[0])[:-2] + "였음"}],  # 끝 두 글자를 바꾼 구절
    lambda ps: [{"source_id": "LAW-OSH-STD-RULE#9999", "quote": "사업주는 안전밸브를 설치하여야 한다"}],  # 없는 id
    lambda ps: [{"source_id": next(p.chunk_id for p in load_corpus() if p.chunk_id not in {q.chunk_id for q in ps}),
                 "quote": _quote(next(p for p in load_corpus() if p.chunk_id not in {q.chunk_id for q in ps}))}],  # 안 보낸 발췌
])
def test_fabricated_citation_is_removed_and_flagged_review(fake: Any) -> None:
    """결함 재삽입: 가짜 인용은 지워지고 그 행은 🔴 review — 조용히 통과하지 않는다."""
    _, _, out = _run(fake)
    assert out and all(r.evidence == [] and r.citation_flags for r in out)
    assert {r.confidence for r in out} == {"review"}
    _, summary = verify(out)
    assert summary.by_rule["fabricated_citation"] == len(out)


def test_standard_number_backed_by_evidence_is_not_flagged() -> None:
    """본문에 '산업안전보건기준에 관한 규칙 제261조' 를 써도 그 조를 인용했으면 근거 있음(R-01 과 맞물림)."""
    corpus = load_corpus_by_id()
    p261 = next(p for p in corpus.values() if p.locator.startswith("제261조"))
    _, _, out = _run(lambda ps: [])
    rec = out[0].model_copy(update={
        "recommendations": ["산업안전보건기준에 관한 규칙 제261조에 따라 안전밸브 점검"],
        "evidence": [p261.evidence(p261.text[:30])], "confidence": "inferred",
    })
    assert verify([rec])[0][0].confidence == "single_source"
    bare = rec.model_copy(update={"evidence": []})
    assert verify([bare])[0][0].confidence == "review"
