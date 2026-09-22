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
_PROVIDERS = frozenset({"bedrock", "anthropic"})


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


def _read_provider(raw: dict[str, Any]) -> str:
    """REQ-12. 누락 시 기본값 `bedrock` — 기존 models.yaml 은 그대로 동작한다."""
    provider = str(raw.get("provider") or "bedrock").strip().lower()
    if provider not in _PROVIDERS:
        raise ConfigValidationError(f"provider must be one of {sorted(_PROVIDERS)}: {provider!r}")
    return provider


def _validate_raw(raw: dict[str, Any]) -> None:
    provider = _read_provider(raw)
    # region·embedding·guardrails 는 Bedrock 전용 필드다. provider=anthropic 이면
    # 비어 있어도 통과시킨다(REQ-12). provider=bedrock 검증 규칙은 현행 유지.
    bedrock_only = provider == "bedrock"

    required_top = {"generation", "verifier"} | ({"region", "embedding"} if bedrock_only else set())
    missing = sorted(required_top - raw.keys())
    if missing:
        raise ConfigValidationError(f"missing fields: {missing}")

    empty: list[str] = []
    required_ids = ["generation", "verifier"] + (["embedding"] if bedrock_only else [])
    if bedrock_only and not str(raw.get("region") or "").strip():
        empty.append("region")
    for key in required_ids:
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
        region=str(raw.get("region") or ""),
        generation=_profile(raw["generation"]),
        verifier=_profile(raw["verifier"]),
        embedding_model_id=str((raw.get("embedding") or {}).get("model_id") or ""),
        guardrails_id=(raw.get("guardrails") or {}).get("id"),
        cost_limit_usd=float(raw.get("cost_limit_usd", 0.30)),
        provider=_read_provider(raw),  # type: ignore[arg-type]
    )


def _profile(section: dict[str, Any]) -> ModelProfile:
    return ModelProfile(
        model_id=str(section["model_id"]),
        temperature=float(section.get("temperature", 0.0)),
        max_tokens=int(section.get("max_tokens", 4096)),
        prompt_caching=bool(section.get("prompt_caching", False)),
    )
