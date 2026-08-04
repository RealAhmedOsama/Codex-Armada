# ADR-002: Consume Luna Forge from an exact upstream Git commit

**Status:** Accepted

## Context

Vendoring Luna Forge would duplicate its release, make provenance less obvious, and require every Codex Armada release to carry a second project's source tree. Following a branch or mutable tag would allow runtime behavior to drift without a Codex Armada review.

## Decision

Fetch Luna Forge directly from its public Git repository using a full 40-character commit as both `ref` and `expected_commit`. Verify its version, clean Git state, complete SHA-256 manifest, source inventory, symbolic-link absence, and upstream validator before installing it project-locally with the upstream installer.

Record the repository, ref, commit, version, and digest in every Luna route. Re-check the installed Skill and agent after every Luna call.

## Consequences

- Codex Armada does not redistribute Luna Forge.
- First use requires network access; subsequent runs may use the validated cache.
- Upgrades are explicit release changes.
- A source mismatch blocks instead of falling back.
- Tests use a local commit-pinned fixture; CI separately tests the real upstream source.
