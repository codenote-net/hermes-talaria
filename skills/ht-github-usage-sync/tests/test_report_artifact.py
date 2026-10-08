import csv
import io
import os
import subprocess
from datetime import datetime, timezone
from unittest.mock import patch
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import report_artifact as ra

DETAILED = ['date', 'product', 'sku', 'quantity', 'gross_amount', 'net_amount', 'organization', 'repository', 'username', 'workflow_path']
SUMMARY = DETAILED[:8]
AI = ['date', 'model', 'username', 'quantity', 'gross_amount', 'discount_amount', 'net_amount', 'input', 'output', 'cache_read', 'cache_write']


def make_csv(path, headers=DETAILED, dates=('2026-01-02',)):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        for day in dates:
            writer.writerow([day if h == 'date' else '1' if h in {'quantity', 'gross_amount', 'net_amount', 'discount_amount', 'input', 'output', 'cache_read', 'cache_write'} else 'example' for h in headers])
    path.chmod(0o600)
    return path


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.file = make_csv(self.root / 'report.csv')

    def validate(self, kind='detailed'):
        return ra.validate(self.file, kind, '2026-01-01', '2026-01-31')

    def test_metadata_and_immutable_comparison(self):
        before = self.file.read_bytes()
        result = self.validate()
        self.assertEqual(result['rows'], 1)
        self.assertEqual(result['workflow_rows'], 1)
        self.assertEqual(result['min_date_utc'], '2026-01-02')
        self.assertEqual(result['bytes'], len(before))
        copy = self.root / 'copy.csv'
        copy.write_bytes(before)
        copy.chmod(0o600)
        self.assertTrue(ra.compare_files(self.file, copy)['equal'])
        copy.write_bytes(before + b'\n')
        with self.assertRaises(ValueError):
            ra.compare_files(self.file, copy)
        self.assertEqual(self.file.read_bytes(), before)

    def test_profiles(self):
        with self.assertRaises(ValueError):
            self.validate('summarized')
        make_csv(self.file, SUMMARY)
        self.assertNotIn('workflow_rows', self.validate('summarized'))
        with self.assertRaises(ValueError):
            self.validate()
        make_csv(self.file, AI)
        self.assertEqual(self.validate('ai_usage')['rows'], 1)
        self.assertNotIn('workflow_rows', self.validate('ai_usage'))
        with self.assertRaises(ValueError):
            self.validate()

    def test_sparse_dates_accepted(self):
        make_csv(self.file, dates=('2026-01-02', '2026-01-30'))
        self.assertEqual(self.validate()['max_date_utc'], '2026-01-30')

    def test_bad_csv(self):
        for content in ('', '<html>login</html>', 'date,date\n2026-01-01,x', ',date\nx,2026-01-01', 'date\n2026-01-01', '\ufffd'):
            with self.subTest(content=content):
                self.file.write_text(content)
                with self.assertRaises(ValueError):
                    self.validate()
        for suffix in ('\nextra,column', '\n"unclosed'):
            make_csv(self.file)
            with self.file.open('a') as stream:
                stream.write(suffix)
            with self.assertRaises(ValueError):
                self.validate()
        make_csv(self.file, dates=())
        with self.assertRaises(ValueError):
            self.validate()
        self.file.write_bytes(b'\xff')
        with self.assertRaises(ValueError):
            self.validate()

    def test_dates_and_numbers(self):
        for day in ('20260102', '2026-1-2', '2026-02-30', '2026-01-02T00:00:00Z', '2025-12-31'):
            make_csv(self.file, dates=(day,))
            with self.assertRaises(ValueError):
                self.validate()
        make_csv(self.file)
        self.file.write_text(self.file.read_text(encoding='utf-8-sig').replace(',1,', ',NaN,', 1))
        with self.assertRaises(ValueError):
            self.validate()
        for start, end in [('20260101', '2026-01-31'), ('2026-02-01', '2026-01-01')]:
            with self.assertRaises(ValueError):
                ra.validate(self.file, 'detailed', start, end)

    def test_git_and_symlink_rejected(self):
        repo = self.root / 'repo'
        repo.mkdir()
        (repo / '.git').write_text('gitdir: /nonexistent')
        nested = repo / 'nested'
        nested.mkdir()
        with self.assertRaises(ValueError):
            ra.validate(make_csv(nested / 'report.csv'), 'detailed', '2026-01-01', '2026-01-31')
        link = self.root / 'link.csv'
        link.symlink_to(self.file)
        with self.assertRaises(ValueError):
            ra.validate(link, 'detailed', '2026-01-01', '2026-01-31')

    def test_period_policy(self):
        now = datetime(2026, 2, 15, tzinfo=timezone.utc)
        cases = [('detailed', DETAILED, '2026-01-01', '2026-02-15'),
                 ('ai_usage', AI, '2026-01-01', '2026-02-01'),
                 ('summarized', SUMMARY, '2024-01-01', '2026-01-31'),
                 ('detailed', DETAILED, '2099-01-01', '2099-01-31')]
        for kind, headers, start, end in cases:
            make_csv(self.file, headers, dates=(start,))
            with self.subTest(kind=kind, start=start), self.assertRaises(ValueError):
                ra.validate(self.file, kind, start, end, now=now)
        make_csv(self.file, SUMMARY, dates=('2024-02-29',))
        self.assertEqual(ra.validate(self.file, 'summarized', '2024-02-29', '2025-02-28', now=now)['rows'], 1)
        with self.assertRaises(ValueError):
            ra.validate(self.file, 'summarized', '2024-02-29', '2025-03-01', now=now)
        make_csv(self.file, dates=('2026-02-15',))
        self.assertEqual(ra.validate(self.file, 'detailed', '2026-01-16', '2026-02-15', now=now)['rows'], 1)
        with self.assertRaises(ValueError):
            ra.validate(self.file, 'detailed', '2026-01-16', '2026-02-16', now=now)

    def test_private_permissions_no_mutation(self):
        original = self.file.read_bytes()
        self.file.chmod(0o644)
        with self.assertRaises(ValueError):
            ra.fingerprint(self.file)
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o644)
        self.file.chmod(0o600)
        self.root.chmod(0o755)
        with self.assertRaises(ValueError):
            ra.fingerprint(self.file)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o755)
        self.root.chmod(0o700)
        self.assertEqual(ra.fingerprint(self.file)['bytes'], len(original))
        self.assertEqual(self.file.read_bytes(), original)

    def test_real_git_managed_paths_rejected(self):
        for bare in (False, True):
            repo = self.root / ('bare' if bare else 'worktree')
            subprocess.run(['git', 'init', *(['--bare'] if bare else []), str(repo)], check=True, capture_output=True)
            repo.chmod(0o700)
            if not bare:
                (repo / '.gitignore').write_text('*.csv\n')
            report = make_csv(repo / 'report.csv')
            with self.subTest(bare=bare), self.assertRaises(ValueError):
                ra.fingerprint(report)
        fake = self.root / 'fake'
        fake.mkdir(mode=0o700)
        (fake / '.git').mkdir()
        with self.assertRaises(ValueError):
            ra.private_path(fake / 'report.csv')

    def test_git_discovery_fail_closed_and_scrubbed(self):
        for failure in (FileNotFoundError(), PermissionError(), subprocess.TimeoutExpired('git', 5)):
            with patch.object(ra.subprocess, 'run', side_effect=failure), self.assertRaises(ValueError):
                ra.private_path(self.file)
        for code, stderr in ((1, b''), (128, b'fatal: dubious ownership SECRET'), (0, b'')):
            result = subprocess.CompletedProcess([], code, b'', stderr)
            with patch.object(ra.subprocess, 'run', return_value=result), self.assertRaises(ValueError):
                ra.private_path(self.file)
        outside = subprocess.CompletedProcess([], 128, b'', b'fatal: not a git repository (or any of the parent directories): .git\n')
        with patch.dict(os.environ, {'GIT_DIR': '/SECRET', 'GIT_CONFIG_COUNT': '1'}):
            with patch.object(ra.subprocess, 'run', return_value=outside) as run:
                self.assertEqual(ra.private_path(self.file), self.file)
                kwargs = run.call_args.kwargs
                self.assertNotIn('GIT_DIR', kwargs['env'])
                self.assertNotIn('GIT_CONFIG_COUNT', kwargs['env'])
                self.assertEqual(kwargs['env']['GIT_CONFIG_GLOBAL'], os.devnull)
                self.assertEqual(kwargs['env']['GIT_CONFIG_NOSYSTEM'], '1')
                self.assertIn('--absolute-git-dir', run.call_args.args[0])

    def test_system_alias_and_artifact_links(self):
        if sys.platform == 'darwin' and str(self.file).startswith('/private/var/'):
            alias = Path(str(self.file).replace('/private/var/', '/var/', 1))
            self.assertEqual(ra.private_path(alias), self.file)
            self.assertEqual(ra.fingerprint(alias), ra.fingerprint(self.file))
        link = self.root / 'linked-directory'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            ra.fingerprint(link / self.file.name)

    def test_cli_sanitized_error(self):
        from contextlib import redirect_stderr
        output = io.StringIO()
        with redirect_stderr(output):
            code = ra.main([str(self.root / 'SECRET.csv'), '--kind', 'detailed', '--start-date', '2026-01-01', '--end-date', '2026-01-31'])
        self.assertEqual(code, 2)
        self.assertNotIn('SECRET', output.getvalue())


if __name__ == '__main__':
    unittest.main()
