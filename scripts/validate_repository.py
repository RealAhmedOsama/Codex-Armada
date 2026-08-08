from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PACKAGE = SRC / "codex_armada"
TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".yml", ".yaml", ".txt", ".cff", ".in", ".sh", ".bat", ".svg"}
# Assemble retired/private identifiers so this validator can search for them without
# embedding the forbidden byte sequences in its own public source.
FORBIDDEN_TERMS = {
    "max" + "booster": "product-specific content",
    "max" + " booster": "product-specific content",
    "sol advisor" + " ultimate": "stale project identity",
    "soladvisor" + "ultimate": "stale project identity",
    "sau" + "_home": "stale environment variable",
    "vendor/" + "luna-forge": "vendored Luna Forge reference",
    "embedded luna" + " forge": "bundled upstream source reference",
}
REQUIRED_ROOT_FILES = {
    ".editorconfig", ".gitattributes", ".gitignore", "README.md", "LICENSE",
    "CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
    "SUPPORT.md", "PUBLISHING.md", "CITATION.cff", "THIRD_PARTY_NOTICES.md",
    "AGENTS.md", "ROADMAP.md", "MANIFEST.in", "pyproject.toml",
}
REQUIRED_REPOSITORY_PATHS = {
    ".github/CODEOWNERS",
    ".github/dependabot.yml",
    ".github/pull_request_template.md",
    ".github/workflows/codeql.yml",
    ".github/workflows/release.yml",
    ".github/workflows/validate.yml",
    "src/codex_armada/py.typed",
}


def fail(message: str) -> None:
    raise SystemExit(message)


def text_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"LICENSE", "MANIFEST.in"}:
            files.append(path)
    return sorted(files)


def validate_versions_and_config() -> None:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        pyproject = tomllib.load(stream)
    namespace: dict[str, object] = {}
    exec((PACKAGE / "version.py").read_text(encoding="utf-8"), namespace)
    version = str(namespace.get("__version__", ""))
    if pyproject["project"]["version"] != version:
        fail("pyproject.toml and version.py disagree")
    if pyproject["project"].get("dependencies") != []:
        fail("Runtime dependency list must remain empty")
    if pyproject["project"].get("requires-python") != ">=3.11":
        fail("Python compatibility floor must remain 3.11")

    with (PACKAGE / "resources" / "default_config.toml").open("rb") as stream:
        config = tomllib.load(stream)
    if config.get("version") != 1:
        fail("Default configuration schema must be version 1")
    forge = config.get("luna_forge", {})
    expected = "ff37273ba761195ef5ab338d2e90ef3408ce8d8c"
    if forge.get("expected_commit") != expected or forge.get("ref") != expected:
        fail("Default Luna Forge source must use the reviewed exact commit as ref and expected_commit")
    if forge.get("required_version") != "2.2.1":
        fail("Default Luna Forge version must be 2.2.1")
    if forge.get("repository") != "https://github.com/RealAhmedOsama/Luna-Forge.git":
        fail("Default Luna Forge repository is incorrect")

    for path in (PACKAGE / "resources" / "schemas").glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
    with (PACKAGE / "resources" / "project_config.toml").open("rb") as stream:
        if tomllib.load(stream).get("version") != 1:
            fail("Project configuration template must use schema version 1")
    with (ROOT / "examples" / "codex-armada.minimal.toml").open("rb") as stream:
        if tomllib.load(stream).get("version") != 1:
            fail("Example configuration must use schema version 1")


def validate_public_text() -> None:
    failures: list[str] = []
    arabic = re.compile(r"[\u0600-\u06ff]")
    for path in text_files():
        value = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT).as_posix()
        if "\x00" in value:
            failures.append(f"{relative}: contains a NUL byte")
        if arabic.search(value):
            failures.append(f"{relative}: contains Arabic text; the public package is English-only")
        lowered = value.lower()
        for term, reason in FORBIDDEN_TERMS.items():
            if term in lowered:
                failures.append(f"{relative}: contains {reason}: {term!r}")
    if failures:
        fail("Public text validation failed:\n- " + "\n- ".join(failures))


def validate_tree_hygiene() -> None:
    missing = sorted(REQUIRED_ROOT_FILES - {path.name for path in ROOT.iterdir() if path.is_file()})
    missing_paths = sorted(path for path in REQUIRED_REPOSITORY_PATHS if not (ROOT / path).is_file())
    if missing or missing_paths:
        fail(f"Required repository files are missing: {sorted([*missing, *missing_paths])}")
    forbidden_parts = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist"}
    bad: list[str] = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if ".git" in relative.parts:
            continue
        if path.is_symlink():
            bad.append(f"symbolic link: {relative.as_posix()}")
        if any(part in forbidden_parts or part.endswith(".egg-info") for part in relative.parts):
            bad.append(f"generated path: {relative.as_posix()}")
        if path.is_file() and path.suffix in {".pyc", ".pyo"}:
            bad.append(f"generated bytecode: {relative.as_posix()}")
    if bad:
        fail("Repository hygiene failures:\n- " + "\n- ".join(sorted(set(bad))))


def validate_markdown_links() -> None:
    pattern = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
    failures: list[str] = []
    documents = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md")), ROOT / "CONTRIBUTING.md", ROOT / "PUBLISHING.md", ROOT / "SECURITY.md"]
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for raw in pattern.findall(text):
            target = raw.strip().split(maxsplit=1)[0].strip("<>")
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            relative = target.split("#", 1)[0]
            if not relative:
                continue
            candidate = (document.parent / relative).resolve()
            try:
                candidate.relative_to(ROOT.resolve())
            except ValueError:
                failures.append(f"{document.relative_to(ROOT)} -> unsafe {target}")
                continue
            if not candidate.exists():
                failures.append(f"{document.relative_to(ROOT)} -> missing {target}")
    if failures:
        fail("Broken local Markdown links:\n- " + "\n- ".join(failures))



def validate_workflow_pins() -> None:
    failures: list[str] = []
    pattern = re.compile(r"^\s*uses:\s+([^@\s]+)@([^\s#]+)")
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for line_number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            if "uses:" not in line:
                continue
            match = pattern.match(line)
            if not match:
                failures.append(f"{workflow.relative_to(ROOT)}:{line_number}: malformed action reference")
                continue
            reference = match.group(2)
            if not re.fullmatch(r"[0-9a-f]{40}", reference):
                failures.append(
                    f"{workflow.relative_to(ROOT)}:{line_number}: action `{match.group(1)}` is not pinned to a full commit SHA"
                )
    if failures:
        fail("GitHub Actions pin validation failed:\n- " + "\n- ".join(failures))

def validate_runtime_boundaries() -> None:
    runtime = "\n".join(path.read_text(encoding="utf-8") for path in sorted(PACKAGE.glob("*.py")))
    forbidden = [
        '["push"', "['push'", '["merge"', "['merge'", '["reset", "--hard"',
        "gh pr create", "git push", "kubectl apply", "terraform apply",
    ]
    hits = [item for item in forbidden if item in runtime]
    if hits:
        fail(f"Runtime contains forbidden publication/destructive command patterns: {hits}")


def run_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="codex-armada-compile-") as temporary:
        compile_env = os.environ.copy()
        compile_env["PYTHONPYCACHEPREFIX"] = str(Path(temporary) / "pycache")
        compile_env["PYTHONDONTWRITEBYTECODE"] = "1"
        compile_env["PYTHONUTF8"] = "1"
        compile_env["PYTHONIOENCODING"] = "utf-8"
        temporary_source = Path(temporary) / "source"
        shutil.copytree(
            SRC,
            temporary_source,
            ignore=shutil.ignore_patterns("__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"),
        )
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "compileall", "-q", "-f", str(temporary_source)],
            cwd=ROOT,
            env=compile_env,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            fail(completed.stderr.strip() or completed.stdout.strip() or "Python compilation failed")
    if shutil.which("sh"):
        for script in ("codex-armada.sh", "run-tests.sh"):
            completed = subprocess.run(["sh", "-n", str(ROOT / script)], text=True, capture_output=True, check=False)
            if completed.returncode != 0:
                fail(f"Shell syntax failed for {script}: {completed.stderr}")
    completed = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts" / "generate_metrics.py"), "--check"],
        cwd=ROOT,
        env=compile_env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        fail(completed.stderr.strip() or completed.stdout.strip() or "Metrics validation failed")


def main() -> int:
    validate_versions_and_config()
    validate_public_text()
    validate_tree_hygiene()
    validate_markdown_links()
    validate_workflow_pins()
    validate_runtime_boundaries()
    run_checks()
    print("Repository validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
