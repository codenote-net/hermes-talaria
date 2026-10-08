"""Hermetic rclone contract tests; no cloud/authentication is exercised."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import upload_report as upload
import run_state as rs

CSV = b'date,product,sku,quantity,gross_amount,net_amount,organization,repository\n2026-01-01,Actions,example,1,1,1,example,example\n'


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.source = self.root / 'original.csv'
        self.source.write_bytes(CSV)
        self.source.chmod(0o600)
        self.config = {'version': 1, 'github': {'deployment': 'enterprise_cloud', 'enterprise': 'example', 'pages': {'usage': {'url': 'https://github.com/enterprises/example/settings/billing/usage'}}}, 'destination': {'provider': 'dropbox', 'transport': 'rclone', 'remote': 'example', 'folder_path': 'reports'}, 'local': {'output_dir': str(self.root)}}
        self.items = []
        self.calls = []
        self.remote_type = 'dropbox'
        self.stat = {'Path': 'reports', 'Name': 'reports', 'IsDir': True, 'ID': 'example-folder'}
        self.download = CSV
        self.error = None
        self.freeze()

    def freeze(self):
        self.state = self.root / ('ledger-' + str(len(list(self.root.glob('ledger-*')))))
        payload = dict(run_id='synthetic', github_account='synthetic', enterprise='example',
                       page='usage', kind='summarized', start_date='2026-01-01', end_date='2026-01-01',
                       upload_mode=self.config.get('upload', {}).get('mode', 'archive'),
                       destination_id=upload.destination_identity(self.config['destination']), required_ids=['summary'])
        data = rs.init(self.state, payload)
        self.name = data['filenames']['summary']
        rs.advance(self.state, 'downloaded', {'user_link': True, 'notification_verified': False, 'source_correspondence': True})
        rs.register_artifact(self.state, 'summary', self.source)
        rs.advance(self.state, 'validated')

    def tearDown(self):
        self.temp.cleanup()

    def fake(self, argv):
        self.calls.append(argv)
        command = argv[0]
        if command == 'listremotes':
            return 'example: ' + self.remote_type + '\n'
        if command == 'lsjson':
            if '--stat' in argv:
                return json.dumps(self.stat)
            if argv[1] in {'example:', 'example:example-bucket'} and self.config['destination']['provider'] not in {'google_drive', 'box'}:
                return json.dumps([{'Name': 'reports', 'Path': 'reports', 'IsDir': True}])
            return json.dumps(self.items)
        if command == 'copyto':
            if argv[1] == str(self.source):
                if self.error:
                    raise self.error
                if not self.items:
                    self.items = [self.item()]
            else:
                Path(argv[2]).write_bytes(self.download)
                Path(argv[2]).chmod(0o600)
            return ''
        raise AssertionError(argv)

    def item(self, **kw):
        return dict({'Name': self.name, 'Path': self.name, 'IsDir': False, 'ID': 'example-object', 'Size': len(CSV)}, **kw)

    def transfer(self, **kw):
        options = dict(config=self.config, file=self.source, filename=self.name, kind='summarized', start_date='2026-01-01', end_date='2026-01-01', confirm_destination=upload.destination_identity(self.config['destination']), readback_dir=self.root, state_dir=self.state)
        options.update(kw)
        with patch.object(upload, '_run', side_effect=self.fake):
            return upload.transfer(**options)

    def writes(self):
        return [a for a in self.calls if a[0] == 'copyto' and a[1] == str(self.source)]

    def test_upload_and_independent_readback(self):
        result = self.transfer()
        self.assertTrue(result['verified'])
        self.assertEqual(result['action'], 'uploaded')
        self.assertEqual(len(self.writes()), 1)
        self.assertIn('--immutable', self.writes()[0])
        self.assertEqual(self.source.read_bytes(), CSV)
        self.assertNotIn('example', json.dumps(result))

    def test_changed_archive_mode_rejected_before_remote_calls(self):
        self.config['upload'] = {'mode': 'replace'}
        self.items = [self.item()]
        self.download = CSV.replace(b'Actions', b'Example')
        with self.assertRaises(ValueError):
            self.transfer(replace_target='example:reports/' + self.name)
        self.assertEqual(self.calls, [])

    def test_frozen_identity_original_filename_period_and_state_gate(self):
        alternate = self.root / 'alternate.csv'
        alternate.write_bytes(CSV)
        alternate.chmod(0o600)
        for changes in [{'filename': 'other.csv'}, {'file': alternate}, {'end_date': '2026-01-02'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.transfer(**changes)
            self.assertEqual(self.calls, [])
        self.config['destination']['folder_path'] = 'other'
        with self.assertRaises(ValueError):
            self.transfer()
        self.assertEqual(self.calls, [])
        self.config['destination']['folder_path'] = 'reports'
        rs.advance(self.state, 'blocked_by_pending', {'pending_ids': ['summary']})
        with self.assertRaises(ValueError):
            self.transfer()
        self.assertEqual(self.calls, [])

    def test_success_leaves_ledger_unchanged(self):
        before = (self.state / 'state.json').read_bytes()
        self.transfer()
        self.assertEqual((self.state / 'state.json').read_bytes(), before)

    def test_equal_existing_skips_after_readback(self):
        self.items = [self.item()]
        self.assertEqual(self.transfer()['action'], 'skipped')
        self.assertEqual(self.writes(), [])

    def test_same_length_different_bytes_archive_never_overwrites(self):
        self.items = [self.item()]
        self.download = CSV.replace(b'Actions', b'Example')
        with self.assertRaises(ValueError): self.transfer()
        self.assertEqual(self.writes(), [])

    def test_wrong_backend_missing_folder_directory_collision_duplicates(self):
        cases = ['backend', 'folder', 'directory', 'duplicates']
        for case in cases:
            with self.subTest(case=case):
                self.remote_type = 's3' if case == 'backend' else 'dropbox'
                self.stat['IsDir'] = case != 'folder'
                self.items = [self.item(IsDir=True)] if case == 'directory' else [self.item(), self.item(ID='other')] if case == 'duplicates' else []
                self.calls = []
                with self.assertRaises(ValueError): self.transfer()
                self.assertFalse(self.writes())

    def test_strict_configuration_and_confirmation_before_cli(self):
        for changes in [{'folder_path': '../escape'}, {'folder_path': ''}, {'remote': '--bad'}, {'token': 'secret'}]:
            old = copy.deepcopy(self.config)
            self.config['destination'].update(changes)
            with self.assertRaises(ValueError): self.transfer()
            self.assertEqual(self.calls, [])
            self.config = old
        with self.assertRaises(ValueError): self.transfer(confirm_destination='wrong')
        self.assertEqual(self.calls, [])

    def test_browser_rejected(self):
        self.config['destination'] = {'provider': 'google_drive', 'folder_id': 'example-folder', 'folder_url': 'https://drive.google.com/drive/folders/example-folder'}
        with self.assertRaises(ValueError): self.transfer()
        self.assertEqual(self.calls, [])

    def test_provider_matrix_and_root_flags(self):
        for provider, backend in upload.BACKENDS.items():
            with self.subTest(provider=provider):
                self.remote_type = backend
                d = {'provider': provider, 'transport': 'rclone', 'remote': 'example'}
                if provider in {'google_drive', 'box'}:
                    d['folder_id'] = 'example-folder'
                elif provider in {'s3', 'gcs'}:
                    d.update(bucket='example-bucket', prefix='reports')
                else:
                    d['folder_path'] = 'reports'
                if provider == 'google_drive': d['shared_drive_id'] = 'example-shared'
                self.config['destination'] = d
                self.freeze()
                self.items = []; self.calls = []
                self.assertTrue(self.transfer()['verified'])
                if provider == 'google_drive':
                    self.assertIn('--drive-root-folder-id', self.writes()[0])
                    self.assertIn('--drive-team-drive', self.writes()[0])
                if provider == 'box': self.assertIn('--box-root-folder-id', self.writes()[0])

    def test_synthetic_missing_folder(self):
        real_fake = self.fake
        def missing(argv):
            if argv[:2] == ['lsjson', 'example:']: return '[]'
            return real_fake(argv)
        with patch.object(upload, '_run', side_effect=missing), self.assertRaises(ValueError):
            upload.transfer(self.config, self.source, self.name, 'summarized', '2026-01-01', '2026-01-01', upload.destination_identity(self.config['destination']), self.root, self.state)
        self.assertFalse(self.writes())

    def test_replacement_download_error_never_authorizes_mutation(self):
        self.config['upload'] = {'mode': 'replace'}
        self.freeze()
        self.items = [self.item()]
        real_fake = self.fake
        def broken(argv):
            if argv[0] == 'copyto': raise upload.TransferError('Download failed.')
            return real_fake(argv)
        with patch.object(upload, '_run', side_effect=broken), self.assertRaises(ValueError):
            upload.transfer(self.config, self.source, self.name, 'summarized', '2026-01-01', '2026-01-01', upload.destination_identity(self.config['destination']), self.root, self.state, 'example:reports/' + self.name)
        self.assertFalse(self.writes())

    def test_frozen_replace_with_exact_target_can_replace(self):
        self.config['upload'] = {'mode': 'replace'}
        self.freeze()
        self.items = [self.item()]
        self.download = CSV.replace(b'Actions', b'Example')
        original_fake = self.fake
        def replace(argv):
            result = original_fake(argv)
            if argv[0] == 'copyto' and argv[1] == str(self.source):
                self.download = CSV
            return result
        with patch.object(upload, '_run', side_effect=replace):
            result = upload.transfer(self.config, self.source, self.name, 'summarized',
                                     '2026-01-01', '2026-01-01',
                                     upload.destination_identity(self.config['destination']),
                                     self.root, self.state, 'example:reports/' + self.name)
        self.assertEqual(result['action'], 'replaced')
        self.assertTrue(result['verified'])
        self.assertEqual(len(self.writes()), 1)
        self.assertNotIn('--immutable', self.writes()[0])

    def test_wrong_replace_target_and_archive_race(self):
        self.config['upload'] = {'mode': 'replace'}
        self.freeze()
        self.items = [self.item()]
        self.download = CSV.replace(b'Actions', b'Example')
        with self.assertRaises(ValueError): self.transfer(replace_target='wrong')
        self.assertFalse(self.writes())
        self.config['upload'] = {'mode': 'archive'}
        self.freeze()
        self.items = []
        self.error = ValueError('Remote operation failed; mutation may be unverified.')
        with self.assertRaises(ValueError): self.transfer()
        self.assertEqual(len(self.writes()), 1)
        self.assertIn('--immutable', self.writes()[0])

    def test_readback_mismatch(self):
        self.download = CSV.replace(b'Actions', b'Example')
        with self.assertRaises(ValueError): self.transfer()
        self.assertEqual(len(self.writes()), 1)

    def test_filename_git_and_symlink_rejected(self):
        for name in ['../bad.csv', '--bad.csv', 'a/b.csv', 'a\\b.csv', 'bad\n.csv', '.csv']:
            with self.subTest(name=name), self.assertRaises(ValueError): self.transfer(filename=name)
        link = self.root / 'link.csv'; link.symlink_to(self.source)
        with self.assertRaises(ValueError): self.transfer(file=link)
        gitdir = self.root / 'repo'; gitdir.mkdir(); (gitdir / '.git').mkdir()
        f = gitdir / 'original.csv'; f.write_bytes(CSV)
        with self.assertRaises(ValueError): self.transfer(file=f)
        self.assertEqual(self.calls, [])

    def test_timeout_no_retry_or_stderr_leak(self):
        error = subprocess.TimeoutExpired(['rclone', 'private'], 30, stderr=b'SECRET https://example.test/private')
        with patch.object(upload.subprocess, 'run', side_effect=error) as run:
            with self.assertRaises(ValueError) as caught: upload._run(['copyto', 'private', 'private'])
            self.assertEqual(run.call_count, 1)
        self.assertNotIn('SECRET', str(caught.exception))
        self.assertNotIn('private', str(caught.exception))

    def test_sanitized_environment_and_failure(self):
        result = subprocess.CompletedProcess([], 1, 'SECRET', 'SECRET https://example.test/private')
        with patch.dict('os.environ', {'RCLONE_CONFIG_EXAMPLE_TYPE': 's3', 'RCLONE_LOG_FILE': '/private/log'}), patch.object(upload.subprocess, 'run', return_value=result) as run:
            with self.assertRaises(ValueError) as caught: upload._run(['listremotes', '--long'])
            self.assertFalse(any(k.startswith('RCLONE_') for k in run.call_args.kwargs['env']))
            self.assertFalse(run.call_args.kwargs['shell'])
        self.assertNotIn('SECRET', str(caught.exception))


if __name__ == '__main__': unittest.main()
