"""Strictly validate personal YAML outside Git without handling credentials."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

import yaml
from report_period import PeriodError, normalize_report


class ConfigError(ValueError):
    """User-facing configuration error that does not expose values."""


class UniqueSafeLoader(yaml.SafeLoader):
    """Extend SafeLoader to reject duplicate keys, including after merges."""


def _unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in result:
                raise ConfigError('YAML: Remove duplicate keys.')
            result[key] = loader.construct_object(value_node, deep=deep)
        except TypeError:
            raise ConfigError('YAML: Specify keys as strings.') from None
    return result


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _map(value, allowed, label):
    if type(value) is not dict or any(type(k) is not str or k not in allowed for k in value):
        raise ConfigError(f'{label}: Provide a mapping containing only allowed keys.')
    return value.copy()


def _text(value, label):
    if type(value) is not str or not value or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ConfigError(f'{label}: Provide a nonempty string without control characters.')
    return value


def _choice(value, allowed, label):
    if type(value) is not str or value not in allowed:
        raise ConfigError(f'{label}: Specify a supported option.')
    return value


def _https(value, label):
    _text(value, label)
    try:
        url = urlsplit(value)
        port = url.port
        if url.scheme != 'https' or not url.hostname or url.username is not None or url.password is not None or any(c.isspace() for c in value) or '\\' in value:
            raise ValueError
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ConfigError(f'{label}: Provide a full HTTPS URL without credentials.') from None
    return url


def _id(value, label):
    _text(value, label)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', value) or value.lower() == 'root':
        raise ConfigError(f'{label}: Provide a valid non-root ID.')
    return value


def _relative(value, label):
    _text(value, label)
    if value.startswith(('/', '~')) or '\\' in value or ':' in value or any(part in {'', '.', '..'} for part in value.split('/')):
        raise ConfigError(f'{label}: Provide a relative path without root, empty components, or parent traversal.')
    return value


def external_path(value, label='path'):
    """Resolve nonexistent children and symlinks; reject Git worktree/administrative paths."""
    _text(str(value) if isinstance(value, Path) else value, label)
    raw = Path(value).expanduser()
    if '..' in raw.parts:
        raise ConfigError(f'{label}: Provide a path without parent traversal.')
    try:
        path = raw.resolve(strict=False)
        if path == Path(path.anchor):
            raise ConfigError(f'{label}: Provide a non-root path outside Git.')
        ancestor = path
        while not ancestor.exists():
            ancestor = ancestor.parent
        if not ancestor.is_dir():
            ancestor = ancestor.parent
        # Discovery with -C also rejects ignored files. Do not read personal Git settings
        # or let Git environment variables redirect discovery to another repository.
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, LC_ALL='C')
        result = subprocess.run(['git', '-C', str(ancestor), 'rev-parse', '--absolute-git-dir'],
            capture_output=True, text=True, env=env, timeout=10)
        if result.returncode == 0:
            raise ConfigError(f'{label}: Specify a destination outside Git repositories.')
        if result.returncode != 128 or 'not a git repository' not in result.stderr.lower():
            raise ConfigError(f'{label}: Cannot verify that the path is outside Git.')
    except (OSError, RuntimeError, subprocess.SubprocessError):
        raise ConfigError(f'{label}: Provide a resolvable path outside Git and ensure Git is available.') from None
    return path


def _email(value, label):
    _text(value, label)
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', value):
        raise ConfigError(f'{label}: Specify the email address to verify.')
    return value


def _notification(value):
    n = _map(value, {'mode', 'mail_url', 'expected_recipient', 'expected_account',
        'approved_forwarded_recipients', 'wait_interval_seconds', 'wait_timeout_seconds'}, 'notification')
    mode = _choice(n.get('mode', 'user_link'), {'user_link', 'browser_mail'}, 'notification.mode')
    if mode == 'user_link':
        if set(n) - {'mode'}:
            raise ConfigError('notification: Specify mail settings only for browser_mail.')
    else:
        _https(n.get('mail_url'), 'notification.mail_url')
        _email(n.get('expected_recipient'), 'notification.expected_recipient')
        _text(n.get('expected_account'), 'notification.expected_account')
        recipients = n.get('approved_forwarded_recipients', [])
        if type(recipients) is not list:
            raise ConfigError('notification: Provide approved forwarding recipients as an array.')
        for recipient in recipients:
            _email(recipient, 'notification.approved_forwarded_recipients')
        if len(recipients) != len(set(recipients)):
            raise ConfigError('notification: Remove duplicate approved forwarding recipients.')
        interval = n.get('wait_interval_seconds', 30)
        timeout = n.get('wait_timeout_seconds', 600)
        if type(interval) is not int or not 30 <= interval <= 60 or type(timeout) is not int or not 1 <= timeout <= 600 or interval > timeout:
            raise ConfigError('notification: Specify a 30-60-second wait interval and 1-600-second timeout, with interval <= timeout.')
        n.update(approved_forwarded_recipients=recipients, wait_interval_seconds=interval, wait_timeout_seconds=timeout)
    n['mode'] = mode
    return n


def _destination(value):
    common = {'provider', 'transport'}
    d = _map(value, common | {'remote', 'folder_url', 'folder_id', 'shared_drive_id', 'folder_path', 'bucket', 'prefix'}, 'destination')
    provider = _choice(d.get('provider'), {'google_drive', 'onedrive', 'sharepoint', 'dropbox', 'box', 's3', 'gcs'}, 'destination.provider')
    transport = _choice(d.get('transport', 'browser'), {'browser', 'rclone'}, 'destination.transport')
    if transport == 'browser':
        if provider != 'google_drive':
            raise ConfigError('destination: browser supports only google_drive. Explicitly select rclone for other providers.')
        allowed = common | {'folder_id', 'folder_url'}
        _id(d.get('folder_id'), 'destination.folder_id')
        url = _https(d.get('folder_url'), 'destination.folder_url')
        if url.hostname != 'drive.google.com' or url.port not in {None, 443} or unquote(url.path) != '/drive/folders/' + d['folder_id']:
            raise ConfigError('destination: Match the drive.google.com folder URL to folder_id.')
    else:
        remote = _text(d.get('remote'), 'destination.remote')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', remote):
            raise ConfigError('destination.remote: Specify an existing remote name without colons, flags, or paths.')
        allowed = common | {'remote'}
        if provider in {'google_drive', 'box'}:
            allowed |= {'folder_id'}
            _id(d.get('folder_id'), 'destination.folder_id')
            if provider == 'box' and d['folder_id'] == '0':
                raise ConfigError('destination.folder_id: Specify a non-root Box folder ID.')
            if provider == 'google_drive':
                allowed |= {'shared_drive_id'}
                if 'shared_drive_id' in d:
                    _id(d['shared_drive_id'], 'destination.shared_drive_id')
        elif provider in {'onedrive', 'sharepoint', 'dropbox'}:
            allowed |= {'folder_path'}
            _relative(d.get('folder_path'), 'destination.folder_path')
        else:
            allowed |= {'bucket', 'prefix'}
            bucket = _text(d.get('bucket'), 'destination.bucket')
            if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket) or '..' in bucket or re.fullmatch(r'\d+\.\d+\.\d+\.\d+', bucket):
                raise ConfigError('destination.bucket: Specify a valid bucket name, not a URI or path.')
            _relative(d.get('prefix'), 'destination.prefix')
    if set(d) - allowed:
        raise ConfigError('destination: Remove keys incompatible with the selected provider/transport.')
    d['transport'] = transport
    return d


def validate_config(config):
    """Return a normalized dictionary without modifying input; reject unknown and secret keys."""
    c = _map(config, {'version', 'github', 'report', 'notification', 'acquisition', 'destination', 'upload', 'local'}, 'config')
    if type(c.get('version')) is not int or c['version'] != 1:
        raise ConfigError('version: Specify integer 1.')
    github = _map(c.get('github'), {'deployment', 'enterprise', 'pages'}, 'github')
    _choice(github.get('deployment'), {'enterprise_cloud'}, 'github.deployment')
    enterprise = _text(github.get('enterprise'), 'github.enterprise')
    if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?', enterprise):
        raise ConfigError('github.enterprise: Specify an enterprise slug.')
    pages = _map(github.get('pages'), {'usage', 'ai_usage'}, 'github.pages')
    for page, value in pages.items():
        if value is not None:
            entry = _map(value, {'url'}, 'github.pages')
            _https(entry.get('url'), 'github.pages.url')
    try:
        report = normalize_report(c.get('report', {}))
    except PeriodError as exc:
        raise ConfigError(str(exc)) from None
    if pages.get(report['page']) is None:
        raise ConfigError('github.pages: Specify the full URL of the selected page.')
    acquisition = _map(c.get('acquisition', {}), {'method'}, 'acquisition')
    acquisition['method'] = _choice(acquisition.get('method', 'browser'), {'browser'}, 'acquisition.method')
    upload = _map(c.get('upload', {}), {'mode'}, 'upload')
    upload['mode'] = _choice(upload.get('mode', 'archive'), {'archive', 'replace'}, 'upload.mode')
    local = _map(c.get('local', {}), {'output_dir'}, 'local')
    output = external_path(local.get('output_dir', '~/.local/share/hermes-talaria/github-usage/'), 'local.output_dir')
    if output.exists() and not output.is_dir():
        raise ConfigError('local.output_dir: Specify a directory.')
    c.update(report=report, notification=_notification(c.get('notification', {})),
        acquisition=acquisition, destination=_destination(c.get('destination')), upload=upload,
        local={'output_dir': str(output)})
    return copy.deepcopy(c)


def load_config(explicit=None):
    """Explicit path > dedicated environment variable > default path. Never open files inside Git."""
    selected = explicit if explicit is not None else os.environ.get('HT_GITHUB_USAGE_CONFIG', '~/.config/hermes-talaria/github-usage.yaml')
    path = external_path(selected, 'config path')
    try:
        with path.open(encoding='utf-8') as stream:
            config = yaml.load(stream, Loader=UniqueSafeLoader)
    except ConfigError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError, RecursionError):
        raise ConfigError('YAML: Create the configuration file outside Git and verify safe YAML syntax and types.') from None
    return validate_config(config)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Safely validate personal GitHub usage configuration without displaying values.')
    parser.add_argument('--config', help='Personal YAML path outside Git')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f'Configuration error: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({'valid': True, 'version': config['version'], 'page': config['report']['page'],
        'kind': config['report']['kind'], 'period_mode': config['report']['period']['mode'],
        'notification_mode': config['notification']['mode'], 'provider': config['destination']['provider'],
        'transport': config['destination']['transport'], 'upload_mode': config['upload']['mode']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
