"""실 LLM 호출 스모크 테스트 — REQ-11 / G0 킬체크 (T-12).

`pytest -m live` 로만 실행된다. 기본 `pytest -m "not live"` 에서는 수집되지 않는다.

2026-09-28 (지시문 E-2 0단계): `provider` 를 보고 자격증명 판정과 클라이언트 선택을 모두 분기하도록
고쳤다. 그 전에는 AWS 자격증명만 보고 `BedrockClient` 를 직접 만들었기 때문에, `provider=anthropic`
에서는 항상 skip 되고(자격증명 판정 실패) 설령 통과시켜도 Bedrock 경로로 가서 틀린 것을 재던 셈이었다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.llm import (  # noqa: E402
    ConfigValidationError,
    Message,
    get_bedrock_client,
    load_model_config,
)

pytestmark = pytest.mark.live


def _has_credentials(provider: str) -> bool:
    """공급자별 자격증명 유무 (REQ-12).

    `anthropic` 은 SDK 가 `ANTHROPIC_API_KEY` 환경변수만 읽으므로(AC-12-3) 그 유무가 곧 판정이다.
    키 값은 읽지 않는다 — 존재 여부만 본다.
    """
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE"):
        return True
    try:
        import boto3

        boto3.client("sts").get_caller_identity()
    except Exception:  # noqa: BLE001 — 자격증명 유무 판정에만 쓴다
        return False
    return True


def test_smoke_live_converse() -> None:
    """실제 LLM 1회 호출 — G0 킬체크 통과 조건. 공급자는 models.yaml 이 정한다."""
    try:
        config = load_model_config()
    except ConfigValidationError as exc:
        pytest.skip(f"config/models.yaml 미완성 — G0 미완료: {exc}")
    if not _has_credentials(config.provider):
        pytest.skip(f"{config.provider} 자격증명 없음")

    # BedrockClient 를 직접 만들지 않는다 — provider 분기는 get_bedrock_client 한 곳에만 둔다.
    client = get_bedrock_client()
    response = client.converse(
        system="당신은 공정안전 전문가입니다.",
        messages=[Message(role="user", content="안녕하세요")],
        context={"node": "smoke"},
    )
    assert response.stop_reason == "end_turn"
    assert response.cost_usd > 0
    assert response.latency_s > 0
