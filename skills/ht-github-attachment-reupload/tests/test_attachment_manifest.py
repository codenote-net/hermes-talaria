import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "attachment_manifest", ROOT / "scripts" / "ht_attachment_manifest.py"
)
assert spec is not None and spec.loader is not None
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # macOS /var can be a symlink; use the actual private directory.
        self.root = Path(self.temp.name).resolve()

    def make(self, name="original.png", data=b"\x89PNG\r\n\x1a\nfixture"):
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_inspect_hash_and_size(self):
        path = self.make(data=b"x" * (1024 * 1024 + 31))
        result = helper.inspect_file(path)
        self.assertEqual(result["size"], path.stat().st_size)
        self.assertEqual(result["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_reject_missing_empty_directory_and_partial(self):
        for path in (self.root / "absent", self.make("empty", b""), self.root,
                     self.make("image.CRDOWNLOAD"), self.make("image.part")):
            with self.subTest(path=path), self.assertRaises(ValueError):
                helper.inspect_file(path)

    def test_reject_html_under_image_name(self):
        for data in (b"<!DOCTYPE html><html>Login", b"\xef\xbb\xbf \n<HTML>Login",
                     b"<!-- proxy -->\n<html>Denied", b"<body>Error"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                helper.inspect_file(self.make(data=data))

    def test_reject_symlink_and_symlink_parent(self):
        original = self.make()
        link = self.root / "link.png"
        link.symlink_to(original)
        folder = self.root / "folder"
        folder.symlink_to(self.root, target_is_directory=True)
        for path in (link, folder / original.name):
            with self.subTest(path=path), self.assertRaises(ValueError):
                helper.inspect_file(path)

    def test_same_basename_different_bytes(self):
        first = self.make()
        second_dir = self.root / "second"
        second_dir.mkdir()
        second = second_dir / first.name
        second.write_bytes(b"different")
        self.assertNotEqual(helper.inspect_file(first)["sha256"],
                            helper.inspect_file(second)["sha256"])

    def run_cli(self, args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = helper.main(args)
        return code, output.getvalue(), errors.getvalue()

    def test_compare_equal_and_unequal(self):
        original = self.make()
        copy = self.make("copy.png")
        code, output, _ = self.run_cli(["compare", str(original), str(copy)])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output)["equal"])
        copy.write_bytes(b"mismatch")
        code, output, _ = self.run_cli(["compare", str(original), str(copy)])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(output)["equal"])

    def test_inspect_cli_and_error_exit(self):
        code, output, _ = self.run_cli(["inspect", str(self.make())])
        self.assertEqual(code, 0)
        self.assertIn("sha256", json.loads(output))
        code, _, errors = self.run_cli(["inspect", str(self.root / "missing")])
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(errors))
        self.assertNotIn(str(self.root), errors)

    def test_mutation_during_read_is_rejected(self):
        path = self.make()
        original_open = Path.open

        def changing_open(target, *args, **kwargs):
            stream = original_open(target, *args, **kwargs)
            with original_open(target, "ab") as writer:
                writer.write(b"changed")
            return stream

        with patch.object(Path, "open", changing_open), self.assertRaises(ValueError):
            helper.inspect_file(path)


class PackageTests(unittest.TestCase):
    def test_relative_markdown_links_exist(self):
        for path in ROOT.rglob("*.md"):
            for link in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                if "://" not in link and not link.startswith("#"):
                    self.assertTrue((path.parent / link).is_file(), (path, link))

    def test_ledger_defaults_are_unverified(self):
        ledger = json.loads((ROOT / "templates/run-manifest.json").read_text())
        self.assertIsNone(ledger["approval_evidence"])
        self.assertEqual(ledger["permission_check"]["status"], "not_verified")
        self.assertEqual(ledger["items"][0]["state"], "pending")
        self.assertIsNone(ledger["items"][0]["new_asset_url"])


if __name__ == "__main__":
    unittest.main()
