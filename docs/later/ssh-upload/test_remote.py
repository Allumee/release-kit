"""The release server round trip: remote.py talks to the real server/receive-release
through a stand-in ssh that checks how it was called, then runs the script locally."""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from release_kit import KitError, remote
from release_kit.config import load

from helpers import BASIC_CONFIG, BASIC_FILES, make_repo

SERVER = Path(__file__).resolve().parents[1] / "server" / "receive-release"
HOST_KEY = "server.example ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeHostKeyForTheKitTests"
TARGET = "release@server.example"

PUBLISH = f"""
[publish]
ssh = "{TARGET}"
host_key = "{HOST_KEY}"
channels = ["stable", "testing"]
"""

FAKE_SSH = """#!{python}
import os, stat, sys
args = sys.argv[1:]
key = args[args.index("-i") + 1]
assert stat.S_IMODE(os.stat(key).st_mode) == 0o600, "the key file must be 0600"
opts = [args[i + 1] for i, a in enumerate(args) if a == "-o"]
assert "StrictHostKeyChecking=yes" in opts and "BatchMode=yes" in opts, opts
known = [o.split("=", 1)[1] for o in opts if o.startswith("UserKnownHostsFile=")][0]
assert open(known).read().strip() == os.environ["FAKE_HOST_KEY"], "wrong known_hosts"
assert args[-2] == os.environ["FAKE_TARGET"], args[-2]
env = dict(os.environ, SSH_ORIGINAL_COMMAND=args[-1])
os.execve("/bin/bash", ["bash", os.environ["FAKE_SERVER"], *os.environ["FAKE_CHANNELS"].split()], env)
"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kit-remote-"))
        self.stable = self.tmp / "srv" / "statics"
        self.testing = self.tmp / "srv" / "testing"
        for folder in (self.stable, self.testing, self.tmp / "home", self.tmp / "bin", self.tmp / "out"):
            folder.mkdir(parents=True)
        ssh = self.tmp / "bin" / "ssh"
        ssh.write_text(FAKE_SSH.replace("{python}", sys.executable), encoding="utf-8")
        ssh.chmod(0o755)
        self.repo = make_repo(BASIC_FILES, BASIC_CONFIG + PUBLISH)
        self.cfg = load(self.repo / "release.toml", self.repo)
        self.env = mock.patch.dict(os.environ, {
            "PATH": f"{self.tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.tmp / "home"),
            "RELEASE_UPLOAD_KEY": "-----BEGIN OPENSSH PRIVATE KEY-----\nnot a key\n-----END OPENSSH PRIVATE KEY-----",
            "FAKE_SERVER": str(SERVER),
            "FAKE_CHANNELS": f"stable={self.stable} testing={self.testing}",
            "FAKE_HOST_KEY": HOST_KEY,
            "FAKE_TARGET": TARGET,
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.repo, ignore_errors=True)

    def zip_file(self, name, data):
        path = self.tmp / "out" / name
        path.write_bytes(data)
        return path

    def test_publish_and_read_back(self):
        data = b"zip bytes for 1.2.3"
        result = remote.put(self.cfg, "stable", self.zip_file("Demo-1.2.3.zip", data))
        self.assertEqual(result["sha256"], sha(data))
        self.assertFalse(result["already_stored"])
        self.assertEqual((self.stable / "Demo-1.2.3.zip").read_bytes(), data)
        self.assertEqual(remote.point(self.cfg, "stable", "1.2.3"), {"channel": "stable", "version": "1.2.3"})
        self.assertEqual((self.stable / "release").read_text(), "1.2.3\n")
        live = remote.check_live(self.cfg, "stable", "1.2.3", sha(data))
        self.assertEqual(live["file"], "Demo-1.2.3.zip")
        log = (self.tmp / "home" / "receive-release.log").read_text().splitlines()
        self.assertEqual([line.split()[2] for line in log], ["put", "point"])
        self.assertEqual([p.name for p in self.stable.iterdir() if p.name.startswith(".")], [])

    def test_zips_are_write_once(self):
        remote.put(self.cfg, "stable", self.zip_file("Demo-1.2.3.zip", b"first"))
        again = remote.put(self.cfg, "stable", self.zip_file("Demo-1.2.3.zip", b"first"))
        self.assertTrue(again["already_stored"])
        with self.assertRaisesRegex(KitError, "other bytes"):
            remote.put(self.cfg, "stable", self.zip_file("Demo-1.2.3.zip", b"second"))
        self.assertEqual((self.stable / "Demo-1.2.3.zip").read_bytes(), b"first")

    def test_stable_takes_final_versions_only(self):
        remote.put(self.cfg, "testing", self.zip_file("Demo-1.3.0-rc.1.zip", b"rc"))
        remote.point(self.cfg, "testing", "1.3.0-rc.1")
        self.assertEqual((self.testing / "release").read_text(), "1.3.0-rc.1\n")
        remote.put(self.cfg, "stable", self.zip_file("Demo-1.3.0-rc.1.zip", b"rc"))
        with self.assertRaisesRegex(KitError, "final versions"):
            remote.point(self.cfg, "stable", "1.3.0-rc.1")
        self.assertFalse((self.stable / "release").exists())

    def test_point_needs_the_zip(self):
        with self.assertRaisesRegex(KitError, "not stored"):
            remote.point(self.cfg, "stable", "9.9.9")

    def test_rollback_and_mismatches(self):
        for version in ("1.2.2", "1.2.3"):
            remote.put(self.cfg, "stable", self.zip_file(f"Demo-{version}.zip", version.encode()))
            remote.point(self.cfg, "stable", version)
        remote.point(self.cfg, "stable", "1.2.2")
        self.assertEqual(remote.live(self.cfg, "stable")["version"], "1.2.2")
        with self.assertRaisesRegex(KitError, "expected 1.2.3"):
            remote.check_live(self.cfg, "stable", "1.2.3")
        with self.assertRaisesRegex(KitError, "sha256"):
            remote.check_live(self.cfg, "stable", "1.2.2", sha(b"other"))

    def test_version_url_is_read_back(self):
        cfg = load(self.repo / "release.toml", self.repo)
        cfg = cfg.__class__(**{**cfg.__dict__, "publish": cfg.publish.__class__(
            **{**cfg.publish.__dict__, "version_url": "https://server.example/release"})})
        remote.put(cfg, "stable", self.zip_file("Demo-1.2.3.zip", b"x"))
        remote.point(cfg, "stable", "1.2.3")
        with mock.patch.object(remote, "fetch_text", return_value="1.2.3"):
            self.assertEqual(remote.check_live(cfg, "stable", "1.2.3")["version_url"], "ok")
        with mock.patch.object(remote, "fetch_text", return_value="8.6.0"):
            with self.assertRaisesRegex(KitError, "answers '8.6.0'"):
                remote.check_live(cfg, "stable", "1.2.3")

    def test_needs_the_key_and_the_channel(self):
        del os.environ["RELEASE_UPLOAD_KEY"]
        with self.assertRaisesRegex(KitError, "RELEASE_UPLOAD_KEY"):
            remote.live(self.cfg, "stable")
        cfg = self.cfg.__class__(**{**self.cfg.__dict__, "publish": self.cfg.publish.__class__(
            **{**self.cfg.publish.__dict__, "channels": ("stable",)})})
        with self.assertRaisesRegex(KitError, "no testing channel"):
            remote.live(cfg, "testing")


class ServerScript(unittest.TestCase):
    """Requests a leaked upload key could send straight to the script."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kit-server-"))
        self.stable = self.tmp / "statics"
        self.stable.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_request(self, request, data=b""):
        env = dict(os.environ, HOME=str(self.tmp), SSH_ORIGINAL_COMMAND=request)
        return subprocess.run(["bash", str(SERVER), f"stable={self.stable}"], input=data,
                              capture_output=True, env=env)

    def files(self):
        return sorted(p.name for p in self.stable.iterdir())

    def test_refuses_bad_requests(self):
        good = sha(b"abc")
        for request in (
            "",
            "ls -la",
            "put stable ../escape-1.0.0.zip " + good + " 3",
            "put stable sub/dir-1.0.0.zip " + good + " 3",
            "put stable .hidden-1.0.0.zip " + good + " 3",
            "put stable notes-1.0.0.txt " + good + " 3",
            "put stable a-1.0.0.zip;id " + good + " 3",
            "put stable $(id)-1.0.0.zip " + good + " 3",
            "put stable a-1.0.0.zip " + good + " 3 extra",
            "put other a-1.0.0.zip " + good + " 3",
            "put stable a-1.0.0.zip " + good.upper() + " 3",
            "put stable a-1.0.0.zip " + good + " 0",
            "put stable a-1.0.0.zip " + good + " 9999999999999",
            "point stable 1.0.0",
            "point stable 1.0.0 /etc/passwd",
        ):
            result = self.run_request(request, b"abc")
            self.assertEqual(result.returncode, 2, (request, result.stderr))
        self.assertEqual(self.files(), [])

    def test_refuses_bytes_that_dont_match(self):
        wrong_sha = self.run_request(f"put stable a-1.0.0.zip {sha(b'xyz')} 3", b"abc")
        too_short = self.run_request(f"put stable a-1.0.0.zip {sha(b'abcd')} 4", b"abc")
        too_long = self.run_request(f"put stable a-1.0.0.zip {sha(b'ab')} 2", b"abc")
        self.assertEqual([wrong_sha.returncode, too_short.returncode, too_long.returncode], [4, 4, 4])
        self.assertEqual(self.files(), [])

    def test_version_file_names_the_matching_zip(self):
        for name in ("a-1.0.0.zip", "a-11.0.0.zip", "a-2.0.0.zip"):
            self.assertEqual(self.run_request(f"put stable {name} {sha(name.encode())} {len(name)}",
                                              name.encode()).returncode, 0)
        self.assertEqual(self.run_request("point stable 1.0.0 a-11.0.0.zip").returncode, 2)
        self.assertEqual(self.run_request("point stable 1.0.0 a-2.0.0.zip").returncode, 2)
        self.assertEqual(self.run_request("point stable 1.0.0 a-1.0.0.zip").returncode, 0)
        self.assertEqual((self.stable / "release").read_text(), "1.0.0\n")


if __name__ == "__main__":
    unittest.main()
