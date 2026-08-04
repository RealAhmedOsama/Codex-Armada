from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .domain import RuntimeAttestation
from .jsonl import observed_runtime, parse_jsonl_file

_THREAD_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def build_attestation(
    *,
    events: list[dict[str, Any]],
    requested_model: str,
    requested_effort: str,
    requested_sandbox: str,
    thread_id: str | None,
) -> RuntimeAttestation:
    event_runtime = observed_runtime(events)
    observed = dict(event_runtime)
    source = "events"
    evidence_conflicts: list[str] = []
    if any(not event_runtime.get(field) for field in ("model", "effort", "sandbox", "permission_profile")):
        rollout = _rollout_runtime(thread_id)
        if rollout:
            event_has_runtime = any(event_runtime.values())
            for field, rollout_value in rollout.items():
                event_value = event_runtime.get(field)
                if event_value and rollout_value and _normalize(event_value) != _normalize(rollout_value):
                    evidence_conflicts.append(
                        f"runtime evidence conflict for {field}: events={event_value} rollout={rollout_value}"
                    )
                elif not event_value and rollout_value:
                    observed[field] = rollout_value
            source = "events+rollout" if event_has_runtime else "rollout"
    requested_mismatch = _mismatch(
        requested_model=requested_model,
        requested_effort=requested_effort,
        requested_sandbox=requested_sandbox,
        observed=observed,
    )
    mismatch = "; ".join([*evidence_conflicts, *([requested_mismatch] if requested_mismatch else [])]) or None
    verified = bool(observed.get("model") and observed.get("effort") and not mismatch)
    return RuntimeAttestation(
        requested_model=requested_model,
        requested_effort=requested_effort,
        requested_sandbox=requested_sandbox,
        observed_model=observed.get("model"),
        observed_effort=observed.get("effort"),
        observed_sandbox=observed.get("sandbox"),
        permission_profile=observed.get("permission_profile"),
        thread_id=thread_id,
        source=source if verified or any(observed.values()) else "requested-only",
        verified=verified,
        mismatch=mismatch,
    )


def _mismatch(
    *, requested_model: str,
    requested_effort: str,
    requested_sandbox: str,
    observed: dict[str, str | None],
) -> str | None:
    parts: list[str] = []
    if observed.get("model") and _normalize(observed["model"]) != _normalize(requested_model):
        parts.append(f"model requested={requested_model} observed={observed['model']}")
    if observed.get("effort") and _normalize(observed["effort"]) != _normalize(requested_effort):
        parts.append(f"effort requested={requested_effort} observed={observed['effort']}")
    if observed.get("sandbox") and _normalize(observed["sandbox"]) != _normalize(requested_sandbox):
        parts.append(f"sandbox requested={requested_sandbox} observed={observed['sandbox']}")
    return "; ".join(parts) or None


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower().replace("_", "-")


def _sessions_root() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    return Path(codex_home).expanduser() / "sessions" if codex_home else Path.home() / ".codex" / "sessions"


def _rollout_runtime(thread_id: str | None) -> dict[str, str | None] | None:
    if not thread_id or not _THREAD_ID.fullmatch(thread_id):
        return None
    root = _sessions_root()
    if not root.is_dir():
        return None
    matches = list(root.rglob(f"rollout-*-{thread_id}.jsonl"))
    if len(matches) != 1:
        return None
    events = parse_jsonl_file(matches[0])
    runtime = observed_runtime(events)
    # Preserve compatibility with rollout variants that place routing fields only
    # inside the turn_context payload. Continue even when model and effort were
    # already found so sandbox and permission evidence are not lost.
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if event.get("type") == "turn_context":
            runtime["model"] = runtime.get("model") or _string(payload.get("model"))
            runtime["effort"] = runtime.get("effort") or _string(payload.get("effort"))
            sandbox = payload.get("sandbox_policy")
            if isinstance(sandbox, dict):
                runtime["sandbox"] = runtime.get("sandbox") or _string(sandbox.get("type"))
            permission = payload.get("permission_profile")
            if isinstance(permission, dict):
                runtime["permission_profile"] = runtime.get("permission_profile") or _string(permission.get("type"))
    return runtime if any(runtime.values()) else None


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
