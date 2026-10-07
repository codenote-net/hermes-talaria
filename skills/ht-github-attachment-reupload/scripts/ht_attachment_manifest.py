#!/usr/bin/env python3
"""Local byte inspection only. Never download, upload, or infer permissions."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


PARTIAL_SUFFIXES = {".crdownload", ".part", ".partial", ".download", ".tmp"}


def inspect_file(filename):
    path = Path(filename)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Symlinks are not accepted")
    if not path.is_file():
        raise ValueError("Expected a regular downloaded file")
    if path.suffix.lower() in PARTIAL_SUFFIXES:
        raise ValueError("Partial-download filename is not accepted")
    before = path.stat()
    if before.st_size == 0:
        raise ValueError("Empty download is not accepted")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        prefix = stream.read(4096)
        probe = prefix.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
        if any(marker in probe for marker in (b"<!doctype html", b"<html", b"<head", b"<body")):
            raise ValueError("Likely HTML response; inspect the browser, not a successful attachment")
        digest.update(prefix)
        size += len(prefix)
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size, after.st_mtime_ns, after.st_ino
    ) or size != after.st_size:
        raise ValueError("File changed during inspection")
    return {"name": path.name, "size": size, "sha256": digest.hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("path")
    compare = commands.add_parser("compare")
    compare.add_argument("original")
    compare.add_argument("downloaded")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_file(args.path)
            status = 0
        else:
            original = inspect_file(args.original)
            downloaded = inspect_file(args.downloaded)
            equal = (original["size"], original["sha256"]) == (
                downloaded["size"], downloaded["sha256"]
            )
            result = {"equal": equal, "original": original, "downloaded": downloaded}
            status = 0 if equal else 1
        print(json.dumps(result, ensure_ascii=True))
        return status
    except (OSError, ValueError) as error:
        # Avoid printing filesystem paths or untrusted server-provided error text.
        message = str(error) if isinstance(error, ValueError) else "Cannot inspect local file"
        print(json.dumps({"error": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
