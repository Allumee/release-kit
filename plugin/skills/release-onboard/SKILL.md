---
name: release-onboard
description: Set up the Allumee release kit in this repository (release.toml, the three caller workflows, a dry run) and open the PR. Use only when the user types /release-onboard.
disable-model-invocation: true
---

# Onboard this repository onto the Allumee release kit

The kit's scripts are in `release_kit/` and its templates in `templates/`, both two folders above this skill's base directory. From the repo root, run the scripts as `PYTHONPATH=<that folder> python3 -m release_kit <command>`.

The goal is a PR that a person only has to merge. After that, a release is: tag, then click Publish.

## 1. Read the repository

Find out, and note what you find:

- Where the version lives: a top-level assignment such as `__version__ = "1.2.3"` or `bl_info["version"]`.
- The changelog and its format. The kit expects `- vX.Y.Z` headings with indented `  - ` items, and accepts `- Unreleased`.
- What the shipped zip must contain, and how it ships today. Read any deploy script line by line; its file list is the starting point.
- Private submodules, and Git LFS (`.gitattributes`).
- How to prove the package starts: a Blender add-on enables; a Python tool imports and runs `--help`.
- Who calls the current release path: other repos, Dockerfiles, docs. Search the sibling repos.

## 2. Write release.toml

Start from `templates/release.toml.example`; the kit repo's `examples/` holds the add-on's and TLS's. Prefer whole folders in `include` and a short `exclude`, so a new file ships without anyone remembering it.

## 3. Dry run, and compare with what ships today

1. `python3 -m release_kit files`: read the whole list. Nothing secret, no tests, no local junk.
2. `python3 -m release_kit build --out /tmp/onboard --allow-dirty`
3. `python3 -m release_kit verify --zip <zip> --no-smoke`, then without `--no-smoke` if the smoke test's tools are installed here.
4. If an older release zip exists, compare its file list with yours and explain every difference in the PR.

## 4. Add the workflows, remove the old path

- Copy `templates/release-build.yml`, `release-publish.yml` and `release-watch.yml` into `.github/workflows/`. Keep `@v1`. Without private submodules, set `token-source: none`.
- Remove the old release path: old workflows, server-side steps, deploy scripts. Keep any script another repo calls, unchanged, and say which repo calls it.
- Add a short "Releasing" section to the README pointing to `/release`.

## 5. Open the PR (ask first)

Branch, commit, push and open the PR. Its description lists what a person still has to do, normally only:

- merge this PR;
- tag the first version (or tell the agent "tag it") and click Publish.

If the build reads private submodules with `token-source: app-secret`, add: "an admin adds the `RELEASE_APP_ID` variable and the `RELEASE_APP_PRIVATE_KEY` secret". If the repo had public download links, say they now need the back-office sign-in.
