# Publishing

## Release checklist

1. Update `src/codex_armada/version.py`, `pyproject.toml`, badges, and `CHANGELOG.md`.
2. Review the Luna Forge pin and current Codex rate card.
3. Run all tests and repository validation.
4. Run the real-upstream source verification.
5. Build and install the wheel in an isolated directory.
6. Generate and check metrics.
7. Confirm local documentation links and English-only public text.
8. Confirm `git status --short` is empty.
9. Review the logical commit history.
10. Create an annotated tag `vX.Y.Z`.
11. Push the branch and tag manually.
12. Allow the release workflow to build deterministic artifacts from the tag.
13. Compare uploaded checksums with local release evidence.

## Commands

```bash
./run-tests.sh
python scripts/generate_metrics.py --check
python scripts/validate_repository.py
python scripts/verify_release.py --artifact-dir verification --results TEST-RESULTS.txt
wheel="$(find verification/wheel -maxdepth 1 -name '*.whl' -print -quit)"
python scripts/build_release.py \
  --output-dir release \
  --wheel "$wheel" \
  --test-results TEST-RESULTS.txt
```

## Release artifacts

- wheel;
- source ZIP without `.git`;
- Git-ready ZIP including logical history and portable local Git mode settings so extraction remains clean across supported hosts;
- SHA-256 checksum file;
- release manifest;
- test-results summary;
- commit-history text.

The runtime never publishes a release automatically. GitHub Actions release automation runs only from an explicitly pushed version tag.
