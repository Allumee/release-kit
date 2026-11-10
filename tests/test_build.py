import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from release_kit import KitError
from release_kit.build import build
from release_kit.config import load
from release_kit.files import compile_pattern
from release_kit.verify import check_contents, verify

from helpers import BASIC_CONFIG, BASIC_FILES, git, make_repo


class Patterns(unittest.TestCase):
    def test_semantics(self):
        def m(pattern, path):
            return bool(compile_pattern(pattern).match(path))
        self.assertTrue(m("*.py", "main.py"))
        self.assertFalse(m("*.py", "demo/core.py"))
        self.assertTrue(m("demo/", "demo/core.py"))
        self.assertFalse(m("demo/", "demo"))
        self.assertTrue(m("**/tests/", "demo/tests/test_core.py"))
        self.assertTrue(m("**/tests/", "tests/x.py"))
        self.assertTrue(m("**/*.md", "README.md"))
        self.assertTrue(m("**/*.md", "a/b/c.md"))
        self.assertTrue(m("**/.git", "sub/.git"))
        self.assertTrue(m("blender_assets/*.blend", "blender_assets/a.blend"))
        self.assertFalse(m("blender_assets/*.blend", "blender_assets/a.blend1"))


class Build(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo(BASIC_FILES, BASIC_CONFIG)
        self.cfg = load(self.repo / "release.toml", self.repo)
        self.out = Path(tempfile.mkdtemp(prefix="kit-out-"))

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.out, ignore_errors=True)

    def names(self, result):
        with zipfile.ZipFile(result["zip"]) as archive:
            return archive.namelist()

    def test_selects_renames_and_excludes(self):
        result = build(self.cfg, self.out)
        names = self.names(result)
        self.assertIn("Demo/demo/core.py", names)
        self.assertIn("Demo/main.py", names)
        self.assertIn("Demo/README.md", names)
        self.assertIn("Demo/build_info.json", names)
        self.assertIn("Demo/demo/", names)
        for absent in ("Demo/demo/tests/test_core.py", "Demo/demo/.DS_Store", "Demo/setup_dev.py",
                       "Demo/README.release.md", "Demo/docs/guide.md", "Demo/release.toml"):
            self.assertNotIn(absent, names)
        self.assertEqual(result["version"], "1.2.3")
        self.assertEqual(result["files"], 4)

    def test_same_bytes_every_build(self):
        first = build(self.cfg, self.out / "a")
        second = build(self.cfg, self.out / "b")
        self.assertEqual(first["sha256"], second["sha256"])
        sums = (self.out / "a" / "SHA256SUMS").read_text()
        self.assertEqual(sums, f"{first['sha256']}  Demo-1.2.3.zip\n")

    def test_build_info(self):
        result = build(self.cfg, self.out, tag="v1.2.3-rc.2")
        self.assertEqual(result["version"], "1.2.3-rc.2")
        self.assertEqual(result["prerelease"], "rc.2")
        with zipfile.ZipFile(result["zip"]) as archive:
            info = json.loads(archive.read("Demo/build_info.json"))
        self.assertEqual(info["product"], "demo-tool")
        self.assertEqual(info["tag"], "v1.2.3-rc.2")
        self.assertFalse(info["dirty"])
        self.assertEqual(len(info["commit"]), 40)

    def test_tag_must_match_version(self):
        with self.assertRaises(KitError):
            build(self.cfg, self.out, tag="v1.2.4")

    def test_dirty_tree_refused_unless_allowed(self):
        (self.repo / "demo/core.py").write_text("VALUE = 2\n")
        with self.assertRaises(KitError):
            build(self.cfg, self.out)
        result = build(self.cfg, self.out, allow_dirty=True)
        self.assertTrue(result["dirty"])

    def test_untracked_files_never_ship(self):
        (self.repo / "demo/scratch.py").write_text("SECRET = 1\n")
        self.assertNotIn("Demo/demo/scratch.py", self.names(build(self.cfg, self.out)))

    def test_lfs_pointer_refused(self):
        pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 123\n"
        (self.repo / "demo/asset.bin").write_bytes(pointer)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "pointer")
        with self.assertRaisesRegex(KitError, "LFS pointer"):
            build(self.cfg, self.out)


class Verify(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo(BASIC_FILES, BASIC_CONFIG)
        self.cfg = load(self.repo / "release.toml", self.repo)
        self.out = Path(tempfile.mkdtemp(prefix="kit-out-"))

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.out, ignore_errors=True)

    def test_built_zip_passes(self):
        result = build(self.cfg, self.out)
        self.assertEqual(verify(self.cfg, result["zip"])["contents"], "ok")

    def test_catches_junk_and_wrong_root(self):
        bad = self.out / "bad.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("Demo/build_info.json", json.dumps({"product": "demo-tool", "version": "1.2.3"}))
            archive.writestr("Demo/demo/tests/test_x.py", "x")
            archive.writestr("Demo/.DS_Store", "x")
            archive.writestr("Other/file.py", "x")
        problems = "\n".join(check_contents(self.cfg, bad, "1.2.3"))
        self.assertIn("tests/", problems)
        self.assertIn(".DS_Store", problems)
        self.assertIn("top-level entries", problems)


if __name__ == "__main__":
    unittest.main()
