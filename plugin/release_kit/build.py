"""Build the release zip from tracked files only, with the same bytes for the
same commit: sorted entries, the commit's time on every entry, no clock reads."""

import hashlib
import json
import os
import time
import zipfile
from pathlib import Path

from . import KIT_VERSION, KitError
from . import files as files_mod
from . import gitutil
from .version import parse_tag, read_version


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_time(timestamp):
    # ZIP dates start in 1980.
    return time.gmtime(max(timestamp, 315532800))[:6]


def write_zip(path, entries, timestamp):
    """entries: {archive name: bytes}. Folder entries are added for every parent."""
    date_time = _zip_time(timestamp)
    folders = set()
    for name in entries:
        parts = name.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            folders.add("/".join(parts[:i]) + "/")
    with zipfile.ZipFile(path, "w") as archive:
        for name in sorted(set(entries) | folders):
            info = zipfile.ZipInfo(name, date_time=date_time)
            info.create_system = 3
            if name in folders:
                info.external_attr = (0o40755 << 16) | 0x10
                archive.writestr(info, b"")
            else:
                data, executable = entries[name]
                info.external_attr = (0o100755 if executable else 0o100644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data, compresslevel=9)


def build(cfg, out_dir, tag="", allow_dirty=False):
    version = read_version(cfg)
    prerelease = ""
    if tag:
        tag_version, prerelease = parse_tag(tag)
        if tag_version != version:
            raise KitError(f"tag {tag} does not match version {version} in {cfg.version_file}")
    full_version = f"{version}-{prerelease}" if prerelease else version

    dirty = gitutil.dirty_paths(cfg.root)
    if dirty and not allow_dirty:
        listed = ", ".join(dirty[:8]) + (" …" if len(dirty) > 8 else "")
        raise KitError(f"uncommitted changes in tracked files: {listed} (commit them, or pass --allow-dirty for a dry run)")
    subs = gitutil.submodules(cfg.root)

    selected = files_mod.select(cfg, gitutil.tracked_files(cfg.root))
    if not selected:
        raise KitError("files.include matched no tracked file")

    rename = dict(cfg.rename)
    missing_renames = sorted(set(rename) - set(selected))
    if missing_renames:
        raise KitError("files.rename names files that don't ship: " + ", ".join(missing_renames))

    entries, problems, manifest = {}, [], []
    for rel in selected:
        src = cfg.root / rel
        if src.is_symlink() or not src.is_file():
            problems.append(f"{rel}: missing or not a regular file")
            continue
        data = src.read_bytes()
        if files_mod.is_lfs_pointer(data):
            problems.append(f"{rel}: Git LFS pointer, not the file (run git lfs pull)")
            continue
        arc_rel = rename.get(rel, rel)
        arc_name = f"{cfg.zip_root}/{arc_rel}"
        if arc_name in entries or arc_rel == "build_info.json":
            problems.append(f"{rel}: two files would ship as {arc_rel}")
            continue
        entries[arc_name] = (data, os.access(src, os.X_OK))
        manifest.append(f"{hashlib.sha256(data).hexdigest()}  {len(data):>10}  {arc_rel}")
    if problems:
        raise KitError("cannot build:\n  " + "\n  ".join(problems))

    commit_time = gitutil.head_time(cfg.root)
    info = {
        "product": cfg.product,
        "version": full_version,
        "tag": tag,
        "commit": gitutil.head_commit(cfg.root),
        "commit_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(commit_time)),
        "submodules": subs,
        "dirty": bool(dirty),
        "kit": KIT_VERSION,
    }
    info_bytes = (json.dumps(info, indent=2, sort_keys=True) + "\n").encode("utf-8")
    entries[f"{cfg.zip_root}/build_info.json"] = (info_bytes, False)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    zip_path = out / cfg.artifact_name(full_version)
    write_zip(zip_path, entries, commit_time)
    size = zip_path.stat().st_size
    if cfg.max_mb and size > cfg.max_mb * 1024 * 1024:
        raise KitError(f"{zip_path.name} is {size / 1048576:.1f} MB, over files.max_mb = {cfg.max_mb}")

    digest = sha256_file(zip_path)
    manifest.sort(key=lambda line: line.split(None, 2)[2])
    (out / "MANIFEST.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    (out / "SHA256SUMS").write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    return {
        "product": cfg.product,
        "version": full_version,
        "prerelease": prerelease,
        "zip": str(zip_path),
        "sha256": digest,
        "size": size,
        "files": len(selected),
        "commit": info["commit"],
        "dirty": info["dirty"],
    }
