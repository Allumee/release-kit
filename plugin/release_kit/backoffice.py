"""Client for the back office's release API (docs/backoffice-contract.md).

Every call authenticates with the GitHub Actions OIDC token of the running job,
so no repository stores a secret. Outside GitHub Actions only `latest` works,
and only for products whose version is public.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from . import KitError

DEFAULT_AUDIENCE = "allumee-backoffice"


def oidc_token(audience=DEFAULT_AUDIENCE):
    url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")
    bearer = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not url or not bearer:
        raise KitError("no GitHub OIDC token here: the job needs `permissions: id-token: write`")
    sep = "&" if "?" in url else "?"
    request = urllib.request.Request(f"{url}{sep}audience={urllib.parse.quote(audience)}",
                                     headers={"Authorization": f"bearer {bearer}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)["value"]
    except urllib.error.HTTPError as exc:
        exc.close()
        raise KitError(f"GitHub gave no OIDC token: {exc}") from None
    except (OSError, ValueError, KeyError) as exc:
        raise KitError(f"GitHub gave no OIDC token: {exc}") from None


def _call(method, url, token="", body=None, headers=None, timeout=300):
    headers = dict(headers or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        with exc:
            raw = exc.read()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"detail": raw.decode("utf-8", "replace")[:500]}
        return exc.code, payload
    except OSError as exc:
        raise KitError(f"cannot reach the back office at {url}: {getattr(exc, 'reason', exc)}") from None
    try:
        return status, json.loads(raw) if raw else {}
    except ValueError:
        raise KitError(f"{url} did not answer with JSON. If it is a sign-in page, the edge doesn't let "
                       "this call through (docs/backoffice-contract.md).") from None


def _json(data):
    return json.dumps(data).encode("utf-8"), {"Content-Type": "application/json"}


def github_token(base, audience=DEFAULT_AUDIENCE):
    body, headers = _json({})
    status, payload = _call("POST", f"{base.rstrip('/')}/ci/github-token", oidc_token(audience), body, headers)
    if status != 200 or "token" not in payload:
        raise KitError(f"token broker refused ({status}): {payload.get('detail', payload)}")
    return payload


def upload(base, product, zip_path, version, sha256, notes="", prerelease=False, public_version=False,
           audience=DEFAULT_AUDIENCE):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("version", version), ("sha256", sha256), ("notes", notes),
                        ("prerelease", "true" if prerelease else "false"),
                        ("public_version", "true" if public_version else "false")):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    zip_path = Path(zip_path)
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{zip_path.name}"\r\n'
                 f"Content-Type: application/zip\r\n\r\n".encode())
    parts.append(zip_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    status, payload = _call("POST", f"{base.rstrip('/')}/releases/{product}", oidc_token(audience), b"".join(parts),
                            {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    if status == 409 and payload.get("sha256") == sha256:
        return {"version": version, "sha256": sha256, "already_stored": True}
    if status == 409:
        raise KitError(f"{product} {version} is already stored with different bytes; release a new version instead")
    if status not in (200, 201):
        raise KitError(f"upload refused ({status}): {payload.get('detail', payload)}")
    if payload.get("sha256") != sha256:
        raise KitError(f"the back office stored sha256 {payload.get('sha256')}, expected {sha256}")
    return payload


def point(base, product, channel, version, audience=DEFAULT_AUDIENCE):
    body, headers = _json({"version": version})
    status, payload = _call("PUT", f"{base.rstrip('/')}/releases/{product}/channels/{channel}",
                            oidc_token(audience), body, headers)
    if status != 200:
        raise KitError(f"moving {channel} to {version} was refused ({status}): {payload.get('detail', payload)}")
    return payload


def latest(base, product, channel="stable", audience=DEFAULT_AUDIENCE):
    token = oidc_token(audience) if os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL") else ""
    query = urllib.parse.urlencode({"channel": channel})
    status, payload = _call("GET", f"{base.rstrip('/')}/releases/{product}/latest?{query}", token, timeout=30)
    if status != 200:
        raise KitError(f"reading the latest {product} ({channel}) failed ({status}): {payload.get('detail', payload)}")
    return payload


def check_live(base, product, channel, version, sha256, audience=DEFAULT_AUDIENCE):
    live = latest(base, product, channel, audience)
    if live.get("version") != version or (sha256 and live.get("sha256") != sha256):
        raise KitError(f"{channel} serves {live.get('version')} ({live.get('sha256')}), "
                       f"expected {version} ({sha256})")
    return live
