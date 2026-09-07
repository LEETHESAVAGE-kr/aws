"""실 Bedrock 호출 스모크 테스트 — REQ-11 / G0 킬체크 (T-12).

`pytest -m live` 로만 실행된다. 기본 `pytest -m "not live"` 에서는 수집되지 않는다.
2026-09-06 현재 자격증명과 모델 ID 가 모두 없어 skip 된다 — **미검증 경로다.**
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.llm import BedrockClient, ConfigValidationError, Message, load_model_config  # noqa: E402

pytestmark = pytest.mark.live


def _has_credentials() -> bool:
    if os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE"):
        return True
    try:
        import boto3

        boto3.client("sts").get_caller_identity()
    except Exception:  # noqa: BLE001 — 자격증명 유무 판정에만 쓴다
        return False
    return True


def test_smoke_live_converse() -> None:
    """실제 Bedrock Converse API 1회 호출 — G0 킬체크 통과 조건."""
    if not _has_credentials():
        pytest.skip("AWS credentials not set")
    try:
        load_model_config()
    except ConfigValidationError as exc:
        pytest.skip(f"config/models.yaml 미완성 — G0 미완료: {exc}")

    client = BedrockClient()
    response = client.converse(
        system="당신은 공정안전 전문가입니다.",
        messages=[Message(role="user", content="안녕하세요")],
        context={"node": "smoke"},
    )
    assert response.stop_reason == "end_turn"
    assert response.cost_usd > 0
    assert response.latency_s > 0
