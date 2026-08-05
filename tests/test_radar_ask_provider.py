from __future__ import annotations

import json
from collections import deque

import pytest
import requests

from services.radar_ask.config import RadarAskSettings
from services.radar_ask.contracts import (
    ProviderMessage,
    ProviderRequest,
    ProviderToolDefinition,
)
from services.radar_ask.provider import (
    DeepSeekProvider,
    ProviderInvalidResponse,
    ProviderRejected,
    ProviderUnavailable,
)


class FakeResponse:
    def __init__(self, payload=None, *, status_code=200, raw_content=None, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.content = raw_content if raw_content is not None else json.dumps(payload).encode("utf-8")
        self.closed = False
        self.bytes_yielded = 0

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def iter_content(self, chunk_size=1):
        for offset in range(0, len(self.content), chunk_size):
            chunk = self.content[offset : offset + chunk_size]
            self.bytes_yielded += len(chunk)
            yield chunk

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self):
        self.queued = deque()
        self.calls = []

    def queue(self, response_or_error):
        self.queued.append(response_or_error)

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        result = self.queued.popleft()
        if isinstance(result, Exception):
            raise result
        return result


class AdvancingSession(FakeSession):
    def __init__(self, clock, advances):
        super().__init__()
        self.clock = clock
        self.advances = deque(advances)

    def post(self, url, **kwargs):
        result = super().post(url, **kwargs)
        self.clock.value += self.advances.popleft()
        return result


class FakeMonotonic:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    return RadarAskSettings.from_env()


def completion_payload(*, content="Kết quả", tool_calls=None, reasoning=None, usage=None):
    return {
        "id": "chatcmpl-test",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls" if tool_calls else "stop",
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": reasoning,
                    "tool_calls": tool_calls or [],
                },
            }
        ],
        "usage": usage
        or {
            "prompt_tokens": 10,
            "completion_tokens": 4,
            "prompt_cache_hit_tokens": 6,
            "prompt_cache_miss_tokens": 4,
        },
    }


def simple_request(**overrides):
    values = {
        "model": "deepseek-v4-flash",
        "messages": [ProviderMessage(role="user", content="Giá Phú Mỹ?")],
        "max_output_tokens": 1_500,
        "thinking_enabled": False,
    }
    values.update(overrides)
    return ProviderRequest(**values)


def test_complete_sends_exact_safe_http_boundary(settings):
    session = FakeSession()
    session.queue(FakeResponse(completion_payload()))
    provider = DeepSeekProvider(settings=settings, session=session)

    response = provider.complete(simple_request())

    assert response.content == "Kết quả"
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["url"] == "https://api.deepseek.com/chat/completions"
    assert call["headers"] == {
        "Authorization": "Bearer unit-test-key",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    assert call["timeout"] == (5, 30)
    assert call["json"] == {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "Giá Phú Mỹ?"}],
        "max_tokens": 1_500,
        "stream": False,
        "thinking": {"type": "disabled"},
    }


def test_complete_maps_tools_and_preserves_reasoning_only_for_continuation(settings):
    session = FakeSession()
    session.queue(
        FakeResponse(
            completion_payload(
                content=None,
                reasoning="private next-step reasoning",
                tool_calls=[
                    {
                        "id": "call_market_1",
                        "type": "function",
                        "function": {
                            "name": "compare_areas",
                            "arguments": '{"wards":["Phú Mỹ","Định Hòa"]}',
                        },
                    }
                ],
            )
        )
    )
    provider = DeepSeekProvider(settings=settings, session=session)
    tool = ProviderToolDefinition(
        name="compare_areas",
        description="Compare two canonical wards.",
        parameters={
            "type": "object",
            "properties": {"wards": {"type": "array", "items": {"type": "string"}}},
            "required": ["wards"],
            "additionalProperties": False,
        },
    )
    request = simple_request(
        model="deepseek-v4-pro",
        thinking_enabled=True,
        messages=[
            ProviderMessage(role="user", content="So sánh hai phường"),
            ProviderMessage(
                role="assistant",
                content=None,
                reasoning_content="private prior reasoning",
                tool_calls=[],
            ),
            ProviderMessage(role="tool", tool_call_id="call_prior", content='{"ok":true}'),
        ],
        tools=[tool],
    )

    response = provider.complete(request)

    assert response.reasoning_content == "private next-step reasoning"
    assert "reasoning_content" not in response.model_dump()
    assert response.tool_calls[0].name == "compare_areas"
    assert response.tool_calls[0].arguments == {"wards": ["Phú Mỹ", "Định Hòa"]}
    body = session.calls[0]["json"]
    assert body["thinking"] == {"type": "enabled"}
    assert body["messages"][1]["reasoning_content"] == "private prior reasoning"
    assert body["messages"][2] == {
        "role": "tool",
        "content": '{"ok":true}',
        "tool_call_id": "call_prior",
    }
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "compare_areas",
                "description": "Compare two canonical wards.",
                "parameters": tool.parameters,
            },
        }
    ]


def test_complete_normalizes_usage_fields(settings):
    session = FakeSession()
    session.queue(FakeResponse(completion_payload()))
    response = DeepSeekProvider(settings=settings, session=session).complete(simple_request())

    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 4
    assert response.usage.cache_hit_input_tokens == 6
    assert response.usage.cache_miss_input_tokens == 4


def test_provider_usage_is_bounded_before_any_database_accounting(settings):
    session = FakeSession()
    session.queue(
        FakeResponse(
            completion_payload(
                usage={
                    "prompt_tokens": 10_000_001,
                    "completion_tokens": 1,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 10_000_001,
                }
            )
        )
    )

    with pytest.raises(ProviderInvalidResponse, match="usage is invalid"):
        DeepSeekProvider(settings=settings, session=session).complete(simple_request())


def test_json_mode_retries_once_for_empty_content(settings):
    session = FakeSession()
    session.queue(FakeResponse(completion_payload(content="")))
    session.queue(FakeResponse(completion_payload(content='{"route":"fast"}')))
    provider = DeepSeekProvider(settings=settings, session=session)

    response = provider.complete_json(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "Route this question"}],
        max_output_tokens=500,
    )

    assert response.json_value == {"route": "fast"}
    assert response.usage.input_tokens == 20
    assert response.usage.output_tokens == 8
    assert response.usage.cache_hit_input_tokens == 12
    assert response.usage.cache_miss_input_tokens == 8
    assert len(session.calls) == 2
    assert session.calls[0]["json"]["response_format"] == {"type": "json_object"}
    assert "valid JSON object" in session.calls[0]["json"]["messages"][0]["content"]


def test_json_mode_does_not_retry_valid_content(settings):
    session = FakeSession()
    session.queue(FakeResponse(completion_payload(content='{"route":"fast"}')))
    provider = DeepSeekProvider(settings=settings, session=session)

    response = provider.complete_json(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "Route"}],
        max_output_tokens=500,
    )

    assert response.json_value == {"route": "fast"}
    assert len(session.calls) == 1


def test_json_mode_rejects_two_invalid_responses(settings):
    session = FakeSession()
    session.queue(FakeResponse(completion_payload(content="not-json")))
    session.queue(FakeResponse(completion_payload(content="still-not-json")))
    provider = DeepSeekProvider(settings=settings, session=session)

    with pytest.raises(ProviderInvalidResponse, match="valid JSON") as caught:
        provider.complete_json(
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": "Route"}],
            max_output_tokens=500,
        )

    assert len(session.calls) == 2
    assert caught.value.usage.input_tokens == 20
    assert caught.value.usage.output_tokens == 8


def test_deep_json_repair_shares_one_monotonic_deadline(settings):
    clock = FakeMonotonic()
    session = AdvancingSession(clock, advances=(45.0, 16.0))
    session.queue(FakeResponse(completion_payload(content="not-json")))
    session.queue(FakeResponse(completion_payload(content='{"answer":"late"}')))
    provider = DeepSeekProvider(settings=settings, session=session, monotonic_fn=clock)

    with pytest.raises(ProviderUnavailable, match="deadline") as caught:
        provider.complete_until(simple_request(json_mode=True), deadline=60.0)

    assert len(session.calls) == 2
    first_timeout = session.calls[0]["timeout"]
    second_timeout = session.calls[1]["timeout"]
    assert first_timeout.total == pytest.approx(60.0)
    assert second_timeout.total == pytest.approx(15.0)
    assert caught.value.usage.input_tokens == 20
    assert caught.value.usage.output_tokens == 8


def test_json_retry_network_failure_keeps_first_attempt_usage(settings):
    session = FakeSession()
    session.queue(FakeResponse(completion_payload(content="not-json")))
    session.queue(requests.Timeout("private timeout"))
    provider = DeepSeekProvider(settings=settings, session=session)

    with pytest.raises(ProviderUnavailable) as caught:
        provider.complete(simple_request(json_mode=True))

    assert caught.value.usage.input_tokens == 10
    assert caught.value.usage.output_tokens == 4


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [(400, ProviderRejected), (401, ProviderRejected), (429, ProviderUnavailable), (500, ProviderUnavailable)],
)
def test_http_errors_are_mapped_without_response_body(settings, status_code, error_type):
    session = FakeSession()
    session.queue(
        FakeResponse(
            {
                "error": {"message": "sensitive provider body"},
                "usage": {"prompt_tokens": 13, "completion_tokens": 2},
            },
            status_code=status_code,
        )
    )
    provider = DeepSeekProvider(settings=settings, session=session)

    with pytest.raises(error_type) as raised:
        provider.complete(simple_request())

    assert "sensitive provider body" not in str(raised.value)
    assert "unit-test-key" not in str(raised.value)
    assert raised.value.usage.input_tokens == 13
    assert raised.value.usage.output_tokens == 2


@pytest.mark.parametrize("error", [requests.Timeout("slow"), requests.ConnectionError("offline")])
def test_network_failures_are_provider_unavailable(settings, error):
    session = FakeSession()
    session.queue(error)

    with pytest.raises(ProviderUnavailable, match="unavailable"):
        DeepSeekProvider(settings=settings, session=session).complete(simple_request())


def test_response_size_is_bounded_before_json_parsing(settings):
    session = FakeSession()
    session.queue(
        FakeResponse(
            completion_payload(),
            raw_content=b"x" * (1_048_576 + 1),
            headers={"Content-Length": str(1_048_576 + 1)},
        )
    )

    with pytest.raises(ProviderInvalidResponse, match="too large"):
        DeepSeekProvider(settings=settings, session=session).complete(simple_request())


@pytest.mark.parametrize(
    "content_length",
    ["not-an-integer", "-1", str(1_048_576 + 1)],
)
def test_invalid_content_length_keeps_bounded_actual_usage(settings, content_length):
    session = FakeSession()
    response = FakeResponse(
        completion_payload(),
        headers={"Content-Length": content_length},
    )
    session.queue(response)

    with pytest.raises(ProviderInvalidResponse) as caught:
        DeepSeekProvider(settings=settings, session=session).complete(simple_request())

    assert caught.value.usage.input_tokens == 10
    assert caught.value.usage.output_tokens == 4
    assert response.closed is True


def test_actually_oversized_body_stops_at_bounded_read_without_usage_parse(settings):
    session = FakeSession()
    response = FakeResponse(
        completion_payload(),
        raw_content=b"x" * (1_048_576 + 100_000),
    )
    session.queue(response)

    with pytest.raises(ProviderInvalidResponse, match="too large") as caught:
        DeepSeekProvider(settings=settings, session=session).complete(simple_request())

    assert caught.value.usage.input_tokens == 0
    assert response.bytes_yielded <= 1_048_576 + 65_536
    assert response.closed is True


def test_invalid_tool_argument_json_is_rejected(settings):
    session = FakeSession()
    session.queue(
        FakeResponse(
            completion_payload(
                content=None,
                tool_calls=[
                    {
                        "id": "call_bad",
                        "type": "function",
                        "function": {"name": "compare_areas", "arguments": "not-json"},
                    }
                ],
            )
        )
    )

    with pytest.raises(ProviderInvalidResponse, match="tool arguments") as caught:
        DeepSeekProvider(settings=settings, session=session).complete(simple_request())

    assert caught.value.usage.input_tokens == 10
    assert caught.value.usage.output_tokens == 4
    assert caught.value.usage.cache_hit_input_tokens == 6
    assert caught.value.usage.cache_miss_input_tokens == 4


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"choices": [], "usage": {"prompt_tokens": 17, "completion_tokens": 3}}, "choice"),
        (
            {
                "choices": [{"message": "not-an-object"}],
                "usage": {"prompt_tokens": 17, "completion_tokens": 3},
            },
            "message",
        ),
        (
            {
                "choices": [{"message": {"content": None, "tool_calls": {"bad": True}}}],
                "usage": {"prompt_tokens": 17, "completion_tokens": 3},
            },
            "tool calls",
        ),
    ],
)
def test_structurally_invalid_completion_preserves_independently_parsed_usage(
    settings,
    payload,
    message,
):
    session = FakeSession()
    session.queue(FakeResponse(payload))

    with pytest.raises(ProviderInvalidResponse, match=message) as caught:
        DeepSeekProvider(settings=settings, session=session).complete(simple_request())

    assert caught.value.usage.input_tokens == 17
    assert caught.value.usage.output_tokens == 3


def test_provider_requires_api_key_only_when_called(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    settings = RadarAskSettings.from_env()
    provider = DeepSeekProvider(settings=settings, session=FakeSession())

    with pytest.raises(ProviderUnavailable, match="not configured"):
        provider.complete(simple_request())


def test_provider_rejects_unconfigured_model_without_http_call(settings):
    session = FakeSession()
    provider = DeepSeekProvider(settings=settings, session=session)

    with pytest.raises(ProviderRejected, match="model is not allowed"):
        provider.complete(simple_request(model="untrusted-model"))

    assert session.calls == []
