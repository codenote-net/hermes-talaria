import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_state as rs
from test_report_artifact import make_csv


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'private'
        self.file = make_csv(Path(self.temp.name).resolve() / 'report.csv')
        self.readback = Path(self.temp.name).resolve() / 'readback.csv'
        self.readback.write_bytes(self.file.read_bytes())
        self.file.chmod(0o600)
        self.readback.chmod(0o600)
        self.payload = dict(run_id='example-run', enterprise='example-enterprise', page='usage', github_account='synthetic-account', kind='detailed', start_date='2026-01-01', end_date='2026-01-31', destination_id='example-destination', upload_mode='archive', required_ids=['first', 'second'])
        rs.init(self.root, self.payload)

    def download(self):
        return rs.advance(self.root, 'downloaded', {'user_link': True, 'notification_verified': False, 'source_correspondence': True})

    def artifacts(self):
        self.download()
        for key in self.payload['required_ids']:
            rs.register_artifact(self.root, key, self.file)
        rs.advance(self.root, 'validated')

    def upload(self):
        self.artifacts()
        for key in self.payload['required_ids']:
            rs.record_destination(self.root, key, 'example-destination', 'https://example.invalid/files/' + key, True)
        rs.advance(self.root, 'uploaded')

    def attempt(self, root=None):
        return rs.advance(root or self.root, 'request_attempted', {'request_attempted_at': '2026-01-01T12:00:00+00:00'})

    def test_account_reservation_survives_calls_and_enterprises(self):
        other = self.root.with_name('other')
        rs.init(other, dict(self.payload, run_id='other', enterprise='other-enterprise'))
        self.attempt()
        with self.assertRaises(ValueError):
            self.attempt(other)
        self.assertEqual(rs.show(self.root)['state'], 'request_attempted')
        with self.assertRaises(ValueError):
            rs.advance(self.root, 'requested', {'request_observed': True})
        self.assertEqual(rs.show(self.root)['state'], 'request_attempted')
        rs.advance(self.root, 'requested', {'request_observed': True, 'request_accepted_at': '2026-01-01T12:01:00+00:00'})
        rs.advance(self.root, 'downloaded', {'source_correspondence': True})
        self.attempt(other)

    def test_duplicate_payload_cli_cannot_share_reservation(self):
        import subprocess
        accounts = self.root.parent / '.accounts'
        other = self.root.with_name('duplicate')
        rs.init(other, self.payload, account_lock_dir=accounts)
        self.attempt()
        self.assertEqual(rs.init(self.root, self.payload, accounts)['state'], 'request_attempted')
        result = subprocess.run([sys.executable, str(rs.__file__), '--state-dir', str(other),
                                 'advance', 'request_attempted', '--evidence',
                                 '{"request_attempted_at":"2026-01-01T12:00:00+00:00"}'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(rs.show(other)['state'], 'prepared')

    def test_cloned_pending_ledger_and_malformed_owner_fail_closed(self):
        import shutil
        self.attempt()
        clone = self.root.with_name('clone')
        shutil.copytree(self.root, clone)
        with self.assertRaises(ValueError):
            rs.show(clone)
        reservation = next((self.root.parent / '.accounts').glob('*.json'))
        reservation.write_text(json.dumps({'run_key': rs.show(self.root)['run_key']}))
        with self.assertRaises(ValueError):
            rs.show(self.root)

    def test_upload_mode_is_required_and_frozen(self):
        missing = dict(self.payload)
        missing.pop('upload_mode', None)
        with self.assertRaises(ValueError):
            rs.init(self.root.with_name('missing-mode'), missing)
        for mode in ['replace', 'unknown', True]:
            with self.assertRaises(ValueError):
                rs.init(self.root, dict(self.payload, upload_mode=mode))

    def test_manual_resolution_requires_explicit_evidence(self):
        self.attempt()
        with self.assertRaises(ValueError):
            rs.advance(self.root, 'cancelled')
        rs.advance(self.root, 'cancelled', {'request_cancelled_observed': True, 'request_resolved_at': '2026-01-01T12:02:00+00:00'})
        other = self.root.with_name('other')
        rs.init(other, dict(self.payload, run_id='other'))
        self.attempt(other)

    def test_page_symbols_and_pairing(self):
        for page, kind in [('https://github.com/settings?tab=usage', 'detailed'), ('usage', 'ai_usage'), ('ai_usage', 'detailed')]:
            with self.assertRaises(ValueError):
                rs.init(self.root.with_name('bad'), dict(self.payload, page=page, kind=kind))
        rs.init(self.root.with_name('ai'), dict(self.payload, page='ai_usage', kind='ai_usage'))

    def test_stable_remote_target_and_cli_privacy(self):
        import subprocess
        self.artifacts()
        target = 'synthetic-s3:billing/2026/report.csv'
        rs.record_destination(self.root, 'first', 'example-destination', target, True)
        self.assertEqual(rs.read_private(self.root)['destinations']['first']['url'], target)
        for bad in ['remote:key?token=x', 'remote:../key', 's3://bucket/key', 'remote:key --token=x', 'remote:key%3Fsignature=x']:
            with self.assertRaises(ValueError):
                rs.record_destination(self.root, 'second', 'example-destination', bad, True)
        result = subprocess.run([sys.executable, str(rs.__file__), '--state-dir', str(self.root), 'show'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for secret in [*self.payload['required_ids'], self.payload['enterprise'], self.payload['github_account'], self.payload['destination_id'], self.payload['run_id'], target, str(self.file), 'filenames', 'payload']:
            self.assertNotIn(secret, result.stdout)
        self.assertEqual(json.loads(result.stdout)['required_count'], 2)

    def test_verified_tamper_source_and_direct_proof(self):
        self.upload()
        for key in self.payload['required_ids']:
            rs.record_readback(self.root, key, self.readback)
        rs.advance(self.root, 'verified')
        original = (self.root / 'state.json').read_text()
        for key in ['source_correspondence', 'user_link', 'notification_verified']:
            data = json.loads(original)
            data['evidence'].pop(key)
            (self.root / 'state.json').write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                rs.show(self.root)

    def test_pending_does_not_bypass_direct_or_attempt_proof(self):
        rs.advance(self.root, 'blocked_by_pending', {'pending_ids': ['first']})
        with self.assertRaises(ValueError):
            rs.advance(self.root, 'downloaded', {'source_correspondence': True, 'pending_ids': []})
        with self.assertRaises(ValueError):
            rs.advance(self.root, 'requested', {'request_observed': True, 'request_accepted_at': '2026-01-01T12:01:00+00:00', 'pending_ids': []})

    def test_timezone_attempt_and_blocked_reservation(self):
        for timestamp in ['2026-01-01T12:00:00', '2026-01-01', True]:
            with self.assertRaises(ValueError):
                rs.advance(self.root, 'request_attempted', {'request_attempted_at': timestamp})
        self.attempt()
        rs.advance(self.root, 'blocked_by_pending', {'pending_ids': ['first']})
        other = self.root.with_name('other')
        rs.init(other, dict(self.payload, run_id='other'))
        with self.assertRaises(ValueError):
            self.attempt(other)
        with self.assertRaises(ValueError):
            rs.advance(self.root, 'request_attempted', {'pending_ids': [], 'request_attempted_at': '2026-01-01T12:00:00+00:00'})
        with self.assertRaises(ValueError):
            rs.advance(self.root, 'requested', {'request_observed': True, 'request_accepted_at': '2026-01-01T12:01:00+00:00'})
        rs.advance(self.root, 'requested', {'pending_ids': [], 'request_observed': True, 'request_accepted_at': '2026-01-01T12:01:00+00:00'})
        self.assertTrue(rs.read_private(self.root)['evidence']['request_observed'])

    def test_concurrent_cli_reservation_has_only_one_winner(self):
        import subprocess
        other = self.root.with_name('other')
        rs.init(other, dict(self.payload, run_id='other', enterprise='other'))
        commands = [[sys.executable, str(rs.__file__), '--state-dir', str(root), 'advance', 'request_attempted', '--evidence', '{"request_attempted_at":"2026-01-01T12:00:00+00:00"}'] for root in [self.root, other]]
        processes = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for cmd in commands]
        outputs = [proc.communicate(timeout=15) for proc in processes]
        self.assertEqual(sorted(proc.returncode for proc in processes), [0, 2], outputs)
        reservations = list((self.root.parent / '.accounts').glob('*.json'))
        self.assertEqual(len(reservations), 1)
        self.assertEqual(reservations[0].stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.payload['github_account'], reservations[0].name)

    def test_attempted_acceptance_tamper_fails_closed(self):
        self.attempt()
        rs.advance(self.root, 'requested', {'request_observed': True, 'request_accepted_at': '2026-01-01T12:01:00+00:00'})
        rs.advance(self.root, 'downloaded', {'source_correspondence': True})
        for key in self.payload['required_ids']:
            rs.register_artifact(self.root, key, self.file)
        rs.advance(self.root, 'validated')
        for key in self.payload['required_ids']:
            rs.record_destination(self.root, key, 'example-destination', 'synthetic-s3:reports/' + key + '.csv', True)
            rs.record_readback(self.root, key, self.readback)
        rs.advance(self.root, 'uploaded')
        rs.advance(self.root, 'verified')
        original = (self.root / 'state.json').read_text()
        for key in ['request_attempted_at', 'request_observed', 'request_accepted_at']:
            data = json.loads(original)
            data['evidence'].pop(key)
            (self.root / 'state.json').write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                rs.show(self.root)

    def test_resume_and_permissions(self):
        before = rs.show(self.root)
        self.assertEqual(rs.init(self.root, copy.deepcopy(self.payload)), before)
        self.assertEqual(before['filenames']['first'], 'usage-' + before['run_key'][:12] + '-first.csv')
        self.assertEqual(os.stat(self.root).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(self.root / 'state.json').st_mode & 0o777, 0o600)
        changed = dict(self.payload, end_date='2026-02-01')
        with self.assertRaises(ValueError):
            rs.init(self.root, changed)
        self.assertEqual(rs.show(self.root), before)

    def test_verify_all_files_evidence(self):
        self.upload()
        rs.record_readback(self.root, 'first', self.readback)
        with self.assertRaises(ValueError):
            rs.advance(self.root, 'verified')
        rs.record_readback(self.root, 'second', self.readback)
        self.assertEqual(rs.advance(self.root, 'verified')['state'], 'verified')

    def test_false_bypass_unknown_and_direct_evidence(self):
        for state, evidence in [('verified', {'verified': True}), ('downloaded', {}), ('nonsense', {})]:
            with self.assertRaises(ValueError):
                rs.advance(self.root, state, evidence)
        with self.assertRaises(ValueError):
            rs.init(self.root, dict(self.payload, unknown='ignored'))
        with self.assertRaises(ValueError):
            rs.register_artifact(self.root, 'unknown', self.file)
        with self.assertRaises(ValueError):
            rs.advance(self.root, 'requested', {'signed_url': 'https://example.invalid/?token=example'})
        self.assertEqual(self.download()['evidence']['notification_verified'], False)

    def test_pending_and_unverified(self):
        rs.advance(self.root, 'blocked_by_pending', {'pending_ids': ['first']})
        with self.assertRaises(ValueError):
            rs.advance(self.root, 'verified')
        rs.advance(self.root, 'downloaded', {'source_correspondence': True, 'pending_ids': [], 'user_link': True, 'notification_verified': False})
        for key in self.payload['required_ids']:
            rs.register_artifact(self.root, key, self.file)
        rs.advance(self.root, 'validated')
        for key in self.payload['required_ids']:
            rs.record_destination(self.root, key, 'example-destination', 'https://example.invalid/files/' + key, True)
        self.assertEqual(rs.advance(self.root, 'uploaded_unverified')['state'], 'uploaded_unverified')

    def test_mutation_mismatch_and_destination_confirmation(self):
        self.artifacts()
        for identity, url, confirm in [('wrong', 'https://example.invalid/file', True), ('example-destination', 'https://example.invalid/file?signature=example', True), ('example-destination', 'https://example.invalid/file', False)]:
            with self.assertRaises(ValueError):
                rs.record_destination(self.root, 'first', identity, url, confirm)
        rs.record_destination(self.root, 'first', 'example-destination', 'https://example.invalid/file', True)
        mismatch = make_csv(Path(self.temp.name).resolve() / 'different.csv', dates=('2026-01-03',))
        mismatch.chmod(0o600)
        with self.assertRaises(ValueError):
            rs.record_readback(self.root, 'first', mismatch)
        self.file.write_bytes(self.file.read_bytes() + b'\n')
        with self.assertRaises(ValueError):
            rs.record_readback(self.root, 'first', self.file)

    def test_lock_and_interrupted_atomic_write(self):
        before = (self.root / 'state.json').read_bytes()
        (self.root / '.lock').write_text('interrupted operator')
        with self.assertRaises(ValueError):
            rs.advance(self.root, 'requested')
        self.assertTrue((self.root / '.lock').exists())
        (self.root / '.lock').unlink()
        with patch.object(rs.os, 'replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                self.attempt()
        self.assertEqual((self.root / 'state.json').read_bytes(), before)
        self.assertFalse((self.root / '.lock').exists())

    def test_corrupt_state_and_symlink(self):
        data = json.loads((self.root / 'state.json').read_text())
        data['state'] = 'unknown'
        (self.root / 'state.json').write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            rs.show(self.root)
        link = Path(self.temp.name).resolve() / 'link'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            rs.init(link, self.payload)

    def test_source_disappears_after_registration(self):
        self.upload()
        self.file.rename(self.file.with_suffix('.moved'))
        with self.assertRaises((ValueError, OSError)):
            rs.record_readback(self.root, 'first', self.file.with_suffix('.moved'))


    def test_original_is_not_readback_and_hardlinks_fail(self):
        self.upload()
        with self.assertRaises(ValueError):
            rs.record_readback(self.root, 'first', self.file)
        hardlink = self.file.with_name('hardlink.csv')
        os.link(self.file, hardlink)
        with self.assertRaises(ValueError):
            rs.record_readback(self.root, 'first', hardlink)

    def test_pending_files_and_changed_readback_block_verification(self):
        self.upload()
        for key in self.payload['required_ids']:
            rs.record_readback(self.root, key, self.readback)
        partial = self.file.with_suffix('.crdownload')
        partial.write_bytes(b'pending')
        with self.assertRaises(ValueError):
            rs.advance(self.root, 'verified')
        partial.unlink()
        self.readback.write_bytes(self.readback.read_bytes() + b'\n')
        with self.assertRaises(ValueError):
            rs.advance(self.root, 'verified')

    def test_ledger_unknown_metadata_and_malformed_state(self):
        self.artifacts()
        original = (self.root / 'state.json').read_text()
        for mutate in (lambda d: d.update(state=[]), lambda d: d['artifacts']['first']['metadata'].update(csv_body='not allowed')):
            data = json.loads(original)
            mutate(data)
            (self.root / 'state.json').write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                rs.show(self.root)

    def test_cli_end_to_end_and_sanitized_output(self):
        import subprocess
        assert rs.__file__ is not None
        script = Path(rs.__file__)
        def cli(*args):
            result = subprocess.run([sys.executable, str(script), '--state-dir', str(self.root), *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(str(self.file), result.stdout)
            self.assertNotIn(str(self.readback), result.stdout)
            return json.loads(result.stdout)
        init_args = ['init']
        for key, value in self.payload.items():
            if key != 'required_ids':
                assert isinstance(value, str)
                init_args.extend(['--' + key.replace('_', '-'), value])
        for key in self.payload['required_ids']:
            init_args.extend(['--required-id', key])
        self.assertEqual(cli(*init_args)['state'], 'prepared')
        cli('advance', 'downloaded', '--evidence', '{"user_link":true,"notification_verified":false,"source_correspondence":true}')
        for key in self.payload['required_ids']:
            cli('register-artifact', key, str(self.file))
        cli('advance', 'validated')
        for key in self.payload['required_ids']:
            cli('record-destination', key, '--identity', 'example-destination', '--url', 'https://example.invalid/files/' + key, '--confirmed')
        cli('advance', 'uploaded')
        for key in self.payload['required_ids']:
            cli('record-readback', key, str(self.readback))
        cli('advance', 'verified')
        self.assertEqual(cli('show')['state'], 'verified')

    def test_generated_names_distinguish_runs_and_do_not_change_on_resume(self):
        before = rs.show(self.root)
        other = rs.init(self.root.with_name('other-private'), dict(self.payload, run_id='other-example-run'))
        self.assertNotEqual(before['filenames'], other['filenames'])
        self.download()
        resumed = rs.init(self.root, self.payload)
        self.assertEqual(resumed['filenames'], before['filenames'])

    def test_readback_directory_pending_is_a_gate(self):
        self.upload()
        download_dir = self.root.with_name('readback-dir')
        download_dir.mkdir(mode=0o700)
        readback = download_dir / 'readback.csv'
        readback.write_bytes(self.file.read_bytes())
        readback.chmod(0o600)
        for key in self.payload['required_ids']:
            rs.record_readback(self.root, key, readback)
        (download_dir / 'unfinished.part').write_bytes(b'pending')
        with self.assertRaises(ValueError):
            rs.advance(self.root, 'verified')

    def test_private_permissions_and_git_root_fail_closed(self):
        self.root.chmod(0o755)
        with self.assertRaises(ValueError):
            rs.show(self.root)
        self.root.chmod(0o700)
        (self.root / 'state.json').chmod(0o644)
        with self.assertRaises(ValueError):
            rs.show(self.root)
        repo = self.root.with_name('example-repo')
        repo.mkdir()
        (repo / '.git').mkdir()
        with self.assertRaises(ValueError):
            rs.init(repo / 'private-ledger', self.payload)


if __name__ == '__main__':
    unittest.main()
