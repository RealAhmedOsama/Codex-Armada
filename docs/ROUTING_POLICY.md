# Routing policy

## Inputs

Routing uses:

- selected profile;
- task kind;
- declared risk;
- owned and excluded paths;
- configured risk rules;
- deletion and production flags;
- model and effort availability observed by `doctor`;
- Luna Forge protocol requirements.

## Risk levels

| Risk | Typical examples | Default posture |
|---|---|---|
| Low | Documentation, fixtures, focused tests, mechanical bounded edits | Prefer Luna Forge in economy/balanced profiles. |
| Medium | Normal feature implementation and bug fixes | Prefer Terra in balanced mode. |
| High | Authentication, authorization, identity, tenancy, security, CI/CD, container configuration | Stronger worker, fresh final review. |
| Critical | Migrations, financial state, payments, destructive or production changes | Sol, plan review, explicit approval, final review. |

Risk is monotonic: rules may raise a task but never lower a more severe classification already present in the plan.

## Profile matrix

| Profile | Low | Medium | High | Critical |
|---|---|---|---|---|
| Economy | Luna/High | Luna/High | Terra/High | Sol/xHigh |
| Balanced | Luna/High | Terra/High | Terra/xHigh | Sol/xHigh |
| Quality | Terra/Medium | Terra/High | Sol/High | Sol/Max |
| Critical | Sol/High | Sol/High | Sol/xHigh | Sol/Max |

Luna Forge pins its worker to High effort. If a profile requests a lower Luna effort, the router raises it to High and records the reason.

## Review and approval

Each profile defines independent thresholds for:

- commitment-boundary plan review;
- final diff review;
- explicit user approval.

Deletion and production flags always require approval regardless of the profile threshold.

## No silent fallback

A route either runs exactly as planned or stops. Codex Armada does not silently replace Luna with Terra, Terra with Sol, or an unavailable effort with another value. A user must update the policy, rerun `doctor`, and create a fresh plan.

## Cost estimates

A route estimate uses the configured typical task credits for the selected worker and adds the configured reviewer estimate when final review is required. Actual credits use observed input, cached-input, and output tokens when available. The report identifies the source of each value.

The router optimizes expected cost only after risk, protocol, approval, and review constraints are satisfied.
