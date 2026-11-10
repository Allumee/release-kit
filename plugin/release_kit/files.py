"""Which tracked files ship: include and exclude patterns, matched against
paths relative to the repo root.

Pattern rules:
  *      any characters except "/"        "*.py" is a top-level .py file
  **/    any number of folders             "**/tests/" is every tests folder
  dir/   everything inside that folder     "panel/" ships the whole folder
"""

import re

LFS_HEADER = b"version https://git-lfs.github.com/spec/v1"

# Never shipped, whatever release.toml says.
ALWAYS_EXCLUDE = (
    "**/.git",
    "**/.gitmodules",
    "**/.gitignore",
    "**/.gitattributes",
    "**/.github/",
    "**/.claude/",
    "**/CLAUDE.md",
    "**/AGENTS.md",
    "**/.DS_Store",
    "**/__pycache__/",
    "**/*.pyc",
)


def compile_pattern(pattern):
    dir_only = pattern.endswith("/")
    body = pattern.rstrip("/")
    regex, i = "", 0
    while i < len(body):
        if body.startswith("**/", i):
            regex += "(?:.*/)?"
            i += 3
        elif body.startswith("**", i):
            regex += ".*"
            i += 2
        elif body[i] == "*":
            regex += "[^/]*"
            i += 1
        elif body[i] == "?":
            regex += "[^/]"
            i += 1
        else:
            regex += re.escape(body[i])
            i += 1
    regex += "/.*" if dir_only else "(?:/.*)?"
    return re.compile("^" + regex + "$")


class Matcher:
    def __init__(self, patterns):
        self.patterns = [(p, compile_pattern(p)) for p in patterns]

    def first(self, path):
        for pattern, regex in self.patterns:
            if regex.match(path):
                return pattern
        return None


def select(cfg, tracked):
    """Sorted list of tracked paths that ship."""
    include = Matcher(cfg.include)
    exclude = Matcher(tuple(cfg.exclude) + ALWAYS_EXCLUDE)
    return sorted(p for p in tracked if include.first(p) and not exclude.first(p))


def is_lfs_pointer(data):
    return len(data) < 1024 and data.startswith(LFS_HEADER)
