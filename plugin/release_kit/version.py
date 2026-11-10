"""Reading and writing a project's version, and matching it against a tag."""

import ast
import re

from . import KitError

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
TAG = re.compile(r"^(?:refs/tags/)?v(\d+\.\d+\.\d+)(?:-((?:rc|beta|alpha)\.\d+))?$")


def parse_tag(tag):
    """'v9.2.0' -> ('9.2.0', ''); 'v9.2.0-rc.1' -> ('9.2.0', 'rc.1')."""
    match = TAG.match(tag.strip())
    if not match:
        raise KitError(f"tag {tag!r} is not vX.Y.Z or vX.Y.Z-rc.N")
    return match.group(1), match.group(2) or ""


def normalize(value):
    if isinstance(value, (tuple, list)) and len(value) == 3 and all(
            isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in value):
        return ".".join(str(x) for x in value)
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in ("v", "V"):
            text = text[1:]
        if SEMVER.match(text):
            return text
    raise KitError(f"unsupported version value {value!r}: expected (X, Y, Z) or 'X.Y.Z'")


def _top_level_assignments(tree):
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            found[node.targets[0].id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            found[node.target.id] = node.value
    return found


def _locate(source, expr):
    """The AST node that holds the version, for an expression like `__version__`
    or `bl_info["version"]`."""
    try:
        target = ast.parse(expr, mode="eval").body
    except SyntaxError:
        raise KitError(f"version.python {expr!r} is not a Python expression") from None
    keys = []
    while isinstance(target, ast.Subscript):
        if not isinstance(target.slice, ast.Constant):
            raise KitError(f"version.python {expr!r}: only constant keys are supported")
        keys.append(target.slice.value)
        target = target.value
    if not isinstance(target, ast.Name):
        raise KitError(f"version.python {expr!r} must be a name, optionally with [key] lookups")
    assignments = _top_level_assignments(ast.parse(source))
    if target.id not in assignments:
        raise KitError(f"no top-level assignment to {target.id} for version.python {expr!r}")
    node = assignments[target.id]
    for key in reversed(keys):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == key:
                    node = v
                    break
            else:
                raise KitError(f"{expr}: key {key!r} not found")
        elif isinstance(node, (ast.Tuple, ast.List)) and isinstance(key, int) and -len(node.elts) <= key < len(node.elts):
            node = node.elts[key]
        else:
            raise KitError(f"{expr}: cannot look up {key!r} here")
    return node


def read_version(cfg):
    source = (cfg.root / cfg.version_file).read_text(encoding="utf-8")
    if cfg.version_regex:
        match = re.search(cfg.version_regex, source, re.M)
        if not match:
            raise KitError(f"version.regex found nothing in {cfg.version_file}")
        return normalize(match.group(1) if match.groups() else match.group(0))
    node = _locate(source, cfg.version_python)
    try:
        value = ast.literal_eval(node)
    except ValueError:
        raise KitError(f"{cfg.version_python} in {cfg.version_file} is not a literal") from None
    return normalize(value)


def write_version(cfg, new):
    """Rewrite the version in place, keeping the file's formatting and quote style."""
    if not SEMVER.match(new):
        raise KitError(f"{new!r} is not X.Y.Z")
    if not cfg.version_python:
        raise KitError("bump needs version.python; edit the file by hand when version.regex is used")
    path = cfg.root / cfg.version_file
    source = path.read_text(encoding="utf-8")
    node = _locate(source, cfg.version_python)
    old = ast.literal_eval(node)
    segment = ast.get_source_segment(source, node) or ""
    if isinstance(old, (tuple, list)):
        replacement = "(" + ", ".join(new.split(".")) + ")"
    else:
        prefix = "v" if old.strip()[:1] in ("v", "V") else ""
        quote = '"' if segment.startswith('"') else "'"
        replacement = f"{quote}{prefix}{new}{quote}"
    raw = source.encode("utf-8")
    starts = [0]
    for line in raw.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    begin = starts[node.lineno - 1] + node.col_offset
    end = starts[node.end_lineno - 1] + node.end_col_offset
    path.write_bytes(raw[:begin] + replacement.encode("utf-8") + raw[end:])
    return normalize(old)
