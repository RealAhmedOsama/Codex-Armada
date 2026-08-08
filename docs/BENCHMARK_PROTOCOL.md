# Benchmark protocol

Codex Armada includes deterministic routing economics, but quality and end-to-end savings must be measured on real repositories.

## Question

Does adaptive routing produce more independently accepted bounded engineering tasks per unit of Codex credit than executing every task directly with Sol?

## Experimental lanes

1. direct Sol at the selected effort;
2. direct Terra at the selected effort;
3. Luna with Luna Forge at High;
4. Codex Armada adaptive routing.

## Task eligibility

Include tasks with:

- a fixed repository commit;
- an observable objective;
- stable owned paths;
- deterministic verification;
- no unresolved product decision;
- no external production side effect.

Stratify by documentation, tests, bugfix, implementation, refactor, security, and migration.

## Controls

- identical repository base;
- equivalent task capsule and acceptance criteria;
- fresh task context per lane;
- same Codex CLI version and account;
- same maximum correction policy;
- no manual patch repair before scoring;
- blinded diff review where practical.

## Metrics

- accepted on first attempt;
- accepted after one correction;
- verification pass rate;
- scope violations;
- reviewer findings;
- human corrections required;
- input, cached-input, output, and reasoning usage when exposed;
- credits;
- latency;
- changed lines and files;
- regression rate after broader tests.

## Promotion gate

A cheaper lane should be promoted for a task class only when it preserves the chosen acceptance-rate floor and lowers median credit consumption on representative samples. Equal-token arithmetic alone is not a quality benchmark.
