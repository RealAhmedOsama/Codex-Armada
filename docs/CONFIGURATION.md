# Configuration reference

Codex Armada uses TOML configuration schema version `1`.

## Merge order

1. packaged `default_config.toml`;
2. target repository `.codex-armada.toml`;
3. explicit `--config` overlay;
4. selected CLI profile and Codex binary overrides.

Nested tables merge recursively. Risk rules and protection lists are additive so a project cannot accidentally erase packaged safety defaults with a short overlay.

## Core settings

```toml
version = 1
profile = "balanced"
language = "en"
report_language = "en"
codex_binary = "codex"
commit_per_task = true
use_isolated_worktrees = true
require_clean_tree = true
keep_failed_worktrees = true
store_prompts = false
ignore_user_config = false
max_corrections = 1
command_timeout_seconds = 3600
verification_timeout_seconds = 1800
attestation_required_from = "critical"
default_budget_credits = 250.0
```

### Prompt storage

`store_prompts = false` stores a SHA-256 prompt digest and execution artifacts without the full prompt. Set it to `true` only when the task does not contain sensitive material and full replayability is required.

### User Codex configuration

`ignore_user_config = true` asks supported Codex versions to ignore user-level configuration for more reproducible runs. `doctor` verifies whether the installed CLI exposes the required flag before using it.

## Models

```toml
[models]
luna = "gpt-5.6-luna"
terra = "gpt-5.6-terra"
sol = "gpt-5.6-sol"
```

Luna Forge currently requires the `luna` alias to remain `gpt-5.6-luna`.

## Luna Forge

```toml
[luna_forge]
enabled = true
repository = "https://github.com/RealAhmedOsama/Luna-Forge.git"
ref = "ff37273ba761195ef5ab338d2e90ef3408ce8d8c"
expected_commit = "ff37273ba761195ef5ab338d2e90ef3408ce8d8c"
required_version = "2.2.1"
auto_fetch = true
auto_install = true
install_scope = "project"
strict_integrity = true
allow_non_github_source = false
cache_dir = ""
skill_name = "luna-forge"
agent_name = "luna_worker"
default_effort = "high"
invoke_for_aliases = ["luna"]
```

`ref` and `expected_commit` must be the same full lowercase 40-character SHA. Floating branches and tags are rejected so a reviewed configuration cannot silently resolve to different upstream code. `allow_non_github_source` should be limited to controlled mirrors and tests.

## Profiles

```toml
[profiles.balanced]
low_worker = "luna"
medium_worker = "terra"
high_worker = "terra"
critical_worker = "sol"
low_effort = "high"
medium_effort = "high"
high_effort = "xhigh"
critical_effort = "xhigh"
final_review_from = "high"
plan_review_from = "critical"
approval_from = "critical"
```

Supported effort values are `none`, `low`, `medium`, `high`, `xhigh`, and `max`. Availability is verified at runtime; configuration support is not proof that a specific Codex account exposes the route.

## Risk rules

```toml
[[risk_rules]]
pattern = "src/Payments/**"
risk = "critical"
reason = "Payment authorization and financial state"
```

Patterns use Git-style forward-slash paths and support `*`, `?`, character classes, and recursive `**` matching.

## Protection lists

`protected_paths` block acceptance entirely. `production_paths` require both a plan flag and explicit approval. Project overlays add to packaged lists.

## Verification tools

`allowed_verification_tools` controls executable names. Every accepted executable must also have a built-in safety policy. Git, Python, dotnet, package-manager, Cargo, Go, Maven, and Gradle commands are restricted to read-only or test/build/check operations. Package-manager scripts must use names such as `test`, `lint`, `check`, `verify`, `validate`, `build`, `typecheck`, or `ci`; publication, deployment, migration, and release script names are rejected. Verification runs without a shell and is rejected if it changes repository state.

## Environment variables

| Variable | Purpose |
|---|---|
| `CODEX_ARMADA_HOME` | Override durable state root. |
| `CODEX_ARMADA_CACHE_DIR` | Override external source cache root. |
| `CODEX_ARMADA_CODEX_BINARY` | Override the Codex executable. |
| `PYTHON` | Select Python in the source launchers. |
