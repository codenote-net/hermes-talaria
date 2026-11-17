#!/usr/bin/env python3
"""Read-only GitHub PR search; freeze candidates, never review or approve them."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import parse_qsl, urlsplit

QUERY = "is:pr state:open user-review-requested:@me sort:created-asc"
PATH = re.compile(r"/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+)(/pulls)?\Z")


def parse_target(target):
    # urlsplit strips controls/leading spaces: reject before parsing, never repair.
    if not target.startswith("https://github.com/") or re.search(r"[\x00-\x20\x7f]", target):
        raise ValueError("URL must be literal HTTPS without whitespace or controls")
    url = urlsplit(target)
    match = PATH.fullmatch(url.path)
    if (url.scheme != "https" or url.netloc != "github.com" or url.fragment
            or "#" in target or not match or match[2] in (".", "..")):
        raise ValueError("expected an exact GitHub repository or pulls search URL")
    if match[3]:
        if re.search(r"%(?![0-9a-fA-F]{2})", url.query):
            raise ValueError("invalid percent encoding")
        if parse_qsl(url.query, keep_blank_values=True, strict_parsing=True) != [("q", QUERY)]:
            raise ValueError("search URL must contain only the exact fixed q query")
    elif url.query or "?" in target:
        raise ValueError("repository URL must not have a query")
    return f"{match[1]}/{match[2]}"


def gh(args):
    return subprocess.check_output(["gh", *args], text=True, stderr=subprocess.PIPE, timeout=60)


def discover(target, execute=gh):
    repository = parse_target(target)
    execute(["auth", "status"])
    identity = json.loads(execute(["api", "--hostname", "github.com", "user"]))
    reviewer = identity.get("login")
    if not isinstance(reviewer, str) or not re.fullmatch(r"[A-Za-z0-9-]+", reviewer):
        raise ValueError("missing authenticated GitHub identity")
    query = f"{QUERY} repo:{repository}"
    records = {}
    total = None
    received = 0
    for number in range(1, 11):
        data = json.loads(execute(["api", "--hostname", "github.com", "--method", "GET",
                                   "search/issues", "-f", f"q={query}",
                                   "-f", "per_page=100", "-f", f"page={number}"]))
        count = data.get("total_count")
        if (data.get("incomplete_results") is not False or type(count) is not int
                or count < 0 or count >= 1000):
            raise ValueError("incomplete search or search at/above the 1000-result cap")
        if total is not None and count != total:
            raise ValueError("search total changed during pagination; no complete snapshot")
        total = count
        items = data.get("items")
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError("invalid search items")
        received += len(items)
        if received > total:
            raise ValueError("search returned more items than declared")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("invalid search item")
            pr_number = item.get("number")
            if type(pr_number) is not int or pr_number < 1:
                raise ValueError("invalid PR number")
            expected_url = f"https://github.com/{repository}/pull/{pr_number}"
            if (item.get("repository_url") != f"https://api.github.com/repos/{repository}"
                    or item.get("html_url") != expected_url
                    or not isinstance(item.get("pull_request"), dict) or item.get("state") != "open"):
                raise ValueError("search returned an out-of-scope or non-open PR")
            created = item.get("created_at")
            if not isinstance(created, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", created):
                raise ValueError("invalid creation timestamp")
            dt.datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ")
            record = {"number": pr_number, "url": expected_url, "created_at": created}
            if pr_number in records and records[pr_number] != record:
                raise ValueError("conflicting duplicate PR metadata")
            records[pr_number] = record
        if received == total:
            break
        if len(items) != 100:
            raise ValueError("pagination ended before declared total")
    else:
        raise ValueError("search pagination exceeded cap")
    return {"repository": repository, "input_url": target, "reviewer": reviewer,
            "query": query, "discovered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "search_total_count": total, "candidate_count": len(records),
            "prs": sorted(records.values(), key=lambda row: (row["created_at"], row["number"])),
            "scope": "Frozen search candidates only; live direct-user eligibility must be rechecked."}


def source_root(repo):
    return Path(subprocess.check_output(["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
                                       text=True, stderr=subprocess.PIPE, timeout=30).strip()).resolve()


def save_snapshot(snapshot, output, repo):
    output = Path(output)
    resolved = output.resolve()
    root = Path(repo).resolve()
    if output.exists() or output.is_symlink() or resolved == root or root in resolved.parents:
        raise ValueError("output must be a new file outside the source checkout")
    # Exclusive creation preserves prior evidence even if another process races us.
    with output.open("x", encoding="utf-8") as stream:
        json.dump(snapshot, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target_url")
    parser.add_argument("--repo", required=True, type=Path, help="source checkout whose output boundary to enforce")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        root = source_root(args.repo)
        snapshot = discover(args.target_url)
        save_snapshot(snapshot, args.output, root)
        print(f"SNAPSHOT: {args.output} ({snapshot['candidate_count']} candidates)")
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"INCOMPLETE: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
