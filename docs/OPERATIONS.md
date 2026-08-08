# Operations

## First-time rollout

1. Install Codex Armada.
2. Enter a clean Git repository with at least one commit.
3. Run `codex-armada --repo <path> init`.
4. Run `doctor` without model probes.
5. Review the reported Luna Forge source and commit.
6. Run `doctor --probe-models` when the expected routes are correct.
7. Run one Luna, Terra, and Sol canary as applicable.
8. Start with a low-risk, one-file task.
9. Inspect the JSON and HTML report before broadening use.

## Routine workflow

```bash
codex-armada --repo <path> doctor
codex-armada --repo <path> plan "<goal>"
codex-armada --repo <path> run --run-id <run-id>
codex-armada --repo <path> verify <run-id>
codex-armada --repo <path> report <run-id> --open
```

## Approval workflow

An approval-waiting run is durable. Review:

- task objective and paths;
- deletion and production flags;
- selected model and effort;
- expected verification;
- plan-review findings.

Then approve only the intended task:

```bash
codex-armada --repo <path> resume <run-id> --approve <task-id>
```

`--approve-all-required` is convenient but less precise.

## Monitoring usage

Use `status --all` for local run summaries and `report` for per-run evidence. Actual usage is calculated from Codex JSONL when token fields are present. Reasoning-output tokens are retained as diagnostic detail without being charged twice. Otherwise the configured typical task estimate is used and identified as estimated.

Runtime route verification uses the exact thread ID returned by `codex exec`. If public events omit model or effort, the matching local rollout must be unique. Preserve the Codex sessions directory until acceptance is complete; deleting it can make a route unverifiable and correctly block an attestation-required task.

## Updating Codex CLI

After a Codex update:

1. run `doctor`;
2. compare the capability digest;
3. run model probes;
4. run canaries;
5. create fresh plans rather than resuming a plan created under different capabilities.

## Updating Luna Forge

Follow [Luna Forge integration](LUNA_FORGE_INTEGRATION.md#upgrades). Do not point production usage at a floating branch.

## Cleanup

Successful temporary worktrees are removed by default. Failed worktrees are retained under the Codex Armada state root. Inspect them before deletion. The project never automatically deletes a failed worktree containing evidence.
