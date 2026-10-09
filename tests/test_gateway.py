"""오프라인 시험 — 본선 F-01 대회 게이트웨이 전환 배선. 외부 네트워크 0회(127.0.0.1 가짜 게이트웨이).

실 `anthropic` SDK·`AnthropicClient`·`service.run_quick` 를 그대로 타고, 응답만 `tools/fake_gateway.py` 가
재생 레코드로 만든다. 키 수령 뒤 바뀌는 것은 환경변수뿐이라는 것을 못 박는다.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from apps.web import service
from apps.web.replay import load_replays
from tools.fake_gateway import Gateway, make_server

if TYPE_CHECKING:
    from collections.abc import Iterator

_SENTENCE = "수소충전소 압축기에서 디스펜서로 고압 수소를 보낸다. 안전장치는 긴급차단밸브."


@pytest.fixture
def gateway() -> Iterator[tuple[Gateway, str]]:
    gw = Gateway("N1")
    server = make_server(gw)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield gw, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    service._daily_runs.clear()
    for name in ("HAZOP_USE_MOCK", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                 "HAZOP_ENDPOINT_LABEL", "HAZOP_PROVIDER", "KIRO_API_KEY", "HAZOP_GATEWAY_KEY"):
        monkeypatch.delenv(name, raising=False)


def _live(monkeypatch: pytest.MonkeyPatch, **env: str) -> dict[str, str]:
    env = {"HAZOP_ALLOW_LIVE": "true", **env}
    for name, value in env.items():
        monkeypatch.setenv(name, value)  # SDK 는 os.environ 을 읽는다
    return env


def test_quick_run_goes_through_gateway_with_env_only(
    gateway: tuple[Gateway, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    gw, url = gateway
    env = _live(monkeypatch, ANTHROPIC_BASE_URL=url, ANTHROPIC_API_KEY="fake-key")
    assert service.live_block_reason(env) is None
    result = service.run_quick(_SENTENCE, "More", load_replays()["N1"], env)
    assert [e["stage"] for e in gw.log] == ["parse", "enumerate", "judge"]
    assert {e["auth"] for e in gw.log} == {"x-api-key"}
    assert {e["tool_choice"] for e in gw.log} == {"structured_output"}  # 스키마 강제가 게이트웨이까지 간다
    assert not any(e["has_temperature"] for e in gw.log)  # REQ-12: sampling 파라미터 미전송
    assert gw.log[1]["model"] == result.meta["model_id"]  # models.yaml 의 ID 가 그대로 전달
    assert result.records and result.meta["judged_cells"] == result.meta["expected_cells"]
    assert result.meta["endpoint"] == "대회 제공 API"
    assert "대회 제공 API 경유" in service.provenance_line(result)


def test_bearer_token_alone_enables_live_and_is_sent(
    gateway: tuple[Gateway, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    gw, url = gateway
    env = _live(monkeypatch, ANTHROPIC_BASE_URL=url, ANTHROPIC_AUTH_TOKEN="fake-token",
                HAZOP_ENDPOINT_LABEL="Amazon Bedrock(대회 제공)")
    assert service.live_block_reason(env) is None
    result = service.run_quick(_SENTENCE, "More", load_replays()["N1"], env)
    assert {e["auth"] for e in gw.log} == {"bearer"}
    assert "Amazon Bedrock(대회 제공) 경유" in service.provenance_line(result)


def test_without_base_url_nothing_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _live(monkeypatch)
    assert service.live_block_reason(env) == "실호출 비활성 — ANTHROPIC_API_KEY 가 없습니다."
    assert service.endpoint_label({"ANTHROPIC_API_KEY": "sk-ant-x"}) is None
    assert service.endpoint_label({"ANTHROPIC_BASE_URL": "https://api.anthropic.com/"}) is None  # 기본값 명시 = 직결
    assert "sk-ant- 로 시작하지 않음" in service.key_hint({"ANTHROPIC_API_KEY": "abc"})
    mock = service.run_quick(_SENTENCE, "More", load_replays()["N1"], {**env, "HAZOP_USE_MOCK": "true"})
    assert mock.meta["endpoint"] is None and "경유" not in service.provenance_line(mock)


def test_gateway_secrets_are_synced_and_stripped() -> None:
    environ: dict[str, str] = {}
    service.sync_secrets({"ANTHROPIC_BASE_URL": " http://gw \n", "ANTHROPIC_AUTH_TOKEN": "t\n"}, environ)
    assert environ == {"ANTHROPIC_BASE_URL": "http://gw", "ANTHROPIC_AUTH_TOKEN": "t"}
    hint = service.key_hint({**environ})
    assert "ANTHROPIC_AUTH_TOKEN" in hint and "sk-ant-" not in hint  # 게이트웨이 키에 접두사 오경보 없음


# ── 대회 AI 모델 게이트웨이(OpenAI 호환, PRD 추론경계·Kiro K-2 B) ───────────────────
def _gateway_reply(arguments: str, finish: str = "tool_calls") -> dict[str, object]:
    return {"choices": [{"finish_reason": finish, "message": {"content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "structured_output", "arguments": arguments}}]}}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 300, "prompt_tokens_details": {"cached_tokens": 200}}}


def test_gateway_client_payload_and_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """가이드 형식: Bearer·별칭 모델·function tool 로 스키마 강제 → tool 인자가 content JSON 으로 올라온다."""
    from core.llm import Message, load_model_config
    from core.llm.gateway_client import GatewayClient

    client = GatewayClient(load_model_config())
    alias = load_model_config().gateway["generation_model_id"]
    assert client.base_url == "https://52.79.201.46/v1" and client.model_id == alias
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(client, "_post", lambda payload: sent.append(payload) or _gateway_reply('{"a": 1}'))
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}
    r = client.converse(system="S", messages=[Message(role="user", content="U")], response_schema=schema)
    assert r.content == '{"a": 1}' and r.stop_reason == "tool_use"
    assert (r.usage.input, r.usage.output, r.usage.cache_read) == (1000, 300, 200)
    p = sent[0]
    assert p["model"] == alias and p["messages"][0] == {"role": "system", "content": "S"}
    assert p["tool_choice"] == {"type": "function", "function": {"name": "structured_output"}}
    assert "temperature" not in p


def test_gateway_truncation_maps_to_max_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.llm import load_model_config
    from core.llm.gateway_client import GatewayClient

    client = GatewayClient(load_model_config())
    assert client._parse(_gateway_reply("{", "length"), "c", 0.1).stop_reason == "max_tokens"


def test_gateway_429_is_retried_and_key_never_in_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import urllib.error

    from core.llm import client as client_mod
    from core.llm import load_model_config
    from core.llm.gateway_client import APIStatusError, GatewayClient

    monkeypatch.setenv("KIRO_API_KEY", "sk-secret-value")
    monkeypatch.setattr(client_mod, "_sleep", lambda _s: None)
    calls: list[int] = []

    def fail(*_a: object, **_k: object) -> object:
        calls.append(1)
        raise urllib.error.HTTPError("u", 429, "rate", {}, io.BytesIO(b'{"error":"rate limited"}'))

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(client_mod.BedrockCallError) as info:
        GatewayClient(load_model_config())._post({"model": "m"})
    cause = info.value.__cause__
    assert len(calls) == 3 and isinstance(cause, APIStatusError) and cause.status_code == 429
    assert "sk-secret" not in str(info.value) + str(cause)


def test_provider_switch_selects_gateway_and_blocks_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """HAZOP_PROVIDER=kiro(=gateway): 키 없으면 직결로 넘어가지 않고 막는다. 키가 있으면 게이트웨이 클라이언트·출처 표시."""
    import os

    from core.llm import get_bedrock_client
    from core.llm.gateway_client import GatewayClient

    _live(monkeypatch, HAZOP_PROVIDER="kiro", ANTHROPIC_API_KEY="direct-key")
    assert "게이트웨이 키" in (service.live_block_reason(os.environ) or "")
    monkeypatch.setenv("KIRO_API_KEY", "sk-test")
    assert service.live_block_reason(os.environ) is None
    assert isinstance(get_bedrock_client(), GatewayClient)
    assert service.endpoint_label(os.environ) == service.GATEWAY_LABEL
