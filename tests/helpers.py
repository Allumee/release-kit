"""Throwaway git repos for the tests."""

import os
import subprocess
import tempfile
from pathlib import Path

ENV = dict(os.environ, GIT_AUTHOR_NAME="kit tests", GIT_AUTHOR_EMAIL="kit-tests@example.invalid",
           GIT_COMMITTER_NAME="kit tests", GIT_COMMITTER_EMAIL="kit-tests@example.invalid",
           GIT_AUTHOR_DATE="2026-10-30T12:00:00Z", GIT_COMMITTER_DATE="2026-10-30T12:00:00Z")


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=ENV)


def make_repo(files, config=None):
    """A committed repo holding `files` ({path: text or bytes}) and an optional release.toml."""
    root = Path(tempfile.mkdtemp(prefix="kit-test-"))
    git(root, "init", "-q", "-b", "main")
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    if config is not None:
        (root / "release.toml").write_text(config, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial")
    return root


BASIC_CONFIG = """
product = "demo-tool"
zip_root = "Demo"
changelog = "CHANGELOG.md"

[version]
file = "demo/__init__.py"
python = "__version__"

[files]
include = ["demo/", "*.py", "README.release.md"]
exclude = ["**/tests/", "setup_dev.py"]
rename = { "README.release.md" = "README.md" }

[smoke]
runner = "none"
"""

BASIC_FILES = {
    "demo/__init__.py": '__version__ = "v1.2.3"\n',
    "demo/core.py": "VALUE = 1\n",
    "demo/tests/test_core.py": "assert True\n",
    "demo/.DS_Store": b"\x00\x01junk",
    "main.py": "print('hi')\n",
    "setup_dev.py": "# developer helper\n",
    "README.release.md": "# Demo\n",
    "README.md": "# Repo readme\n",
    "docs/guide.md": "# Guide\n",
    "CHANGELOG.md": "- Unreleased\n  - next thing\n\n- v1.2.3\n  - first change #12\n  - second change\n    wrapped line\n\n- v1.2.2\n  - older change\n",
}
