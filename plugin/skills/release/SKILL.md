---
name: release
description: Prepare, tag and check a release of this repository with the Allumee release kit. Use only when the user types /release <version>.
disable-model-invocation: true
argument-hint: "<version, like 9.2.0 or 9.2.0-rc.1>"
---

# Release $ARGUMENTS

The repo has a `release.toml` at its root; it says where the version lives, what ships and how CI proves the zip starts. The kit's scripts are in `release_kit/`, two folders above this skill's base directory. From the repo root, run them as `PYTHONPATH=<that folder> python3 -m release_kit <command>`. Each command ends with one JSON line: read that line, not the log above it.

## Rules

- Never build, upload or hand out a zip yourself; GitHub Actions builds every release.
- Never force-push, delete or move a tag, or edit, upload to or delete a GitHub Release. A hook refuses these.
- A person merges the release PR, pushes the tag or tells you "tag it", and clicks Publish.
- A version number is never reused. A bad release is fixed by the next one.

## 1. Check you can start

Stop and report if any of these fails:

- `git status`: the tree is clean, on the integration branch (usually `dev`), and up to date with its remote.
- Each submodule's commit is pushed: `git submodule foreach --recursive 'git branch -r --contains HEAD | grep -q . || echo "NOT PUSHED: $sm_path"'` prints nothing.
- `gh run list --commit "$(git rev-parse HEAD)" --limit 10`: the latest runs on this commit passed.
- `git tag -l "v$ARGUMENTS"` prints nothing.

## 2. Prepare the release PR

1. `git switch -c release/v$ARGUMENTS`
2. `python3 -m release_kit bump --version <X.Y.Z>`, without any `-rc.N` part.
3. In the changelog named by `release.toml`, add a `- vX.Y.Z` section at the top, or rename `- Unreleased` to it. Fill it from the PRs merged since the last tag (`git describe --tags --abbrev=0`, then `gh pr list --state merged --base <branch> --search "merged:>=<that tag's date>" --limit 200`). Match the file's existing style, keep every issue number, and add nothing that no PR contains.
4. Dry run: `python3 -m release_kit build --out /tmp/release-$ARGUMENTS --allow-dirty`, then `python3 -m release_kit verify --zip <zip from the build> --no-smoke`.
5. Package diff against the last release: `gh release download <last tag> --pattern MANIFEST.txt --dir /tmp/release-prev`, then `python3 -m release_kit manifest-diff /tmp/release-prev/MANIFEST.txt /tmp/release-$ARGUMENTS/MANIFEST.txt --markdown`. If the last release has no MANIFEST.txt, say so.
6. Commit as `set vX.Y.Z (#issue #issue)`, push the branch, and open a PR whose body holds the changelog section and the package diff. Stop until a person merges it.

## 3. Tag, only when the user says "tag it"

1. `git fetch origin` and find the merge commit on the integration branch.
2. `git tag -a v$ARGUMENTS <merge commit> -m "v$ARGUMENTS"` and `git push origin v$ARGUMENTS`.
3. `gh run watch` the "Release build" run. If it fails, report the failing step and its log; nothing was published.
4. Report the draft release: its assets, the zip's sha256 from `SHA256SUMS`, and the notes. Stop: a person checks it and clicks Publish.

## 4. Check what is live

After the person says it is published: `gh run watch` the "Release publish" run. It reads the result back from the back office and fails if the version or sha256 don't match. Report its outcome. If the project's `public_version` is true, also run `python3 -m release_kit latest --backoffice <API base>` and compare.
