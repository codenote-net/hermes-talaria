#!/usr/bin/env python3
"""Read-only, stdlib GitHub billing CSV inspection; never prints CSV or paths."""
import argparse
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from report_period import resolve_period

PROFILES = {
    'detailed': {'date', 'product', 'sku', 'quantity', 'gross_amount', 'net_amount', 'organization', 'repository', 'username', 'workflow_path'},
    'summarized': {'date', 'product', 'sku', 'quantity', 'gross_amount', 'net_amount', 'organization', 'repository'},
    # Official billing-reports reference: AI tokens are not workflow usage.
    'ai_usage': {'date', 'model', 'username', 'quantity', 'gross_amount', 'discount_amount', 'net_amount', 'input', 'output', 'cache_read', 'cache_write'},
}
NUMERIC = {'quantity', 'gross_amount', 'net_amount', 'discount_amount', 'applied_cost_per_quantity', 'input', 'output', 'cache_read', 'cache_write'}
PARTIAL_SUFFIXES = {'.crdownload', '.part', '.partial', '.download', '.tmp'}


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes rejected values, which may contain secrets.
        self.exit(2, 'Invalid command arguments; use --help for required options.\n')


def iso_date(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        raise ValueError('Use a canonical UTC calendar date (YYYY-MM-DD).') from None


def private_path(value):
    """Reject artifact symlinks and Git worktrees/administrative areas, fail closed."""
    try:
        path = Path(os.path.abspath(value))
        # Only normalize OS-owned macOS aliases; never resolve user symlinks first.
        if sys.platform == 'darwin' and len(path.parts) > 1 and path.parts[1] in {'var', 'tmp', 'etc'}:
            alias = Path('/') / path.parts[1]
            if alias.is_symlink() and alias.resolve() == Path('/private') / path.parts[1]:
                path = alias.resolve().joinpath(*path.parts[2:])
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('Use a non-symlink path outside Git repositories.')
        path = path.resolve()
        if any((p / '.git').exists() or (p / '.git').is_symlink()
               for p in (path, *path.parents) if p.is_dir()):
            raise ValueError('Move private artifacts outside all Git repositories.')
        anchor = path if path.is_dir() else path.parent
        while not anchor.exists():
            anchor = anchor.parent
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, LC_ALL='C')
        result = subprocess.run(['git', '-C', str(anchor), 'rev-parse', '--absolute-git-dir'],
                                env=env, capture_output=True, timeout=5, check=False)
        if result.returncode == 0:
            raise ValueError('Move private artifacts outside all Git repositories.')
        if result.returncode != 128 or b'not a git repository' not in result.stderr.lower():
            raise ValueError('Cannot confirm private path; retry Git discovery.')
    except (OSError, RuntimeError, subprocess.SubprocessError):
        raise ValueError('Cannot confirm private path; ensure Git discovery is available.') from None
    return path


def _signature(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def fingerprint(path):
    """Stream a private file without changing it.

    Browser downloads often arrive as 0644: the operator must explicitly chmod
    the file to 0600 and its containing directory to 0700 before inspection.
    Only the containing private directory is checked, not shared OS/home parents.
    """
    path = private_path(path)
    if not path.is_file() or path.suffix.lower() in PARTIAL_SUFFIXES:
        raise ValueError('Select a completed regular file outside Git.')
    before = path.stat()
    parent = path.parent.stat()
    if stat.S_IMODE(before.st_mode) != 0o600 or before.st_uid != os.getuid():
        raise ValueError('Require an owned private file; explicitly chmod the report to 0600.')
    if stat.S_IMODE(parent.st_mode) != 0o700 or parent.st_uid != os.getuid():
        raise ValueError('Require an owned private containing directory with mode 0700.')
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
            size += len(chunk)
    if size == 0:
        raise ValueError('The report is empty; download a complete CSV.')
    if _signature(before) != _signature(path.stat()) or size != before.st_size:
        raise ValueError('File changed during inspection; retry a completed download.')
    return {'bytes': size, 'sha256': digest.hexdigest()}


def validate(path, kind, start_date, end_date, now=None):
    if kind not in PROFILES:
        raise ValueError('Select detailed, summarized, or ai_usage.')
    start, end = iso_date(start_date), iso_date(end_date)
    resolve_period({'page': 'ai_usage' if kind == 'ai_usage' else 'usage',
                    'kind': kind, 'period': {'mode': 'custom',
                    'start_date': start_date, 'end_date': end_date}}, now=now)
    path = private_path(path)
    before = fingerprint(path)
    rows, workflows = 0, 0
    minimum, maximum = None, None
    try:
        with path.open('r', encoding='utf-8-sig', errors='strict', newline='') as stream:
            reader = csv.reader(stream, strict=True)
            headers = next(reader, None)
            if not headers or any(not h or h != h.strip() for h in headers) or len(set(headers)) != len(headers):
                raise ValueError('CSV needs unique, nonempty header names.')
            if any('<html' in h.lower() or '<!doctype' in h.lower() for h in headers):
                raise ValueError('HTML is not a report; download the CSV in the browser.')
            fields = set(headers)
            if not PROFILES[kind] <= fields:
                raise ValueError('CSV is missing required fields for the selected report kind.')
            if kind == 'summarized' and fields & {'username', 'workflow_path', 'model', 'input', 'output', 'cache_read', 'cache_write'}:
                raise ValueError('CSV profile does not match summarized billing usage.')
            if kind == 'detailed' and fields & {'model', 'input', 'output', 'cache_read', 'cache_write'}:
                raise ValueError('AI usage is a separate report profile.')
            if kind == 'ai_usage' and fields & {'workflow_path', 'product', 'sku'}:
                raise ValueError('Workflow billing is not the AI usage profile.')
            for values in reader:
                if len(values) != len(headers):
                    raise ValueError('CSV row width is invalid; download a complete report.')
                row = dict(zip(headers, values))
                day = iso_date(row['date'])
                if not start <= day <= end:
                    raise ValueError('CSV date falls outside the explicit UTC bounds.')
                for key in fields & NUMERIC:
                    try:
                        number = Decimal(row[key])
                        if not number.is_finite():
                            raise InvalidOperation
                    except InvalidOperation:
                        raise ValueError('CSV numeric fields must contain finite numbers.') from None
                rows += 1
                if kind == 'detailed' and row['workflow_path'].strip():
                    workflows += 1
                minimum = day if minimum is None else min(minimum, day)
                maximum = day if maximum is None else max(maximum, day)
    except (UnicodeError, csv.Error):
        raise ValueError('Expected a strict UTF-8 CSV; download a complete report.') from None
    if not rows or minimum is None or maximum is None:
        raise ValueError('CSV has no data rows; confirm the report period.')
    if before != fingerprint(path):
        raise ValueError('File changed during validation; retry a completed download.')
    result = dict(before, rows=rows, min_date_utc=minimum.isoformat(), max_date_utc=maximum.isoformat(), kind=kind, start_date=start_date, end_date=end_date)
    if kind == 'detailed':
        result['workflow_rows'] = workflows
    return result


def compare_files(original, readback):
    source, target = fingerprint(original), fingerprint(readback)
    if source != target:
        raise ValueError('Readback bytes or SHA256 differ; do not mark verified.')
    return dict(source, equal=True)


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument('file')
    parser.add_argument('--kind', required=True, choices=PROFILES)
    parser.add_argument('--start-date', required=True)
    parser.add_argument('--end-date', required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(validate(args.file, args.kind, args.start_date, args.end_date), sort_keys=True))
        return 0
    except (ValueError, OSError) as error:
        print(json.dumps({'error': str(error) if isinstance(error, ValueError) else 'Cannot read file; check private path and permissions.'}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
