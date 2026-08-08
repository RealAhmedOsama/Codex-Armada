from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path
from typing import Any

from .benchmark import routing_benchmark
from .canary import CanaryRunner
from .config import AppConfig, load_config
from .console import Console
from .doctor import Doctor
from .domain import RunRecord, RunStatus, TaskStatus
from .errors import ArmadaError
from .executor import Executor
from .git import GitRepository
from .luna_forge import LunaForgeManager
from .paths import project_paths
from .planner import Planner
from .report import ReportGenerator
from .resources import resource_path
from .run_verifier import RunVerifier
from .state import StateStore
from .util import atomic_write_text
from .version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-armada",
        description="Codex Armada — evidence-driven, cost-aware orchestration for Codex CLI.",
    )
    parser.add_argument("--repo", default=".", help="Target Git repository (default: current directory)")
    parser.add_argument("--config", type=Path, help="Additional TOML configuration overlay")
    parser.add_argument("--profile", choices=["economy", "balanced", "quality", "critical"])
    parser.add_argument("--codex-binary", help="Codex command or executable path")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output where practical")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=__version__,
        help="Print project version and exit",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create a project-local Codex Armada configuration")
    init.add_argument("--force", action="store_true", help="Replace an existing local configuration")
    init.add_argument(
        "--tracked",
        action="store_true",
        help="Leave .codex-armada.toml visible to Git; the default stores it as a local exclude",
    )
    init.add_argument(
        "--skip-luna-forge-install",
        action="store_true",
        help="Create configuration only; fetch/install Luna Forge later",
    )
    init.add_argument(
        "--force-luna-forge",
        action="store_true",
        help="Back up and replace conflicting project-local Luna Forge files",
    )

    doctor = sub.add_parser("doctor", help="Validate Python, Git, Codex, Luna Forge, and active routes")
    doctor.add_argument(
        "--probe-models",
        action="store_true",
        help="Spend Codex usage to probe every unique model/effort route in the active profile",
    )
    repair_group = doctor.add_mutually_exclusive_group()
    repair_group.add_argument(
        "--repair-luna-forge",
        dest="repair_luna_forge",
        action="store_const",
        const=True,
        default=None,
        help="Fetch and install the pinned Luna Forge source when missing",
    )
    repair_group.add_argument(
        "--no-auto-install",
        dest="repair_luna_forge",
        action="store_const",
        const=False,
        help="Run doctor read-only and fail when Luna Forge is not already installed",
    )

    forge = sub.add_parser("forge", help="Manage the pinned upstream Luna Forge integration")
    forge.add_argument("action", choices=["status", "fetch", "install", "verify"], nargs="?", default="status")
    forge.add_argument("--force", action="store_true", help="Refresh cache or back up and replace conflicts")
    forge.add_argument("--dry-run", action="store_true", help="Show installation changes without writing")

    plan = sub.add_parser("plan", help="Create and validate a durable execution plan")
    plan.add_argument("goal", help="Observable outcome to achieve")
    plan.add_argument("--budget", type=float)
    plan.add_argument("--plan-file", type=Path, help="Use an existing structured plan")

    run = sub.add_parser("run", help="Plan and execute a goal, or continue an existing run")
    run.add_argument("goal", nargs="?", help="Goal when creating a new run")
    run.add_argument("--run-id", help="Continue an existing planned or approval-waiting run")
    run.add_argument("--plan-file", type=Path)
    run.add_argument("--budget", type=float)
    _add_execution_options(run)

    resume = sub.add_parser("resume", help="Resume an existing run")
    resume.add_argument("run_id")
    _add_execution_options(resume)

    status = sub.add_parser("status", help="Show durable run state")
    status.add_argument("run_id", nargs="?")
    status.add_argument("--all", action="store_true")

    report = sub.add_parser("report", help="Generate JSON and standalone HTML reports")
    report.add_argument("run_id", nargs="?")
    report.add_argument("--open", action="store_true")

    verify = sub.add_parser("verify", help="Verify final Git and evidence invariants for a run")
    verify.add_argument("run_id", nargs="?")

    canary = sub.add_parser("canary", help="Run a disposable end-to-end model-routing canary")
    canary.add_argument("--model", choices=["luna", "terra", "sol"], default="luna")
    canary.add_argument(
        "--effort",
        choices=["none", "low", "medium", "high", "xhigh", "max"],
        default="medium",
    )
    canary.add_argument("--keep", action="store_true", help="Keep the disposable repository for inspection")

    sub.add_parser("benchmark", help="Show routing and estimated-credit economics for the active profile")
    sub.add_parser("show-config", help="Print the effective merged configuration")
    sub.add_parser("wizard", help="Run the interactive English setup and execution wizard")
    sub.add_parser("version", help="Print the installed version")
    return parser


def _add_execution_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--approve", action="append", default=[], metavar="TASK_ID", help="Approve one task")
    parser.add_argument("--approve-all-required", action="store_true", help="Approve all gated tasks")
    parser.add_argument("--no-commit", action="store_true", help="Do not commit; valid only for one-task plans")
    parser.add_argument("--keep-worktrees", action="store_true", help="Keep successful isolated worktrees")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console(json_mode=args.json, quiet=args.quiet)
    try:
        if args.command == "wizard":
            return _wizard(args, console)
        if args.command == "version":
            print(__version__)
            return 0

        repo = Path(args.repo).expanduser().resolve()
        if args.command == "init":
            return _init(repo, args, console)

        repo = GitRepository(repo).repo
        config = load_config(repo, profile=args.profile, config_path=args.config, codex_binary=args.codex_binary)
        paths = project_paths(repo)
        state = StateStore(paths)

        if args.command == "forge":
            return _forge(config, repo, args, console)
        if args.command == "doctor":
            return _doctor(config, paths, args, console)
        if args.command == "show-config":
            console.payload(config.raw)
            return 0
        if args.command == "benchmark":
            payload = routing_benchmark(config)
            console.payload(payload) if args.json else _print_benchmark(payload, console)
            return 0
        if args.command == "canary":
            Doctor(config, paths).require_healthy()
            result = CanaryRunner(config, paths).run(model_alias=args.model, effort=args.effort, keep=args.keep)
            console.payload(result) if args.json else _print_canary(result, console)
            return 0 if result["succeeded"] else 5
        if args.command == "plan":
            capabilities = Doctor(config, paths).require_healthy()
            record = Planner(config=config, capabilities=capabilities, state=state).create(
                goal=args.goal,
                repo=repo,
                budget_credits=args.budget,
                plan_file=args.plan_file,
            )
            _print_run(record, console)
            return 0
        if args.command in {"run", "resume"}:
            if args.command == "resume":
                args.goal = None
                args.plan_file = None
                args.budget = None
            return _run_command(config, paths, state, repo, args, console)
        if args.command == "status":
            if args.all:
                records = state.list()
                if args.json:
                    console.payload([record.to_dict() for record in records])
                else:
                    console.table(
                        ["Run", "Status", "Profile", "Credits", "Goal"],
                        [[r.run_id, r.status.value, r.profile, f"{r.actual_credits:.3f}", r.goal] for r in records],
                    )
                return 0
            record = state.load(args.run_id) if args.run_id else state.latest()
            _print_run(record, console)
            return 0
        if args.command == "report":
            record = state.load(args.run_id) if args.run_id else state.latest()
            json_path, html_path = ReportGenerator(state, language=config.report_language).generate(record)
            if args.open:
                ReportGenerator(state, language=config.report_language).open(html_path)
            console.payload({"json": str(json_path), "html": str(html_path)}) if args.json else console.success(
                f"Report: {html_path}"
            )
            return 0
        if args.command == "verify":
            record = state.load(args.run_id) if args.run_id else state.latest()
            result = RunVerifier().verify(record)
            console.payload(result) if args.json else _print_verification(result, console)
            return 0 if result["valid"] else 6

        parser.error(f"Unhandled command: {args.command}")
        return 2
    except ArmadaError as exc:
        console.error(str(exc))
        if args.debug:
            traceback.print_exc()
        return 2
    except KeyboardInterrupt:
        console.warning("Cancelled by user")
        return 130
    except Exception as exc:  # pragma: no cover - final defensive boundary
        console.error(f"Unexpected failure: {exc}")
        if args.debug:
            traceback.print_exc()
        return 1


def _init(repo: Path, args: argparse.Namespace, console: Console) -> int:
    git = GitRepository(repo)
    target = git.repo / ".codex-armada.toml"
    if target.exists() and not args.force:
        console.warning(f"Configuration already exists: {target}; use --force to replace it")
        return 3
    _write_project_config(git, tracked=args.tracked)
    suffix = "tracked-ready" if args.tracked else "stored in .git/info/exclude"
    console.success(f"Created {target} ({suffix})")

    if not args.skip_luna_forge_install:
        config = load_config(git.repo, profile=args.profile, config_path=args.config, codex_binary=args.codex_binary)
        result = LunaForgeManager(config).ensure_project_install(git.repo, force=args.force_luna_forge)
        console.success(
            f"Luna Forge {result.status.source_version} ready from {result.status.resolved_commit[:12]} "
            f"· source digest={result.status.source_digest[:16]}"
        )
    else:
        console.warning("Skipped Luna Forge installation; run `codex-armada forge install` before Luna work")
    return 0


def _write_project_config(git: GitRepository, *, tracked: bool = False) -> Path:
    target = git.repo / ".codex-armada.toml"
    atomic_write_text(target, resource_path("project_config.toml").read_text(encoding="utf-8"))
    if not tracked:
        git.add_local_exclude(".codex-armada.toml")
    return target


def _forge(config: AppConfig, repo: Path, args: argparse.Namespace, console: Console) -> int:
    manager = LunaForgeManager(config)
    if args.action == "fetch":
        path, changed = manager.fetch_source(force=args.force)
        status = manager.inspect(repo)
        payload = {"changed": changed, "cache_path": str(path), "status": status.to_dict()}
        if console.json_mode:
            console.payload(payload)
        else:
            console.success(
                f"{'Fetched' if changed else 'Already cached'} Luna Forge {status.source_version or status.required_version} "
                f"at {status.resolved_commit[:12] if status.resolved_commit else status.expected_commit[:12]}"
            )
        return 0
    if args.action == "install":
        result = manager.ensure_project_install(repo, force=args.force, dry_run=args.dry_run)
        if console.json_mode:
            console.payload(result.to_dict())
        else:
            verb = "Would install" if result.dry_run else ("Installed" if result.changed else "Already current")
            console.success(
                f"{verb}: Luna Forge {result.status.source_version or result.status.required_version} "
                f"from {result.status.resolved_commit[:12] if result.status.resolved_commit else 'uncached'}"
            )
            for item in result.backed_up:
                console.warning(f"Backup: {item}")
        return 0

    status = manager.inspect(repo)
    if args.action == "verify":
        status = manager.require_installed(repo)
    if console.json_mode:
        console.payload(status.to_dict())
    else:
        console.table(
            ["Luna Forge check", "Value"],
            [
                ["Repository", status.repository],
                ["Pinned ref", status.requested_ref],
                ["Expected commit", status.expected_commit],
                ["Resolved commit", status.resolved_commit or "not cached"],
                ["Required version", status.required_version],
                ["Source version", status.source_version or "not cached"],
                ["Source integrity", status.source_valid],
                ["Project skill exact", status.skill_exact],
                ["Project agent exact", status.agent_exact],
                ["Installed", status.installed],
                ["Conflict", status.conflict],
                ["Source digest", (status.source_digest or "unknown")[:16]],
            ],
        )
        for warning in status.warnings:
            console.warning(warning)
        for error in status.errors:
            console.error(error)
    return 0 if status.installed and status.source_valid and not status.errors else 2


def _forge_summary(payload: dict[str, Any]) -> str:
    status = payload.get("status") if isinstance(payload, dict) else None
    if not isinstance(status, dict):
        return "not checked"
    version = status.get("source_version") or status.get("required_version") or "unknown"
    state = "ready" if status.get("installed") and status.get("source_valid") else "not ready"
    commit = str(status.get("resolved_commit") or status.get("expected_commit") or "")[:12]
    return f"{version} · {state}" + (f" · {commit}" if commit else "")


def _doctor(config: AppConfig, paths: Any, args: argparse.Namespace, console: Console) -> int:
    result = Doctor(config, paths).inspect(
        probe_models=args.probe_models,
        repair_luna_forge=args.repair_luna_forge,
    )
    if args.json:
        console.payload(result.to_dict())
    else:
        console.table(
            ["Check", "Value"],
            [
                ["Healthy", result.healthy],
                ["Python", result.python_version],
                ["Git", result.git_version or "missing"],
                ["Codex", result.codex_version or "missing"],
                ["Required exec flags", result.flags.get("required_ready", False)],
                ["Model catalog", ", ".join(sorted(result.available_models)) or "not exposed"],
                ["Luna Forge", _forge_summary(result.luna_forge)],
                ["Capability digest", result.digest[:16]],
            ],
        )
        for warning in result.warnings:
            console.warning(warning)
        for error in result.errors:
            console.error(error)
    return 0 if result.healthy else 2


def _run_command(
    config: AppConfig,
    paths: Any,
    state: StateStore,
    repo: Path,
    args: argparse.Namespace,
    console: Console,
) -> int:
    capabilities = Doctor(config, paths).require_healthy()
    if getattr(args, "run_id", None):
        record = state.load(args.run_id)
    else:
        if not args.goal:
            raise ArmadaError("A goal is required when --run-id is not supplied")
        record = Planner(config=config, capabilities=capabilities, state=state).create(
            goal=args.goal,
            repo=repo,
            budget_credits=args.budget,
            plan_file=args.plan_file,
        )
        _print_run(record, console)
    result = Executor(config=config, capabilities=capabilities, state=state).execute(
        record,
        approved_tasks=set(args.approve),
        approve_all_required=args.approve_all_required,
        commit_enabled=False if args.no_commit else None,
        keep_worktrees=args.keep_worktrees,
    )
    _, html_path = ReportGenerator(state, language=config.report_language).generate(result)
    _print_run(result, console)
    console.info(f"Report: {html_path}")
    if result.status == RunStatus.COMPLETED:
        return 0
    if result.status == RunStatus.AWAITING_APPROVAL:
        waiting = [task.plan.id for task in result.tasks if task.status == TaskStatus.AWAITING_APPROVAL]
        console.warning(
            f"Approval required. Resume with: codex-armada --repo \"{repo}\" resume {result.run_id} "
            + " ".join(f"--approve {task_id}" for task_id in waiting)
        )
        return 3
    return 4


def _print_run(record: RunRecord, console: Console) -> None:
    if console.json_mode:
        console.payload(record.to_dict())
        return
    console.info(
        f"Run {record.run_id} · {record.status.value} · profile={record.profile} · "
        f"credits={record.actual_credits:.3f}/{record.budget_credits if record.budget_credits is not None else '∞'}"
    )
    rows: list[list[Any]] = []
    for task in record.tasks:
        rows.append(
            [
                task.plan.id,
                task.plan.risk.value,
                f"{task.route.worker_alias}/{task.route.worker_effort}"
                + (f" · {task.route.worker_protocol}" if task.route.worker_protocol != "standard" else ""),
                task.status.value,
                f"{task.credits:.3f}",
                (task.applied_commit_sha or task.source_commit_sha or "—")[:12],
            ]
        )
    if rows:
        console.table(["Task", "Risk", "Route", "Status", "Credits", "Commit"], rows)
    if record.error:
        console.warning(record.error)


def _print_benchmark(payload: dict[str, object], console: Console) -> None:
    routes = payload.get("routes", [])
    assert isinstance(routes, list)
    console.info(f"Profile: {payload.get('profile')}")
    console.table(
        ["Task", "Risk", "Worker", "Effort", "Protocol", "Plan review", "Final review", "Approval", "Est. credits"],
        [
            [
                row["task"],
                row["risk"],
                row["model_alias"],
                row["effort"],
                row.get("worker_protocol", "standard"),
                row["plan_review"],
                row["final_review"],
                row["approval"],
                f"{float(row['estimated_credits']):.2f}",
            ]
            for row in routes
            if isinstance(row, dict)
        ],
    )


def _print_canary(result: dict[str, object], console: Console) -> None:
    if result.get("succeeded"):
        console.success(
            f"Canary passed: {result.get('model')} / {result.get('effort')} · "
            f"protocol={result.get('worker_protocol')} · credits={result.get('credits')}"
        )
    else:
        console.error(f"Canary failed: {json.dumps(result, ensure_ascii=False)}")


def _print_verification(result: dict[str, object], console: Console) -> None:
    if result.get("valid"):
        console.success(f"Run {result.get('run_id')} passes final evidence verification")
    else:
        console.error(f"Run {result.get('run_id')} failed verification")
        for finding in result.get("findings", []):
            console.warning(str(finding))


def _wizard(args: argparse.Namespace, console: Console) -> int:
    console.info("Codex Armada interactive setup")
    default_repo = str(Path(args.repo).expanduser().resolve())
    repo_value = input(f"Project path [{default_repo}]: ").strip() or default_repo
    git = GitRepository(Path(repo_value).expanduser().resolve())
    repo = git.repo
    project_config = repo / ".codex-armada.toml"
    if not project_config.exists():
        create = input("Create a local project configuration now? [Y/n]: ").strip().lower()
        if create not in {"n", "no"}:
            _write_project_config(git, tracked=False)
            console.success(f"Created {project_config} and excluded it locally from Git")
    profile = input("Profile [balanced] (economy/balanced/quality/critical): ").strip() or "balanced"
    goal = input("Describe the observable outcome: ").strip()
    if not goal:
        raise ArmadaError("The goal cannot be empty")
    budget_text = input("Credit budget [250]: ").strip()
    budget = float(budget_text) if budget_text else 250.0
    config = load_config(repo, profile=profile, config_path=args.config, codex_binary=args.codex_binary)
    paths = project_paths(repo)
    state = StateStore(paths)
    capabilities = Doctor(config, paths).require_healthy()
    record = Planner(config=config, capabilities=capabilities, state=state).create(
        goal=goal,
        repo=repo,
        budget_credits=budget,
    )
    _print_run(record, console)
    answer = input("Start execution now? [Y/n]: ").strip().lower()
    if answer in {"n", "no"}:
        console.success(f"Plan saved. Resume with: codex-armada --repo \"{repo}\" resume {record.run_id}")
        return 0
    required = [task.plan.id for task in record.tasks if task.route.approval_required]
    approve_all = False
    if required:
        console.warning(f"Explicit approval is required for: {', '.join(required)}")
        approve_all = input("Type APPROVE to authorize those tasks: ").strip() == "APPROVE"
    result = Executor(config=config, capabilities=capabilities, state=state).execute(
        record,
        approve_all_required=approve_all,
    )
    _, html_path = ReportGenerator(state, language=config.report_language).generate(result)
    _print_run(result, console)
    console.success(f"Report: {html_path}")
    return 0 if result.status == RunStatus.COMPLETED else 4
