# Roadmap

Codex Armada evolves through measured compatibility and benchmark evidence, not by adding agents for their own sake.

## 1.x priorities

- expand compatibility fixtures for future Codex CLI event and flag shapes;
- add benchmark-result import and comparative reporting without inventing missing usage data;
- improve route explanations and policy diagnostics;
- add more language-specific verification presets while keeping shell-free execution;
- support reviewed Luna Forge upgrades through exact commits and release evidence;
- strengthen Windows and macOS failure-recovery fixtures in CI;
- publish real-repository benchmark datasets after they meet the protocol in `docs/BENCHMARK_PROTOCOL.md`.

## Evaluation gates

A proposed capability should answer all of these questions before implementation:

1. What observable user problem does it solve?
2. Can the result be independently verified?
3. Does it preserve explicit human approval at consequential boundaries?
4. What new trusted code, dependency, network access, or mutation surface does it add?
5. How will it be tested on Linux, macOS, and Windows?
6. What is the rollback path?

## Deliberate non-goals

- autonomous push, merge, or deployment;
- silent model fallback;
- uncontrolled nested-agent swarms;
- mutable or floating upstream worker sources;
- claims of universal model equivalence;
- self-modifying policy without explicit review.
