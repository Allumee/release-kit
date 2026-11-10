# Back-office contract for the release kit

What `backend` (and one page in `frontend`) must provide so that any Allumee
project can publish through the kit, with no secret stored in GitHub and no
backend change per new project. The kit's client is
`plugin/release_kit/backoffice.py`, and `tests/test_backoffice.py` holds a small
server that follows this document: read it for the exact answers the client expects.

Base URL: `https://backoffice.allumee.com/api_v1`.

## Authentication: GitHub's OIDC token

Every CI call carries `Authorization: Bearer <JWT>`, a token GitHub signs for
the running job. The back office:

1. Verifies the signature with the keys at
   `https://token.actions.githubusercontent.com/.well-known/jwks` (cache them;
   refetch on an unknown `kid`).
2. Checks `iss` is `https://token.actions.githubusercontent.com`, `aud` is
   `allumee-backoffice`, and `exp`/`nbf` with at most 60 s of clock skew.
3. Checks the claims:

| Claim | Must be | Why |
|---|---|---|
| `repository_owner_id` | Allumee's numeric owner id | no outside repo gets through, even after a rename |
| `job_workflow_ref` | `Allumee/release-kit/.github/workflows/<file>.yml@refs/tags/v1` (a configurable list of accepted kit refs) | only the kit's reviewed workflows act |
| `event_name`, `ref` | per endpoint, below | only a published tag ships |
| `repository_id` | the repository bound to the product | one product, one repo |

Product binding: the first successful upload for a product records the
`repository_id` that sent it. Later calls for that product from another
repository get 403. A product that doesn't exist yet is created on its first
upload, visible only to back-office admins until someone opens it (the
"products" choice on the kit plan).

## 1. Token broker: `POST /ci/github-token`

Gives CI a short-lived token to read private submodules, so no repository
stores the GitHub App's key.

- Accepted from: `job_workflow_ref` = the kit's `build.yml`; any `event_name`
  (dry runs on branches need submodules too).
- Body: `{}`.
- Server: signs a GitHub App JWT with the App key (stored only in the back
  office's secrets) and calls
  `POST /app/installations/{installation_id}/access_tokens` with
  `{"permissions": {"contents": "read"}}`.
- 200: `{"token": "ghs_…", "expires_at": "2026-11-02T10:00:00Z"}` (one hour).
- Log `repository`, `run_id` and `sha` for every token handed out.
- Scope: a token for the whole installation lets anyone who can change a
  project's tests read every repo the App is on, for an hour. Narrow it where
  possible: pass `repositories` with the calling repo and the repos its
  `.gitmodules` names at the token's `sha`, including nested submodules.

## 2. Upload: `POST /releases/{product}`

`multipart/form-data` fields:

| Field | Example |
|---|---|
| `file` | `Allumee-9.2.0.zip` |
| `version` | `9.2.0` or `9.2.0-rc.1` |
| `sha256` | the zip's sha256, from the release's `SHA256SUMS` |
| `notes` | Markdown release notes |
| `prerelease` | `true` / `false` |
| `public_version` | `true` / `false`, from `release.toml`: whether `latest` answers without a login |

- Accepted from: the kit's `publish.yml`, `event_name` = `release`, `ref`
  starting with `refs/tags/v`.
- The server computes the sha256 of what it received; a mismatch with the
  `sha256` field is a 400.
- Write-once: if the version exists, answer 409 with `{"sha256": "<stored>"}`.
  The kit treats an identical sha256 as success (a re-run) and anything else
  as an error.
- Storage: `/data/releases/<product>/<version>/<file>` on a private volume that
  Caddy doesn't serve, plus a metadata row (product, version, sha256, size,
  notes, prerelease, repository, run_id, workflow_sha, created_at).
- 201: `{"product": "blender-addon", "version": "9.2.0", "sha256": "…", "size": 16315267}`.

## 3. Channel pointer: `PUT /releases/{product}/channels/{channel}`

- Body: `{"version": "9.2.0"}`. Channels: `stable`, `testing`.
- Accepted from: the kit's `publish.yml`, `event_name` = `release`, or
  `workflow_dispatch` for a rollback.
- 404 if the version isn't stored; 400 if a pre-release is pointed at `stable`.
- Keep the history of moves, for audit and rollback.
- 200: `{"product": "blender-addon", "channel": "stable", "version": "9.2.0"}`.

## 4. Latest: `GET /releases/{product}/latest?channel=stable`

- 200: `{"product", "channel", "version", "sha256", "size", "published_at"}`.
- No login needed when the product's version is public (the add-on: installed
  copies poll it). Otherwise only the kit's OIDC token from `publish.yml` or
  `watch.yml`. This path skips the sign-in (see "The edge"), so it never knows a
  person; the download page uses the list calls below.
- `GET /releases/{product}/latest.txt?channel=stable` answers the same version as
  plain text (`9.2.0\n`), for public products only. Add-ons already installed read
  it through Caddy at `/blender-release/release`. They parse three integers, which
  is why `stable` never holds a pre-release.

## 5. Download: `GET /releases/{product}/{version}/download`

- Who: a signed-in back-office user (web session) or the add-on's session token
  (`/addon-auth`), with the product's download role.
- Response: the zip, `Content-Disposition: attachment`, and an
  `X-Checksum-SHA256` header.
- Compatibility: Caddy redirects `/blender-release/*.zip` to the download page,
  so an old install's Download button lands on the login.

## 6. Lists: `GET /releases` and `GET /releases/{product}`

- Who: a signed-in back-office user. They see the products they may download.
- 200: for each version the notes, sha256, size, date and channels, newest first.
  Admins also get the pointer history.

## The download page (`frontend`)

One tab per product: stable and testing versions, notes, sha256, a download
button. Admins also see the pointer history and choose who may download.

## The edge (`infra-backoffice`)

- A private volume mounted into the backend at `/data/releases`, outside anything
  Caddy serves.
- CI has no Google session, so these calls must skip the sign-in, like the
  Caddyfile's other machine paths, with the client's identity headers stripped:
  `POST /ci/github-token`, `POST /releases/*`, `PUT /releases/*/channels/*`,
  `GET /releases/*/latest` and `GET /releases/*/latest.txt`. The backend checks
  the OIDC token on each. The download and list calls stay behind the sign-in.
- `/blender-release/release` is rewritten to the add-on's `latest.txt`.
- `/blender-release/*.zip` redirects to the download page, so an old install's
  Download button lands on the sign-in.
- The public `/TLS/*` and `/blender-testing/*` blocks are removed.

## Not in scope

- No endpoint accepts a long-lived secret from CI.
- No endpoint deletes a stored version. A bad release is fixed by the next
  version, or by pointing `stable` back.
