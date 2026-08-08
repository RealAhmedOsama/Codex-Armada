## Outcome

Describe the observable behavior changed by this pull request.

## Scope

- Owned files or modules:
- Explicit non-goals:

## Verification

List exact commands and observed results.

```text
python scripts/validate_repository.py
python -m unittest discover -s tests -v
```

## Risk and rollback

- Risk level:
- Security, data, migration, or compatibility impact:
- Rollback path:

## Checklist

- [ ] The change is bounded and preserves unrelated work.
- [ ] Tests cover the changed behavior where practical.
- [ ] Documentation and release notes are updated when needed.
- [ ] No secrets, generated caches, or local configuration are included.
- [ ] No automatic push, deployment, or destructive behavior was introduced.
