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
                 "HAZOP_ENDPOINT_LABEL"):
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
