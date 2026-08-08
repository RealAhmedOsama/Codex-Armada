# Project overview

Codex Armada is a local Python control plane for Codex CLI. It converts a user goal into a durable execution plan, classifies risk, selects a model tier, executes each task inside explicit Git and approval boundaries, and accepts work only after machine-checkable evidence succeeds.

## Objective

Increase independently accepted engineering work per unit of Codex usage without weakening correctness, traceability, or human control.

## Design principles

1. **Bound before delegating.** Every worker receives one observable objective, owned paths, excluded paths, constraints, and verification.
2. **Route by risk and proofability.** Cheap models are used only when scope is clear and success is observable.
3. **Treat model output as a claim.** Python validates structured output, the real diff, runtime metadata, and test results.
4. **Fail closed.** Missing capabilities, stale source pins, route mismatch, unsafe paths, or unverifiable evidence block acceptance.
5. **Keep the user in control.** No automatic push, PR, merge, deployment, production mutation, or destructive action.
6. **Make state durable.** Runs can be inspected and resumed without trusting conversation memory.
7. **Use upstream Luna Forge directly.** The project fetches and verifies a specific public Git commit rather than vendoring a copy.

## Primary users

- individual developers trying to stretch Codex usage responsibly;
- maintainers who want a repeatable local agent workflow;
- teams that need explicit model-routing and Git safety policy;
- open-source projects that want auditable AI-assisted changes without automatic publication.

## Non-goals

- replacing Codex CLI;
- promising universal model equivalence;
- executing untrusted repositories safely without OS isolation;
- managing cloud tasks or remote deployments;
- creating an autonomous agent swarm;
- hiding fallback or silently changing models.

## Main workflow

```text
Goal → Plan → Validate → Route → Approve → Isolated execution
     → Inspect diff → Verify → Review → Commit → Apply → Report
```

## Release policy

A release is acceptable only when:

- package metadata, documentation, and version agree;
- all source and integration tests pass;
- the wheel installs and runs from an isolated target directory;
- release archives are deterministic and checksummed;
- the repository contains no generated caches, secrets, stale product-specific content, or broken local documentation links;
- Git history is composed of intentional, reviewable commits.
