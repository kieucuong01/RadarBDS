"""Explicit, minimal live compatibility smoke for the configured DeepSeek models."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.radar_ask.config import RadarAskSettings
from services.radar_ask.contracts import (
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
    ProviderToolDefinition,
    ProviderUsage,
)
from services.radar_ask.limits import (
    MODEL_PRICES_USD_PER_MILLION,
    PRICING_VERSION,
    calculate_provider_cost,
)
from services.radar_ask.provider import DeepSeekProvider, ProviderError


OFFICIAL_FLASH_MODEL = "deepseek-v4-flash"
OFFICIAL_PRO_MODEL = "deepseek-v4-pro"
SAFE_FINISH_REASONS = frozenset({"stop", "tool_calls", "length", "content_filter"})


def _usage_payload(usage: ProviderUsage) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_hit_input_tokens": usage.cache_hit_input_tokens,
        "cache_miss_input_tokens": usage.cache_miss_input_tokens,
    }


def _finish_reason(response: ProviderResponse) -> str:
    value = response.finish_reason or "missing"
    return value if value in SAFE_FINISH_REASONS else "other"


def _probe_payload(
    *,
    model: str,
    usage: ProviderUsage,
    finish_reason: str,
    **checks: bool,
) -> dict[str, Any]:
    return {
        "model": model,
        **checks,
        "finish_reason": finish_reason,
        "usage": _usage_payload(usage),
        "estimated_cost_usd": f"{calculate_provider_cost(model, usage):.6f}",
    }


def build_sanitized_report(
    *,
    flash_model: str,
    pro_model: str,
    flash: ProviderResponse,
    tool: ProviderResponse,
    continuation: ProviderResponse,
) -> dict[str, Any]:
    """Return an allowlisted report without messages, content, reasoning, or tool args."""
    pro_usage = tool.usage + continuation.usage
    total_usage = flash.usage + pro_usage
    total_cost = calculate_provider_cost(flash_model, flash.usage) + calculate_provider_cost(
        pro_model, pro_usage
    )
    return {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "pricing_version": PRICING_VERSION,
        "probes": {
            "flash": _probe_payload(
                model=flash_model,
                usage=flash.usage,
                finish_reason=_finish_reason(flash),
                json_object=isinstance(flash.json_value, dict),
            ),
            "pro": _probe_payload(
                model=pro_model,
                usage=pro_usage,
                finish_reason=_finish_reason(continuation),
                tool_call=len(tool.tool_calls) == 1,
                thinking_context=bool(tool.reasoning_content),
                continuation=bool(continuation.content) and not continuation.tool_calls,
            ),
        },
        "total": {
            "usage": _usage_payload(total_usage),
            "estimated_cost_usd": f"{total_cost:.6f}",
        },
    }


def _validate_models(settings: RadarAskSettings) -> None:
    if settings.router_model != OFFICIAL_FLASH_MODEL or settings.free_model != OFFICIAL_FLASH_MODEL:
        raise ValueError("router/free model does not match the reviewed Flash contract")
    if settings.smart_model != OFFICIAL_PRO_MODEL:
        raise ValueError("smart model does not match the reviewed Pro contract")
    for model in (settings.router_model, settings.free_model, settings.smart_model):
        if model not in MODEL_PRICES_USD_PER_MILLION:
            raise ValueError("configured model has no reviewed local pricing")


def _require_usage(label: str, response: ProviderResponse) -> None:
    if response.usage.input_tokens <= 0 or response.usage.output_tokens <= 0:
        raise ValueError(f"{label} response is missing provider usage")


def _run_live_smoke(settings: RadarAskSettings) -> dict[str, Any]:
    _validate_models(settings)
    if not settings.deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY is required")

    provider = DeepSeekProvider(settings=settings)
    flash = provider.complete_json(
        model=settings.free_model,
        messages=[
            ProviderMessage(
                role="user",
                content='Return {"ok":true} and no private or real-estate data.',
            )
        ],
        max_output_tokens=32,
        thinking_enabled=False,
    )
    if not isinstance(flash.json_value, dict) or flash.json_value.get("ok") is not True:
        raise ValueError("Flash JSON contract failed")
    _require_usage("Flash", flash)

    tool_definition = ProviderToolDefinition(
        name="release_probe",
        description="Return a fixed compatibility marker for a release smoke.",
        parameters={
            "type": "object",
            "properties": {"marker": {"type": "string", "enum": ["radar-ask-ok"]}},
            "required": ["marker"],
            "additionalProperties": False,
        },
    )
    pro_user = ProviderMessage(
        role="user",
        content="Call release_probe exactly once with marker radar-ask-ok.",
    )
    tool = provider.complete(
        ProviderRequest(
            model=settings.smart_model,
            messages=[pro_user],
            tools=[tool_definition],
            max_output_tokens=128,
            thinking_enabled=True,
            json_mode=False,
        )
    )
    if (
        len(tool.tool_calls) != 1
        or tool.tool_calls[0].name != "release_probe"
        or tool.tool_calls[0].arguments != {"marker": "radar-ask-ok"}
        or not tool.reasoning_content
    ):
        raise ValueError("Pro thinking/tool-call contract failed")
    _require_usage("Pro tool", tool)

    continuation = provider.complete(
        ProviderRequest(
            model=settings.smart_model,
            messages=[
                pro_user,
                ProviderMessage(
                    role="assistant",
                    content=tool.content,
                    tool_calls=tool.tool_calls,
                    reasoning_content=tool.reasoning_content,
                ),
                ProviderMessage(
                    role="tool",
                    tool_call_id=tool.tool_calls[0].call_id,
                    content='{"ok":true}',
                ),
            ],
            tools=[tool_definition],
            max_output_tokens=64,
            thinking_enabled=True,
            json_mode=False,
        )
    )
    if not continuation.content or continuation.tool_calls:
        raise ValueError("Pro tool continuation contract failed")
    _require_usage("Pro continuation", continuation)

    return build_sanitized_report(
        flash_model=settings.free_model,
        pro_model=settings.smart_model,
        flash=flash,
        tool=tool,
        continuation=continuation,
    )


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-live-cost",
        action="store_true",
        help="Confirm two minimal live provider flows that incur DeepSeek cost.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/radar_ask_release/provider-smoke.json"),
    )
    args = parser.parse_args(argv)
    if not args.confirm_live_cost:
        parser.error("refusing live provider calls without --confirm-live-cost")

    try:
        report = _run_live_smoke(RadarAskSettings.from_env())
        _write_report(args.output, report)
    except (ProviderError, ValueError, OSError):
        print("Radar Ask provider smoke failed; no response content was saved", file=sys.stderr)
        return 1
    print("Radar Ask provider smoke passed; sanitized structural/cost report written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
