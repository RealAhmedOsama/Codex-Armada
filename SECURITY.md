# Security policy

## Supported versions

Security fixes are provided for the latest released major/minor version on the default branch.

| Version | Supported |
|---|---|
| 1.x | Yes |
| Pre-1.0 builds | No |

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose secrets, bypass task scope, mutate protected paths, forge acceptance evidence, alter the pinned Luna Forge source, or trigger unintended publication or production actions.

Use GitHub's private vulnerability reporting for this repository. Include:

- affected version and commit;
- operating system, Python version, Git version, and Codex version;
- configuration relevant to the issue;
- exact reproduction steps using a disposable repository;
- expected and observed behavior;
- impact and any known workaround.

Do not include real credentials, private source code, or customer data. A minimal fixture is preferred.

## Security boundaries

Codex Armada constrains orchestration, Git acceptance, model routing, and evidence. It does not provide operating-system isolation for arbitrary repository build or test code. See [Security design](docs/SECURITY.md) and [Threat model](docs/THREAT_MODEL.md).
