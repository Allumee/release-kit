"""Compare two MANIFEST.txt files: the package diff a reviewer reads in a release PR."""

from pathlib import Path


def read(path):
    entries = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            digest, size, rel = parts
            entries[rel] = (digest, int(size))
    return entries


def diff(old_path, new_path):
    old, new = read(old_path), read(new_path)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(p for p in set(old) & set(new) if old[p][0] != new[p][0])
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": len(set(old) & set(new)) - len(changed),
        "size_before": sum(s for _, s in old.values()),
        "size_after": sum(s for _, s in new.values()),
    }


def as_markdown(result, limit=40):
    out = [f"**Package diff:** {len(result['added'])} added, {len(result['removed'])} removed, "
           f"{len(result['changed'])} changed, {result['unchanged']} unchanged "
           f"({result['size_before'] / 1048576:.1f} MB → {result['size_after'] / 1048576:.1f} MB)"]
    for title, key in (("Added", "added"), ("Removed", "removed"), ("Changed", "changed")):
        items = result[key]
        if items:
            out.append(f"\n{title}:")
            out += [f"- `{p}`" for p in items[:limit]]
            if len(items) > limit:
                out.append(f"- … and {len(items) - limit} more")
    return "\n".join(out) + "\n"
