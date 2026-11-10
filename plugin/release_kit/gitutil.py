"""Read-only git helpers. They never take git's optional locks, so they are safe
to run in a checkout another tool or agent is using."""

import os
import subprocess
from pathlib import Path

from . import KitError


def git(repo, *args, check=True):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=env)
    if check and proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise KitError(f"git {' '.join(args)} failed in {repo}: {detail}")
    return proc.stdout.decode("utf-8", "replace")


def repo_root(path):
    return Path(git(path, "rev-parse", "--show-toplevel").strip())


def head_commit(repo):
    return git(repo, "rev-parse", "HEAD").strip()


def head_time(repo):
    """Commit time of HEAD as a Unix timestamp: the build's only clock."""
    return int(git(repo, "log", "-1", "--format=%ct").strip())


def tracked_files(repo):
    """Every tracked file, submodules included, as POSIX paths relative to the repo."""
    out = git(repo, "ls-files", "--recurse-submodules", "-z")
    return [p for p in out.split("\0") if p]


def submodules(repo):
    """{path: commit} for every submodule, nested ones included. Raises if one is not checked out."""
    result, missing = {}, []
    for line in git(repo, "submodule", "status", "--recursive").splitlines():
        if not line.strip():
            continue
        flag, rest = line[0], line[1:].split()
        sha, path = rest[0], rest[1]
        if flag == "-":
            missing.append(path)
        result[path] = sha
    if missing:
        raise KitError("submodules not checked out: " + ", ".join(missing)
                       + " (run: git submodule update --init --recursive)")
    return result


def dirty_paths(repo):
    """Tracked files or submodules that differ from HEAD. Untracked files are ignored:
    only tracked files are ever shipped."""
    out = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=no",
              "--ignore-submodules=untracked")
    return [entry[3:] for entry in out.split("\0") if len(entry) > 3]
