# Parked: publishing over SSH with a restricted key

The smaller version of the release system, chosen on 30 Oct 2026 and replaced on
2 Nov by the releases API (`docs/backoffice-contract.md`). Nothing here runs. It
is kept because it was tested and needs no backend code, so it is the way back if
the API is delayed or dropped.

CI uploads over SSH with a key the server lets run `receive-release` and nothing
else, and Caddy puts the existing download folders behind the Google sign-in.

| File | Goes back to | What it is |
|---|---|---|
| `receive-release` | `server/` | The only program the upload key may run: stores a zip once, sets a channel's version file, logs each write |
| `remote.py` | `plugin/release_kit/` | The client: `put`, `point`, `sha`, `current` over SSH |
| `test_remote.py` | `tests/` | 10 tests: the real script behind a fake `ssh` |
| `publish.yml`, `watch.yml` | `.github/workflows/` | The workflows, using the `RELEASE_UPLOAD_KEY` secret |

To restore it, also give `release.toml` a `[publish]` table (`ssh`, `host_key`,
`channels`, `version_url`), read it in `config.py`, and point the `upload`, `point`,
`live` and `check-live` commands in `__main__.py` at `remote.py`.

## Server setup

1. As root, `install -m 755 receive-release /usr/local/bin/receive-release`.
2. Compare the host key `ssh-keyscan` gives with `ssh-keygen -lf
   /etc/ssh/ssh_host_ed25519_key.pub` on the server. The line goes in `host_key`.
3. For each project, on your own machine:
   `ssh-keygen -t ed25519 -N "" -C "release-upload <project>" -f release-upload-<project>`.
4. Add the public key to the account's `authorized_keys`, naming the folders it may
   write (the `handle_path` folders in `caddy/Caddyfile` of `Allumee/infra-backoffice`):

   ```
   restrict,command="/usr/local/bin/receive-release stable=<folder> testing=<folder>" ssh-ed25519 AAAA... release-upload <project>
   ```

5. `gh secret set RELEASE_UPLOAD_KEY --repo Allumee/<project> < release-upload-<project>`,
   then delete both key files. This needs admin rights on the repo.

## Sign-in on the existing folders

In `caddy/Caddyfile`, a named matcher next to `@public_pages`:

```
@release_private {
	path /blender-release/* /blender-testing/* /TLS/* /AMB/*
	not path /blender-release/release /blender-testing/release
}
```

and, inside the site's `route`, right after `import sso_strip`:

```
route @release_private {
	import sso_verify
}
```

The sign-in has to run before `handle_path` strips the prefix, or the redirect after
sign-in would lose the folder from the URL.
