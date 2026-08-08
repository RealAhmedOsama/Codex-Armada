# Acceptance criteria

## Task acceptance

A task may enter `accepted` only when every applicable condition holds:

1. the worker call completed successfully;
2. its final JSON passed local schema validation;
3. requested and observed route metadata did not conflict;
4. required runtime attestation was observable;
5. Luna Forge source and project installation remained exact for a Luna route;
6. changed files stay within owned paths and outside excluded paths;
7. protected paths were not changed;
8. changed paths are not symbolic links;
9. deletions and production changes were declared and explicitly approved;
10. the worker reported `complete` with no unresolved gaps;
11. every deterministic verification passed without repository mutation;
12. any required final reviewer returned `ship` and remained read-only;
13. the task produced an expected change, unless it was read-only recon;
14. one focused local commit was created when commits are enabled;
15. the accepted commit was applied safely to the main branch when using an isolated worktree.

## Run acceptance

A run may enter `completed` only when:

- every task is accepted in topological order;
- repository HEAD equals durable `current_commit`;
- the main working tree is clean for committed runs;
- the budget was not exceeded;
- reports were generated from the saved record.

## Release acceptance

A Codex Armada release requires:

- compile validation;
- all automated tests;
- configuration, JSON Schema, prompt, and documentation validation;
- no Arabic text, stale product-specific content, cache files, or symbolic links;
- successful wheel build/install/import smoke;
- deterministic source and Git-ready archives;
- SHA-256 checksums and release manifest;
- clean Git status and intentional commit history.
