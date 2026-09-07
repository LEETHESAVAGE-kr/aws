"""`config/models.yaml` 로드와 검증 — REQ-01 (design.md §4).

모델 ID·리전은 이 모듈을 통해서만 읽는다(steering `aws.md` §2, CLAUDE.md 불변규칙 3).
`model_id` 가 비어 있으면(G0 미완료) 누락 필드와 동일하게 취급하여 즉시 실패한다 —
값을 추측해 채우지 않는다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .types import ModelConfig, ModelProfile

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "models.yaml"
_G0_HINT = "config/models.yaml 미완성 — docs/G0_bedrock_access_*.md 참조(모델 ID 확정 후 기입)"


class ConfigValidationError(ValueError):
    """models.yaml 필수 필드 누락 또는 값 범위 오류."""


@lru_cache(maxsize=8)
def load_model_config(path: Path = _CONFIG_PATH) -> ModelConfig:
    """`models.yaml` 을 읽어 `ModelConfig` 로 반환한다(경로별 1회 캐시)."""
    if not path.is_file():
        raise ConfigValidationError(f"config file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigValidationError(f"config must be a mapping: {path}")
    _validate_raw(raw)
    return _parse(raw)


def _validate_raw(raw: dict[str, Any]) -> None:
    required_top = {"region", "generation", "verifier", "embedding"}
    missing = sorted(required_top - raw.keys())
    if missing:
        raise ConfigValidationError(f"missing fields: {missing}")

    empty: list[str] = []
    if not str(raw.get("region") or "").strip():
        empty.append("region")
    for key in ("generation", "verifier", "embedding"):
        section = raw[key]
        if not isinstance(section, dict):
            raise ConfigValidationError(f"missing fields: ['{key}.model_id']")
        if not str(section.get("model_id") or "").strip():
            empty.append(f"{key}.model_id")
    if empty:
        raise ConfigValidationError(f"missing fields: {sorted(empty)} — {_G0_HINT}")

    for key in ("generation", "verifier"):
        temperature = raw[key].get("temperature", -1)
        if not isinstance(temperature, int | float) or not 0.0 <= float(temperature) <= 1.0:
            raise ConfigValidationError(f"{key}.temperature must be 0.0–1.0")


def _parse(raw: dict[str, Any]) -> ModelConfig:
    return ModelConfig(
        region=str(raw["region"]),
        generation=_profile(raw["generation"]),
        verifier=_profile(raw["verifier"]),
        embedding_model_id=str(raw["embedding"]["model_id"]),
        guardrails_id=(raw.get("guardrails") or {}).get("id"),
        cost_limit_usd=float(raw.get("cost_limit_usd", 0.30)),
    )


def _profile(section: dict[str, Any]) -> ModelProfile:
    return ModelProfile(
        model_id=str(section["model_id"]),
        temperature=float(section.get("temperature", 0.0)),
        max_tokens=int(section.get("max_tokens", 4096)),
        prompt_caching=bool(section.get("prompt_caching", False)),
    )
