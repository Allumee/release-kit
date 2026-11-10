"""Publish to the release server over SSH (docs/later/ssh-upload/README.md).

The upload key in RELEASE_UPLOAD_KEY may run one program on the server,
server/receive-release: it stores each zip once, checks its sha256, and writes
a channel's version file. Nothing here can replace a stored zip or reach
outside the folders the key's authorized_keys line names.
"""

import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from . import KitError
from .build import sha256_file

KEY_ENV = "RELEASE_UPLOAD_KEY"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-(?:rc|beta|alpha)\.\d+)?$")


def _check_channel(cfg, channel):
    if not cfg.publish.ssh:
        raise KitError("release.toml has no [publish] section, so nothing goes to the release server")
    if channel not in cfg.publish.channels:
        raise KitError(f"release.toml's [publish] has no {channel} channel")


def _request(cfg, request, stdin_path=None, timeout=1800):
    """Send one request; return the server's answer line."""
    if not cfg.publish.host_key.strip():
        raise KitError("[publish] host_key is empty: add the server's host key line (docs/later/ssh-upload/README.md)")
    key = os.environ.get(KEY_ENV, "")
    if not key.strip():
        raise KitError(f"{KEY_ENV} is not set: the publish job passes the repo secret of that name")
    verb = request.split()[0]
    with tempfile.TemporaryDirectory(prefix="release-kit-ssh-") as tmp:
        key_path = Path(tmp) / "key"
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(key.strip() + "\n")
        known = Path(tmp) / "known_hosts"
        known.write_text(cfg.publish.host_key.strip() + "\n", encoding="utf-8")
        command = [
            "ssh", "-T", "-i", str(key_path),
            "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known}",
            "-o", "GlobalKnownHostsFile=/dev/null", "-o", "ConnectTimeout=30",
            cfg.publish.ssh, request,
        ]
        stdin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
        try:
            done = subprocess.run(command, stdin=stdin, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise KitError(f"the release server did not answer '{verb}' within {timeout} s") from None
        finally:
            if stdin_path:
                stdin.close()
    if done.returncode != 0:
        lines = (done.stderr or done.stdout).strip().splitlines()
        raise KitError(f"the release server refused '{verb}': {lines[-1] if lines else f'exit {done.returncode}'}")
    lines = done.stdout.strip().splitlines()
    return lines[-1] if lines else ""


def put(cfg, channel, zip_path):
    _check_channel(cfg, channel)
    zip_path = Path(zip_path)
    digest = sha256_file(zip_path)
    size = zip_path.stat().st_size
    answer = _request(cfg, f"put {channel} {zip_path.name} {digest} {size}", stdin_path=zip_path)
    state, _, stored = answer.partition(" ")
    if state not in ("stored", "exists") or stored != digest:
        raise KitError(f"unexpected answer from the release server: {answer!r}")
    return {"channel": channel, "file": zip_path.name, "sha256": digest, "size": size,
            "already_stored": state == "exists"}


def point(cfg, channel, version):
    _check_channel(cfg, channel)
    if not VERSION_RE.match(version):
        raise KitError(f"not a release version: {version}")
    answer = _request(cfg, f"point {channel} {version} {cfg.artifact_name(version)}")
    if answer != f"pointed {channel} {version}":
        raise KitError(f"unexpected answer from the release server: {answer!r}")
    return {"channel": channel, "version": version}


def live(cfg, channel):
    """The version a channel's version file names, and the sha256 of its zip."""
    _check_channel(cfg, channel)
    answer = _request(cfg, f"current {channel}")
    if answer == "none":
        return {"channel": channel, "version": "", "file": "", "sha256": ""}
    state, _, version = answer.partition(" ")
    if state != "version" or not VERSION_RE.match(version):
        raise KitError(f"{channel}'s version file holds {answer!r}, not a version")
    name = cfg.artifact_name(version)
    answer = _request(cfg, f"sha {channel} {name}")
    sha = answer.partition(" ")[2] if answer.startswith("sha256 ") else ""
    return {"channel": channel, "version": version, "file": name, "sha256": sha}


def check_live(cfg, channel, version, sha256=""):
    state = live(cfg, channel)
    if state["version"] != version:
        raise KitError(f"{channel} serves {state['version'] or 'nothing'}, expected {version}")
    if not state["sha256"]:
        raise KitError(f"{state['file']} is missing from {channel}")
    if sha256 and state["sha256"] != sha256:
        raise KitError(f"{state['file']} on the server has sha256 {state['sha256']}, expected {sha256}")
    if channel == "stable" and cfg.publish.version_url:
        public = fetch_text(cfg.publish.version_url)
        if public != version:
            raise KitError(f"{cfg.publish.version_url} answers {public!r}, expected {version}")
        state["version_url"] = "ok"
    return state


def fetch_text(url):
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read(256).decode("utf-8", "replace").strip()
    except OSError as exc:
        raise KitError(f"cannot read {url}: {exc}") from None
