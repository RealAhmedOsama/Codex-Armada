# Luna Forge integration

Codex Armada consumes [Luna Forge](https://github.com/RealAhmedOsama/Luna-Forge) as an external, commit-pinned upstream dependency. No Luna Forge source is vendored into this repository.

## Default source

| Field | Value |
|---|---|
| Repository | `https://github.com/RealAhmedOsama/Luna-Forge.git` |
| Version | `2.2.1` |
| Git ref | `ff37273ba761195ef5ab338d2e90ef3408ce8d8c` |
| Expected commit | `ff37273ba761195ef5ab338d2e90ef3408ce8d8c` |
| Skill | `luna-forge` |
| Agent | `luna_worker` |
| Model | `gpt-5.6-luna` |
| Default effort | `high` |

## Fetch algorithm

1. Validate that the repository is HTTPS GitHub unless a non-GitHub source was explicitly enabled.
2. Require `ref` and `expected_commit` to be the same full 40-character commit SHA; floating branches and tags are rejected.
3. Require the cache root and any existing checkout to be real directories inside the configured cache boundary, never symbolic links.
4. Acquire a cache lock scoped to the expected commit.
5. Initialize a temporary Git repository.
6. Fetch only the configured commit with depth one.
7. Check out `FETCH_HEAD` detached.
8. Require the exact expected commit.
9. Require a clean checkout with no untracked files.
10. Require the configured `VERSION`.
11. Verify every `MANIFEST.sha256` entry.
12. Reject duplicate, missing, escaping, symbolic-link, and unmanifested paths.
13. Run upstream `scripts/validate.py`.
14. Record a validation marker containing commit, version, manifest hash, and validator hash.
15. Atomically move the validated temporary checkout into the commit-keyed cache.

The validation marker avoids repeatedly running the upstream test suite during every local status check. It does not replace integrity verification: the manifest and Git cleanliness are checked each time before the marker is trusted.

## Installation algorithm

Codex Armada invokes the upstream installer rather than reimplementing its copy behavior:

```text
python scripts/install.py --scope project --project-root <target>
```

The exact installed paths are:

```text
<target>/.agents/skills/luna-forge/
<target>/.codex/agents/luna-worker.toml
```

Codex Armada independently compares the installed tree and agent file against the validated cache. It also asks Git for the correct worktree-local `info/exclude` path and adds:

```text
.agents/skills/luna-forge/
.codex/agents/luna-worker.toml
.luna-forge-backups/
```

This works with normal repositories and linked worktrees because the Git metadata path is resolved through `git rev-parse --git-path`.

## Conflict policy

- Identical files are a no-op.
- Partial installations are conflicts.
- Different files, nonregular files, or symbolic links are conflicts.
- No conflict is overwritten without `--force`.
- Forced replacement is delegated to the upstream installer, which backs up the prior files under `.luna-forge-backups/`.

## Per-task attestation

A Luna route records:

- repository URL;
- requested ref;
- expected and resolved commit;
- required and observed version;
- source digest;
- project skill and agent exactness;
- installation digest;
- worker model, effort, sandbox, and transport.

The installation is checked before the worker call and after it. An ignored-file mutation is therefore detected even though Git status does not report it.

## Upgrades

A Luna Forge upgrade is a reviewed release change, not an automatic floating update.

1. inspect the new upstream tag and commit;
2. change `ref`, `expected_commit`, and `required_version` together;
3. run repository tests;
4. run the real-upstream CI job;
5. update documentation and changelog;
6. run model canaries on a compatible Codex account;
7. publish a new Codex Armada release.

Users may override the pin in a project or explicit config overlay, but the override remains subject to the same commit, version, manifest, and validation gates.
