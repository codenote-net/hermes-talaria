"""Configuration validation tests using only synthetic configuration."""
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from validate_config import ConfigError, load_config, validate_config


def fixture():
    return {'version': 1, 'github': {'deployment': 'enterprise_cloud',
            'enterprise': 'example-enterprise', 'pages': {
                'usage': {'url': 'https://github.com/enterprises/example-enterprise/settings/billing/usage?opaque=retain'},
                'ai_usage': None}},
            'destination': {'provider': 'google_drive', 'folder_id': 'example-folder',
                'folder_url': 'https://drive.google.com/drive/folders/example-folder'}}


class ConfigTests(unittest.TestCase):
    def test_defaults_and_no_mutation(self):
        original = fixture(); before = copy.deepcopy(original)
        c = validate_config(original)
        self.assertEqual(original, before)
        self.assertEqual(c['report'], {'page': 'usage', 'kind': 'detailed',
            'period': {'mode': 'page_selection', 'timezone': 'UTC'}})
        self.assertEqual(c['notification']['mode'], 'user_link')
        self.assertEqual(c['acquisition']['method'], 'browser')
        self.assertEqual(c['upload']['mode'], 'archive')
        self.assertEqual(c['destination']['transport'], 'browser')
        self.assertTrue(c['github']['pages']['usage']['url'].endswith('?opaque=retain'))

    def test_strict_schema(self):
        mutations = [lambda c: c.update(token='secret'),
            lambda c: c.update(version=True), lambda c: c.update(version=2),
            lambda c: c['github'].update(deployment='server'),
            lambda c: c['github'].update(enterprise='../bad'),
            lambda c: c['github']['pages']['usage'].update(api_key='secret'),
            lambda c: c.update(report=None),
            lambda c: c.update(acquisition={'method': 'api'}),
            lambda c: c.update(upload={'mode': 'overwrite'}),
            lambda c: c['destination'].update(folder_id='root'),
            lambda c: c['destination'].update(folder_url='http://drive.google.com/drive/folders/example-folder'),
            lambda c: c['destination'].update(folder_id='mismatch'),
            lambda c: c['destination'].update(remote='unused'),
            lambda c: c['destination'].update(provider='box'),
            lambda c: c['github']['pages']['usage'].update(url='https://user:pass@example.test/usage'),
            lambda c: c['github']['pages']['usage'].update(url='https://example.test/usage\n')]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                c = fixture(); mutate(c)
                with self.assertRaises(ConfigError): validate_config(c)

    def test_page_kind_pairs(self):
        c = fixture(); c['report'] = {'page': 'ai_usage'}
        with self.assertRaises(ConfigError): validate_config(c)
        c['github']['pages']['ai_usage'] = {'url': 'https://example.test/ai_usage?selection=opaque'}
        with self.assertRaises(ConfigError): validate_config(c)
        c['report']['kind'] = 'ai_usage'
        self.assertEqual(validate_config(c)['report']['kind'], 'ai_usage')
        for page, kind in [('usage', 'ai_usage'), ('ai_usage', 'detailed'), ('ai_usage', 'summarized')]:
            c['report'] = {'page': page, 'kind': kind}
            with self.assertRaises(ConfigError): validate_config(c)
        c['report'] = {'kind': 'summarized'}
        self.assertEqual(validate_config(c)['report']['kind'], 'summarized')

    def test_notifications(self):
        c = fixture(); c['notification'] = {'mode': 'browser_mail', 'mail_url': 'https://example.test/mail',
            'expected_recipient': 'reader@example.test', 'expected_account': 'reader@example.test',
            'approved_forwarded_recipients': ['forward@example.test'],
            'wait_interval_seconds': 30, 'wait_timeout_seconds': 120}
        self.assertEqual(validate_config(c)['notification'], c['notification'])
        for field, value in [('mail_url', 'http://example.test'), ('expected_account', ''),
                ('expected_recipient', 'bad'), ('wait_interval_seconds', True),
                ('wait_timeout_seconds', 0), ('wait_timeout_seconds', 86401),
                ('approved_forwarded_recipients', ['bad'])]:
            bad = copy.deepcopy(c); bad['notification'][field] = value
            with self.subTest(field=field), self.assertRaises(ConfigError): validate_config(bad)
        c['notification'] = {'mode': 'user_link', 'mail_url': 'https://example.test'}
        with self.assertRaises(ConfigError): validate_config(c)

    def test_browser_mail_wait_contract(self):
        c = fixture()
        c['notification'] = {'mode': 'browser_mail', 'mail_url': 'https://example.test/mail',
            'expected_recipient': 'reader@example.test', 'expected_account': 'example-account'}
        normalized = validate_config(c)['notification']
        self.assertEqual(normalized['wait_interval_seconds'], 30)
        self.assertEqual(normalized['wait_timeout_seconds'], 600)

    def test_browser_mail_wait_boundaries(self):
        c = fixture()
        c['notification'] = {'mode': 'browser_mail', 'mail_url': 'https://example.test/mail',
            'expected_recipient': 'reader@example.test', 'expected_account': 'example-account',
            'wait_interval_seconds': 30, 'wait_timeout_seconds': 600}
        for interval, timeout in [(30, 30), (60, 60), (30, 600), (60, 600)]:
            with self.subTest(interval=interval, timeout=timeout):
                c['notification'].update(wait_interval_seconds=interval, wait_timeout_seconds=timeout)
                self.assertEqual(validate_config(c)['notification'],
                    dict(c['notification'], approved_forwarded_recipients=[]))
        c['notification'].update(wait_interval_seconds=30, wait_timeout_seconds=600)
        for field, values in [('wait_interval_seconds', [1, 29, 61, 300, True, 30.0, '30']),
                ('wait_timeout_seconds', [0, -1, 601, 3600, True, 600.0, '600', 29])]:
            for value in values:
                bad = copy.deepcopy(c); bad['notification'][field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ConfigError) as error:
                        validate_config(bad)
                    for sensitive in ['reader@example.test', 'example-account', 'https://example.test/mail']:
                        self.assertNotIn(sensitive, str(error.exception))

    def test_rclone_provider_matrix(self):
        fields = {'google_drive': {'folder_id': 'example-folder', 'shared_drive_id': 'example-drive'},
            'onedrive': {'folder_path': 'reports/usage'}, 'sharepoint': {'folder_path': 'reports/usage'},
            'dropbox': {'folder_path': 'reports/usage'}, 'box': {'folder_id': '12345'},
            's3': {'bucket': 'example-bucket', 'prefix': 'reports/usage'},
            'gcs': {'bucket': 'example-bucket', 'prefix': 'reports/usage'}}
        for provider, extra in fields.items():
            c = fixture(); c['destination'] = dict(provider=provider, transport='rclone', remote='example_remote', **extra)
            with self.subTest(provider=provider):
                self.assertEqual(validate_config(c)['destination'], c['destination'])
                for remote in ['x:', '--flag', 'x/path', '', 'x y', '../x']:
                    bad = copy.deepcopy(c); bad['destination']['remote'] = remote
                    with self.assertRaises(ConfigError): validate_config(bad)
                bad = copy.deepcopy(c); bad['destination']['folder_url'] = 'https://example.test'
                with self.assertRaises(ConfigError): validate_config(bad)
                for key in ('folder_path', 'prefix'):
                    if key in extra:
                        for value in ['', '/', '../reports', 'reports/../x', 'reports//x', 'reports/./x', '\\reports']:
                            bad = copy.deepcopy(c); bad['destination'][key] = value
                            with self.assertRaises(ConfigError): validate_config(bad)

    def test_git_external_paths_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); repo = root / 'repo'; repo.mkdir()
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            c = fixture(); c['local'] = {'output_dir': str(repo / 'untracked' / 'output')}
            with self.assertRaises(ConfigError): validate_config(c)
            link = root / 'link'; link.symlink_to(repo, target_is_directory=True)
            c['local']['output_dir'] = str(link / 'output')
            with self.assertRaises(ConfigError): validate_config(c)
            c['local']['output_dir'] = str(root / 'outside' / 'output')
            self.assertEqual(validate_config(c)['local']['output_dir'], str((root / 'outside' / 'output').resolve()))
            inside = repo / 'config.yaml'; inside.write_text('secret must not be read')
            with self.assertRaises(ConfigError): load_config(str(inside))

    def test_box_root_and_git_environment(self):
        c = fixture(); c['destination'] = {'provider': 'box', 'transport': 'rclone', 'remote': 'example_remote', 'folder_id': '0'}
        with self.assertRaises(ConfigError): validate_config(c)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'; repo.mkdir()
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            c = fixture(); c['local'] = {'output_dir': str(repo / 'output')}
            with patch.dict(os.environ, {'GIT_DIR': str(Path(tmp) / 'nonexistent'), 'GIT_WORK_TREE': tmp}):
                with self.assertRaises(ConfigError): validate_config(c)

    def test_yaml_duplicates_types_and_precedence(self):
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); explicit = root / 'explicit.yaml'; env = root / 'env.yaml'
            explicit.write_text(yaml.safe_dump(fixture()))
            env.write_text('version: 1\nversion: 1\n')
            with patch.dict(os.environ, {'HT_GITHUB_USAGE_CONFIG': str(env)}):
                self.assertEqual(load_config(str(explicit))['version'], 1)
                with self.assertRaises(ConfigError): load_config()
            for text in ['[]', 'version: true', '!!python/object:builtins.object {}', 'a: &a {x: 1}\nb: {<<: *a, x: 2}', 'version: 1\n? [x, y]\n: 2']:
                explicit.write_text(text)
                with self.subTest(text=text), self.assertRaises(ConfigError): load_config(str(explicit))
            explicit.write_text(yaml.safe_dump(fixture()))
            default = root / '.config/hermes-talaria/github-usage.yaml'
            default.parent.mkdir(parents=True); default.write_text(explicit.read_text())
            with patch.dict(os.environ, {'HOME': tmp}, clear=True):
                self.assertEqual(load_config()['version'], 1)
            with self.assertRaises(ConfigError): load_config(str(root / 'missing.yaml'))

    def test_cli_redaction(self):
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'config.yaml'; p.write_text(yaml.safe_dump(fixture()))
            result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/validate_config.py'), '--config', str(p)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for sensitive in ['example-enterprise', 'https://', 'example-folder', str(p), 'remote']:
                self.assertNotIn(sensitive, result.stdout + result.stderr)
            c = fixture(); c['notification'] = {'mode': 'browser_mail', 'mail_url': 'https://example.test/private-mail',
                'expected_recipient': 'reader@example.test', 'expected_account': 'reader@example.test',
                'wait_interval_seconds': True}
            p.write_text(yaml.safe_dump(c))
            result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/validate_config.py'), '--config', str(p)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            for sensitive in ['example-enterprise', 'https://', 'reader@example.test', str(p)]:
                self.assertNotIn(sensitive, result.stdout + result.stderr)

    def test_template_and_optional_values(self):
        import yaml
        template = Path(__file__).resolve().parents[1] / 'templates/github-usage.example.yaml'
        self.assertEqual(validate_config(yaml.safe_load(template.read_text()))['version'], 1)
        c = fixture(); c['destination'] = {'provider': 'google_drive', 'transport': 'rclone',
            'remote': 'example_remote', 'folder_id': 'example-folder'}
        validate_config(c)
        c['notification'] = {'mode': 'browser_mail', 'mail_url': 'https://example.test/mail',
            'expected_recipient': 'reader@example.test', 'expected_account': 'example-account'}
        self.assertEqual(validate_config(c)['notification']['wait_timeout_seconds'], 600)
        for section in ['report', 'notification', 'acquisition', 'destination', 'upload', 'local']:
            bad = fixture(); bad[section] = []
            with self.subTest(section=section), self.assertRaises(ConfigError): validate_config(bad)
        for period in [{'mode': 'custom', 'start_date': '2024-01-01', 'end_date': '2024-02-01'},
                {'timezone': 'Invalid/Zone'}, {'mode': 'previous_month', 'start_date': '2024-01-01'}]:
            bad = fixture(); bad['report'] = {'period': period}
            with self.subTest(period=period), self.assertRaises(ConfigError): validate_config(bad)


if __name__ == '__main__': unittest.main()
