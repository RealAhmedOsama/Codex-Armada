# Threat model

## Assets

- target repository and history;
- local source code and uncommitted work;
- Codex account usage and credits;
- secrets accessible to the current process;
- Luna Forge source and project installation;
- durable orchestration evidence;
- user approval decisions.

## Actors

- honest user;
- fallible or compromised model output;
- malicious repository content;
- malicious upstream source before pin verification;
- another local process with user-level filesystem access;
- accidental operator error.

## Threats and mitigations

| Threat | Mitigation | Residual risk |
|---|---|---|
| Worker edits unrelated files | Owned-path and excluded-path checks; isolated worktree; no apply on failure | A broad ownership pattern can authorize too much. |
| Worker changes ignored agent files | Exact Luna Forge before/after attestation | Other ignored files require project-specific protection rules. |
| Prompt injection inside repository | Control instructions remain in Python/config; repository text is evidence | Model may still produce a poor patch, caught only by available tests/review. |
| Silent model fallback | Explicit model/effort flags; runtime attestation; no fallback policy | Some Codex versions may omit metadata, causing a safe block. |
| Forged structured result | Local JSON parsing and schema validation | Schema-valid content can still be semantically wrong. |
| Destructive Git action | Runtime contains no reset/push/merge commands; verification Git allowlist | Repository hooks and manual actions remain outside the control plane. |
| Verification command injection | `shlex` tokenization, no shell, operator rejection, executable/subcommand allowlists | Allowed tools can execute trusted repository code with host permissions. |
| Upstream dependency drift | Full commit pin, version, manifest, clean Git status, upstream validator | Compromise of the pinned commit itself requires upstream/reviewer trust. |
| Cache race or partial fetch | Commit-scoped lock, temporary checkout, atomic replace | Same-user filesystem attackers can still tamper; subsequent integrity checks detect changes. |
| Budget runaway | Pre-call budget governor, bounded corrections, serial tasks | Token metadata may be absent and estimates may differ from billing. |
| Automatic publication | No push, PR, merge, or deploy implementation | User may manually publish without review. |

## Out of scope

- defending against a fully compromised operating system or user account;
- securely executing arbitrary malicious build/test code without sandboxing;
- validating the intrinsic security of OpenAI or GitHub infrastructure;
- guaranteeing model correctness.
