"""spec:bedrock-client 오프라인 테스트 (T-02~T-11).

AWS 자격증명·네트워크 없이 전부 통과해야 한다(NFR-B05). boto3 경계는 stub 으로 대체한다.
테스트 함수명은 tasks.md 의 추적 매트릭스(`tests/test_bedrock_client.py::…`)와 동일하게 유지했다.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.llm import (  # noqa: E402  (위 sys.path 보정 이후여야 한다)
    AbstractBedrockClient,
    BedrockCallError,
    BedrockClient,
    CachingBuilder,
    ConfigValidationError,
    ConverseResponse,
    Message,
    MockBedrockClient,
    MockExhaustedError,
    ModelConfig,
    ModelProfile,
    SchemaValidator,
    TokenUsage,
    ToolDefinition,
    ToolUseBlock,
    calculate_cost,
    get_bedrock_client,
    is_throttling_error,
    load_model_config,
)
from core.llm import client as client_mod  # noqa: E402

SONNET = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["deviation"],
    "properties": {"deviation": {"type": "string"}},
    "additionalProperties": False,
}


def _response(**kwargs: Any) -> ConverseResponse:
    defaults: dict[str, Any] = {
        "content": "안녕하세요",
        "usage": TokenUsage(input=100, output=50),
        "cost_usd": 0.001,
        "latency_s": 0.2,
    }
    return ConverseResponse(**(defaults | kwargs))


def _messages() -> list[Message]:
    return [Message(role="user", content="N1 노드의 이탈을 도출하라")]


def _model_config(**overrides: Any) -> ModelConfig:
    base: dict[str, Any] = {
        "region": "ap-northeast-2",
        "generation": ModelProfile(SONNET, temperature=0.2, max_tokens=4096, prompt_caching=True),
        "verifier": ModelProfile(SONNET, temperature=0.0, max_tokens=1024, prompt_caching=False),
        "embedding_model_id": "amazon.titan-embed-text-v2:0",
        "guardrails_id": None,
        "cost_limit_usd": 0.30,
    }
    return ModelConfig(**(base | overrides))


def _write_yaml(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


VALID_YAML = """
region: ap-northeast-2
generation:
  model_id: model-a
  temperature: 0.2
  max_tokens: 4096
  prompt_caching: true
verifier:
  model_id: model-b
  temperature: 0.0
  max_tokens: 1024
  prompt_caching: false
embedding:
  model_id: model-c
guardrails:
  id: null
cost_limit_usd: 0.25
"""


# ── T-02 ConfigLoader (REQ-01) ──────────────────────────────────────────────
def test_config_load_path_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write_yaml(tmp_path / "models.yaml", VALID_YAML)
    monkeypatch.chdir(tmp_path.parent)  # 작업 디렉토리를 바꿔도 절대경로로 로드된다
    config = load_model_config(path)
    assert config.region == "ap-northeast-2"
    assert config.generation.model_id == "model-a"
    assert config.cost_limit_usd == 0.25


def test_config_missing_field(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path / "m.yaml", "region: ap-northeast-2\ngeneration: {}\n")
    with pytest.raises(ConfigValidationError, match=r"missing fields: \['embedding', 'verifier'\]"):
        load_model_config(path)


def test_config_temperature_out_of_range(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path / "t.yaml", VALID_YAML.replace("temperature: 0.2", "temperature: 1.5"))
    with pytest.raises(ConfigValidationError, match="generation.temperature must be"):
        load_model_config(path)


def test_config_lru_cache(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path / "c.yaml", VALID_YAML)
    assert load_model_config(path) is load_model_config(path)


def test_config_null_model_id_is_missing(tmp_path: Path) -> None:
    """G0 미완료 상태(model_id 비어 있음)를 누락 필드로 취급한다 — 추측 금지."""
    path = _write_yaml(tmp_path / "n.yaml", VALID_YAML.replace("model_id: model-a", "model_id: null"))
    with pytest.raises(ConfigValidationError, match=r"generation.model_id"):
        load_model_config(path)


def test_repo_config_is_pending_g0() -> None:
    """저장소의 config/models.yaml 은 아직 모델 ID 가 비어 있어야 한다(값을 지어내지 않았다는 증거)."""
    with pytest.raises(ConfigValidationError, match="G0"):
        load_model_config(REPO_ROOT / "config" / "models.yaml")


# ── T-03 CostCalculator (REQ-09) ────────────────────────────────────────────
def test_cost_calculation() -> None:
    assert calculate_cost(SONNET, 1000, 500) == pytest.approx(0.0105)


def test_cost_cache_discount() -> None:
    plain = calculate_cost(SONNET, 1000, 0)
    cached = calculate_cost(SONNET, 500, 0, cache_read_tokens=500)
    assert cached < plain


def test_cost_zero_tokens() -> None:
    assert calculate_cost(SONNET, 0, 0) == 0.0


def test_cost_unknown_model(caplog: pytest.LogCaptureFixture) -> None:
    """지시문·CLAUDE.md 범위 규율에 따라 예외 대신 비용 0 + WARNING (REQ-09 AC 와 상이)."""
    client_mod._warned_models.clear()
    with caplog.at_level(logging.WARNING, logger="core.llm.client"):
        assert calculate_cost("unknown.model:0", 1000, 1000) == 0.0
        calculate_cost("unknown.model:0", 1000, 1000)  # 두 번째 호출은 로그하지 않는다
    warnings = [m for m in caplog.messages if "가격표에 없는 모델" in m]
    assert len(warnings) == 1


# ── T-04 CachingBuilder (REQ-08) ────────────────────────────────────────────
def test_caching_marker_present() -> None:
    assert CachingBuilder.build_system_blocks("S", True)[0]["cachePoint"] == {"type": "default"}


def test_caching_marker_absent() -> None:
    assert "cachePoint" not in CachingBuilder.build_system_blocks("S", False)[0]


def test_caching_system_text_preserved() -> None:
    for flag in (True, False):
        assert CachingBuilder.build_system_blocks("시스템 프롬프트", flag)[0]["text"] == "시스템 프롬프트"


# ── T-05 RetryHandler (REQ-05) ──────────────────────────────────────────────
def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "Converse")


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_mod, "_sleep", lambda _s: None)


def test_retry_throttling_success(no_sleep: None) -> None:
    attempts = {"n": 0}

    @client_mod.bedrock_retry
    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _client_error("ThrottlingException")
        return "ok"

    assert flaky() == "ok"
    assert attempts["n"] == 3


def test_retry_throttling_exhausted(no_sleep: None) -> None:
    @client_mod.bedrock_retry
    def always_throttled() -> str:
        raise _client_error("ThrottlingException")

    with pytest.raises(BedrockCallError):
        always_throttled()


def test_retry_warning_logged(no_sleep: None, caplog: pytest.LogCaptureFixture) -> None:
    @client_mod.bedrock_retry
    def always_throttled() -> str:
        raise _client_error("ServiceUnavailableException")

    with caplog.at_level(logging.WARNING, logger="core.llm.client"), pytest.raises(BedrockCallError):
        always_throttled()
    assert any("재시도 attempt=1/3 reason=ServiceUnavailableException" in m for m in caplog.messages)


def test_no_retry_for_validation_exception(no_sleep: None) -> None:
    attempts = {"n": 0}

    @client_mod.bedrock_retry
    def invalid() -> str:
        attempts["n"] += 1
        raise _client_error("ValidationException")

    with pytest.raises(ClientError):
        invalid()
    assert attempts["n"] == 1  # 재시도 없음


def test_is_throttling_error_discriminates() -> None:
    assert is_throttling_error(_client_error("ThrottlingException"))
    assert not is_throttling_error(_client_error("ValidationException"))
    assert not is_throttling_error(RuntimeError("boom"))


# ── T-06 SchemaValidator (REQ-04) ───────────────────────────────────────────
def test_schema_enforcement_pass() -> None:
    good = _response(content=json.dumps({"deviation": "압력 과다"}, ensure_ascii=False))
    client = MockBedrockClient(responses=[good])
    result = client.converse(system="S", messages=_messages(), response_schema=SCHEMA)
    assert result.content is not None
    assert json.loads(result.content)["deviation"] == "압력 과다"
    assert result.confidence_override is None


def test_schema_enforcement_fail_review() -> None:
    bad = [_response(content='{"wrong": 1}'), _response(content="not json")]
    client = MockBedrockClient(responses=bad)
    result = client.converse(system="S", messages=_messages(), response_schema=SCHEMA)
    assert result.content is None
    assert result.confidence_override == "review"
    assert len(client.calls) == 2  # 원 호출 + 재시도 1회


def test_schema_retry_warning(caplog: pytest.LogCaptureFixture) -> None:
    client = MockBedrockClient(responses=[_response(content="{}"), _response(content="{}")])
    with caplog.at_level(logging.WARNING, logger="core.llm.client"):
        client.converse(system="S", messages=_messages(), response_schema=SCHEMA)
    assert any("schema validation failed, retry 1/1" in m for m in caplog.messages)


def test_schema_retry_succeeds() -> None:
    responses = [_response(content="{}"), _response(content='{"deviation": "역류"}')]
    client = MockBedrockClient(responses=responses)
    result = client.converse(system="S", messages=_messages(), response_schema=SCHEMA)
    assert result.content is not None
    assert json.loads(result.content)["deviation"] == "역류"
    assert result.confidence_override is None


def test_schema_validator_rejects_none_content() -> None:
    assert not SchemaValidator.passes(None, SCHEMA)


# ── T-07 AbstractBedrockClient (REQ-02·06·07) ───────────────────────────────
def test_converse_empty_system_raises() -> None:
    with pytest.raises(ValueError, match="system prompt"):
        MockBedrockClient(responses=[_response()]).converse(system="", messages=_messages())


def test_converse_empty_messages_raises() -> None:
    with pytest.raises(ValueError, match="messages"):
        MockBedrockClient(responses=[_response()]).converse(system="S", messages=[])


def test_logging_format(caplog: pytest.LogCaptureFixture) -> None:
    client = MockBedrockClient(responses=[_response()])
    with caplog.at_level(logging.INFO, logger="core.llm.client"):
        client.converse(system="S", messages=_messages(), context={"node": "N1"})
    line = next(m for m in caplog.messages if "call_id=" in m)
    for token in ("node=N1", "model=mock", "tokens_in=100", "tokens_out=50", "cache_read=0"):
        assert token in line
    assert "cost_usd=0.0010" in line  # 소수점 4자리
    assert "latency_s=" in line


def test_node_unknown_default(caplog: pytest.LogCaptureFixture) -> None:
    client = MockBedrockClient(responses=[_response()])
    with caplog.at_level(logging.INFO, logger="core.llm.client"):
        client.converse(system="S", messages=_messages())
    assert any("node=unknown" in m for m in caplog.messages)


def test_cost_limit_warning(caplog: pytest.LogCaptureFixture) -> None:
    client = MockBedrockClient(responses=[_response(cost_usd=0.31)])
    with caplog.at_level(logging.WARNING, logger="core.llm.client"):
        result = client.converse(system="S", messages=_messages(), context={"node": "N1"})
    assert any("EXCEEDS LIMIT 0.30" in m for m in caplog.messages)
    assert result.cost_usd == 0.31  # 경고만 하고 흐름은 계속된다


def test_call_id_is_uuid4() -> None:
    import uuid

    result = MockBedrockClient(responses=[_response()]).converse(system="S", messages=_messages())
    assert uuid.UUID(result.call_id).version == 4


# ── T-08 MockBedrockClient (REQ-10) ─────────────────────────────────────────
def test_mock_implements_interface() -> None:
    assert isinstance(MockBedrockClient(), AbstractBedrockClient)


def test_mock_records_calls() -> None:
    client = MockBedrockClient(responses=[_response()])
    client.converse(system="당신은 HAZOP 전문가입니다.", messages=_messages())
    assert client.calls[0]["system"] == "당신은 HAZOP 전문가입니다."
    assert client.calls[0]["tools"] == []


def test_mock_exhausted() -> None:
    client = MockBedrockClient(responses=[_response()])
    client.converse(system="S", messages=_messages())
    with pytest.raises(MockExhaustedError):
        client.converse(system="S", messages=_messages())


def test_mock_factory_callable() -> None:
    def factory(**_: Any) -> ConverseResponse:
        return _response(content="factory")

    client = MockBedrockClient(response_factory=factory)
    for _ in range(3):
        assert client.converse(system="S", messages=_messages()).content == "factory"


def test_mock_tool_use_flow() -> None:
    block = ToolUseBlock(id="tu-1", name="lookup_substance", input={"name": "NH3"})
    client = MockBedrockClient(
        responses=[_response(content=None, stop_reason="tool_use", tool_use_blocks=[block])]
    )
    result = client.converse(
        system="S",
        messages=_messages(),
        tools=[ToolDefinition("lookup_substance", "물질 조회", {"type": "object"})],
    )
    assert result.stop_reason == "tool_use"
    assert result.tool_use_blocks[0].name == "lookup_substance"
    assert client.calls[0]["tools"][0].name == "lookup_substance"


# ── T-09 팩토리 (REQ-10) ────────────────────────────────────────────────────
def test_factory_mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAZOP_USE_MOCK", "true")
    assert isinstance(get_bedrock_client(), MockBedrockClient)


def test_factory_real_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAZOP_USE_MOCK", "false")
    monkeypatch.setattr(client_mod, "load_model_config", lambda *a, **k: _model_config())
    monkeypatch.setattr(client_mod.boto3, "client", lambda *a, **k: object())
    client = get_bedrock_client()
    assert isinstance(client, BedrockClient)
    assert not isinstance(client, MockBedrockClient)


# ── T-10 BedrockClient (boto3 경계는 stub) ──────────────────────────────────
class _BotoStub:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or _boto_end_turn()
        self.kwargs: dict[str, Any] = {}

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.kwargs = kwargs
        return self.response


def _boto_end_turn() -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": "안녕하세요"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 1000, "outputTokens": 500, "cacheReadInputTokens": 0},
    }


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any] | None = None,
    **config_overrides: Any,
) -> tuple[BedrockClient, _BotoStub]:
    stub = _BotoStub(response)
    monkeypatch.setattr(client_mod.boto3, "client", lambda *a, **k: stub)
    return BedrockClient(config=_model_config(**config_overrides)), stub


def test_converse_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _make_client(monkeypatch)
    result = client.converse(system="S", messages=_messages())
    assert result.stop_reason == "end_turn"
    assert result.content == "안녕하세요"
    assert result.usage.input == 1000
    assert result.cost_usd == pytest.approx(0.0105)  # 가격표 반영
    assert result.latency_s > 0
    assert result.call_id


def test_no_tools_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _make_client(monkeypatch)
    client.converse(system="S", messages=_messages(), tools=[])
    assert "toolConfig" not in stub.kwargs


def test_tool_use_blocks_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    response = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": "tu-1", "name": "kb", "input": {"q": "NH3"}}}],
            }
        },
        "stopReason": "tool_use",
        "usage": {"inputTokens": 10, "outputTokens": 5},
    }
    client, _ = _make_client(monkeypatch, response)
    result = client.converse(
        system="S", messages=_messages(), tools=[ToolDefinition("kb", "검색", {"type": "object"})]
    )
    assert result.stop_reason == "tool_use"
    assert result.tool_use_blocks == [ToolUseBlock(id="tu-1", name="kb", input={"q": "NH3"})]


def test_guardrail_not_sent_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _make_client(monkeypatch)
    client.converse(system="S", messages=_messages())
    assert "guardrailConfig" not in stub.kwargs


def test_guardrail_sent_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _make_client(monkeypatch, guardrails_id="gr-123")
    client.converse(system="S", messages=_messages())
    assert stub.kwargs["guardrailConfig"]["guardrailIdentifier"] == "gr-123"


def test_caching_marker_in_boto_call(monkeypatch: pytest.MonkeyPatch) -> None:
    client, stub = _make_client(monkeypatch)  # generation.prompt_caching=True
    client.converse(system="S", messages=_messages())
    assert stub.kwargs["system"][0]["cachePoint"] == {"type": "default"}


def test_caching_marker_absent_for_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _BotoStub()
    monkeypatch.setattr(client_mod.boto3, "client", lambda *a, **k: stub)
    BedrockClient(config=_model_config(), profile="verifier").converse(
        system="S", messages=_messages()
    )
    assert "cachePoint" not in stub.kwargs["system"][0]


def test_structured_output_tool_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    response = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "tu-9",
                            "name": "structured_output",
                            "input": {"deviation": "과압"},
                        }
                    }
                ],
            }
        },
        "stopReason": "tool_use",
        "usage": {"inputTokens": 10, "outputTokens": 5},
    }
    client, stub = _make_client(monkeypatch, response)
    result = client.converse(system="S", messages=_messages(), response_schema=SCHEMA)
    assert stub.kwargs["toolConfig"]["toolChoice"] == {"tool": {"name": "structured_output"}}
    assert result.content is not None
    assert json.loads(result.content) == {"deviation": "과압"}
    assert result.confidence_override is None


def test_boto_retry_path(monkeypatch: pytest.MonkeyPatch, no_sleep: None) -> None:
    """_call_converse 가 throttling 을 재시도한 뒤 성공한다."""
    calls = {"n": 0}

    class Flaky(_BotoStub):
        def converse(self, **kwargs: Any) -> dict[str, Any]:
            calls["n"] += 1
            if calls["n"] == 1:
                raise _client_error("ThrottlingException")
            return super().converse(**kwargs)

    stub = Flaky()
    monkeypatch.setattr(client_mod.boto3, "client", lambda *a, **k: stub)
    client = BedrockClient(config=_model_config())
    assert client.converse(system="S", messages=_messages()).content == "안녕하세요"
    assert calls["n"] == 2


def test_message_content_blocks_serialized(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.llm import ContentBlock

    client, stub = _make_client(monkeypatch)
    client.converse(
        system="S",
        messages=[
            Message(
                role="user",
                content=[ContentBlock(type="text", text="첫 블록"), ContentBlock(type="text", text="둘")],
            )
        ],
    )
    assert stub.kwargs["messages"][0]["content"] == [{"text": "첫 블록"}, {"text": "둘"}]


# ── T-11 오프라인 통합 (REQ-10, NFR-B05) ────────────────────────────────────
def test_mock_end_to_end_offline(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """자격증명·네트워크·models.yaml 없이 전체 흐름이 성립한다."""
    monkeypatch.setenv("HAZOP_USE_MOCK", "true")
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    assert isinstance(get_bedrock_client(), MockBedrockClient)
    client = MockBedrockClient(responses=[_response(content='{"deviation": "과압"}', cost_usd=0.05)])
    with caplog.at_level(logging.INFO, logger="core.llm.client"):
        result = client.converse(
            system="S", messages=_messages(), response_schema=SCHEMA, context={"node": "N1"}
        )
    assert result.confidence_override is None
    assert result.cost_usd == 0.05
    assert any("node=N1" in m for m in caplog.messages)
