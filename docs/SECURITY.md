# Security design

## Security objectives

- prevent a worker from broadening its authorized repository scope;
- prevent ignored Codex or Luna Forge files from being modified without detection;
- prevent silent route or model substitution;
- prevent model text from becoming control-plane authority;
- prevent automatic publication or deployment;
- preserve evidence for failed and accepted tasks;
- limit accidental command-shell injection in verification.

## Controls

### Source integrity

Luna Forge is fetched at a full Git commit, checked against its manifest, validated with its own tooling, installed project-locally, and re-attested after model calls.

### Structured-output boundary

Codex may be asked to honor an output schema, but Codex Armada validates the resulting JSON independently. Invalid output is not deserialized into a plan or worker decision.

### Git boundary

Work happens in isolated worktrees when commits are enabled. Only task-owned files are staged. The main branch receives a reviewed commit through cherry-pick after all gates pass.

### Command boundary

Verification runs as an argument vector without a shell. Operators, pipes, redirection, unsafe Git/Python forms, arbitrary package scripts, deployment/release goals, and allowlisted tools without a dedicated safety policy are rejected. Repository build and test tools still execute repository code and therefore require a trusted host boundary.

### Secret handling

Secret-like paths are protected by default. Prompts are hash-only unless explicitly enabled. Logs are redacted for common credential patterns before evidence diffs and reports are written.

### Publication boundary

There is no push, PR, merge, release, deployment, or secret-rotation implementation in the runtime.

## Residual risk

- A model or repository program can read or affect resources allowed by the host sandbox and operating-system account.
- A malicious compiler, test runner, package script, or Git hook may have external side effects.
- Codex runtime metadata can change across versions; `doctor` and canaries reduce but do not eliminate this dependency.
- A user can deliberately weaken project policy.
- Local state and cached source can be modified by another process with the same filesystem permissions.

Use containers, virtual machines, separate credentials, or least-privilege accounts for untrusted repositories.
