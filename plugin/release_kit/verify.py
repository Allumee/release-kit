"""Check a built zip before anyone can publish it: what is inside, then whether it starts."""

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from . import KitError
from .files import ALWAYS_EXCLUDE, Matcher, is_lfs_pointer


def check_contents(cfg, zip_path, expected_version=""):
    problems = []
    excluded = Matcher(tuple(cfg.exclude) + ALWAYS_EXCLUDE)
    renamed_from = {dst: src for src, dst in cfg.rename}
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        roots = {n.split("/", 1)[0] for n in names}
        if roots != {cfg.zip_root}:
            problems.append(f"top-level entries {sorted(roots)}, expected only {cfg.zip_root}/")
        info_name = f"{cfg.zip_root}/build_info.json"
        if info_name in names:
            info = json.loads(archive.read(info_name))
            if info.get("product") != cfg.product:
                problems.append(f"build_info.json names product {info.get('product')!r}, expected {cfg.product!r}")
            if expected_version and info.get("version") != expected_version:
                problems.append(f"build_info.json says {info.get('version')}, expected {expected_version}")
        else:
            problems.append("build_info.json is missing")
        prefix = cfg.zip_root + "/"
        for name in names:
            if name.endswith("/") or name == info_name or not name.startswith(prefix):
                continue
            rel = name[len(prefix):]
            pattern = excluded.first(renamed_from.get(rel, rel))
            if pattern:
                problems.append(f"{rel} ships but matches exclude pattern {pattern}")
            entry = archive.getinfo(name)
            if entry.file_size < 1024 and is_lfs_pointer(archive.read(name)):
                problems.append(f"{rel} is a Git LFS pointer")
        if cfg.smoke.runner == "blender" and f"{prefix}__init__.py" not in names:
            problems.append(f"{prefix}__init__.py is missing; Blender cannot load the add-on")
    size = Path(zip_path).stat().st_size
    if cfg.max_mb and size > cfg.max_mb * 1024 * 1024:
        problems.append(f"zip is {size / 1048576:.1f} MB, over files.max_mb = {cfg.max_mb}")
    return problems


def _run(cmd, timeout_min, **kwargs):
    try:
        proc = subprocess.run(cmd, timeout=timeout_min * 60, **kwargs)
    except subprocess.TimeoutExpired:
        raise KitError(f"smoke test timed out after {timeout_min} minutes: {cmd}") from None
    return proc.returncode


def smoke_blender(cfg, zip_path, version, blender_bin=""):
    script = Path(__file__).with_name("smoke_blender.py")
    args = [str(Path(zip_path).resolve()), cfg.smoke.module, version, cfg.smoke.check_attr]
    with tempfile.TemporaryDirectory(prefix="release-kit-blender-") as tmp:
        # Keep the install away from the user's own Blender settings and add-ons.
        env = dict(os.environ,
                   BLENDER_USER_SCRIPTS=f"{tmp}/scripts",
                   BLENDER_USER_CONFIG=f"{tmp}/config",
                   BLENDER_USER_DATAFILES=f"{tmp}/datafiles")
        if blender_bin:
            cmd = [blender_bin, "--background", "--factory-startup", "--python-exit-code", "1",
                   "--python", str(script), "--", *args]
        else:
            cmd = [sys.executable, str(script), *args]
        code = _run(cmd, cfg.smoke.timeout_min, env=env)
    if code != 0:
        raise KitError(f"Blender smoke test failed (exit {code})")


def smoke_python(cfg, zip_path, python_bin=""):
    with tempfile.TemporaryDirectory(prefix="release-kit-python-") as tmp:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(tmp)
        root = Path(tmp) / cfg.zip_root
        venv = Path(tmp) / ".venv"
        if _run([python_bin or sys.executable, "-m", "venv", str(venv)], cfg.smoke.timeout_min) != 0:
            raise KitError("could not create a virtual environment for the smoke test")
        bindir = venv / ("Scripts" if os.name == "nt" else "bin")
        env = dict(os.environ, VIRTUAL_ENV=str(venv), PATH=f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
        env.pop("PYTHONPATH", None)
        if cfg.smoke.requirements:
            requirements = root / cfg.smoke.requirements
            if not requirements.is_file():
                raise KitError(f"smoke.requirements {cfg.smoke.requirements} is not in the zip")
            cmd = [str(bindir / "python"), "-m", "pip", "install", "--disable-pip-version-check",
                   "-r", str(requirements), *cfg.smoke.pip_args]
            if _run(cmd, cfg.smoke.timeout_min, env=env) != 0:
                raise KitError("installing the zip's requirements failed")
        for command in cfg.smoke.run:
            if _run(command, cfg.smoke.timeout_min, shell=True, cwd=root, env=env) != 0:
                raise KitError(f"smoke command failed: {command}")


def verify(cfg, zip_path, smoke=True, blender_bin="", python_bin=""):
    path = Path(zip_path)
    if not path.is_file():
        raise KitError(f"no zip at {zip_path}")
    with zipfile.ZipFile(path) as archive:
        try:
            info = json.loads(archive.read(f"{cfg.zip_root}/build_info.json"))
        except KeyError:
            info = {}
    version = info.get("version", "")
    problems = check_contents(cfg, path, version)
    if problems:
        raise KitError("the zip failed its content checks:\n  " + "\n  ".join(problems))
    ran = "skipped"
    if smoke and cfg.smoke.runner == "blender":
        smoke_blender(cfg, path, version, blender_bin)
        ran = "blender"
    elif smoke and cfg.smoke.runner == "python":
        smoke_python(cfg, path, python_bin)
        ran = "python"
    elif cfg.smoke.runner == "none":
        ran = "none configured"
    return {"zip": str(path), "version": version, "contents": "ok", "smoke": ran}
