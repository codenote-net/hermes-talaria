#!/usr/bin/env python3
"""Run four authenticated PR reviews in a disposable detached worktree; never approve."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile

SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
URL = re.compile(r"https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/pull/(?P<number>[1-9][0-9]*)\Z")


def git(repo, *args):
    return subprocess.check_output([
        "git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
        "-C", str(repo), *args], stderr=subprocess.PIPE, timeout=120).decode().strip()


def run(command, cwd, timeout):
    """Kill the whole reviewer process group on timeout, not only the CLI parent."""
    try:
        process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as exc:
        return 127, str(exc)
    try:
        output, _ = process.communicate(timeout=timeout)
        return process.returncode, output.decode(errors="replace")
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate()
        return 124, output.decode(errors="replace") + "\nERROR: reviewer timed out"
    except BaseException:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise


def checked(command, repo):
    code, text = run(command, repo, 60)
    if code:
        raise ValueError(f"command failed ({code}): {command!r}\n{text}")
    return text


def live(repo, match):
    endpoint = f"repos/{match['owner']}/{match['repo']}/pulls/{match['number']}"
    data = json.loads(checked(["gh", "api", endpoint], repo))
    if data["base"]["repo"]["full_name"].lower() != f"{match['owner']}/{match['repo']}".lower():
        raise ValueError("PR repository mismatch")
    if data["number"] != int(match["number"]):
        raise ValueError("PR number mismatch")
    for side in ("head", "base"):
        if not SHA.fullmatch(data[side]["sha"]):
            raise ValueError("invalid live commit SHA")
    return {"head": data["head"]["sha"], "base": data["base"]["sha"],
            "state": data["state"], "draft": data["draft"]}


@contextmanager
def detached(repo, head):
    with tempfile.TemporaryDirectory(prefix="ht-pr-approve-") as temporary:
        path = Path(temporary) / "review"
        try:
            git(repo, "worktree", "add", "--detach", str(path), head)
            yield path
        finally:
            if path.exists():
                git(repo, "worktree", "remove", "--force", str(path))


def review(repo, url, timeout=1800, head=None, base=None):
    match = URL.fullmatch(url)
    if not match or timeout < 1:
        raise ValueError("invalid PR URL or timeout")
    for value in (head, base):
        if value is not None and not SHA.fullmatch(value):
            raise ValueError("expected commits must be literal full lowercase SHAs")
    expected = f"{match['owner']}/{match['repo']}"
    identity = checked(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], repo).strip()
    if identity.lower() != expected.lower():
        raise ValueError("current repository does not match PR")
    for command in (["gh", "auth", "status"], ["claude", "auth", "status", "--text"],
                    ["codex", "login", "status"]):
        checked(command, repo)
    before = live(repo, match)
    if (head and head != before["head"]) or (base and base != before["base"]):
        raise ValueError("requested commits differ from live PR")
    if before["state"] != "open" or before["draft"]:
        raise ValueError("PR must be open and non-draft")
    head, base = before["head"], before["base"]
    # Fetch exact objects from the validated repository, including fork PR heads.
    remote = f"https://github.com/{expected}.git"
    git(repo, "fetch", "--no-tags", remote, head, base)
    for value in (head, base):
        if git(repo, "rev-parse", "--verify", value + "^{commit}") != value:
            raise ValueError("fetched commit identity mismatch")
    report = {"pr_url": url, "head": head, "base": base, "before": before,
              "executed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "raw_reviews": [], "review_complete": False, "approval_submitted": False,
              "boundary": "Detached worktree is not a security boundary; authenticated CLIs retain host access."}
    with detached(repo, head) as worktree:
        commands = [(name, ["claude", "--permission-mode", "auto", "-p", "--model",
                     "claude-opus-5-5", "--effort", "high", "--no-session-persistence",
                     f"/{name} {url}\nReview only head {head} against base {base}. Do not publish reviews, comments, approvals, or other remote writes. Do not modify files."])
                    for name in ("review", "security-review", "code-review")]
        commands.append(("codex", ["codex", "--yolo", "review", "-c", 'model="gpt-6.1-sol"',
                         "-c", 'model_reasoning_effort="high"', "-c", 'service_tier="priority"',
                         "--base", base]))
        report["merge_base"] = git(worktree, "merge-base", base, head)
        for name, command in commands:
            start_ok = git(worktree, "rev-parse", "HEAD") == head and not git(worktree, "status", "--porcelain", "--untracked-files=all")
            code, text = run(command, worktree, timeout)
            end_ok = git(worktree, "rev-parse", "HEAD") == head and not git(worktree, "status", "--porcelain", "--untracked-files=all")
            report["raw_reviews"].append({"name": name, "command": command, "exit_code": code,
                                           "output": text, "checkout_unchanged": start_ok and end_ok})
    try:
        report["after"] = live(repo, match)
        report["fresh"] = report["after"] == before
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        report["fresh"] = False
        report["freshness_error"] = str(exc)
    report["review_complete"] = report["fresh"] and all(
        item["exit_code"] == 0 and item["output"].strip() and item["checkout_unchanged"]
        for item in report["raw_reviews"])
    report["status"] = "REVIEWED" if report["review_complete"] else "INCOMPLETE"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr_url")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--head")
    parser.add_argument("--base")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)
    try:
        repo = Path(git(args.repo, "rev-parse", "--show-toplevel")).resolve()
        output = args.output.resolve()
        if output == repo or repo in output.parents or args.output.exists() or args.output.is_symlink():
            raise ValueError("output must be a new file outside the source checkout")
        report = review(repo, args.pr_url, args.timeout, args.head, args.base)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        print(f"{report['status']}: {output}")
        return 0 if report["review_complete"] else 2
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"INCOMPLETE: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())