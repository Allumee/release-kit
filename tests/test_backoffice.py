"""The back-office round trip: backoffice.py against a small server that follows
docs/backoffice-contract.md, and the command line around it. No network."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from helpers import BASIC_CONFIG, BASIC_FILES, make_repo

from release_kit import KitError, backoffice
from release_kit.config import load

PLUGIN = str(Path(__file__).resolve().parent.parent / "plugin")
RUNNER_TOKEN = "runner-request-token"
GOOD_JWT = f"jwt-for-{backoffice.DEFAULT_AUDIENCE}"
BROKER_TOKEN = "ghs_fake_broker_token"


def sha(data):
    return hashlib.sha256(data).hexdigest()


class FakeBackOffice(BaseHTTPRequestHandler):
    """GitHub's token endpoint, plus the CI side of the contract."""

    def log_message(self, *args):
        pass

    def _send(self, status, payload):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    def _authorized(self):
        if self.headers.get("Authorization") == f"Bearer {GOOD_JWT}":
            return True
        self._send(403, {"detail": "not the kit's workflow"})
        return False

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/oidc":
            if self.headers.get("Authorization") != f"bearer {RUNNER_TOKEN}":
                self._send(401, {"message": "bad request token"})
            else:
                self._send(200, {"value": f"jwt-for-{query['audience'][0]}"})
            return
        if url.path == "/oauth2/sign_in":
            self._send(200, b"<html>Sign in with Google</html>")
            return
        match = re.fullmatch(r"/releases/([^/]+)/latest", url.path)
        channel = query.get("channel", ["stable"])[0]
        if not match or (match.group(1), channel) not in self.server.pointers:
            self._send(404, {"detail": "nothing on this channel"})
            return
        version = self.server.pointers[(match.group(1), channel)]
        stored = self.server.versions[(match.group(1), version)]
        self._send(200, {"product": match.group(1), "channel": channel, "version": version,
                         "sha256": stored["sha256"], "size": stored["size"]})

    def do_POST(self):
        body = self._body()
        if not self._authorized():
            return
        if self.path == "/ci/github-token":
            self._send(200, {"token": BROKER_TOKEN, "expires_at": "2026-11-02T10:00:00Z"})
            return
        match = re.fullmatch(r"/releases/([^/]+)", self.path)
        if not match:
            self._send(404, {"detail": "no such call"})
            return
        boundary = self.headers["Content-Type"].split("boundary=")[1].encode()
        fields = {}
        for part in body.split(b"--" + boundary):
            head, _, value = part.partition(b"\r\n\r\n")
            name = re.search(rb'name="([^"]+)"', head)
            if name:
                fields[name.group(1).decode()] = value[:-2]
        digest = sha(fields["file"])
        if digest != fields["sha256"].decode():
            self._send(400, {"detail": "sha256 mismatch"})
            return
        key = (match.group(1), fields["version"].decode())
        if key in self.server.versions:
            self._send(409, {"sha256": self.server.versions[key]["sha256"]})
            return
        self.server.versions[key] = {"sha256": digest, "size": len(fields["file"]),
                                     "prerelease": fields["prerelease"] == b"true",
                                     "public_version": fields["public_version"] == b"true",
                                     "notes": fields["notes"].decode()}
        self._send(201, {"product": key[0], "version": key[1], "sha256": digest, "size": len(fields["file"])})

    def do_PUT(self):
        body = self._body()
        if not self._authorized():
            return
        match = re.fullmatch(r"/releases/([^/]+)/channels/([^/]+)", self.path)
        version = json.loads(body)["version"]
        product, channel = match.group(1), match.group(2)
        stored = self.server.versions.get((product, version))
        if stored is None:
            self._send(404, {"detail": "version not stored"})
        elif channel == "stable" and stored["prerelease"]:
            self._send(400, {"detail": "a pre-release can't go on stable"})
        else:
            self.server.pointers[(product, channel)] = version
            self._send(200, {"product": product, "channel": channel, "version": version})


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeBackOffice)
        self.server.versions = {}
        self.server.pointers = {}
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.oidc_env = {"ACTIONS_ID_TOKEN_REQUEST_URL": f"{self.base}/oidc?api-version=2.0",
                         "ACTIONS_ID_TOKEN_REQUEST_TOKEN": RUNNER_TOKEN}
        patcher = mock.patch.dict(os.environ, self.oidc_env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = Path(tempfile.mkdtemp(prefix="kit-backoffice-"))

    def zip_file(self, name, data):
        path = self.tmp / name
        path.write_bytes(data)
        return path

    def upload(self, version, data, **kwargs):
        path = self.zip_file(f"Demo-{version}.zip", data)
        return backoffice.upload(self.base, "demo-tool", path, version, sha(data), **kwargs)


class RoundTrip(ServerCase):
    def test_publish_and_read_back(self):
        data = b"the zip"
        stored = self.upload("1.2.3", data, notes="- fixed é", public_version=True)
        self.assertEqual(stored["sha256"], sha(data))
        kept = self.server.versions[("demo-tool", "1.2.3")]
        self.assertEqual(kept["notes"], "- fixed é")
        self.assertTrue(kept["public_version"])
        self.assertEqual(backoffice.point(self.base, "demo-tool", "stable", "1.2.3")["version"], "1.2.3")
        live = backoffice.check_live(self.base, "demo-tool", "stable", "1.2.3", sha(data))
        self.assertEqual(live["size"], len(data))

    def test_versions_are_write_once(self):
        self.upload("1.2.3", b"first")
        self.assertTrue(self.upload("1.2.3", b"first")["already_stored"])
        with self.assertRaisesRegex(KitError, "different bytes"):
            self.upload("1.2.3", b"second")

    def test_a_wrong_stored_sha256_fails(self):
        path = self.zip_file("Demo-1.2.3.zip", b"the zip")
        with self.assertRaisesRegex(KitError, "upload refused \\(400\\)"):
            backoffice.upload(self.base, "demo-tool", path, "1.2.3", sha(b"other"))

    def test_pointer_rules_and_rollback(self):
        with self.assertRaisesRegex(KitError, "refused \\(404\\)"):
            backoffice.point(self.base, "demo-tool", "stable", "9.9.9")
        self.upload("1.3.0-rc.1", b"rc", prerelease=True)
        backoffice.point(self.base, "demo-tool", "testing", "1.3.0-rc.1")
        with self.assertRaisesRegex(KitError, "refused \\(400\\)"):
            backoffice.point(self.base, "demo-tool", "stable", "1.3.0-rc.1")
        for version in ("1.2.2", "1.2.3"):
            self.upload(version, version.encode())
            backoffice.point(self.base, "demo-tool", "stable", version)
        backoffice.point(self.base, "demo-tool", "stable", "1.2.2")
        self.assertEqual(backoffice.latest(self.base, "demo-tool")["version"], "1.2.2")

    def test_check_live_finds_drift(self):
        self.upload("1.2.3", b"the zip")
        backoffice.point(self.base, "demo-tool", "stable", "1.2.3")
        with self.assertRaisesRegex(KitError, "expected 1.2.4"):
            backoffice.check_live(self.base, "demo-tool", "stable", "1.2.4", "")
        with self.assertRaisesRegex(KitError, "serves 1.2.3"):
            backoffice.check_live(self.base, "demo-tool", "stable", "1.2.3", sha(b"other"))
        with self.assertRaisesRegex(KitError, "failed \\(404\\)"):
            backoffice.latest(self.base, "demo-tool", "testing")

    def test_token_broker(self):
        self.assertEqual(backoffice.github_token(self.base)["token"], BROKER_TOKEN)
        with self.assertRaisesRegex(KitError, "token broker refused \\(403\\)"):
            backoffice.github_token(self.base, audience="someone-else")


class Failures(ServerCase):
    def test_no_oidc_token_in_this_job(self):
        with mock.patch.dict(os.environ, {"ACTIONS_ID_TOKEN_REQUEST_URL": ""}):
            with self.assertRaisesRegex(KitError, "id-token: write"):
                backoffice.oidc_token()

    def test_github_refuses_the_oidc_request(self):
        with mock.patch.dict(os.environ, {"ACTIONS_ID_TOKEN_REQUEST_TOKEN": "wrong"}):
            with self.assertRaisesRegex(KitError, "GitHub gave no OIDC token"):
                backoffice.oidc_token()

    def test_a_sign_in_page_is_named(self):
        # What CI gets if the edge doesn't let a call through: urllib follows the
        # redirect and receives the sign-in page with a 200.
        with self.assertRaisesRegex(KitError, "did not answer with JSON.*sign-in page"):
            backoffice._call("GET", f"{self.base}/oauth2/sign_in")

    def test_server_down(self):
        with self.assertRaisesRegex(KitError, "cannot reach the back office"):
            backoffice._call("GET", "http://127.0.0.1:9/releases/demo-tool/latest", timeout=5)


class CommandLine(ServerCase):
    def run_kit(self, *args, repo=None, output=None):
        env = dict(os.environ, PYTHONPATH=PLUGIN, **self.oidc_env)
        env.pop("GITHUB_OUTPUT", None)
        if output:
            env["GITHUB_OUTPUT"] = str(output)
        return subprocess.run([sys.executable, "-m", "release_kit", *args], cwd=repo or self.tmp, env=env,
                              capture_output=True, text=True)

    def test_the_broker_token_is_masked_first_and_never_printed(self):
        output = self.tmp / "github_output"
        done = self.run_kit("github-token", "--backoffice", self.base, "--github-output", output=output)
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.splitlines()
        self.assertEqual(lines[0], f"::add-mask::{BROKER_TOKEN}")
        self.assertEqual(len(lines), 2)
        self.assertNotIn(BROKER_TOKEN, lines[1])
        self.assertEqual(json.loads(lines[1])["token"], "***")
        self.assertIn(f"token={BROKER_TOKEN}\n", output.read_text())

    def test_upload_point_check_live(self):
        repo = make_repo(BASIC_FILES, BASIC_CONFIG + '\n')
        data = b"the zip"
        path = self.zip_file("Demo-1.2.3.zip", data)
        notes = self.zip_file("notes.md", b"- first")
        common = ("--repo", str(repo), "--backoffice", self.base)
        done = self.run_kit("upload", *common, "--zip", str(path), "--version", "1.2.3", "--notes-file", str(notes))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.server.versions[("demo-tool", "1.2.3")]["notes"], "- first")
        self.assertFalse(self.server.versions[("demo-tool", "1.2.3")]["public_version"])
        done = self.run_kit("point", *common, "--channel", "stable", "--version", "1.2.3")
        self.assertEqual(done.returncode, 0, done.stderr)
        done = self.run_kit("check-live", *common, "--version", "1.2.3", "--sha256", sha(data))
        self.assertEqual(done.returncode, 0, done.stderr)
        done = self.run_kit("check-live", *common, "--version", "1.2.4")
        self.assertEqual(done.returncode, 1)
        self.assertIn("expected 1.2.4", done.stderr)


class Settings(unittest.TestCase):
    def config(self, *lines):
        top = "\n".join(lines) + "\n"
        return make_repo(BASIC_FILES, top + BASIC_CONFIG)

    def test_defaults(self):
        repo = self.config()
        cfg = load(repo / "release.toml", repo)
        self.assertEqual(cfg.channels, ("stable",))
        self.assertFalse(cfg.public_version)
        self.assertEqual(cfg.summary()["channels"], "stable")

    def test_testing_channel(self):
        repo = self.config('channels = ["stable", "testing"]', "public_version = true")
        cfg = load(repo / "release.toml", repo)
        self.assertEqual(cfg.summary()["channels"], "stable testing")
        self.assertTrue(cfg.summary()["public_version"])

    def test_refusals(self):
        for line, message in (('channels = ["testing"]', "channels must hold stable"),
                              ('channels = ["stable", "beta"]', "channels must hold stable"),
                              ('artifact = "Demo.zip"', "artifact must be"),
                              ('artifact = "../Demo-{version}.zip"', "artifact must be"),
                              ('artifact = "Demo-{version}.tar"', "artifact must be")):
            repo = self.config(line)
            with self.assertRaisesRegex(KitError, message):
                load(repo / "release.toml", repo)


if __name__ == "__main__":
    unittest.main()
