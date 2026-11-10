"""python -m release_kit <command>. Every command prints one JSON line at the end;
with --github-output its scalar values also go to $GITHUB_OUTPUT."""

import argparse
import json
import os
import sys
from pathlib import Path

from . import KIT_VERSION, KitError
from . import backoffice, manifest, notes
from . import files as files_mod
from . import gitutil
from .build import build, sha256_file
from .config import CHANNELS, load
from .verify import verify
from .version import parse_tag, read_version, write_version


def emit(result, github_output=False, secret_keys=()):
    # GitHub hides a value only from the moment it is masked, so mask first, and
    # keep the value out of the JSON line.
    for key in secret_keys:
        if result.get(key):
            print(f"::add-mask::{result[key]}")
    print(json.dumps({k: "***" if k in secret_keys else v for k, v in result.items()}, sort_keys=True))
    target = os.environ.get("GITHUB_OUTPUT")
    if not (github_output and target):
        return
    with open(target, "a", encoding="utf-8") as fh:
        for key, value in result.items():
            if isinstance(value, bool):
                value = "true" if value else "false"
            if isinstance(value, (str, int, float)):
                text = str(value)
                if "\n" in text:
                    fh.write(f"{key}<<__KIT_EOF__\n{text}\n__KIT_EOF__\n")
                else:
                    fh.write(f"{key}={text}\n")


def _config(args):
    repo = Path(args.repo).resolve()
    return load(Path(args.config) if Path(args.config).is_absolute() else repo / args.config, repo)


def cmd_read_config(args):
    return _config(args).summary()


def cmd_version(args):
    cfg = _config(args)
    return {"product": cfg.product, "version": read_version(cfg)}


def cmd_files(args):
    cfg = _config(args)
    selected = files_mod.select(cfg, gitutil.tracked_files(cfg.root))
    for path in selected:
        print(path)
    return {"product": cfg.product, "files": len(selected)}


def cmd_check_tag(args):
    cfg = _config(args)
    tag_version, prerelease = parse_tag(args.tag)
    version = read_version(cfg)
    if tag_version != version:
        raise KitError(f"tag {args.tag} does not match version {version} in {cfg.version_file}")
    notes.release_notes(cfg, version, prerelease=bool(prerelease))
    return {"tag": args.tag, "version": version, "prerelease": prerelease, "changelog": "ok"}


def cmd_build(args):
    return build(_config(args), args.out, tag=args.tag or "", allow_dirty=args.allow_dirty)


def cmd_verify(args):
    return verify(_config(args), args.zip, smoke=not args.no_smoke,
                  blender_bin=args.blender_bin or os.environ.get("BLENDER_BIN", ""),
                  python_bin=args.python_bin)


def cmd_notes(args):
    cfg = _config(args)
    if args.tag:
        version, prerelease = parse_tag(args.tag)
    else:
        version, prerelease = args.version or read_version(cfg), ""
    text = notes.release_notes(cfg, version, prerelease=bool(prerelease))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return {"version": version, "lines": len(text.splitlines())}


def cmd_bump(args):
    cfg = _config(args)
    old = write_version(cfg, args.version)
    return {"file": cfg.version_file, "from": old, "to": read_version(cfg)}


def cmd_manifest_diff(args):
    result = manifest.diff(args.old, args.new)
    if args.markdown:
        sys.stdout.write(manifest.as_markdown(result))
    return {k: (len(v) if isinstance(v, list) else v) for k, v in result.items()}


def cmd_github_token(args):
    payload = backoffice.github_token(args.backoffice, args.audience)
    return {"token": payload["token"], "expires_at": payload.get("expires_at", "")}


def cmd_upload(args):
    cfg = _config(args)
    text = Path(args.notes_file).read_text(encoding="utf-8") if args.notes_file else ""
    digest = sha256_file(args.zip)
    return backoffice.upload(args.backoffice, cfg.product, args.zip, args.version, digest,
                             notes=text, prerelease=args.prerelease, public_version=cfg.public_version,
                             audience=args.audience)


def cmd_point(args):
    cfg = _config(args)
    return backoffice.point(args.backoffice, cfg.product, args.channel, args.version, args.audience)


def cmd_latest(args):
    cfg = _config(args)
    return backoffice.latest(args.backoffice, cfg.product, args.channel, args.audience)


def cmd_check_live(args):
    cfg = _config(args)
    return backoffice.check_live(args.backoffice, cfg.product, args.channel, args.version,
                                 args.sha256, args.audience)


def parser():
    # The common options work before or after the command name. The main parser
    # and the commands get separate option objects: argparse shares a parent's
    # actions, and a default set on one copy would overwrite values on the other.
    def add_common(target, suppress):
        def default(value):
            return argparse.SUPPRESS if suppress else value
        target.add_argument("--repo", default=default("."), help="project root (default: current folder)")
        target.add_argument("--config", default=default("release.toml"), help="release config, relative to --repo")
        target.add_argument("--github-output", action="store_true", default=default(False),
                            help="also write results to $GITHUB_OUTPUT")

    p = argparse.ArgumentParser(prog="python -m release_kit", description=f"Allumee release kit {KIT_VERSION}")
    add_common(p, suppress=False)
    common = argparse.ArgumentParser(add_help=False)
    add_common(common, suppress=True)
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, fn, help_text):
        s = sub.add_parser(name, parents=[common], help=help_text)
        s.set_defaults(fn=fn)
        return s

    add("read-config", cmd_read_config, "settings a workflow needs")
    add("version", cmd_version, "the project's version")
    add("files", cmd_files, "list the files that ship")

    s = add("check-tag", cmd_check_tag, "tag matches the version and the changelog has its section")
    s.add_argument("--tag", required=True)

    s = add("build", cmd_build, "build the release zip, SHA256SUMS and MANIFEST.txt")
    s.add_argument("--out", required=True)
    s.add_argument("--tag", default="")
    s.add_argument("--allow-dirty", action="store_true", help="dry runs only: build despite uncommitted changes")

    s = add("verify", cmd_verify, "check the zip's contents, then run the smoke test")
    s.add_argument("--zip", required=True)
    s.add_argument("--no-smoke", action="store_true")
    s.add_argument("--blender-bin", default="", help="a Blender executable; default: the bpy module")
    s.add_argument("--python-bin", default="", help="Python used to create the smoke test's venv")

    s = add("notes", cmd_notes, "release notes from the changelog")
    s.add_argument("--tag", default="")
    s.add_argument("--version", default="")
    s.add_argument("--out", default="")

    s = add("bump", cmd_bump, "write a new version into the version file")
    s.add_argument("--version", required=True)

    s = add("manifest-diff", cmd_manifest_diff, "compare two MANIFEST.txt files")
    s.add_argument("old")
    s.add_argument("new")
    s.add_argument("--markdown", action="store_true")

    for name, fn, extra in (
        ("github-token", cmd_github_token, ()),
        ("upload", cmd_upload, ("zip", "version", "notes_file", "prerelease")),
        ("point", cmd_point, ("version", "channel")),
        ("latest", cmd_latest, ("channel",)),
        ("check-live", cmd_check_live, ("version", "channel", "sha256")),
    ):
        s = add(name, fn, f"back office: {name}")
        s.add_argument("--backoffice", required=True, help="API base, like https://backoffice.allumee.com/api_v1")
        s.add_argument("--audience", default=backoffice.DEFAULT_AUDIENCE)
        if "zip" in extra:
            s.add_argument("--zip", required=True)
        if "version" in extra:
            s.add_argument("--version", required=True)
        if "notes_file" in extra:
            s.add_argument("--notes-file", default="")
        if "prerelease" in extra:
            s.add_argument("--prerelease", action="store_true")
        if "channel" in extra:
            s.add_argument("--channel", default="stable", choices=CHANNELS)
        if "sha256" in extra:
            s.add_argument("--sha256", default="")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = args.fn(args)
    except KitError as exc:
        print(f"release-kit: {exc}", file=sys.stderr)
        return 1
    emit(result, args.github_output, secret_keys=("token",))
    return 0


if __name__ == "__main__":
    sys.exit(main())
