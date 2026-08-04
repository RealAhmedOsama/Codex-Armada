$luna-forge

You are running a disposable Codex routing canary in a temporary Git repository using the pinned Luna Forge protocol.

Task capsule:
- Goal: create exactly one file named `canary.txt` containing exactly `Codex Armada canary OK` followed by a newline.
- Authorized scope: `canary.txt` only.
- Acceptance: the file exists with exact content and no other repository file changes.
- Non-goals: no refactor, no dependency, no commit, no push, no external write.
- Validation: inspect the exact file content and Git changed-file scope.

Use one active objective, make the smallest patch, do not spawn agents, and do not modify any other file.
Return only the JSON object required by the supplied output schema with status `ok` after the file is correct.
