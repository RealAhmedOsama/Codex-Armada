# Recovery

## Interrupted task

If a process stops while a task is `running`, `verifying`, or `reviewing`, the next resume marks it blocked instead of guessing whether a side effect completed.

1. inspect the recorded worktree path in run state;
2. inspect `git status`, the full diff, and task artifacts;
3. preserve useful work manually if appropriate;
4. remove the stale worktree through Git after review;
5. create a fresh plan or deliberately reset the task state outside normal operation.

## Failed cherry-pick

Codex Armada attempts `git cherry-pick --abort`. The main branch must remain at the pre-apply commit. If automatic rollback itself fails, stop all orchestration and repair Git manually before continuing.

## Corrupted or changed state

State is JSON stored outside the project. Back up the complete `CODEX_ARMADA_HOME` directory to preserve plans, events, diffs, reviews, reports, and locks.

A changed config or capability digest intentionally prevents resume. Restore the exact prior configuration and Codex version only when that is safer than creating a new plan.

## Luna Forge cache failure

Run:

```bash
codex-armada --repo <path> forge status
codex-armada --repo <path> forge fetch --force
codex-armada --repo <path> forge verify
```

A forced cache refresh still must resolve to the exact expected commit and pass all integrity checks.

## Project-local Luna Forge conflict

Use `forge install --dry-run` first. If replacement is intentional, use `--force`; the upstream installer creates a local backup. Do not manually merge agent files and then claim exact installation.

## Lost task commit

`verify` checks that recorded commits still exist. If history was rewritten or garbage collection removed an unreferenced source commit, use the applied commit on the main branch when available. Otherwise recover from the retained worktree or artifacts and create a new audited commit.
