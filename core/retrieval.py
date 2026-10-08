"""근거 검색(RAG) — 지시문 Y-3. 공식 문서 발췌 코퍼스에서 셀 질의에 맞는 문단을 찾는다.

코퍼스: `data/kb/law/*.json`(법령·고시 원문 조문 — 저작권법 제7조), 목록 `data/kb/manifest.csv`.
검색: 키워드(BM25, 한글 글자 2-gram) + 다국어 임베딩(multilingual-e5-small ONNX) 을 순위 융합(RRF).
모델 파일이 없으면 BM25 만으로 돈다(`mode == "bm25"`) — 배포 메모리·네트워크가 막혀도 검색은 된다(Q2).
LLM 을 부르지 않는다. 인용 검사(`check_citation`)도 여기 있다 — 인용문은 이 코퍼스 원문의 부분 문자열이어야 한다.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import urllib.request
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
CORPUS_DIRS: Final[tuple[Path, ...]] = (_ROOT / "data" / "kb" / "law", _ROOT / "data" / "kb" / "msds")
INDEX_PATH: Final[Path] = _ROOT / "data" / "kb" / "embeddings.npz"
MODEL_DIR: Final[Path] = Path(os.environ.get("HAZOP_EMBED_DIR", _ROOT / "models" / "multilingual-e5-small"))
#: 실행 시 내려받는 위치(118MB 라 저장소에 넣지 않는다). sha256 은 10/9 내려받은 파일 값.
MODEL_FILES: Final[dict[str, tuple[str, str]]] = {
    "model_quantized.onnx": (
        "https://huggingface.co/Xenova/multilingual-e5-small/resolve/main/onnx/model_quantized.onnx",
        "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193",
    ),
    "tokenizer.json": (
        "https://huggingface.co/Xenova/multilingual-e5-small/resolve/main/tokenizer.json",
        "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    ),
}
RRF_K: Final[int] = 60
_WS: Final = re.compile(r"\s+")
_TOKEN: Final = re.compile(r"[0-9A-Za-z]+|[가-힣]+")


@dataclass(frozen=True)
class Passage:
    chunk_id: str
    source_id: str
    doc_title: str
    issuer: str
    locator: str
    text: str
    url: str

    def evidence(self, quote: str) -> dict[str, str]:
        """산출물 `evidence[]` 항목 — 제목·위치는 코퍼스에서 채운다(모델이 쓰지 않는다)."""
        return {"source_id": self.chunk_id, "doc_title": self.doc_title, "issuer": self.issuer,
                "locator": self.locator, "quote": quote}


def normalize(text: str) -> str:
    return _WS.sub(" ", text).strip()


def tokens(text: str) -> list[str]:
    """영숫자 단어 + 한글 덩어리의 글자 2-gram(형태소 분석기 없이 조사 붙은 낱말도 겹치게)."""
    out: list[str] = []
    for t in _TOKEN.findall(text.lower()):
        if t[0] >= "가" and len(t) > 1:
            out.extend(t[i:i + 2] for i in range(len(t) - 1))
        else:
            out.append(t)
    return out


@cache
def load_corpus() -> tuple[Passage, ...]:
    passages: list[Passage] = []
    for directory in CORPUS_DIRS:
        for path in sorted(directory.glob("*.json")):
            for e in json.loads(path.read_text(encoding="utf-8")):
                passages.append(Passage(
                    chunk_id=str(e.get("chunk_id") or e["source_id"]), source_id=str(e["source_id"]),
                    doc_title=str(e["doc_title"]), issuer=str(e.get("issuer", "")), locator=str(e["locator"]),
                    text=normalize(str(e["text"])), url=str(e.get("url", "")),
                ))
    return tuple(passages)


class _BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = sum(self.len) / max(len(docs), 1)
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, length in zip(self.tf, self.len, strict=True):
            s = 0.0
            for t in query:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self.avg))
            out.append(s)
        return out


class _Embedder:
    """multilingual-e5-small — 'query: '/'passage: ' 접두, 평균 풀링, L2 정규화."""

    def __init__(self, model_dir: Path) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tok.enable_truncation(512)
        self.tok.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.sess = ort.InferenceSession(str(model_dir / "model_quantized.onnx"), options)
        self.inputs = {i.name for i in self.sess.get_inputs()}

    def encode(self, texts: list[str], prefix: str) -> Any:
        import numpy as np

        out = []
        for i in range(0, len(texts), 16):
            enc = self.tok.encode_batch([prefix + t for t in texts[i:i + 16]])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self.sess.run(None, feed)[0]
            pooled = (hidden * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
            out.append(pooled / np.linalg.norm(pooled, axis=1, keepdims=True))
        return np.concatenate(out) if out else np.zeros((0, 384), dtype=np.float32)


def ensure_model(model_dir: Path = MODEL_DIR) -> bool:
    """모델 파일이 없으면 내려받는다(`HAZOP_EMBED_DOWNLOAD=false` 면 받지 않음). sha256 이 다르면 버린다."""
    import hashlib

    if all((model_dir / n).exists() for n in MODEL_FILES):
        return True
    if os.environ.get("HAZOP_EMBED_DOWNLOAD", "true").strip().lower() != "true":
        return False
    try:
        model_dir.mkdir(parents=True, exist_ok=True)
        for name, (url, sha) in MODEL_FILES.items():
            dst = model_dir / name
            if dst.exists():
                continue
            tmp = dst.with_suffix(".part")
            urllib.request.urlretrieve(url, tmp)  # noqa: S310 — 고정 URL(huggingface.co)
            if hashlib.sha256(tmp.read_bytes()).hexdigest() != sha:
                tmp.unlink()
                raise ValueError(f"{name} sha256 불일치")
            tmp.replace(dst)
        return True
    except Exception:  # noqa: BLE001 — 내려받기 실패는 BM25 로 계속
        logger.warning("임베딩 모델 준비 실패 — BM25 만으로 검색한다", exc_info=True)
        return False


class Retriever:
    """코퍼스 검색기. `mode` 는 "hybrid"(BM25+임베딩) 또는 "bm25"."""

    def __init__(self, passages: tuple[Passage, ...] | None = None, *, use_embeddings: bool = True) -> None:
        self.passages = load_corpus() if passages is None else passages
        self.bm25 = _BM25([tokens(p.doc_title + " " + p.locator + " " + p.text) for p in self.passages])
        self.embedder: _Embedder | None = None
        self.matrix: Any = None
        if use_embeddings and self.passages and ensure_model():
            try:
                self.embedder = _Embedder(MODEL_DIR)
                self.matrix = self._passage_matrix()
            except Exception:  # noqa: BLE001
                logger.warning("임베딩 초기화 실패 — BM25 만으로 검색한다", exc_info=True)
                self.embedder = None
        self.mode = "hybrid" if self.embedder is not None else "bm25"

    def _passage_matrix(self) -> Any:
        """미리 계산한 코퍼스 임베딩(`embeddings.npz`)이 이 코퍼스와 같으면 그걸, 아니면 지금 계산."""
        import numpy as np

        assert self.embedder is not None
        ids = [p.chunk_id for p in self.passages]
        if INDEX_PATH.exists():
            saved = np.load(INDEX_PATH, allow_pickle=False)
            if list(saved["ids"]) == ids and str(saved["digest"]) == corpus_digest(self.passages):
                return saved["vectors"].astype(np.float32)
        return self.embedder.encode([p.doc_title + " " + p.text for p in self.passages], "passage: ")

    def search(self, query: str, k: int = 3) -> list[Passage]:
        if not self.passages:
            return []
        bm = self.bm25.scores(tokens(query))
        ranks: dict[int, float] = {}
        for rank, i in enumerate(sorted(range(len(bm)), key=lambda i: -bm[i])[:50]):
            if bm[i] > 0:
                ranks[i] = ranks.get(i, 0.0) + 1 / (RRF_K + rank)
        if self.embedder is not None:
            q = self.embedder.encode([query], "query: ")[0]
            sims = self.matrix @ q
            for rank, i in enumerate(sorted(range(len(sims)), key=lambda i: -sims[i])[:50]):
                ranks[i] = ranks.get(i, 0.0) + 1 / (RRF_K + rank)
        best = sorted(ranks, key=lambda i: (-ranks[i], i))[:k]
        return [self.passages[i] for i in best]


@cache
def default_retriever() -> Retriever:
    """프로세스당 1개(모델 적재 약 2초) — Streamlit 세션·병렬 판정이 같이 쓴다(onnxruntime run 은 스레드 안전)."""
    return Retriever()


def corpus_digest(passages: tuple[Passage, ...]) -> str:
    import hashlib

    return hashlib.sha256("\n".join(p.chunk_id + "\t" + p.text for p in passages).encode("utf-8")).hexdigest()


def build_index(path: Path = INDEX_PATH) -> int:
    """코퍼스 임베딩을 미리 계산해 저장한다(배포 앱은 질의만 임베딩). 반환: 문단 수."""
    import numpy as np

    passages = load_corpus()
    if not ensure_model():
        raise RuntimeError("임베딩 모델이 없다")
    vectors = _Embedder(MODEL_DIR).encode([p.doc_title + " " + p.text for p in passages], "passage: ")
    np.savez_compressed(path, ids=np.array([p.chunk_id for p in passages]), vectors=vectors.astype(np.float16),
                        digest=np.array(corpus_digest(passages)))
    return len(passages)


def check_citation(chunk_id: str, quote: str, allowed: dict[str, Passage]) -> Passage | None:
    """인용 계약(Y-3-3): `chunk_id` 가 허용 집합에 있고 `quote` 가 그 원문의 부분 문자열(공백 정규화)이면 그 문단."""
    passage = allowed.get(chunk_id)
    q = normalize(quote)
    if passage is None or len(q) < 8 or q not in passage.text:
        return None
    return passage


__all__ = [
    "Passage", "Retriever", "build_index", "check_citation", "default_retriever", "load_corpus", "normalize", "tokens",
]
