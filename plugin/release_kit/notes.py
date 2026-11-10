"""Release notes from the changelog. Both Allumee changelogs use:

    - v9.1.0
      - first change #1186
      - second change

    - v9.0.7
      ...

with an optional "- Unreleased" section at the top.
"""

import re

from . import KitError

HEADING = re.compile(r"^- (v\d+\.\d+\.\d+|Unreleased)\s*$", re.I)


def section(text, name):
    """Lines of the section headed `- <name>` (like 'v9.1.0' or 'Unreleased'), or None."""
    lines, found = [], False
    for line in text.splitlines():
        match = HEADING.match(line.rstrip())
        if match:
            if found:
                break
            found = match.group(1).lower() == name.lower()
            continue
        if found and line.strip():
            lines.append(line.rstrip())
    return lines if found else None


def dedent(lines):
    indent = min((len(l) - len(l.lstrip(" ")) for l in lines), default=0)
    return [l[indent:] for l in lines]


def release_notes(cfg, version, prerelease=False):
    path = cfg.root / cfg.changelog
    if not path.is_file():
        raise KitError(f"no changelog at {cfg.changelog}")
    text = path.read_text(encoding="utf-8")
    lines = section(text, f"v{version}")
    if lines is None and prerelease:
        lines = section(text, "Unreleased")
    if lines is None:
        raise KitError(f"{cfg.changelog} has no '- v{version}' section")
    if not lines:
        raise KitError(f"the '- v{version}' section of {cfg.changelog} is empty")
    return "\n".join(dedent(lines)) + "\n"
