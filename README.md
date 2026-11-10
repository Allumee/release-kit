# Allumee release kit

One way to build, check and publish a release, shared by every Allumee
project. A project describes itself in a `release.toml` and adds three short
workflow files; the kit does the rest.

```
tag v9.2.0 ──► build.yml: tests, build the zip, check it starts, draft GitHub Release
                                         │
                    a person clicks Publish
                                         ▼
               publish.yml: upload the same zip to the back office, move the
               channel pointer, read it back; watch.yml checks weekly
```

## What's here

| Path | What it is |
|---|---|
| `plugin/release_kit/` | The Python package (standard library only) that CI and agents run |
| `.github/workflows/build.yml` | Reusable: build, verify, draft release |
| `.github/workflows/publish.yml` | Reusable: upload to the back office, move the pointer, read back, roll back |
| `.github/workflows/watch.yml` | Reusable: weekly check that the back office serves the latest release |
| `actions/locate/` | Puts `release_kit` on `PYTHONPATH` inside those workflows |
| `plugin/` | The Claude Code plugin: `/release`, `/release-onboard`, and a guard hook |
| `plugin/templates/` | What a project copies: three caller workflows and `release.toml.example` |
| `examples/` | The `release.toml` for the Blender add-on and for TLS |
| `docs/backoffice-contract.md` | What the back office must provide |
| `docs/later/ssh-upload/` | Parked: publishing over SSH with a restricted key, instead of the API |

## Bring a project onto the kit

In the project, with the plugin installed, type `/release-onboard`. By hand:

1. Write `release.toml` from `plugin/templates/release.toml.example`.
2. Copy the three files from `plugin/templates/` into `.github/workflows/`.
3. Dry run: `PYTHONPATH=<kit>/plugin python3 -m release_kit files`, then
   `build --out /tmp/dry --allow-dirty`, then `verify --zip /tmp/dry/<zip>`.
4. Open a PR. After it's merged, a release is a `v*` tag and a Publish click.

## Commands

Run from a project's root with `PYTHONPATH=<kit>/plugin python3 -m release_kit <command>`.
Every command ends with one JSON line.

| Command | Does |
|---|---|
| `version` | Read the version from the file `release.toml` names |
| `files` | List the files that ship |
| `build --out DIR [--tag vX.Y.Z] [--allow-dirty]` | Zip, `SHA256SUMS`, `MANIFEST.txt`; the same bytes for the same commit |
| `verify --zip Z [--no-smoke]` | Check the zip's contents, then run the smoke test |
| `check-tag --tag vX.Y.Z` | The tag matches the version and the changelog has its section |
| `notes --tag vX.Y.Z` | Release notes from the changelog |
| `bump --version X.Y.Z` | Write a new version, keeping the file's formatting |
| `manifest-diff OLD NEW [--markdown]` | What changed between two releases' files |
| `github-token`, `upload`, `point`, `latest`, `check-live` | Back-office calls, from CI |

## How the trust works

- The back office accepts calls only with GitHub's OIDC token for a job running
  this kit's workflows at `@v1`, from a repository owned by Allumee. No
  repository stores a secret once the token broker is live.
- Until then, a project can read private submodules with the GitHub App key in
  its own secrets (`token-source: app-secret`).
- Published releases are immutable (an org policy), versions are write-once in
  the back office, and a person's Publish click is the gate.
- The plugin's hook stops agents from force-pushing, deleting or moving tags,
  and editing, uploading to or deleting releases.

## Versions of the kit

Projects call `@v1`. A compatible change is released as `v1.x.y`, and the `v1`
tag then moves to it; a person does both. `KIT_VERSION` in
`plugin/release_kit/__init__.py` and the version in
`plugin/.claude-plugin/plugin.json` change together.

## The plugin

```
/plugin marketplace add Allumee/release-kit
/plugin install allumee-release@allumee-release-kit
```

or add it once to your team's plugin catalog.

## Tests

```
PYTHONPATH=plugin python3 -m unittest discover -s tests
```
