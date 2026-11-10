# Allumee release kit

The shared release pipeline for Allumee projects: a Python package, three
reusable GitHub workflows and a Claude Code plugin. See README.md.

## Rules for changes here

- `plugin/release_kit/` uses the Python standard library only, Python 3.11+.
  CI, laptops and the plugin all run it without installing anything.
- Every command ends with one JSON line; workflows and agents read it.
- Builds read tracked files only and use no clock but the commit's time, so a
  commit always gives the same zip bytes. Keep it that way, and keep the
  determinism test passing.
- Never put a secret, a token or a back-office credential in this repo. It is
  meant to be public.
- Workflows in `.github/workflows/` call `Allumee/release-kit/actions/locate@v1`.
  Projects call the workflows at `@v1`, and the back office trusts only those
  refs. Renaming a workflow file breaks that trust: change
  `docs/backoffice-contract.md` and the back office together.
- `plugin/release_kit/backoffice.py`, `docs/backoffice-contract.md` and the fake
  server in `tests/test_backoffice.py` describe one API: change them together.
- A change projects must adapt to needs `v2`. A person tags releases and
  moves `v1`.

## Checks before a PR

```
PYTHONPATH=plugin python3 -m unittest discover -s tests
```

and a dry run against a real project:

```
PYTHONPATH=plugin python3 -m release_kit build --repo ../blender --config examples/blender.release.toml --out /tmp/kit-dry --allow-dirty
```
