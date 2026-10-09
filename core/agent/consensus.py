"""합의 생성(PRD 본선 추론근거 §8 C, self-consistency) — 가이드워드 판정 N회 → 셀 투표 · 문장 합의.

규칙 정본은 `docs/사전등록_C_합의생성_20261009.md` §1. 이 모듈은 LLM 을 부르지 않는다 — 생성기가 모은
N개의 판정 묶음(batch)을 한 묶음으로 합친다. 합친 셀은 기존 `_build_records` 가 그대로 레코드로 만들고,
투표·문장 일치 내역은 셀의 `_consensus` 에 실려 `DeviationRecord.consensus` 로 간다.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any, Final

logger = logging.getLogger(__name__)

#: 문장 짝짓기 e5 코사인 문턱 — 사전등록 §1(9/29 재캡처로 보정, PRD 후보 0.85 에서 바꿈).
TAU: Final[float] = 0.92
APPLICABLE, NOT_APPLICABLE, HELD, MISSING = "applicable", "not_applicable", "insufficient", "missing"
#: 동률로 보류가 된 셀의 '없는 정보' 칸 — 모델이 적은 것이 아니라 코드가 붙인 사유.
SPLIT_REASON: Final[str] = "반복 실행 간 판정이 갈림"
LIST_FIELDS: Final[tuple[str, ...]] = ("causes", "consequences", "recommendations")

#: 문장 목록 → 유사도 행렬(행 i·열 j = 코사인). None 이면 정규화 문자열 일치만 쓴다.
Similarity = Callable[[list[str]], Any]


def norm_param(name: str) -> str:
    """셀 키 — 모델이 파라미터 이름을 조금 바꿔 되돌려도(공백·괄호) 같은 칸으로 본다."""
    return re.sub(r"[\s()（）·/,_-]+", "", str(name)).lower()


def _norm_text(text: str) -> str:
    return re.sub(r"[\s.,·()（）\"'`]+", "", str(text)).lower()


def cell_state(cell: dict[str, Any] | None) -> str:
    """한 실행의 셀 상태. `_build_records` 의 분기와 같은 조건이어야 한다(보류·완전·결측)."""
    if cell is None:
        return MISSING
    if not cell.get("applicable", False):
        return NOT_APPLICABLE
    complete = bool(cell.get("deviation")) and cell.get("S") is not None and cell.get("F") is not None
    if cell.get(HELD) or (cell.get("missing") and not complete):
        return HELD
    return APPLICABLE if complete else MISSING


def vote(states: Sequence[str]) -> str | None:
    """`누락`을 뺀 다수결. 최다가 둘 이상이면 정보 부족(덜하는 쪽). 전부 누락이면 None(판정 안 한 셀)."""
    counts = Counter(s for s in states if s != MISSING)
    if not counts:
        return None
    top = max(counts.values())
    winners = [s for s, c in counts.items() if c == top]
    return winners[0] if len(winners) == 1 else HELD


def cells_by_param(batch: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """batch → {정규화 파라미터: 셀}. 같은 파라미터가 두 번 오면 첫 셀."""
    out: dict[str, dict[str, Any]] = {}
    for cell in (batch or {}).get("cells", []):
        out.setdefault(norm_param(cell.get("parameter", "")), cell)
    return out


def cluster_sentences(
    per_run: Sequence[Sequence[str]], n_runs: int, similarity: Similarity | None, tau: float = TAU
) -> list[dict[str, Any]]:
    """실행별 문장 목록 → 묶음 [{text, agree, runs}]. 순서: agree 내림차순, 같으면 처음 나온 순서.

    실행 순서대로 훑어, 이 실행의 문장이 아직 없는 기존 묶음 중 대표 문장과 가장 비슷한 것(≥ τ 또는
    정규화 일치)에 넣는다. 대표 문장은 묶음의 첫 문장이다.
    """
    flat = [(run, str(t)) for run, texts in enumerate(per_run) for t in texts if str(t).strip()]
    if not flat:
        return []
    matrix = similarity([t for _, t in flat]) if similarity is not None and len(flat) > 1 else None
    clusters: list[dict[str, Any]] = []  # {"rep": flat index, "runs": set}
    for i, (run, text) in enumerate(flat):
        best, best_sim = None, -1.0
        for c in clusters:
            if run in c["runs"]:
                continue
            rep = c["rep"]
            same = _norm_text(flat[rep][1]) == _norm_text(text)
            sim = 1.0 if same else (float(matrix[i][rep]) if matrix is not None else -1.0)
            if (same or sim >= tau) and sim > best_sim:
                best, best_sim = c, sim
        if best is None:
            clusters.append({"rep": i, "runs": {run}})
        else:
            best["runs"].add(run)
    ordered = sorted(enumerate(clusters), key=lambda ic: (-len(ic[1]["runs"]), ic[0]))
    return [
        {"text": flat[c["rep"]][1], "agree": len(c["runs"]), "runs": sorted(c["runs"]), "of": n_runs}
        for _, c in ordered
    ]


def kept(agree: int, n_runs: int) -> bool:
    """워크시트에 남길 문장 — agree/N ≥ 2/3."""
    return 3 * agree >= 2 * n_runs


def merge_batches(
    runs: Sequence[dict[str, Any] | None],
    parameters: Sequence[str],
    similarity: Similarity | None = None,
    tau: float = TAU,
) -> dict[str, Any] | None:
    """한 가이드워드의 N개 판정 묶음 → 합친 묶음. 전부 실패면 None(그 가이드워드는 review).

    합친 셀은 기존 레코드 조립 규칙을 그대로 탄다: 해당 셀은 완전한 셀, 보류 셀은 `insufficient`+`missing`,
    해당 없음은 `applicable=false`. 셀마다 `_consensus` 에 투표·문장 일치 내역을 싣는다.
    """
    n = len(runs)
    alive = [b for b in runs if b is not None]
    if not alive:
        return None
    by_run = [cells_by_param(b) for b in runs]
    order = list(dict.fromkeys([norm_param(p) for p in parameters] + [k for m in by_run for k in m]))
    passages: dict[str, Any] = {}
    for b in alive:
        passages.update(b.get("_passages") or {})
    cells: list[dict[str, Any]] = []
    for key in order:
        run_cells = [m.get(key) for m in by_run]
        states = [cell_state(c) for c in run_cells]
        winner = vote(states)
        if winner is None:
            continue  # 세 실행 모두 누락 — 판정하지 않은 셀(커버리지 경고로 드러난다)
        votes = dict(Counter(states))
        name = next(str(c["parameter"]) for c in run_cells if c is not None)
        meta: dict[str, Any] = {"runs": n, "votes": votes, "states": states}
        if winner == NOT_APPLICABLE:
            cells.append({"parameter": name, "applicable": False, "_consensus": meta})
        elif winner == HELD:
            cells.append(_held_cell(name, run_cells, states, meta))
        else:
            cells.append(_applicable_cell(name, run_cells, states, meta, n, similarity, tau))
    return {"guideword": alive[0].get("guideword", ""), "cells": cells, "_passages": passages}


def _held_cell(
    name: str, run_cells: list[dict[str, Any] | None], states: list[str], meta: dict[str, Any]
) -> dict[str, Any]:
    held = [c for c, s in zip(run_cells, states, strict=True) if s == HELD and c is not None]
    base = dict(held[0]) if held else dict(next(
        c for c, s in zip(run_cells, states, strict=True) if s == APPLICABLE and c is not None
    ))
    missing = list(dict.fromkeys(str(m).strip() for c in held for m in c.get("missing") or [] if str(m).strip()))
    if not held:  # 아무 실행도 보류하지 않았는데 동률로 보류 — 이유는 코드가 적는다
        missing = [SPLIT_REASON]
    elif len(held) < sum(s != MISSING for s in states):
        missing = [*missing[:2], SPLIT_REASON]
    base.update({"parameter": name, "applicable": True, HELD: True, "missing": missing[:3], "_consensus": meta})
    return base


def _applicable_cell(
    name: str,
    run_cells: list[dict[str, Any] | None],
    states: list[str],
    meta: dict[str, Any],
    n: int,
    similarity: Similarity | None,
    tau: float,
) -> dict[str, Any]:
    used = [c for c, s in zip(run_cells, states, strict=True) if s == APPLICABLE and c is not None]
    base = dict(used[0])
    for field in LIST_FIELDS:
        clusters = cluster_sentences([c.get(field) or [] for c in used], n, similarity, tau)
        meta[field] = clusters
        base[field] = [c["text"] for c in clusters if kept(c["agree"], n)]
    for grade in ("S", "F"):
        values = sorted(int(c[grade]) for c in used)
        meta[f"{grade}_values"] = values
        base[grade] = values[len(values) // 2]  # 짝수 개면 위쪽 — 위험을 낮춰 잡지 않는다
    base["safeguards_before"] = list(dict.fromkeys(s for c in used for s in c.get("safeguards_before") or []))
    evidence: list[Any] = []
    for c in used:
        for e in c.get("evidence") or []:
            if e not in evidence:
                evidence.append(e)
    base["evidence"] = evidence
    base.update({"parameter": name, "_consensus": meta})
    base.pop(HELD, None)
    base.pop("missing", None)
    return base


# ── 문장 유사도(e5) ─────────────────────────────────────────────────────────────
_embedder: Any = None


def e5_similarity() -> Similarity | None:
    """검색기와 같은 e5 모델로 코사인 행렬. 모델을 못 쓰면 None — 정규화 문자열 일치로만 짝짓는다(경고)."""
    global _embedder
    if _embedder is None:
        try:
            from core.retrieval import MODEL_DIR, _Embedder, ensure_model

            if not ensure_model():
                raise RuntimeError("e5 모델 없음")
            _embedder = _Embedder(MODEL_DIR)
        except Exception:  # noqa: BLE001 — 합의는 문자열 일치로 계속한다
            logger.warning("e5 임베딩을 못 써 문장 합의를 정규화 문자열 일치로만 한다", exc_info=True)
            _embedder = False
    if _embedder is False:
        return None
    return _cached_similarity()


def _cached_similarity() -> Similarity:
    """노드 1건(합의 1회)마다 새 캐시 — 프로세스 전역으로 쌓이지 않게."""

    import numpy as np

    cache: dict[str, Any] = {}  # 문장 → 벡터. 한 실행 안에서 같은 문장을 다시 인코딩하지 않는다

    def similarity(texts: list[str]) -> Any:
        new = [t for t in dict.fromkeys(texts) if t not in cache]
        if new:
            cache.update(zip(new, _embedder.encode(new, "query: "), strict=True))
        vectors = np.stack([cache[t] for t in texts])
        return vectors @ vectors.T

    return similarity


__all__ = [
    "APPLICABLE", "HELD", "MISSING", "NOT_APPLICABLE", "SPLIT_REASON", "TAU",
    "cell_state", "cells_by_param", "cluster_sentences", "e5_similarity", "kept", "merge_batches",
    "norm_param", "vote",
]
