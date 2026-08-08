# Publishing

## Release checklist

1. Update `src/codex_armada/version.py`, `pyproject.toml`, badges, and `CHANGELOG.md`.
2. Run the tests and repository validation.
3. Confirm `git status --short` is empty.
4. Create an annotated tag `vX.Y.Z`.
5. Push the branch and tag.
6. Confirm the tagged workflow published the GitHub release.

## Commands

```bash
./run-tests.sh
python scripts/validate_repository.py
python -m pip wheel . --no-deps --wheel-dir wheel
python scripts/build_release.py --output-dir release --wheel wheel/codex_armada-*.whl --no-git-ready
```

## Release artifacts

- wheel;
- source ZIP without `.git`;
- SHA-256 checksum file;
- release manifest;
- commit-history text.

The runtime never publishes a release automatically. GitHub Actions release automation runs only from an explicitly pushed version tag.

## Rollback

If publication fails, delete the failed GitHub release and its remote tag, fix `main`, create a new patch version, and push the new tag. Never move a published version tag to a different commit.
