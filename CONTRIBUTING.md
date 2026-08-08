# Contributing

Thank you for improving Codex Armada. Contributions should preserve its central promise: cheaper execution is useful only when acceptance remains evidence-driven and explicit.

## Before opening a pull request

1. Search existing issues and pull requests.
2. For a behavior change, open or reference an issue that states the observable outcome and risk.
3. Keep one coherent change per pull request.
4. Do not weaken a fail-closed gate merely to make a workflow appear successful.
5. Do not add automatic push, PR, merge, deployment, destructive operations, or global Codex configuration writes without prior design discussion.

## Development setup

```bash
git clone https://github.com/RealAhmedOsama/Codex-Armada.git
cd Codex-Armada
python -m venv .venv
python -m pip install -e .
```

Install optional development tooling when needed:

```bash
python -m pip install -e .[dev]
```

## Required checks

```bash
./run-tests.sh
python scripts/generate_metrics.py --check
python scripts/validate_repository.py
```

On Windows:

```powershell
.\run-tests.bat
py -3.11 scripts\generate_metrics.py --check
py -3.11 scripts\validate_repository.py
```

## Code standards

- Python 3.11 is the syntax floor.
- Runtime code must remain standard-library only unless a design proposal proves a dependency is necessary.
- Use type hints and focused modules.
- Preserve explicit error messages and fail-closed behavior.
- Add deterministic tests for every bugfix and behavior change.
- Keep prompts bounded and outcome-focused.
- Update documentation when configuration, commands, safety, or public behavior changes.
- Never add real credentials, private repositories, or user-specific paths.

## Test design

Tests must not require a real Codex account. Use `tests/fake_codex.py` and the commit-pinned fake Luna Forge upstream from `tests/helpers.py`. Networked real-upstream verification belongs in its dedicated CI job.

## Commit style

Use Conventional Commits where practical:

```text
feat(routing): add explicit capability gate
fix(forge): reject unmanifested upstream files
test(executor): cover reviewer mutation refusal
docs: explain route provenance
```

Do not push generated caches, build directories, local policy files, or release archives.

## Pull-request expectations

A pull request should include:

- problem and observable result;
- design and alternatives considered;
- security and compatibility impact;
- tests and exact commands;
- documentation changes;
- migration or rollback notes when applicable.
