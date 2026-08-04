from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Protocol

import requests
from pydantic import ValidationError

from .config import RadarAskSettings
from .contracts import (
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
    ProviderToolDefinition,
    ProviderUsage,
    ToolCall,
)


MAX_RESPONSE_BYTES = 1_048_576
CONNECT_TIMEOUT_SECONDS = 5
JSON_SYSTEM_INSTRUCTION = "Return exactly one valid JSON object and no surrounding text."


class ProviderError(RuntimeError):
    """Base class for sanitized provider-boundary failures."""


class ProviderUnavailable(ProviderError):
    """The configured provider cannot safely serve the request now."""


class ProviderRejected(ProviderError):
    """The provider or local policy rejected the request."""


class ProviderInvalidResponse(ProviderError):
    """The provider returned a response outside the typed contract."""


class RadarAskProvider(Protocol):
    def complete(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError


def _extract_usage(payload: Mapping[str, object]) -> ProviderUsage:
    raw_usage = payload.get("usage")
    usage = raw_usage if isinstance(raw_usage, Mapping) else {}
    try:
        return ProviderUsage(
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            cache_hit_input_tokens=usage.get("prompt_cache_hit_tokens", 0),
            cache_miss_input_tokens=usage.get("prompt_cache_miss_tokens", 0),
        )
    except ValidationError as exc:
        raise ProviderInvalidResponse("provider usage is invalid") from exc


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


def _parse_tool_call(raw_call: object) -> ToolCall:
    if not isinstance(raw_call, Mapping):
        raise ProviderInvalidResponse("provider tool call is invalid")
    raw_function = raw_call.get("function")
    if raw_call.get("type") != "function" or not isinstance(raw_function, Mapping):
        raise ProviderInvalidResponse("provider tool call is invalid")
    raw_arguments = raw_function.get("arguments")
    if not isinstance(raw_arguments, str):
        raise ProviderInvalidResponse("provider tool arguments are invalid")
    try:
        arguments = json.loads(raw_arguments)
    except (TypeError, ValueError) as exc:
        raise ProviderInvalidResponse("provider tool arguments are not valid JSON") from exc
    if not isinstance(arguments, dict):
        raise ProviderInvalidResponse("provider tool arguments must be an object")
    try:
        return ToolCall(
            call_id=raw_call.get("id"),
            name=raw_function.get("name"),
            arguments=arguments,
        )
    except ValidationError as exc:
        raise ProviderInvalidResponse("provider tool arguments violate the contract") from exc


def _parse_response(payload: object) -> ProviderResponse:
    if not isinstance(payload, Mapping):
        raise ProviderInvalidResponse("provider response must be an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise ProviderInvalidResponse("provider response has no completion choice")
    choice = choices[0]
    raw_message = choice.get("message")
    if not isinstance(raw_message, Mapping):
        raise ProviderInvalidResponse("provider response message is invalid")
    content = raw_message.get("content")
    reasoning_content = raw_message.get("reasoning_content")
    if content is not None and not isinstance(content, str):
        raise ProviderInvalidResponse("provider response content is invalid")
    if reasoning_content is not None and not isinstance(reasoning_content, str):
        raise ProviderInvalidResponse("provider reasoning content is invalid")
    raw_tool_calls = raw_message.get("tool_calls") or []
    if not isinstance(raw_tool_calls, list):
        raise ProviderInvalidResponse("provider tool calls are invalid")
    tool_calls = [_parse_tool_call(raw_call) for raw_call in raw_tool_calls]
    if not content and not tool_calls:
        content = ""
    try:
        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            usage=_extract_usage(payload),
            finish_reason=choice.get("finish_reason"),
            reasoning_content=reasoning_content,
        )
    except ValidationError as exc:
        raise ProviderInvalidResponse("provider response violates the contract") from exc


class DeepSeekProvider:
    def __init__(self, *, settings: RadarAskSettings, session: requests.Session | None = None):
        self._settings = settings
        self._session = session or requests.Session()

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        allowed_models = {
            self._settings.router_model,
            self._settings.free_model,
            self._settings.smart_model,
        }
        if request.model not in allowed_models:
            raise ProviderRejected("provider model is not allowed")

        attempts = 2 if request.json_mode else 1
        for _attempt in range(attempts):
            response = self._post_once(request)
            if not request.json_mode:
                return response
            raw_content = (response.content or "").strip()
            if not raw_content:
                continue
            try:
                json_value = json.loads(raw_content)
            except ValueError:
                continue
            if not isinstance(json_value, dict):
                continue
            return response.model_copy(update={"json_value": json_value})
        raise ProviderInvalidResponse("provider did not return a valid JSON object")

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

    def _post_once(self, request: ProviderRequest) -> ProviderResponse:
        if not self._settings.deepseek_api_key:
            raise ProviderUnavailable("DeepSeek API key is not configured")
        url = f"{self._settings.deepseek_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._settings.deepseek_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        timeout = (
            min(CONNECT_TIMEOUT_SECONDS, self._settings.provider_timeout_seconds),
            self._settings.provider_timeout_seconds,
        )
        try:
            response = self._session.post(
                url,
                headers=headers,
                json=_request_payload(request),
                timeout=timeout,
            )
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    if int(content_length) > MAX_RESPONSE_BYTES:
                        raise ProviderInvalidResponse("provider response is too large")
                except ValueError:
                    raise ProviderInvalidResponse("provider Content-Length is invalid") from None
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise ProviderInvalidResponse("provider response is too large")
            response.raise_for_status()
        except ProviderInvalidResponse:
            raise
        except requests.HTTPError as exc:
            status_code = getattr(exc.response, "status_code", 0) or 0
            if status_code == 429 or status_code >= 500:
                raise ProviderUnavailable(f"DeepSeek is unavailable (HTTP {status_code})") from None
            raise ProviderRejected(f"DeepSeek rejected the request (HTTP {status_code})") from None
        except (requests.Timeout, requests.ConnectionError):
            raise ProviderUnavailable("DeepSeek is unavailable") from None
        except requests.RequestException:
            raise ProviderUnavailable("DeepSeek request failed") from None

        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise ProviderInvalidResponse("provider response is not valid JSON") from None
        return _parse_response(payload)
