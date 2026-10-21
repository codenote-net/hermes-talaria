"""Offline local-only contracts; no browser or remote service is exercised."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_state as rs
import upload_report as upload
from validate_config import ConfigError, validate_config
from test_organization import config, payload
from test_report_artifact import make_csv, SUMMARY

ROOT = Path(__file__).resolve().parents[1]


def local_config(deployment='organization'):
    c = config(deployment)
    del c['destination']
    c['mode'] = 'local_only'
    return c


def local_payload(deployment='organization'):
    p = payload(deployment)
    del p['destination_id'], p['upload_mode']
    p['mode'] = 'local_only'
    return p


class LocalOnlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.root.chmod(0o700)
        self.state = self.root / 'run'
        self.file = make_csv(self.root / 'original.csv', SUMMARY)

    def prepare(self, deployment='organization'):
        return rs.init(self.state, local_payload(deployment))

    def validate(self):
        rs.advance(self.state, 'downloaded', {'user_link': True, 'notification_verified': False, 'source_correspondence': True})
        rs.register_artifact(self.state, 'summary', self.file)
        return rs.advance(self.state, 'validated')

    def test_config_explicit_local_and_cloud_default(self):
        for deployment in ('enterprise_cloud', 'organization'):
            c = local_config(deployment)
            before = copy.deepcopy(c)
            result = validate_config(c)
            self.assertEqual(c, before)
            self.assertEqual(result['mode'], 'local_only')
            self.assertNotIn('destination', result)
            self.assertNotIn('upload', result)
            self.assertEqual(validate_config(result), result)
            del c['mode']
            with self.assertRaises(ConfigError): validate_config(c)
        self.assertEqual(validate_config(config())['mode'], 'cloud')
        for mode in (None, True, '', 'local', [], {}):
            with self.subTest(mode=mode), self.assertRaises(ConfigError):
                validate_config(dict(local_config(), mode=mode))

    def test_local_rejects_cloud_keys_even_empty_or_null(self):
        for key in ('destination', 'upload'):
            for value in (None, {}, {'mode': 'archive'}):
                with self.subTest(key=key, value=value), self.assertRaises(ConfigError):
                    validate_config(dict(local_config(), **{key: value}))
        for key in ('destination_id', 'upload_mode'):
            for value in (None, '', 'archive'):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    rs.init(self.state, dict(local_payload(), **{key: value}))
        for mode in ('cloud', None, True):
            with self.assertRaises(ValueError): rs.init(self.state, dict(local_payload(), mode=mode))
        p = local_payload('enterprise_cloud'); del p['deployment']
        with self.assertRaises(ValueError): rs.init(self.state, p)

    def test_completion_is_local_and_revalidates_on_read_and_resume(self):
        p = local_payload()
        initial = self.prepare()
        self.assertEqual(initial['version'], 3)
        self.assertEqual(initial['payload'], p)
        self.validate()
        result = rs.advance(self.state, 'local_validated')
        self.assertEqual(result['state'], 'local_validated')
        self.assertEqual(result['destinations'], {})
        summary = rs._summary(result)
        self.assertEqual(summary['mode'], 'local_only')
        self.assertIs(summary['cloud_verified'], False)
        self.assertIs(summary['mail_verified'], False)
        before = (self.state / 'state.json').read_bytes()
        self.assertEqual(rs.init(self.state, p), result)
        self.assertEqual((self.state / 'state.json').read_bytes(), before)
        self.file.write_bytes(self.file.read_bytes() + b'\n')
        for call in (lambda: rs.show(self.state), lambda: rs.init(self.state, p)):
            with self.assertRaises(ValueError): call()

    def test_local_gates_do_not_relax_validation(self):
        self.prepare()
        with self.assertRaises(ValueError): rs.advance(self.state, 'local_validated')
        with self.assertRaises(ValueError): rs.advance(self.state, 'downloaded')
        rs.advance(self.state, 'downloaded', {'user_link': True, 'notification_verified': False, 'source_correspondence': True})
        with self.assertRaises(ValueError): rs.advance(self.state, 'validated')
        make_csv(self.file, SUMMARY, dates=())
        with self.assertRaises(ValueError): rs.register_artifact(self.state, 'summary', self.file)
        make_csv(self.file, SUMMARY)
        rs.register_artifact(self.state, 'summary', self.file)
        partial = self.root / 'partial.crdownload'; partial.touch()
        with self.assertRaises(ValueError): rs.advance(self.state, 'validated')
        partial.unlink()
        rs.advance(self.state, 'validated')
        for state in ('uploaded', 'uploaded_unverified', 'verified'):
            with self.assertRaises(ValueError): rs.advance(self.state, state)
        with self.assertRaises(ValueError): rs.record_destination(self.state, 'summary', 'forbidden', 'https://example.test/file', True)
        with self.assertRaises(ValueError): rs.record_readback(self.state, 'summary', self.file)
        self.assertEqual(rs.show(self.state)['state'], 'validated')

    def test_request_reservation_shared_with_cloud_and_released_on_download(self):
        self.prepare()
        cloud = self.root / 'cloud'
        rs.init(cloud, payload('enterprise_cloud'))
        attempt = {'request_attempted_at': '2026-01-01T12:00:00+00:00'}
        rs.advance(self.state, 'request_attempted', attempt)
        with self.assertRaises(ValueError): rs.advance(cloud, 'request_attempted', attempt)
        rs.advance(self.state, 'requested', {'request_observed': True, 'request_accepted_at': '2026-01-01T12:01:00+00:00'})
        rs.advance(self.state, 'waiting_for_link')
        self.validate()
        rs.advance(self.state, 'local_validated')
        rs.advance(cloud, 'request_attempted', attempt)

    def test_forged_cloud_records_and_states_rejected_on_local_read(self):
        self.prepare()
        self.validate()
        path = self.state / 'state.json'
        original = json.loads(path.read_text())
        changes = [{'state': state} for state in ('uploaded', 'uploaded_unverified', 'verified')]
        changes += [{'destinations': {'summary': {}}}, {'readbacks': {'summary': {}}}, {'version': 2}]
        for change in changes:
            path.write_text(json.dumps(dict(original, **change)))
            with self.subTest(change=change), self.assertRaises(ValueError): rs.show(self.state)
        path.write_text(json.dumps(original))

    def test_cloud_cannot_claim_local_completion(self):
        rs.init(self.state, payload('organization'))
        self.validate()
        with self.assertRaises(ValueError): rs.advance(self.state, 'local_validated')

    def test_all_profiles_both_deployments_and_required_files(self):
        from test_report_artifact import DETAILED, AI
        for deployment in ('enterprise_cloud', 'organization'):
            for kind, headers in (('detailed', DETAILED), ('summarized', SUMMARY), ('ai_usage', AI)):
                self.state = self.root / (deployment + kind)
                p = local_payload(deployment)
                p.update(kind=kind, page='ai_usage' if kind == 'ai_usage' else 'usage', required_ids=['first', 'second'])
                rs.init(self.state, p)
                make_csv(self.file, headers)
                rs.advance(self.state, 'downloaded', {'user_link': True, 'notification_verified': False, 'source_correspondence': True})
                rs.register_artifact(self.state, 'first', self.file)
                with self.assertRaises(ValueError): rs.advance(self.state, 'validated')
                rs.register_artifact(self.state, 'second', self.file)
                rs.advance(self.state, 'validated')
                partial = self.root / 'pending.part'; partial.touch()
                with self.assertRaises(ValueError): rs.advance(self.state, 'local_validated')
                partial.unlink()
                rs.advance(self.state, 'blocked_by_pending', {'pending_ids': ['second']})
                with self.assertRaises(ValueError): rs.advance(self.state, 'downloaded')
                rs.advance(self.state, 'downloaded', {'pending_ids': []})
                rs.advance(self.state, 'validated')
                self.assertEqual(rs.advance(self.state, 'local_validated')['state'], 'local_validated')

    def test_template_and_documented_local_contract(self):
        import yaml
        c = yaml.safe_load((ROOT / 'templates/github-usage.local-only.example.yaml').read_text())
        self.assertEqual(validate_config(c)['mode'], 'local_only')
        for name in ('SKILL.md', 'references/local-workflow.md', 'templates/configuration.md', 'references/manual-validation.md', 'references/github-export.md', 'references/cloud-destinations.md'):
            text = (ROOT / name).read_text()
            for term in ('local_only', 'local_validated'):
                with self.subTest(name=name, term=term): self.assertIn(term, text)

    def test_upload_blocks_local_config_or_ledger_before_remote(self):
        initial = self.prepare()
        self.validate()
        cloud = config()
        cloud['destination'] = {'provider': 'dropbox', 'transport': 'rclone', 'remote': 'example', 'folder_path': 'reports'}
        for c in (local_config(), cloud):
            with patch.object(upload, '_run') as remote:
                with self.assertRaisesRegex(ValueError, 'local.only|Local.only'):
                    upload.transfer(c, self.file, initial['filenames']['summary'], 'summarized', '2026-01-01', '2026-01-31', upload.destination_identity(cloud['destination']), self.root, self.state)
                remote.assert_not_called()

    def test_old_v1_v2_payload_hash_names_and_bytes_preserved(self):
        for deployment in (None, 'enterprise_cloud', 'organization'):
            p = payload(deployment)
            directory = self.root / str(deployment)
            data = rs.init(directory, p)
            digest = hashlib.sha256(json.dumps(p, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            self.assertEqual(data['version'], 1 if deployment is None else 2)
            self.assertEqual(data['payload'], p)
            self.assertEqual(data['run_key'], digest)
            self.assertEqual(data['filenames'], {'summary': 'usage-' + digest[:12] + '-summary.csv'})
            before = (directory / 'state.json').read_bytes()
            rs.show(directory); rs.init(directory, p)
            self.assertEqual((directory / 'state.json').read_bytes(), before)

    def test_real_cli_local_workflow_and_rejected_flags(self):
        import yaml
        cfg = self.root / 'config.yaml'; cfg.write_text(yaml.safe_dump(local_config())); cfg.chmod(0o600)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_config.py'), '--config', str(cfg)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['mode'], 'local_only')
        common = ['--run-id', 'synthetic', '--github-account', 'synthetic-account', '--deployment', 'organization', '--organization', 'example-org', '--page', 'usage', '--kind', 'summarized', '--start-date', '2026-01-01', '--end-date', '2026-01-31', '--required-id', 'summary']
        def cli(*args):
            return subprocess.run([sys.executable, str(rs.__file__), '--state-dir', str(self.state), *args], capture_output=True, text=True)
        for extra in ([], ['--mode', 'local_only', '--upload-mode', 'archive'], ['--mode', 'local_only', '--destination-id', 'forbidden']):
            self.assertEqual(cli('init', *common, *extra).returncode, 2)
        commands = [('init', *common, '--mode', 'local_only'), ('advance', 'downloaded', '--evidence', '{"user_link":true,"notification_verified":false,"source_correspondence":true}'), ('register-artifact', 'summary', str(self.file)), ('advance', 'validated'), ('advance', 'local_validated'), ('show',)]
        for args in commands:
            result = cli(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertIs(summary['cloud_verified'], False)
            for sensitive in ('example-org', 'synthetic-account', str(self.root)):
                self.assertNotIn(sensitive, result.stdout + result.stderr)
        self.assertEqual(summary['state'], 'local_validated')


if __name__ == '__main__':
    unittest.main()
