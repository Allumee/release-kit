import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

from release_kit import KitError
from release_kit.config import load
from release_kit.manifest import diff
from release_kit.notes import release_notes

from helpers import BASIC_CONFIG, BASIC_FILES, make_repo

GUARD = Path(__file__).resolve().parents[1] / "plugin" / "hooks" / "guard.py"
spec = importlib.util.spec_from_file_location("guard", GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class Notes(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo(BASIC_FILES, BASIC_CONFIG)
        self.cfg = load(self.repo / "release.toml", self.repo)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_version_section(self):
        text = release_notes(self.cfg, "1.2.3")
        self.assertEqual(text, "- first change #12\n- second change\n  wrapped line\n")

    def test_prerelease_falls_back_to_unreleased(self):
        self.assertEqual(release_notes(self.cfg, "1.3.0", prerelease=True), "- next thing\n")

    def test_final_release_needs_its_section(self):
        with self.assertRaises(KitError):
            release_notes(self.cfg, "1.3.0")


class Manifest(unittest.TestCase):
    def test_diff(self):
        folder = Path(tempfile.mkdtemp(prefix="kit-manifest-"))
        old, new = folder / "old.txt", folder / "new.txt"
        old.write_text("aaa  10  keep.py\nbbb  20  change.py\nccc  30  gone.py\n")
        new.write_text("aaa  10  keep.py\nddd  25  change.py\neee  40  added.py\n")
        result = diff(old, new)
        self.assertEqual(result["added"], ["added.py"])
        self.assertEqual(result["removed"], ["gone.py"])
        self.assertEqual(result["changed"], ["change.py"])
        self.assertEqual(result["unchanged"], 1)
        shutil.rmtree(folder)


class Guard(unittest.TestCase):
    def test_blocks(self):
        for command in (
            "gh release delete v9.1.0 --yes",
            "gh release edit v9.1.0 --draft=false",
            "gh release upload v9.1.0 Allumee-9.1.0.zip --clobber",
            "git push --force origin dev",
            "git push origin dev -f",
            "git push --force-with-lease origin feature",
            "git push origin :refs/tags/v9.1.0",
            "git push origin --delete release",
            "git push origin +main",
            "git push --mirror",
            "git tag -d v9.1.0",
            "git tag -a -f v9.1.0 abc123",
            "git fetch && git tag --delete v1.0.0",
        ):
            self.assertIsNotNone(guard.reason(command), command)

    def test_allows(self):
        for command in (
            "git push origin release/v9.2.0",
            "git push -u origin release/v9.2.0",
            "git push origin v9.2.0",
            "git push --follow-tags origin dev",
            "git tag -a v9.2.0 abc123 -m 'v9.2.0'",
            "git tag -l 'v*' --sort=-creatordate",
            "gh release view v9.1.0",
            "gh release download v9.1.0 --pattern MANIFEST.txt",
            "git push origin HEAD:refs/heads/release/v9.2.0",
        ):
            self.assertIsNone(guard.reason(command), command)


if __name__ == "__main__":
    unittest.main()
