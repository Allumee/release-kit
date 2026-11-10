"""release.toml: what a project tells the kit about itself."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import KitError

PRODUCT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
RUNNERS = ("blender", "python", "none")
CHANNELS = ("stable", "testing")


@dataclass(frozen=True)
class Smoke:
    runner: str = "none"
    blender: str = ""          # blender: bpy version family, for example "5.2"
    module: str = ""           # blender: the add-on module to enable
    check_attr: str = ""       # blender: a module attribute that must be truthy once enabled
    requirements: str = ""     # python: requirements file inside the zip
    pip_args: tuple = ()       # python: extra pip arguments
    run: tuple = ()            # python: commands run from the unpacked zip
    timeout_min: int = 30


@dataclass(frozen=True)
class Config:
    root: Path
    path: Path
    product: str
    zip_root: str
    artifact: str
    version_file: str
    version_python: str
    version_regex: str
    include: tuple
    exclude: tuple
    rename: tuple              # (path in the repo, path inside the zip root) pairs
    lfs: tuple
    max_mb: float
    changelog: str
    tests: str
    python: str
    public_version: bool
    channels: tuple
    smoke: Smoke

    def artifact_name(self, version):
        return self.artifact.format(version=version, product=self.product, zip_root=self.zip_root)

    def summary(self):
        """The settings a workflow needs before it can run the kit."""
        return {
            "product": self.product,
            "zip_root": self.zip_root,
            "python": self.python,
            "runner": self.smoke.runner,
            "blender": self.smoke.blender,
            "lfs": " ".join(self.lfs),
            "tests": self.tests,
            "public_version": self.public_version,
            "channels": " ".join(self.channels),
        }


def _strings(table, key, where):
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise KitError(f"{where}.{key} must be a list of non-empty strings")
    return tuple(value)


def _string(table, key, where, default=""):
    value = table.get(key, default)
    if not isinstance(value, str):
        raise KitError(f"{where}.{key} must be a string")
    return value


def load(config_path, repo=None):
    path = Path(config_path)
    root = Path(repo) if repo else path.parent
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        raise KitError(f"no release config at {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise KitError(f"{path}: {exc}") from None

    product = _string(data, "product", "release.toml")
    if not PRODUCT_RE.match(product):
        raise KitError("product must be lowercase letters, digits and dashes, like 'blender-addon'")
    zip_root = _string(data, "zip_root", "release.toml")
    if not zip_root or "/" in zip_root or zip_root.startswith("."):
        raise KitError("zip_root must be one folder name, like 'Allumee'")

    version = data.get("version", {})
    if not isinstance(version, dict):
        raise KitError("[version] must be a table")
    version_file = _string(version, "file", "version")
    version_python = _string(version, "python", "version")
    version_regex = _string(version, "regex", "version")
    if not version_file:
        raise KitError("version.file is required")
    if bool(version_python) == bool(version_regex):
        raise KitError("set exactly one of version.python or version.regex")
    if not (root / version_file).is_file():
        raise KitError(f"version.file {version_file} does not exist in {root}")

    files = data.get("files", {})
    include = _strings(files, "include", "files")
    if not include:
        raise KitError("files.include must list at least one pattern")
    max_mb = files.get("max_mb", 0)
    if not isinstance(max_mb, (int, float)) or max_mb < 0:
        raise KitError("files.max_mb must be a positive number")
    rename = files.get("rename", {})
    if not isinstance(rename, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and v and not v.startswith("/") and ".." not in v.split("/")
            for k, v in rename.items()):
        raise KitError("files.rename must map repo paths to relative paths inside the zip")

    smoke_table = data.get("smoke", {"runner": "none"})
    runner = _string(smoke_table, "runner", "smoke", "none")
    if runner not in RUNNERS:
        raise KitError(f"smoke.runner must be one of {', '.join(RUNNERS)}")
    timeout = smoke_table.get("timeout_min", 30)
    if not isinstance(timeout, int) or timeout <= 0:
        raise KitError("smoke.timeout_min must be a positive integer")
    smoke = Smoke(
        runner=runner,
        blender=_string(smoke_table, "blender", "smoke"),
        module=_string(smoke_table, "module", "smoke"),
        check_attr=_string(smoke_table, "check_attr", "smoke"),
        requirements=_string(smoke_table, "requirements", "smoke"),
        pip_args=_strings(smoke_table, "pip_args", "smoke"),
        run=_strings(smoke_table, "run", "smoke"),
        timeout_min=timeout,
    )
    if runner == "blender" and not (smoke.blender and smoke.module):
        raise KitError("the blender runner needs smoke.blender (like '5.2') and smoke.module")
    if runner == "python" and not smoke.run:
        raise KitError("the python runner needs smoke.run, the commands that prove the package starts")

    public_version = data.get("public_version", False)
    if not isinstance(public_version, bool):
        raise KitError("public_version must be true or false")

    channels = _strings(data, "channels", "release.toml") or ("stable",)
    if "stable" not in channels or any(c not in CHANNELS for c in channels):
        raise KitError("channels must hold stable, and may add testing")

    artifact = _string(data, "artifact", "release.toml", "{zip_root}-{version}.zip")
    if "{version}" not in artifact or not artifact.endswith(".zip") or "/" in artifact:
        raise KitError("artifact must be a file name ending in .zip, with {version} in it")

    return Config(
        root=root,
        path=path,
        product=product,
        zip_root=zip_root,
        artifact=artifact,
        version_file=version_file,
        version_python=version_python,
        version_regex=version_regex,
        include=include,
        exclude=_strings(files, "exclude", "files"),
        rename=tuple(sorted(rename.items())),
        lfs=_strings(files, "lfs", "files"),
        max_mb=float(max_mb),
        changelog=_string(data, "changelog", "release.toml", "CHANGELOG.md"),
        tests=_string(data, "tests", "release.toml"),
        python=_string(data, "python", "release.toml", "3.12"),
        public_version=public_version,
        channels=channels,
        smoke=smoke,
    )
