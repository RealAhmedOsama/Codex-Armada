# Claims and metrics

Codex Armada separates evidence classes so README statistics remain useful rather than promotional guesses.

## Evidence classes

| Class | Meaning |
|---|---|
| Measured | Counted or executed directly in this repository or release. |
| Derived | Reproducible arithmetic from measured inputs or an authoritative rate card. |
| External | Reported by an upstream source under its own conditions. |
| Projected | A falsifiable hypothesis that requires real-repository benchmarks. |

## Allowed public claims

- zero third-party runtime Python dependencies: measured from package metadata;
- source modules, lines, prompts, schemas, commands, and tests: generated from the tree;
- supported Python/OS matrix: declared and exercised by GitHub Actions once published;
- Luna and Terra equal-token credit reductions: derived from the current official Codex rate card;
- exact Luna Forge version and commit: measured from configuration and upstream Git metadata;
- no automatic push: measured by runtime command inventory and code review.

## Prohibited claims without benchmark evidence

- universal superiority over direct Sol;
- a fixed end-to-end savings percentage;
- guaranteed correctness;
- guaranteed compatibility with every Codex version or account;
- guaranteed zero failures on every operating system;
- measured quality uplift when only static tests were run.

## Machine-readable metrics

`scripts/generate_metrics.py` writes `docs/metrics.json`. Repository validation checks that the README metrics block agrees with that file.
