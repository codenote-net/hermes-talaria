"""Fixture-only read-only discovery tests; no real GitHub or model calls."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "discover_prs.py"
spec = importlib.util.spec_from_file_location("discover_prs", SCRIPT)
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

QUERY = "is:pr state:open user-review-requested:@me sort:created-asc"
URL = "https://github.com/example/project"


def item(number, date="2026-01-01T00:00:00Z"):
    return {"number": number, "html_url": f"{URL}/pull/{number}",
            "repository_url": "https://api.github.com/repos/example/project",
            "created_at": date, "pull_request": {}, "state": "open"}


def page(items, total=None, incomplete=False):
    return {"items": items, "total_count": len(items) if total is None else total,
            "incomplete_results": incomplete}


class FakeGh:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args == ["auth", "status"]:
            return ""
        if args == ["api", "--hostname", "github.com", "user"]:
            return json.dumps({"login": "reviewer"})
        return json.dumps(next(self.pages))


class DiscoveryTests(unittest.TestCase):
    def test_urls_and_literal_query(self):
        self.assertEqual(m.parse_target(URL), "example/project")
        for encoded in (quote(QUERY), quote(QUERY).replace("%20", "+")):
            self.assertEqual(m.parse_target(URL + "/pulls?q=" + encoded), "example/project")
        for bad in ("is:pr is:open user-review-requested:@me sort:created-asc",
                    QUERY.replace("user-review-requested", "review-requested"),
                    QUERY + " repo:other/repo", QUERY + " is:pr", QUERY.replace("@me", "reviewer")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                m.parse_target(URL + "/pulls?q=" + quote(bad))
        for bad in (URL + "/pulls", URL + "?q=x", URL + "/pulls?q=" + quote(QUERY) + "&q=" + quote(QUERY),
                    URL + "/pulls?q=" + quote(QUERY) + "&page=2", URL + "#x",
                    URL.replace("https:", "http:"), URL.replace("github.com", "user@github.com"),
                    URL.replace("project", "%70roject"), URL + "/pulls?q=%ZZ",
                    URL + "/pulls?q=" + quote(quote(QUERY)), " " + URL,
                    URL + "\n", URL.replace("project", "pro\nject")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                m.parse_target(bad)

    def test_empty_and_identity(self):
        gh = FakeGh([page([])])
        result = m.discover(URL, gh)
        self.assertEqual(result["reviewer"], "reviewer")
        self.assertEqual(result["prs"], [])
        self.assertEqual(result["query"], QUERY + " repo:example/project")
        self.assertEqual(gh.calls[:2], [["auth", "status"], ["api", "--hostname", "github.com", "user"]])
        command = gh.calls[2]
        self.assertIn("GET", command)
        self.assertIn("q=" + QUERY + " repo:example/project", command)
        self.assertNotIn("review-requested:@me", result["query"].split())

    def test_pagination_ordering_and_deduplication(self):
        first = [item(n, "2026-02-01T00:00:00Z") for n in range(1, 101)]
        gh = FakeGh([page(first, 102), page([item(1, "2026-02-01T00:00:00Z"), item(101)], 102)])
        result = m.discover(URL, gh)
        self.assertEqual(len(result["prs"]), 101)
        self.assertEqual(result["prs"][0]["number"], 101)
        self.assertEqual(result["prs"][1]["number"], 1)
        self.assertIn("page=1", gh.calls[2])
        self.assertIn("page=2", gh.calls[3])
        self.assertEqual(result["search_total_count"], 102)

    def test_incomplete_cap_and_bad_pages(self):
        cases = [[page([], 0, True)], [page([], 1000)], [page([], 1001)],
                 [page([], 1)], [{"message": "denied"}],
                 [page([item(1)] * 100, 101), page([item(2)], 102)],
                 [page([item(1), item(1, "2026-02-01T00:00:00Z")])]]
        for pages in cases:
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                m.discover(URL, FakeGh(pages))

    def test_scope_and_item_validation(self):
        for change in ({"repository_url": "https://api.github.com/repos/other/project"},
                       {"html_url": "https://github.com/other/project/pull/1"},
                       {"pull_request": None}, {"state": "closed"},
                       {"created_at": "not-a-date"}, {"number": True}):
            value = item(1)
            value.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                m.discover(URL, FakeGh([page([value])]))

    def test_last_page_below_cap(self):
        values = [item(n) for n in range(1, 1000)]
        gh = FakeGh([page(values[start:start + 100], 999) for start in range(0, 999, 100)])
        result = m.discover(URL, gh)
        self.assertEqual(result["candidate_count"], 999)
        self.assertIn("page=10", gh.calls[-1])

    def test_error_after_first_page(self):
        gh = FakeGh([page([item(n) for n in range(1, 101)], 101), {"message": "rate limited"}])
        with self.assertRaises(ValueError):
            m.discover(URL, gh)

    def test_missing_identity(self):
        def execute(args):
            return "" if args == ["auth", "status"] else "{}"
        with self.assertRaises(ValueError):
            m.discover(URL, execute)

    def test_api_and_auth_failure_propagate(self):
        def failed(args):
            raise subprocess.CalledProcessError(1, ["gh", *args])
        with self.assertRaises(subprocess.CalledProcessError):
            m.discover(URL, failed)

    def test_external_exclusive_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            outside = root / "snapshot.json"
            m.save_snapshot({"prs": []}, outside, repo)
            self.assertEqual(json.loads(outside.read_text()), {"prs": []})
            for output in (outside, repo / "report.json"):
                with self.assertRaises(ValueError):
                    m.save_snapshot({}, output, repo)
            link = root / "linked"
            link.symlink_to(repo, target_is_directory=True)
            with self.assertRaises(ValueError):
                m.save_snapshot({}, link / "report.json", repo)
            dangling = root / "dangling"
            dangling.symlink_to(root / "missing")
            with self.assertRaises(ValueError):
                m.save_snapshot({}, dangling, repo)

    def test_cli_failure_does_not_write_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "snapshot.json"
            with patch.object(m, "discover", side_effect=ValueError("fixture failure")), \
                 patch.object(m, "source_root", return_value=Path(temporary) / "repo"):
                self.assertEqual(m.main([URL, "--repo", temporary, "--output", str(output)]), 2)
            self.assertFalse(output.exists())

    def test_cli_success_persists_frozen_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            output = root / "snapshot.json"
            original = m.discover
            gh = FakeGh([page([item(3)])])
            with patch.object(m, "source_root", return_value=repo), \
                 patch.object(m, "discover", side_effect=lambda target: original(target, gh)):
                self.assertEqual(m.main([URL, "--repo", str(repo), "--output", str(output)]), 0)
            saved = json.loads(output.read_text())
            self.assertEqual(saved["candidate_count"], 1)
            self.assertEqual(saved["prs"][0]["url"], URL + "/pull/3")
            self.assertEqual(saved["input_url"], URL)


if __name__ == "__main__":
    unittest.main()
