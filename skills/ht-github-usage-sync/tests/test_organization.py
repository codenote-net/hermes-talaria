"""Offline Organization contracts; synthetic data is not browser E2E evidence."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import report_artifact as ra
import run_state as rs
from validate_config import ConfigError, validate_config
import test_config
import test_upload_report

ROOT = Path(__file__).resolve().parents[1]


def config(deployment='organization'):
    c = test_config.fixture()
    key, slug, prefix = ('organization', 'example-org', 'organizations') if deployment == 'organization' else ('enterprise', 'example-enterprise', 'enterprises')
    c['github'] = {'deployment': deployment, key: slug, 'pages': {
        'usage': {'url': f'https://github.com/{prefix}/{slug}/settings/billing/usage?tab=01&tab=%2f+%20&empty=&raw=%FF'},
        'ai_usage': {'url': f'https://github.com/{prefix}/{slug}/settings/billing/ai_usage?opaque=retain'}}}
    return c


def payload(deployment=None):
    p = dict(run_id='synthetic', github_account='synthetic-account', enterprise='example-enterprise',
             page='usage', kind='summarized', start_date='2026-01-01', end_date='2026-01-31',
             destination_id='synthetic-destination', upload_mode='archive', required_ids=['summary'])
    if deployment is not None:
        p['deployment'] = deployment
        if deployment == 'organization':
            p.pop('enterprise')
            p['organization'] = 'example-org'
    return p


class OrganizationConfigTests(unittest.TestCase):
    def test_both_deployments_preserve_literal_urls_and_input(self):
        for deployment in ('enterprise_cloud', 'organization'):
            c = config(deployment)
            before = copy.deepcopy(c)
            self.assertEqual(validate_config(c)['github'], before['github'])
            self.assertEqual(c, before)
            c['report'] = {'page': 'ai_usage', 'kind': 'ai_usage'}
            self.assertEqual(validate_config(c)['report']['kind'], 'ai_usage')

    def test_requested_billing_entrypoint_forms(self):
        for deployment, key, url in [
            ('enterprise_cloud', 'enterprise', 'https://github.com/enterprises/your-org/billing'),
            ('organization', 'organization', 'https://github.com/organizations/your-org/settings/billing/'),
        ]:
            c = config(deployment)
            c['github'][key] = 'your-org'
            c['github']['pages'] = {'usage': {'url': url}, 'ai_usage': None}
            with self.subTest(deployment=deployment):
                self.assertEqual(validate_config(c)['github']['pages']['usage']['url'], url)

    def test_billing_entrypoints_and_report_pages_preserve_supplied_urls(self):
        cases = [('enterprise_cloud', '/enterprises/example-enterprise/billing'),
                 ('enterprise_cloud', '/enterprises/example-enterprise/settings/billing'),
                 ('organization', '/organizations/example-org/settings/billing')]
        for deployment, base in cases:
            for page in ('usage', 'ai_usage'):
                for suffix in ('', '/', '/' + page, '/' + page + '/'):
                    c = config(deployment)
                    url = 'https://github.com' + base + suffix + '?tab=01&tab=%2f+%20&empty=&raw=%FF'
                    c['github']['pages'][page]['url'] = url
                    c['report'] = {'page': page, 'kind': 'ai_usage' if page == 'ai_usage' else 'detailed'}
                    before = copy.deepcopy(c)
                    with self.subTest(deployment=deployment, page=page, suffix=suffix):
                        self.assertEqual(validate_config(c)['github']['pages'][page]['url'], url)
                        self.assertEqual(c, before)

    def test_billing_entrypoints_reject_wrong_target_routes_and_extra_segments(self):
        for deployment, base in [('enterprise_cloud', '/enterprises/example-enterprise/billing'),
                                 ('organization', '/organizations/example-org/settings/billing')]:
            invalid = [base + '//', base + '/usage/extra', base + '/invoices',
                       base.replace('example-', 'other-'), base.replace('/billing', '/%62illing'),
                       base.replace('/billing', '/billing-other')]
            invalid.append('/organizations/example-org/billing' if deployment == 'organization'
                           else '/organizations/example-enterprise/settings/billing')
            for path in invalid:
                c = config(deployment)
                c['github']['pages']['usage']['url'] = 'https://github.com' + path
                with self.subTest(deployment=deployment, path=path), self.assertRaises(ConfigError):
                    validate_config(c)

    def test_selected_slug_required_other_key_prohibited_even_null(self):
        for deployment, selected, other in [('enterprise_cloud', 'enterprise', 'organization'), ('organization', 'organization', 'enterprise')]:
            for value in (None, '', True, '../bad', 'bad_slug', '-bad', 'bad-', 'bad.slug', 'bad/slash', 'bad%2Fslug', ' slug', 'slug ', 'bad\nslug'):
                c = config(deployment); c['github'][selected] = value
                with self.subTest(deployment=deployment, value=value), self.assertRaises(ConfigError):
                    validate_config(c)
            c = config(deployment); del c['github'][selected]
            with self.assertRaises(ConfigError): validate_config(c)
            for value in (None, 'example-other'):
                c = config(deployment); c['github'][other] = value
                with self.assertRaises(ConfigError): validate_config(c)

    def test_all_nonnull_pages_match_host_port_slug_page_and_deployment(self):
        for deployment in ('enterprise_cloud', 'organization'):
            c = config(deployment)
            url = c['github']['pages']['usage']['url'].split('?')[0]
            invalid = [url.replace('https:', 'http:'), url.replace('github.com', 'example.test'),
                       url.replace('github.com', 'github.com.evil.test'), url.replace('github.com', 'user@github.com'),
                       url.replace('github.com', 'github.com:444'), url.replace('github.com', 'github.com:bad'),
                       url.replace('/usage', '/ai_usage'), url + '//', url + '/extra',
                       url.replace('/settings/', '/%73ettings/'), url.replace('example-', 'other-'),
                       url.replace('/enterprises/', '/organizations/') if deployment == 'enterprise_cloud' else url.replace('/organizations/', '/enterprises/')]
            for value in invalid:
                bad = copy.deepcopy(c); bad['github']['pages']['usage']['url'] = value
                with self.subTest(deployment=deployment, value=value), self.assertRaises(ConfigError): validate_config(bad)
            # Unselected but nonnull pages must also be validated.
            c['github']['pages']['ai_usage']['url'] = url
            with self.assertRaises(ConfigError): validate_config(c)
            c['github']['pages']['ai_usage'] = None
            c['github']['pages']['usage']['url'] = url.replace('github.com', 'github.com:443') + '?x=%2F+&x=0001'
            self.assertEqual(validate_config(c)['github'], c['github'])


class OrganizationLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.root.chmod(0o700)

    def test_legacy_hash_names_pending_reservation_and_resume_unchanged(self):
        p = payload()
        data = rs.init(self.root / 'legacy', p)
        digest = hashlib.sha256(json.dumps(p, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(data['version'], 1)
        self.assertEqual(data['run_key'], digest)
        self.assertEqual(data['filenames'], {'summary': 'usage-' + digest[:12] + '-summary.csv'})
        rs.advance(self.root / 'legacy', 'request_attempted', {'request_attempted_at': '2026-01-01T12:00:00+00:00'})
        before = (self.root / 'legacy/state.json').read_bytes()
        reservation = next((self.root / '.accounts').glob('*.json')).read_bytes()
        self.assertEqual(rs.init(self.root / 'legacy', p)['payload'], p)
        self.assertEqual((self.root / 'legacy/state.json').read_bytes(), before)
        self.assertEqual(next((self.root / '.accounts').glob('*.json')).read_bytes(), reservation)

    def test_explicit_deployments_are_v2_and_frozen_without_unused_keys(self):
        for deployment in ('enterprise_cloud', 'organization'):
            p = payload(deployment); directory = self.root / deployment
            data = rs.init(directory, p)
            self.assertEqual(data['version'], 2)
            self.assertEqual(data['payload'], p)
            before = (directory / 'state.json').read_bytes()
            self.assertEqual(rs.init(directory, p), data)
            self.assertEqual((directory / 'state.json').read_bytes(), before)
            other = 'enterprise' if deployment == 'organization' else 'organization'
            with self.assertRaises(ValueError): rs.init(self.root / 'bad', dict(p, **{other: None}))
            changed = dict(p); changed['organization' if deployment == 'organization' else 'enterprise'] = 'other-slug'
            with self.assertRaises(ValueError): rs.init(directory, changed)

    def test_explicit_payload_invalid_shapes_and_versions_fail_closed(self):
        p = payload('organization')
        for changes in ({'deployment': 'server'}, {'organization': 'bad_slug'}, {'organization': None}, {'organization': '../bad'}, {'deployment': None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): rs.init(self.root / 'bad', dict(p, **changes))
        data = rs.init(self.root / 'org', p)
        file = self.root / 'org/state.json'
        for version in (1, 3, True):
            file.write_text(json.dumps(dict(data, version=version)))
            with self.assertRaises(ValueError): rs.show(self.root / 'org')

    def test_shared_account_reservation_across_legacy_enterprise_and_organization(self):
        for name, p in [('legacy', payload()), ('enterprise', payload('enterprise_cloud')), ('org', payload('organization'))]:
            rs.init(self.root / name, p)
        evidence = {'request_attempted_at': '2026-01-01T12:00:00+00:00'}
        rs.advance(self.root / 'org', 'request_attempted', evidence)
        for name in ('legacy', 'enterprise'):
            with self.assertRaises(ValueError): rs.advance(self.root / name, 'request_attempted', evidence)
        rs.advance(self.root / 'org', 'cancelled', {'request_cancelled_observed': True, 'request_resolved_at': '2026-01-01T12:01:00+00:00'})
        rs.advance(self.root / 'legacy', 'request_attempted', evidence)
        with self.assertRaises(ValueError): rs.advance(self.root / 'enterprise', 'request_attempted', evidence)

    def test_cli_legacy_new_targets_pairing_exclusivity_and_redaction(self):
        def cli(name, extra):
            common = ['--run-id', 'synthetic', '--github-account', 'synthetic-account', '--page', 'usage', '--kind', 'summarized', '--start-date', '2026-01-01', '--end-date', '2026-01-31', '--destination-id', 'synthetic-destination', '--required-id', 'summary']
            return subprocess.run([sys.executable, str(ROOT / 'scripts/run_state.py'), '--state-dir', str(self.root / name), 'init', *common, *extra], capture_output=True, text=True)
        for name, args, version in [('legacy', ['--enterprise', 'example-enterprise'], 1), ('org', ['--deployment', 'organization', '--organization', 'example-org'], 2), ('enterprise', ['--deployment', 'enterprise_cloud', '--enterprise', 'example-enterprise'], 2)]:
            result = cli(name, args)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = rs.show(self.root / name)
            self.assertEqual(data['version'], version)
            self.assertNotIn('example-', result.stdout + result.stderr)
            self.assertFalse(any(value is None for value in data['payload'].values()))
        for args in [[], ['--organization', 'example-org'], ['--deployment', 'organization', '--enterprise', 'example-enterprise'], ['--deployment', 'enterprise_cloud', '--organization', 'example-org'], ['--deployment', 'organization', '--organization', 'example-org', '--enterprise', 'example-enterprise']]:
            result = cli('invalid', args)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('example-', result.stdout + result.stderr)


class OrganizationTransferTests(unittest.TestCase):
    def setUp(self):
        self.h = test_upload_report.TransferTests()
        self.h.setUp()
        self.addCleanup(self.h.tearDown)

    def test_legacy_enterprise_slug_mismatch_blocked_before_remote_calls(self):
        self.h.config['github']['enterprise'] = 'other'
        self.h.config['github']['pages']['usage']['url'] = 'https://github.com/enterprises/other/settings/billing/usage'
        with self.assertRaises(ValueError): self.h.transfer()
        self.assertEqual(self.h.calls, [])

    def test_legacy_enterprise_cannot_upload_under_organization(self):
        self.h.config['github'] = config()['github']
        # Same slug still cannot cross deployment; this is not just a slug gate.
        self.h.config['github']['organization'] = 'example'
        self.h.config['github']['pages'] = {'usage': {'url': 'https://github.com/organizations/example/settings/billing/usage'}}
        with self.assertRaises(ValueError): self.h.transfer()
        self.assertEqual(self.h.calls, [])

    def test_v2_transfer_and_target_mismatch_for_both_deployments(self):
        for deployment in ('enterprise_cloud', 'organization'):
            h = self.h
            h.config['github'] = config(deployment)['github']
            p = payload(deployment)
            p['destination_id'] = test_upload_report.upload.destination_identity(h.config['destination'])
            p['end_date'] = '2026-01-01'
            h.state = h.root / deployment
            data = rs.init(h.state, p); h.name = data['filenames']['summary']
            rs.advance(h.state, 'downloaded', {'user_link': True, 'notification_verified': False, 'source_correspondence': True})
            rs.register_artifact(h.state, 'summary', h.source); rs.advance(h.state, 'validated')
            h.items = []; h.calls = []
            before = (h.state / 'state.json').read_bytes()
            self.assertTrue(h.transfer()['verified'])
            self.assertEqual((h.state / 'state.json').read_bytes(), before)
            h.calls = []
            frozen_github = copy.deepcopy(h.config['github'])
            selected = 'organization' if deployment == 'organization' else 'enterprise'
            other_deployment = 'enterprise_cloud' if deployment == 'organization' else 'organization'
            other_key = 'enterprise' if selected == 'organization' else 'organization'
            other_prefix = 'enterprises' if selected == 'organization' else 'organizations'
            slug = frozen_github[selected]
            h.config['github'] = {'deployment': other_deployment, other_key: slug,
                                 'pages': {'usage': {'url': f'https://github.com/{other_prefix}/{slug}/settings/billing/usage'}}}
            with self.assertRaises(ValueError): h.transfer()
            self.assertEqual(h.calls, [])
            h.config['github'] = frozen_github
            selected = 'organization' if deployment == 'organization' else 'enterprise'
            h.config['github'][selected] = 'other'
            prefix = 'organizations' if deployment == 'organization' else 'enterprises'
            h.config['github']['pages'] = {'usage': {'url': f'https://github.com/{prefix}/other/settings/billing/usage'}}
            with self.assertRaises(ValueError): h.transfer()
            self.assertEqual(h.calls, [])


class OrganizationArtifactAndDocsTests(unittest.TestCase):
    def test_synthetic_organization_csv_profiles_unchanged_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); root.chmod(0o700)
            for kind in ('detailed', 'summarized', 'ai_usage'):
                source = ROOT / 'tests/fixtures' / ('organization-' + kind + '.csv')
                original = source.read_bytes()
                target = root / 'report.csv'; target.write_bytes(original); target.chmod(0o600)
                self.assertEqual(ra.validate(target, kind, '2026-01-01', '2026-01-31')['rows'], 1)
                self.assertEqual(target.read_bytes(), original)
                for other in set(ra.PROFILES) - {kind}:
                    with self.assertRaises(ValueError): ra.validate(target, other, '2026-01-01', '2026-01-31')

    def test_docs_cover_organization_and_legacy_contracts(self):
        for name in ('SKILL.md', 'references/github-export.md', 'references/manual-validation.md', 'references/local-workflow.md', 'references/cloud-destinations.md', 'templates/configuration.md'):
            text = (ROOT / name).read_text()
            with self.subTest(name=name): self.assertIn('Organization', text)
        text = (ROOT / 'references/local-workflow.md').read_text()
        for term in ('version 1', 'version 2', '--deployment', '--organization', 'legacy', 'github_account'):
            self.assertIn(term, text)
        import yaml
        c = yaml.safe_load((ROOT / 'templates/github-usage.organization.example.yaml').read_text())
        self.assertEqual(validate_config(c)['github']['organization'], 'example-org')


if __name__ == '__main__': unittest.main()
