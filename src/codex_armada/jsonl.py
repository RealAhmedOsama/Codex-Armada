from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .domain import TokenUsage


def parse_jsonl_text(value: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def parse_jsonl_file(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return parse_jsonl_text(path.read_text(encoding="utf-8", errors="replace"))


def thread_id(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        event_type = str(event.get("type", "")).lower()
        if event_type in {"thread.started", "thread_started", "session_meta"}:
            for candidate in _values_for_keys(event, {"thread_id", "threadId", "id"}):
                if isinstance(candidate, str) and candidate:
                    return candidate
    for candidate in _values_for_keys(events, {"thread_id", "threadId"}):
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def token_usage(events: list[dict[str, Any]]) -> TokenUsage:
    candidates: list[TokenUsage] = []
    for event in events:
        for value in _objects_for_keys(event, {"usage", "token_usage", "tokenUsage"}):
            if not isinstance(value, dict):
                continue
            usage = TokenUsage(
                input_tokens=_first_int(value, "input_tokens", "inputTokens", "prompt_tokens", "promptTokens"),
                cached_input_tokens=_first_int(
                    value,
                    "cached_input_tokens",
                    "cachedInputTokens",
                    "cached_tokens",
                    "cache_read_input_tokens",
                ),
                output_tokens=_first_int(value, "output_tokens", "outputTokens", "completion_tokens", "completionTokens"),
                reasoning_output_tokens=_first_int(
                    value,
                    "reasoning_output_tokens",
                    "reasoningOutputTokens",
                    "reasoning_tokens",
                    "reasoningTokens",
                ),
            )
            if usage.total_tokens or usage.cached_input_tokens:
                candidates.append(usage)
    if not candidates:
        return TokenUsage()
    return max(candidates, key=lambda item: item.total_tokens + item.cached_input_tokens)


def observed_runtime(events: list[dict[str, Any]]) -> dict[str, str | None]:
    result: dict[str, str | None] = {
        "model": None,
        "effort": None,
        "sandbox": None,
        "permission_profile": None,
    }
    for event in events:
        event_type = str(event.get("type", "")).lower()
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
        if event_type in {"turn_context", "turn.started", "turn.completed", "response.completed", "session_meta"}:
            if result["model"] is None:
                result["model"] = _first_string(payload, "model", "model_id", "modelId")
            if result["effort"] is None:
                result["effort"] = _first_string(payload, "effort", "reasoning_effort", "reasoningEffort", "thinking")
            if result["sandbox"] is None:
                sandbox = payload.get("sandbox_policy") or payload.get("sandboxPolicy") or payload.get("sandbox_mode")
                if isinstance(sandbox, dict):
                    result["sandbox"] = _first_string(sandbox, "type", "mode")
                elif isinstance(sandbox, str):
                    result["sandbox"] = sandbox
            if result["permission_profile"] is None:
                permission = payload.get("permission_profile") or payload.get("permissionProfile")
                if isinstance(permission, dict):
                    result["permission_profile"] = _first_string(permission, "type", "mode")
                elif isinstance(permission, str):
                    result["permission_profile"] = permission
    return result


def final_agent_message(events: list[dict[str, Any]]) -> str:
    candidates: list[str] = []
    for event in events:
        event_type = str(event.get("type", "")).lower()
        item = event.get("item")
        if isinstance(item, dict):
            item_type = str(item.get("type", "")).lower()
            if item_type in {"agent_message", "assistant_message", "message", "output_text"}:
                text = _coerce_text(item)
                if text:
                    candidates.append(text)
        if event_type in {"agent_message", "assistant_message", "message", "output_text"}:
            text = _coerce_text(event)
            if text:
                candidates.append(text)
    return candidates[-1] if candidates else ""


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _values_for_keys(value: Any, keys: set[str]) -> Iterable[Any]:
    for item in _walk(value):
        if isinstance(item, dict):
            for key in keys:
                if key in item:
                    yield item[key]


def _objects_for_keys(value: Any, keys: set[str]) -> Iterable[Any]:
    yield from _values_for_keys(value, keys)


def _first_int(data: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _first_string(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _coerce_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (_coerce_text(item) for item in value)))
    if isinstance(value, dict):
        for key in ("text", "output_text", "content", "message"):
            text = _coerce_text(value.get(key))
            if text:
                return text
    return ""
