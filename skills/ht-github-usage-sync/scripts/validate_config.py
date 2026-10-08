"""Git管理外の個人YAMLを厳格に検証する。認証情報は扱わない。"""
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
    """値を表示しない、利用者向け設定エラー。"""


class UniqueSafeLoader(yaml.SafeLoader):
    """SafeLoaderに重複キー（マージ後も含む）拒否を追加する。"""


def _unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in result:
                raise ConfigError('YAML: 重複キーを削除してください。')
            result[key] = loader.construct_object(value_node, deep=deep)
        except TypeError:
            raise ConfigError('YAML: キーは文字列で指定してください。') from None
    return result


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _map(value, allowed, label):
    if type(value) is not dict or any(type(k) is not str or k not in allowed for k in value):
        raise ConfigError(f'{label}: 許可されたキーだけのマッピングを指定してください。')
    return value.copy()


def _text(value, label):
    if type(value) is not str or not value or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ConfigError(f'{label}: 空でない制御文字なしの文字列を指定してください。')
    return value


def _choice(value, allowed, label):
    if type(value) is not str or value not in allowed:
        raise ConfigError(f'{label}: 対応する選択肢を指定してください。')
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
        raise ConfigError(f'{label}: 認証情報を含まない完全なHTTPS URLを指定してください。') from None
    return url


def _id(value, label):
    _text(value, label)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', value) or value.lower() == 'root':
        raise ConfigError(f'{label}: ルート以外の有効なIDを指定してください。')
    return value


def _relative(value, label):
    _text(value, label)
    if value.startswith(('/', '~')) or '\\' in value or ':' in value or any(part in {'', '.', '..'} for part in value.split('/')):
        raise ConfigError(f'{label}: ルート・空要素・上位参照のない相対パスを指定してください。')
    return value


def external_path(value, label='path'):
    """存在しない子パスとsymlinkも解決し、Git作業木/管理領域内を拒否。"""
    _text(str(value) if isinstance(value, Path) else value, label)
    raw = Path(value).expanduser()
    if '..' in raw.parts:
        raise ConfigError(f'{label}: 上位参照を含まないパスを指定してください。')
    try:
        path = raw.resolve(strict=False)
        if path == Path(path.anchor):
            raise ConfigError(f'{label}: ルート以外のGit管理外パスを指定してください。')
        ancestor = path
        while not ancestor.exists():
            ancestor = ancestor.parent
        if not ancestor.is_dir():
            ancestor = ancestor.parent
        # -Cによる探索は無視ファイルも拒否する。個人のGit設定を読まず、
        # Git環境変数による別リポジトリ指定を探索に持ち込まない。
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, LC_ALL='C')
        result = subprocess.run(['git', '-C', str(ancestor), 'rev-parse', '--absolute-git-dir'],
            capture_output=True, text=True, env=env, timeout=10)
        if result.returncode == 0:
            raise ConfigError(f'{label}: Gitリポジトリ外の保存先を指定してください。')
        if result.returncode != 128 or 'not a git repository' not in result.stderr.lower():
            raise ConfigError(f'{label}: Git管理外であることを確認できません。')
    except (OSError, RuntimeError, subprocess.SubprocessError):
        raise ConfigError(f'{label}: 解決可能なGit管理外パスを指定し、Gitを利用可能にしてください。') from None
    return path


def _email(value, label):
    _text(value, label)
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', value):
        raise ConfigError(f'{label}: 確認対象のメールアドレスを指定してください。')
    return value


def _notification(value):
    n = _map(value, {'mode', 'mail_url', 'expected_recipient', 'expected_account',
        'approved_forwarded_recipients', 'wait_interval_seconds', 'wait_timeout_seconds'}, 'notification')
    mode = _choice(n.get('mode', 'user_link'), {'user_link', 'browser_mail'}, 'notification.mode')
    if mode == 'user_link':
        if set(n) - {'mode'}:
            raise ConfigError('notification: メール設定はbrowser_mailでのみ指定してください。')
    else:
        _https(n.get('mail_url'), 'notification.mail_url')
        _email(n.get('expected_recipient'), 'notification.expected_recipient')
        _text(n.get('expected_account'), 'notification.expected_account')
        recipients = n.get('approved_forwarded_recipients', [])
        if type(recipients) is not list:
            raise ConfigError('notification: 承認済み転送先は配列で指定してください。')
        for recipient in recipients:
            _email(recipient, 'notification.approved_forwarded_recipients')
        if len(recipients) != len(set(recipients)):
            raise ConfigError('notification: 承認済み転送先の重複を削除してください。')
        interval = n.get('wait_interval_seconds', 30)
        timeout = n.get('wait_timeout_seconds', 600)
        if type(interval) is not int or not 30 <= interval <= 60 or type(timeout) is not int or not 1 <= timeout <= 600 or interval > timeout:
            raise ConfigError('notification: 待機間隔は30〜60秒、上限は1〜600秒、間隔≦上限で指定してください。')
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
            raise ConfigError('destination: browserはgoogle_driveのみ対応しています。別プロバイダーはrcloneを明示してください。')
        allowed = common | {'folder_id', 'folder_url'}
        _id(d.get('folder_id'), 'destination.folder_id')
        url = _https(d.get('folder_url'), 'destination.folder_url')
        if url.hostname != 'drive.google.com' or url.port not in {None, 443} or unquote(url.path) != '/drive/folders/' + d['folder_id']:
            raise ConfigError('destination: drive.google.comのフォルダーURLとfolder_idを一致させてください。')
    else:
        remote = _text(d.get('remote'), 'destination.remote')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', remote):
            raise ConfigError('destination.remote: コロン・フラグ・パスなしの登録済みremote名を指定してください。')
        allowed = common | {'remote'}
        if provider in {'google_drive', 'box'}:
            allowed |= {'folder_id'}
            _id(d.get('folder_id'), 'destination.folder_id')
            if provider == 'box' and d['folder_id'] == '0':
                raise ConfigError('destination.folder_id: Boxのルート以外のフォルダーIDを指定してください。')
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
                raise ConfigError('destination.bucket: URIやパスではなく有効なbucket名を指定してください。')
            _relative(d.get('prefix'), 'destination.prefix')
    if set(d) - allowed:
        raise ConfigError('destination: 選択したprovider/transportと互換性のないキーを削除してください。')
    d['transport'] = transport
    return d


def validate_config(config):
    """辞書を正規化して返す。元データは変更せず、未知キーと秘密キーを拒否。"""
    c = _map(config, {'version', 'github', 'report', 'notification', 'acquisition', 'destination', 'upload', 'local'}, 'config')
    if type(c.get('version')) is not int or c['version'] != 1:
        raise ConfigError('version: 整数の1を指定してください。')
    github = _map(c.get('github'), {'deployment', 'enterprise', 'pages'}, 'github')
    _choice(github.get('deployment'), {'enterprise_cloud'}, 'github.deployment')
    enterprise = _text(github.get('enterprise'), 'github.enterprise')
    if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?', enterprise):
        raise ConfigError('github.enterprise: enterprise slugを指定してください。')
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
        raise ConfigError('github.pages: 選択したページの完全URLを指定してください。')
    acquisition = _map(c.get('acquisition', {}), {'method'}, 'acquisition')
    acquisition['method'] = _choice(acquisition.get('method', 'browser'), {'browser'}, 'acquisition.method')
    upload = _map(c.get('upload', {}), {'mode'}, 'upload')
    upload['mode'] = _choice(upload.get('mode', 'archive'), {'archive', 'replace'}, 'upload.mode')
    local = _map(c.get('local', {}), {'output_dir'}, 'local')
    output = external_path(local.get('output_dir', '~/.local/share/hermes-talaria/github-usage/'), 'local.output_dir')
    if output.exists() and not output.is_dir():
        raise ConfigError('local.output_dir: ディレクトリを指定してください。')
    c.update(report=report, notification=_notification(c.get('notification', {})),
        acquisition=acquisition, destination=_destination(c.get('destination')), upload=upload,
        local={'output_dir': str(output)})
    return copy.deepcopy(c)


def load_config(explicit=None):
    """明示パス > 専用環境変数 > 既定パス。Git内のファイルは開かない。"""
    selected = explicit if explicit is not None else os.environ.get('HT_GITHUB_USAGE_CONFIG', '~/.config/hermes-talaria/github-usage.yaml')
    path = external_path(selected, 'config path')
    try:
        with path.open(encoding='utf-8') as stream:
            config = yaml.load(stream, Loader=UniqueSafeLoader)
    except ConfigError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError, RecursionError):
        raise ConfigError('YAML: Git管理外に設定ファイルを作成し、安全なYAML構文・型を確認してください。') from None
    return validate_config(config)


def main(argv=None):
    parser = argparse.ArgumentParser(description='GitHub usage個人設定の安全な検証（値は表示しません）。')
    parser.add_argument('--config', help='Git管理外の個人YAMLパス')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f'設定エラー: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({'valid': True, 'version': config['version'], 'page': config['report']['page'],
        'kind': config['report']['kind'], 'period_mode': config['report']['period']['mode'],
        'notification_mode': config['notification']['mode'], 'provider': config['destination']['provider'],
        'transport': config['destination']['transport'], 'upload_mode': config['upload']['mode']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
