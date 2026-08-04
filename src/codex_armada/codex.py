from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .attestation import build_attestation
from .config import AppConfig
from .domain import RuntimeAttestation, TokenUsage
from .errors import ExecutionError
from .jsonl import final_agent_message, parse_jsonl_text, thread_id, token_usage
from .process import command_prefix, run_process
from .schema_validation import validate_json_schema
from .util import atomic_write_json, atomic_write_text, sha256_text


@dataclass(slots=True)
class CodexFlags:
    json_output: bool
    model: bool
    config_override: bool
    sandbox: bool
    cd: bool
    output_schema: bool
    output_last_message: bool
    skip_git_repo_check: bool
    ephemeral: bool
    ignore_user_config: bool

    @property
    def required_ready(self) -> bool:
        return all(
            (
                self.json_output,
                self.model,
                self.config_override,
                self.sandbox,
                self.cd,
                self.output_schema,
                self.output_last_message,
            )
        )

    def to_dict(self) -> dict[str, bool]:
        return {
            "json_output": self.json_output,
            "model": self.model,
            "config_override": self.config_override,
            "sandbox": self.sandbox,
            "cd": self.cd,
            "output_schema": self.output_schema,
            "output_last_message": self.output_last_message,
            "skip_git_repo_check": self.skip_git_repo_check,
            "ephemeral": self.ephemeral,
            "ignore_user_config": self.ignore_user_config,
            "required_ready": self.required_ready,
        }


@dataclass(slots=True)
class CodexExecution:
    command: list[str]
    return_code: int
    duration_seconds: float
    final_response: dict[str, Any] | None
    events: list[dict[str, Any]]
    usage: TokenUsage
    attestation: RuntimeAttestation
    thread_id: str | None
    stdout_path: Path
    stderr_path: Path
    last_message_path: Path
    prompt_digest: str
    schema_errors: list[str]

    @property
    def succeeded(self) -> bool:
        return self.return_code == 0 and self.final_response is not None


class CodexRunner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.prefix = command_prefix(config.codex_binary)
        if not self.prefix:
            raise ExecutionError("Codex binary command is empty")
        self._flags: CodexFlags | None = None
        self._version: str | None = None

    def version(self) -> str:
        if self._version is None:
            result = run_process([*self.prefix, "--version"], timeout=30)
            if not result.succeeded:
                raise ExecutionError(result.stderr.strip() or "Could not run `codex --version`")
            self._version = result.stdout.strip() or result.stderr.strip()
        return self._version

    def flags(self) -> CodexFlags:
        if self._flags is not None:
            return self._flags
        root = run_process([*self.prefix, "--help"], timeout=30)
        execute = run_process([*self.prefix, "exec", "--help"], timeout=30)
        if not root.succeeded or not execute.succeeded:
            raise ExecutionError((root.stderr or execute.stderr).strip() or "Could not inspect Codex CLI help")
        root_help = f"{root.stdout}\n{root.stderr}".lower()
        exec_help = f"{execute.stdout}\n{execute.stderr}".lower()
        self._flags = CodexFlags(
            json_output="--json" in exec_help,
            model="--model" in exec_help or "-m," in exec_help,
            config_override="--config" in root_help or "-c," in root_help or "-c " in root_help or "--config" in exec_help,
            sandbox="--sandbox" in exec_help or "-s," in exec_help,
            cd="--cd" in exec_help,
            output_schema="--output-schema" in exec_help,
            output_last_message="--output-last-message" in exec_help,
            skip_git_repo_check="--skip-git-repo-check" in exec_help,
            ephemeral="--ephemeral" in exec_help,
            ignore_user_config="--ignore-user-config" in exec_help or "--ignore-user-config" in root_help,
        )
        return self._flags

    def run(
        self,
        *,
        repo: Path,
        prompt: str,
        model: str,
        effort: str,
        sandbox: str,
        schema_path: Path,
        artifact_dir: Path,
        label: str,
        timeout: int | None = None,
        skip_git_repo_check: bool = False,
    ) -> CodexExecution:
        flags = self.flags()
        if not flags.required_ready:
            missing = [key for key, value in flags.to_dict().items() if key != "required_ready" and not value]
            raise ExecutionError(f"Installed Codex CLI lacks required exec flags: {', '.join(missing)}")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = artifact_dir / f"{label}.stdout.jsonl"
        stderr_path = artifact_dir / f"{label}.stderr.log"
        last_message_path = artifact_dir / f"{label}.last-message.json"
        for stale in (stdout_path, stderr_path, last_message_path):
            try:
                stale.unlink()
            except FileNotFoundError:
                pass
        prompt_digest = sha256_text(prompt)
        if self.config.store_prompts:
            atomic_write_text(artifact_dir / f"{label}.prompt.txt", prompt)
        atomic_write_json(
            artifact_dir / f"{label}.request.json",
            {
                "model": model,
                "effort": effort,
                "sandbox": sandbox,
                "schema": str(schema_path),
                "repo": str(repo),
                "prompt_sha256": prompt_digest,
            },
        )

        command = [*self.prefix, "exec", "--json", "--model", model]
        command.extend(["-c", f'model_reasoning_effort="{effort}"'])
        command.extend(["--sandbox", sandbox, "--cd", str(repo.resolve())])
        command.extend(["--output-schema", str(schema_path.resolve())])
        command.extend(["--output-last-message", str(last_message_path.resolve())])
        if skip_git_repo_check and flags.skip_git_repo_check:
            command.append("--skip-git-repo-check")
        if self.config.ignore_user_config and flags.ignore_user_config:
            command.append("--ignore-user-config")
        command.append("-")

        result = run_process(
            command,
            cwd=repo,
            input_text=prompt,
            timeout=timeout or self.config.command_timeout_seconds,
        )
        atomic_write_text(stdout_path, result.stdout)
        atomic_write_text(stderr_path, result.stderr)
        events = parse_jsonl_text(result.stdout)
        resolved_thread_id = thread_id(events)
        message = ""
        if last_message_path.is_file():
            message = last_message_path.read_text(encoding="utf-8", errors="replace").strip()
        if not message:
            message = final_agent_message(events)
            if message:
                atomic_write_text(last_message_path, message)
        final_response = _parse_json_object(message)
        schema_errors: list[str] = []
        if final_response is not None:
            try:
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                schema_errors = [f"Could not load output schema: {exc}"]
            else:
                if not isinstance(schema, dict):
                    schema_errors = ["Output schema root must be a JSON object"]
                else:
                    schema_errors = validate_json_schema(final_response, schema)
            if schema_errors:
                atomic_write_json(artifact_dir / f"{label}.schema-errors.json", schema_errors)
                final_response = None
        usage = token_usage(events)
        attestation = build_attestation(
            events=events,
            requested_model=model,
            requested_effort=effort,
            requested_sandbox=sandbox,
            thread_id=resolved_thread_id,
        )
        execution = CodexExecution(
            command=command,
            return_code=result.return_code,
            duration_seconds=result.duration_seconds,
            final_response=final_response,
            events=events,
            usage=usage,
            attestation=attestation,
            thread_id=resolved_thread_id,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            last_message_path=last_message_path,
            prompt_digest=prompt_digest,
            schema_errors=schema_errors,
        )
        atomic_write_json(
            artifact_dir / f"{label}.execution.json",
            {
                "command": command,
                "return_code": result.return_code,
                "duration_seconds": result.duration_seconds,
                "thread_id": resolved_thread_id,
                "usage": usage.to_dict(),
                "attestation": attestation.to_dict(),
                "structured_output": final_response is not None,
                "schema_errors": schema_errors,
            },
        )
        return execution

    def try_model_catalog(self) -> tuple[set[str], str | None]:
        candidates = (
            [*self.prefix, "debug", "models", "--json"],
            [*self.prefix, "models", "list", "--json"],
        )
        for command in candidates:
            result = run_process(command, timeout=30)
            if not result.succeeded:
                continue
            models = _extract_model_ids(result.stdout)
            if models:
                return models, " ".join(command[len(self.prefix) :])
        return set(), None


def _parse_json_object(value: str) -> dict[str, Any] | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.IGNORECASE | re.DOTALL)
    for candidate in reversed(fenced):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def _extract_model_ids(value: str) -> set[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return set()
    result: set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"id", "model", "model_id", "slug"} and isinstance(child, str) and child.startswith("gpt-"):
                    result.add(child)
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(parsed)
    return result
