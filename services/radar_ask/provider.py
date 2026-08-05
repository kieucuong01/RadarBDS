from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from time import monotonic
from typing import Protocol

import requests
from pydantic import ValidationError
from urllib3.util import Timeout

from .config import REQUEST_PROVIDER_MAX_ATTEMPTS, RadarAskSettings
from .contracts import (
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
    ProviderToolDefinition,
    ProviderUsage,
    ToolCall,
)


MAX_RESPONSE_BYTES = 1_048_576
MAX_USAGE_TOKENS_PER_RESPONSE = 10_000_000
CONNECT_TIMEOUT_SECONDS = 5
JSON_SYSTEM_INSTRUCTION = "Return exactly one valid JSON object and no surrounding text."


class ProviderError(RuntimeError):
    """Base class for sanitized provider-boundary failures."""

    def __init__(self, message: str, *, usage: ProviderUsage | None = None):
        self.usage = usage or ProviderUsage()
        super().__init__(message)


class ProviderUnavailable(ProviderError):
    """The configured provider cannot safely serve the request now."""


class ProviderRejected(ProviderError):
    """The provider or local policy rejected the request."""


class ProviderInvalidResponse(ProviderError):
    """The provider returned a response outside the typed contract."""


class RadarAskProvider(Protocol):
    def complete(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError

    def complete_until(
        self,
        request: ProviderRequest,
        *,
        deadline: float,
    ) -> ProviderResponse:
        raise NotImplementedError


def _extract_usage(payload: Mapping[str, object]) -> ProviderUsage:
    raw_usage = payload.get("usage")
    usage = raw_usage if isinstance(raw_usage, Mapping) else {}
    try:
        parsed = ProviderUsage(
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            cache_hit_input_tokens=usage.get("prompt_cache_hit_tokens", 0),
            cache_miss_input_tokens=usage.get("prompt_cache_miss_tokens", 0),
        )
    except ValidationError as exc:
        raise ProviderInvalidResponse("provider usage is invalid") from exc
    if any(
        value > MAX_USAGE_TOKENS_PER_RESPONSE
        for value in (
            parsed.input_tokens,
            parsed.output_tokens,
            parsed.cache_hit_input_tokens,
            parsed.cache_miss_input_tokens,
        )
    ):
        raise ProviderInvalidResponse("provider usage is invalid")
    return parsed


def _extract_bounded_error_usage(payload: object) -> ProviderUsage:
    """Best-effort billing evidence from an already bounded decoded body."""
    if not isinstance(payload, Mapping):
        return ProviderUsage()
    try:
        return _extract_usage(payload)
    except ProviderInvalidResponse:
        return ProviderUsage()


def _read_bounded_body(response: object) -> bytes:
    """Read at most one bounded response body; never buffer an oversized payload."""
    chunks: list[bytes] = []
    total = 0
    try:
        iterator = response.iter_content(chunk_size=65_536)
    except AttributeError:
        content = getattr(response, "content", b"")
        iterator = (content,)
    for chunk in iterator:
        if not chunk:
            continue
        if not isinstance(chunk, (bytes, bytearray)):
            raise ProviderInvalidResponse("provider response body is invalid")
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ProviderInvalidResponse("provider response is too large")
        chunks.append(bytes(chunk))
    return b"".join(chunks)


def _message_payload(message: ProviderMessage) -> dict[str, object]:
    payload: dict[str, object] = {"role": message.role, "content": message.content}
    if message.role in {"system", "user", "tool"} and message.content is None:
        raise ProviderRejected(f"{message.role} message content is required")
    if message.role == "tool":
        if not message.tool_call_id:
            raise ProviderRejected("tool_call_id is required for tool messages")
        payload["tool_call_id"] = message.tool_call_id
    if message.role == "assistant":
        if message.reasoning_content is not None:
            payload["reasoning_content"] = message.reasoning_content
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                }
                for call in message.tool_calls
            ]
    return payload


def _tool_payload(tool: ProviderToolDefinition) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _request_payload(request: ProviderRequest) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": request.model,
        "messages": [_message_payload(message) for message in request.messages],
        "max_tokens": request.max_output_tokens,
        "stream": False,
        "thinking": {"type": "enabled" if request.thinking_enabled else "disabled"},
    }
    if request.tools:
        payload["tools"] = [_tool_payload(tool) for tool in request.tools]
    if request.json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _parse_tool_call(raw_call: object, *, usage: ProviderUsage) -> ToolCall:
    if not isinstance(raw_call, Mapping):
        raise ProviderInvalidResponse("provider tool call is invalid", usage=usage)
    raw_function = raw_call.get("function")
    if raw_call.get("type") != "function" or not isinstance(raw_function, Mapping):
        raise ProviderInvalidResponse("provider tool call is invalid", usage=usage)
    raw_arguments = raw_function.get("arguments")
    if not isinstance(raw_arguments, str):
        raise ProviderInvalidResponse("provider tool arguments are invalid", usage=usage)
    try:
        arguments = json.loads(raw_arguments)
    except (TypeError, ValueError) as exc:
        raise ProviderInvalidResponse(
            "provider tool arguments are not valid JSON",
            usage=usage,
        ) from exc
    if not isinstance(arguments, dict):
        raise ProviderInvalidResponse(
            "provider tool arguments must be an object",
            usage=usage,
        )
    try:
        return ToolCall(
            call_id=raw_call.get("id"),
            name=raw_function.get("name"),
            arguments=arguments,
        )
    except ValidationError as exc:
        raise ProviderInvalidResponse(
            "provider tool arguments violate the contract",
            usage=usage,
        ) from exc


def _parse_response(payload: object) -> ProviderResponse:
    if not isinstance(payload, Mapping):
        raise ProviderInvalidResponse("provider response must be an object")
    # Usage is independent billing evidence. Parse it before any optional
    # completion structure so every later rejection can still be accounted.
    usage = _extract_usage(payload)
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise ProviderInvalidResponse(
            "provider response has no completion choice",
            usage=usage,
        )
    choice = choices[0]
    raw_message = choice.get("message")
    if not isinstance(raw_message, Mapping):
        raise ProviderInvalidResponse("provider response message is invalid", usage=usage)
    content = raw_message.get("content")
    reasoning_content = raw_message.get("reasoning_content")
    if content is not None and not isinstance(content, str):
        raise ProviderInvalidResponse("provider response content is invalid", usage=usage)
    if reasoning_content is not None and not isinstance(reasoning_content, str):
        raise ProviderInvalidResponse("provider reasoning content is invalid", usage=usage)
    raw_tool_calls = raw_message.get("tool_calls") or []
    if not isinstance(raw_tool_calls, list):
        raise ProviderInvalidResponse("provider tool calls are invalid", usage=usage)
    tool_calls = [_parse_tool_call(raw_call, usage=usage) for raw_call in raw_tool_calls]
    if not content and not tool_calls:
        content = ""
    try:
        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=choice.get("finish_reason"),
            reasoning_content=reasoning_content,
        )
    except ValidationError as exc:
        raise ProviderInvalidResponse(
            "provider response violates the contract",
            usage=usage,
        ) from exc


class DeepSeekProvider:
    def __init__(
        self,
        *,
        settings: RadarAskSettings,
        session: requests.Session | None = None,
        monotonic_fn=monotonic,
    ):
        self._settings = settings
        self._session = session or requests.Session()
        self._monotonic = monotonic_fn

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        return self._complete(request, deadline=None)

    def complete_until(
        self,
        request: ProviderRequest,
        *,
        deadline: float,
    ) -> ProviderResponse:
        """Complete within one absolute deadline, including JSON repair attempts."""
        if not math.isfinite(deadline):
            raise ValueError("deadline must be finite")
        return self._complete(request, deadline=float(deadline))

    def _complete(
        self,
        request: ProviderRequest,
        *,
        deadline: float | None,
    ) -> ProviderResponse:
        allowed_models = {
            self._settings.router_model,
            self._settings.free_model,
            self._settings.smart_model,
        }
        if request.model not in allowed_models:
            raise ProviderRejected("provider model is not allowed")

        attempts = REQUEST_PROVIDER_MAX_ATTEMPTS if request.json_mode else 1
        accumulated_usage = ProviderUsage()
        for _attempt in range(attempts):
            remaining = None if deadline is None else deadline - self._monotonic()
            if remaining is not None and remaining <= 0:
                raise ProviderUnavailable(
                    "DeepSeek deadline exceeded",
                    usage=accumulated_usage,
                )
            try:
                response = self._post_once(request, timeout_seconds=remaining)
            except ProviderError as exc:
                raise type(exc)(
                    str(exc),
                    usage=accumulated_usage + exc.usage,
                ) from None
            accumulated_usage = accumulated_usage + response.usage
            if deadline is not None and self._monotonic() >= deadline:
                raise ProviderUnavailable(
                    "DeepSeek deadline exceeded",
                    usage=accumulated_usage,
                )
            if not request.json_mode:
                return response.model_copy(update={"usage": accumulated_usage})
            raw_content = (response.content or "").strip()
            if not raw_content:
                continue
            try:
                json_value = json.loads(raw_content)
            except ValueError:
                continue
            if not isinstance(json_value, dict):
                continue
            return response.model_copy(
                update={"json_value": json_value, "usage": accumulated_usage}
            )
        raise ProviderInvalidResponse(
            "provider did not return a valid JSON object",
            usage=accumulated_usage,
        )

    def complete_json(
        self,
        *,
        model: str,
        messages: Sequence[ProviderMessage | Mapping[str, object]],
        max_output_tokens: int,
        thinking_enabled: bool = False,
    ) -> ProviderResponse:
        typed_messages = [ProviderMessage.model_validate(message) for message in messages]
        typed_messages.insert(
            0,
            ProviderMessage(role="system", content=JSON_SYSTEM_INSTRUCTION),
        )
        request = ProviderRequest(
            model=model,
            messages=typed_messages,
            max_output_tokens=max_output_tokens,
            thinking_enabled=thinking_enabled,
            json_mode=True,
        )
        return self.complete(request)

    def _post_once(
        self,
        request: ProviderRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> ProviderResponse:
        if not self._settings.deepseek_api_key:
            raise ProviderUnavailable("DeepSeek API key is not configured")
        url = f"{self._settings.deepseek_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._settings.deepseek_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if timeout_seconds is None:
            timeout = (
                min(CONNECT_TIMEOUT_SECONDS, self._settings.provider_timeout_seconds),
                self._settings.provider_timeout_seconds,
            )
        else:
            bounded = max(float(timeout_seconds), 0.001)
            timeout = Timeout(
                total=bounded,
                connect=min(CONNECT_TIMEOUT_SECONDS, bounded),
                read=bounded,
            )
        try:
            response = self._session.post(
                url,
                headers=headers,
                json=_request_payload(request),
                timeout=timeout,
                stream=True,
            )
            content_length_error: str | None = None
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                    if declared_length < 0:
                        content_length_error = "provider Content-Length is invalid"
                    elif declared_length > MAX_RESPONSE_BYTES:
                        content_length_error = "provider response is too large"
                except ValueError:
                    content_length_error = "provider Content-Length is invalid"
            body = _read_bounded_body(response)
            try:
                payload = json.loads(body)
            except (TypeError, UnicodeDecodeError, ValueError):
                payload = None
            usage = _extract_bounded_error_usage(payload)
            if content_length_error is not None:
                raise ProviderInvalidResponse(content_length_error, usage=usage)
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                status_code = getattr(exc.response, "status_code", 0) or 0
                if status_code == 429 or status_code >= 500:
                    raise ProviderUnavailable(
                        f"DeepSeek is unavailable (HTTP {status_code})",
                        usage=usage,
                    ) from None
                raise ProviderRejected(
                    f"DeepSeek rejected the request (HTTP {status_code})",
                    usage=usage,
                ) from None
            if payload is None:
                raise ProviderInvalidResponse("provider response is not valid JSON")
        except ProviderInvalidResponse:
            raise
        except (ProviderRejected, ProviderUnavailable):
            raise
        except (requests.Timeout, requests.ConnectionError):
            raise ProviderUnavailable("DeepSeek is unavailable") from None
        except requests.RequestException:
            raise ProviderUnavailable("DeepSeek request failed") from None
        finally:
            if "response" in locals():
                response.close()
        return _parse_response(payload)
