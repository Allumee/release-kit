"""Runs inside Blender (blender --background --python this.py -- ARGS) or with the
bpy module (python this.py ARGS). Installs the zip, enables the add-on, and
checks it really loaded: addon_enable does not raise when register() fails.

ARGS: zip_path module expected_version [check_attr]
"""

import json
import sys


def main(argv):
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    zip_path, module, expected = args[0], args[1], args[2]
    check_attr = args[3] if len(args) > 3 else ""

    # bpy first: as a pip module, it is bpy that puts addon_utils on sys.path.
    import bpy
    import addon_utils

    bpy.ops.preferences.addon_install(filepath=zip_path, overwrite=True)
    addon_utils.modules_refresh()
    bpy.ops.preferences.addon_enable(module=module)
    _, enabled = addon_utils.check(module)
    loaded = sys.modules.get(module)

    problems = []
    if not enabled or loaded is None:
        problems.append(f"add-on {module} did not enable")
    if loaded is not None and expected:
        version = getattr(loaded, "bl_info", {}).get("version")
        if version and ".".join(str(n) for n in version) != expected.split("-")[0]:
            problems.append(f"bl_info version {version} is not {expected}")
    if loaded is not None and check_attr and not getattr(loaded, check_attr, False):
        problems.append(f"{module}.{check_attr} is false after enabling")

    print(json.dumps({"smoke": "blender", "module": module, "ok": not problems, "problems": problems}))
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv)
