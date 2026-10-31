"""Real Git worktrees and fake CLI subprocesses; no network or model authentication."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "review_runner", Path(__file__).parents[1] / "scripts" / "review_pr.py")
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
URL = "https://github.com/example/project/pull/1"


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ht-review-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        (self.repo / "source.py").write_text("base = 1\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        (self.repo / "source.py").write_text("head = 2\n")
        self.git("commit", "-qam", "head")
        self.head = self.git("rev-parse", "HEAD")
        (self.repo / "source.py").write_text("dirty tracked\n")
        (self.repo / "untracked").write_text("keep me\n")
        self.before = self.git("worktree", "list", "--porcelain")
        self.status = self.git("status", "--porcelain")
        self.log = self.root / "calls.jsonl"
        bindir = self.root / "bin"
        bindir.mkdir()
        fake = '''import json, os, pathlib, subprocess, sys, time
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
if name == 'gh':
    if args[0] == 'repo': print('example/project')
    elif args[0] == 'api':
        counter = pathlib.Path(os.environ['COUNTER'])
        n = int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(n+1))
        head = os.environ['HEAD_SHA']
        base = os.environ['BASE_SHA']
        if n and os.environ.get('STALE') == 'head': head = base
        if n and os.environ.get('STALE') == 'base': base = head
        print(json.dumps(dict(number=1, state='open', draft=False,
            head=dict(sha=head), base=dict(sha=base, repo=dict(full_name='example/project')))))
    elif args != ['auth', 'status']: sys.exit(90)
    sys.exit(0)
if args[:2] in (['auth','status'], ['login','status']): sys.exit(0)
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps(dict(name=name, args=args, cwd=os.getcwd(),
        head=subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
        source=pathlib.Path('source.py').read_text()))+'\\n')
if name == 'claude' and '/security-review ' in args[-1]:
    mode = os.environ.get('MODE')
    if mode == 'fail': print('fixture failure'); sys.exit(7)
    if mode == 'timeout': time.sleep(20)
    if mode == 'empty': sys.exit(0)
    if mode == 'mutate': pathlib.Path('source.py').write_text('reviewer mutation')
print('FIXTURE ONLY: reviewer subprocess executed')
'''
        for name in ("gh", "claude", "codex"):
            executable = bindir / name
            executable.write_text(f"#!{sys.executable}\n" + fake)
            executable.chmod(0o755)
        env = {"PATH": str(bindir) + os.pathsep + os.environ["PATH"],
               "HEAD_SHA": self.head, "BASE_SHA": self.base, "CALL_LOG": str(self.log),
               "COUNTER": str(self.root / "counter"), "MODE": "", "STALE": ""}
        self.env = patch.dict(os.environ, env)
        self.env.start()
        self.addCleanup(self.env.stop)
        real_git = runner.git

        def local_fetch(repo, *args):
            if args[0] == "fetch":
                self.assertEqual(args, ("fetch", "--no-tags", "https://github.com/example/project.git", self.head, self.base))
                return ""
            return real_git(repo, *args)
        self.git_patch = patch.object(runner, "git", side_effect=local_fetch)
        self.git_patch.start()
        self.addCleanup(self.git_patch.stop)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True).strip()

    def assert_preserved(self):
        self.assertEqual(self.before, self.git("worktree", "list", "--porcelain"))
        self.assertEqual(self.head, self.git("rev-parse", "HEAD"))
        self.assertEqual(self.status, self.git("status", "--porcelain"))
        self.assertEqual((self.repo / "source.py").read_text(), "dirty tracked\n")
        self.assertEqual((self.repo / "untracked").read_text(), "keep me\n")

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_four_real_subprocesses_exact_flags_and_provenance(self):
        report = runner.review(self.repo, URL)
        self.assertTrue(report["review_complete"])
        self.assertFalse(report["approval_submitted"])
        self.assertEqual(report["merge_base"], self.base)
        calls = self.calls()
        self.assertEqual([x["name"] for x in calls], ["claude"] * 3 + ["codex"])
        for item, slash in zip(calls, ("review", "security-review", "code-review")):
            self.assertEqual(item["args"][:-1], ["--permission-mode", "auto", "-p", "--model", "claude-opus-5-5", "--effort", "high", "--no-session-persistence"])
            self.assertTrue(item["args"][-1].startswith(f"/{slash} {URL}\n"))
            self.assertIn(self.head, item["args"][-1])
            self.assertIn(self.base, item["args"][-1])
        self.assertEqual(calls[-1]["args"], ["--yolo", "review", "-c", 'model="gpt-6.1-sol"', "-c", 'model_reasoning_effort="high"', "-c", 'service_tier="priority"', "--base", self.base])
        for item in calls:
            self.assertEqual(item["head"], self.head)
            self.assertEqual(item["source"], "head = 2\n")
            self.assertNotEqual(item["cwd"], str(self.repo))
            self.assertFalse(Path(item["cwd"]).exists())
        self.assertEqual([x["exit_code"] for x in report["raw_reviews"]], [0] * 4)
        self.assert_preserved()

    def test_failure_continues_and_writes_incomplete_report(self):
        os.environ["MODE"] = "fail"
        output = self.root / "evidence.json"
        self.assertEqual(runner.main([URL, "--repo", str(self.repo), "--output", str(output)]), 2)
        report = json.loads(output.read_text())
        self.assertEqual([x["exit_code"] for x in report["raw_reviews"]], [0, 7, 0, 0])
        self.assertFalse(report["review_complete"])
        self.assertFalse(report["approval_submitted"])
        self.assertEqual(len(self.calls()), 4)
        self.assert_preserved()

    def test_timeout_continues_and_cleans(self):
        os.environ["MODE"] = "timeout"
        report = runner.review(self.repo, URL, timeout=1)
        self.assertEqual(report["raw_reviews"][1]["exit_code"], 124)
        self.assertFalse(report["review_complete"])
        self.assertEqual(len(self.calls()), 4)
        self.assert_preserved()

    def test_empty_output_blocks(self):
        os.environ["MODE"] = "empty"
        self.assertFalse(runner.review(self.repo, URL)["review_complete"])
        self.assert_preserved()

    def test_mutation_blocks_and_preserves_original(self):
        os.environ["MODE"] = "mutate"
        report = runner.review(self.repo, URL)
        self.assertFalse(report["review_complete"])
        self.assertFalse(report["raw_reviews"][1]["checkout_unchanged"])
        self.assert_preserved()

    def test_head_and_base_races_block(self):
        for side in ("head", "base"):
            with self.subTest(side=side):
                (self.root / "counter").unlink(missing_ok=True)
                os.environ["STALE"] = side
                report = runner.review(self.repo, URL)
                self.assertFalse(report["fresh"])
                self.assertFalse(report["review_complete"])
                self.assert_preserved()

    def test_exception_cleans_worktree(self):
        real_run = runner.run
        def error(command, cwd, timeout):
            if command[0] == "claude" and "-p" in command:
                raise RuntimeError("fixture exception")
            return real_run(command, cwd, timeout)
        with patch.object(runner, "run", side_effect=error):
            with self.assertRaises(RuntimeError):
                runner.review(self.repo, URL)
        self.assert_preserved()

    def test_invalid_and_stale_expected_sha(self):
        for value in ("HEAD", self.head[:12], self.head.upper(), "0" * 40):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.review(self.repo, URL, head=value)
        self.assertFalse(self.log.exists())
        self.assert_preserved()

    def test_output_restrictions_and_success_cli(self):
        args = [URL, "--repo", str(self.repo), "--output"]
        self.assertEqual(runner.main(args + [str(self.repo / "report.json")]), 2)
        output = self.root / "report.json"
        self.assertEqual(runner.main(args + [str(output)]), 0)
        original = output.read_bytes()
        self.assertEqual(runner.main(args + [str(output)]), 2)
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(len(self.calls()), 4)
        self.assert_preserved()


    def test_fetch_failure_has_no_fallback_or_review(self):
        real_git = runner.git
        def fail_fetch(repo, *args):
            if args[0] == "fetch":
                raise subprocess.CalledProcessError(1, ["git", *args])
            return real_git(repo, *args)
        with patch.object(runner, "git", side_effect=fail_fetch):
            with self.assertRaises(subprocess.CalledProcessError):
                runner.review(self.repo, URL)
        self.assertFalse(self.log.exists())
        self.assert_preserved()

    def test_post_review_metadata_failure_is_incomplete(self):
        real_live = runner.live
        count = 0
        def unavailable(repo, match):
            nonlocal count
            count += 1
            if count == 2:
                raise ValueError("fixture API unavailable")
            return real_live(repo, match)
        with patch.object(runner, "live", side_effect=unavailable):
            report = runner.review(self.repo, URL)
        self.assertFalse(report["review_complete"])
        self.assertEqual(len(report["raw_reviews"]), 4)
        self.assertIn("fixture API unavailable", report["freshness_error"])
        self.assert_preserved()

    def test_missing_reviewer_executable_is_individual_failure(self):
        (self.root / "bin" / "codex").unlink()
        with patch.dict(os.environ, {"PATH": str(self.root / "bin")}):
            code, output = runner.run(["codex", "review"], self.repo, 1)
        self.assertEqual(code, 127)
        self.assertTrue(output)
        self.assert_preserved()


if __name__ == "__main__":
    unittest.main()