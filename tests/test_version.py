import unittest
from pathlib import Path

from release_kit import KitError
from release_kit.config import load
from release_kit.version import normalize, parse_tag, read_version, write_version

from helpers import BASIC_CONFIG, BASIC_FILES, make_repo

BLENDER_INIT = '''import bpy

bl_info = {
    "name": "Allumee",
    "version": (9, 1, 1),
    "blender": (5, 2, 0),
}
assets_info = {"version": "v6.10"}
'''


class ParseTag(unittest.TestCase):
    def test_final_and_prerelease(self):
        self.assertEqual(parse_tag("v9.2.0"), ("9.2.0", ""))
        self.assertEqual(parse_tag("v9.2.0-rc.1"), ("9.2.0", "rc.1"))
        self.assertEqual(parse_tag("refs/tags/v18.2.2"), ("18.2.2", ""))

    def test_rejects_other_shapes(self):
        for tag in ("9.2.0", "v9.2", "v9.2.0-rc", "v9.2.0-dev.1", "release-9"):
            with self.assertRaises(KitError, msg=tag):
                parse_tag(tag)


class Normalize(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(normalize((9, 1, 1)), "9.1.1")
        self.assertEqual(normalize("v18.2.0"), "18.2.0")
        self.assertEqual(normalize("1.0.0"), "1.0.0")

    def test_rejects(self):
        for value in ((9, 1), (9, 1, "1"), "1.0", (True, 0, 0), 3):
            with self.assertRaises(KitError, msg=repr(value)):
                normalize(value)


class ReadWrite(unittest.TestCase):
    def test_string_version_keeps_prefix_and_quotes(self):
        repo = make_repo(BASIC_FILES, BASIC_CONFIG)
        cfg = load(repo / "release.toml", repo)
        self.assertEqual(read_version(cfg), "1.2.3")
        self.assertEqual(write_version(cfg, "1.3.0"), "1.2.3")
        self.assertEqual((repo / "demo/__init__.py").read_text(), '__version__ = "v1.3.0"\n')

    def test_blender_tuple_in_dict(self):
        config = BASIC_CONFIG.replace('file = "demo/__init__.py"', 'file = "addon/__init__.py"') \
                             .replace('python = "__version__"', "python = 'bl_info[\"version\"]'")
        repo = make_repo({**BASIC_FILES, "addon/__init__.py": BLENDER_INIT}, config)
        cfg = load(repo / "release.toml", repo)
        self.assertEqual(read_version(cfg), "9.1.1")
        write_version(cfg, "9.2.0")
        text = (repo / "addon/__init__.py").read_text()
        self.assertIn('"version": (9, 2, 0),', text)
        self.assertIn('"blender": (5, 2, 0),', text)
        self.assertIn('assets_info = {"version": "v6.10"}', text)

    def test_missing_name(self):
        config = BASIC_CONFIG.replace('python = "__version__"', 'python = "VERSION"')
        repo = make_repo(BASIC_FILES, config)
        with self.assertRaises(KitError):
            read_version(load(repo / "release.toml", repo))


if __name__ == "__main__":
    unittest.main()
