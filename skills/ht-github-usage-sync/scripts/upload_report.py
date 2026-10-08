#!/usr/bin/env python3
"""Optional fail-closed rclone transfer. Never acquires GitHub reports or writes a ledger."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from report_artifact import SafeArgumentParser, compare_files, fingerprint, private_path, validate
from validate_config import load_config, validate_config
from run_state import read_private

BACKENDS = {'google_drive': 'drive', 'onedrive': 'onedrive', 'sharepoint': 'onedrive',
            'dropbox': 'dropbox', 'box': 'box', 's3': 's3', 'gcs': 'googlecloudstorage'}


class TransferError(ValueError):
    def __init__(self, message, unverified=False):
        super().__init__(message)
        self.unverified = unverified


class ContentMismatch(TransferError):
    """Only a completed independent readback may authorize replacement."""


def destination_identity(destination):
    """Opaque stable identity; caller confirms the exact normalized destination."""
    d = dict(destination)
    d.setdefault('transport', 'browser')
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _run(argv):
    # No arbitrary flags, config dump, env overrides, stderr or URL logging.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('RCLONE_')}
    try:
        result = subprocess.run(['rclone', *argv, '--retries', '1', '--low-level-retries', '1'],
                                shell=False, capture_output=True, text=True, timeout=120,
                                check=False, env=env)
    except FileNotFoundError:
        raise TransferError('rclone is unavailable; use the browser guide or provision it separately.') from None
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise TransferError('Remote operation failed or timed out; do not blindly retry.') from None
    if result.returncode:
        raise TransferError('Remote operation failed; do not blindly retry.')
    return result.stdout


def _json(argv):
    try:
        return json.loads(_run(argv))
    except (ValueError, TypeError) as error:
        if isinstance(error, TransferError):
            raise
        raise TransferError('Remote returned invalid JSON; stop and inspect privately.') from None


def _folder(d):
    remote = d['remote'] + ':'
    if d['provider'] == 'google_drive':
        flags = ['--drive-root-folder-id', d['folder_id']]
        if 'shared_drive_id' in d:
            flags += ['--drive-team-drive', d['shared_drive_id']]
        return remote, flags
    if d['provider'] == 'box':
        return remote, ['--box-root-folder-id', d['folder_id']]
    path = d.get('folder_path', d.get('bucket', '') + '/' + d.get('prefix', ''))
    return remote + path, []


def _listing(folder, flags):
    items = _json(['lsjson', folder, *flags])
    if not isinstance(items, list) or any(not isinstance(i, dict) or not isinstance(i.get('Name'), str) or type(i.get('IsDir')) is not bool for i in items):
        raise TransferError('Remote directory listing is invalid; stop.')
    return items


def _preflight(d, folder, flags):
    # --long contains names/types (possibly descriptions); never print it.
    entries = []
    for line in _run(['listremotes', '--long']).splitlines():
        match = re.match(r'^([^\s:]+):\s+([a-z0-9]+)(?:\s|$)', line)
        if match and match.group(1) == d['remote']:
            entries.append(match.group(2))
    if entries != [BACKENDS[d['provider']]]:
        raise TransferError('Named remote backend does not match the configured provider.')
    stat = _json(['lsjson', folder, '--stat', *flags])
    if not isinstance(stat, dict) or stat.get('IsDir') is not True:
        raise TransferError('Destination must be an existing directory; no folders are created.')
    if d['provider'] in {'google_drive', 'box'}:
        # Root stats can be synthetic. Require explicit configured identity
        # confirmation AND independent successful directory enumeration below.
        if stat.get('ID') and stat['ID'] != d['folder_id']:
            raise TransferError('Destination directory identity differs from configured folder.')
    else:
        # Bucket backends can synthesize an empty directory for nonexistent
        # prefixes. Exact parent listing evidence is mandatory even if stat works.
        parent, name = folder.rsplit('/', 1) if '/' in folder else (d['remote'] + ':', d['folder_path'])
        matches = [i for i in _listing(parent, flags) if i['Name'] == name]
        if len(matches) != 1 or matches[0]['IsDir'] is not True:
            raise TransferError('Destination folder is absent or ambiguous in its parent listing.')
    return _listing(folder, flags)


def _target(items, filename):
    matches = [i for i in items if i['Name'] == filename]
    if len(matches) > 1 or matches and matches[0]['IsDir']:
        raise TransferError('Duplicate names or directory collision; preserve the original and stop.')
    if matches and matches[0].get('Path', filename) != filename:
        raise TransferError('Remote object path is not the exact registered filename.')
    return matches[0] if matches else None


def _readback(original, remote, flags, root):
    # A fresh 0700 directory isolates every readback, including failed downloads.
    directory = Path(tempfile.mkdtemp(prefix='readback-', dir=root))
    target = directory / 'report.csv'
    _run(['copyto', remote, str(target), *flags])
    if not target.is_file() or target.is_symlink():
        raise TransferError('Readback is missing or unsafe; do not mark verified.')
    target.chmod(0o600)
    if original.samefile(target):
        raise TransferError('Readback must be independent of the original.')
    source_hash, target_hash = fingerprint(original), fingerprint(target)
    if source_hash != target_hash:
        raise ContentMismatch('Completed readback differs from the original.')
    return compare_files(original, target)


def transfer(config, file, filename, kind, start_date, end_date, confirm_destination,
             readback_dir, state_dir, replace_target=None):
    """Upload validated original bytes, or verify and skip an identical existing file.

    No ledger changes. All command output is private and summaries omit targets.
    Concurrent remote writers must be excluded by the operator; rclone cannot
    provide a transaction across folder listing and upload.
    """
    c = validate_config(config)
    d = c['destination']
    if d['transport'] != 'rclone':
        raise TransferError('Browser transport requires references/cloud-destinations.md; no CLI transfer.')
    if confirm_destination != destination_identity(d):
        raise TransferError('Confirm the exact configured destination identity before transfer.')
    if not isinstance(filename, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\.csv', filename) or '..' in filename:
        raise TransferError('Use the fixed registered safe CSV filename; do not rename on resume.')
    original = private_path(file)
    metadata = validate(original, kind, start_date, end_date)
    ledger = read_private(state_dir)
    payload = ledger['payload']
    if (ledger['state'] not in {'validated', 'uploaded', 'uploaded_unverified'}
            or ledger['evidence'].get('pending_ids')
            or payload['upload_mode'] != c['upload']['mode']
            or payload['destination_id'] != destination_identity(d)
            or any(payload[k] != v for k, v in [('kind', kind), ('start_date', start_date), ('end_date', end_date)])
            or payload['page'] != ('ai_usage' if kind == 'ai_usage' else 'usage')):
        raise TransferError('Transfer must match the validated frozen ledger configuration.')
    matches = [i for i in payload['required_ids'] if ledger['filenames'][i] == filename
               and i in ledger['artifacts'] and ledger['artifacts'][i]['path'] == str(original)
               and ledger['artifacts'][i]['metadata'] == metadata]
    if len(matches) != 1:
        raise TransferError('Transfer must use the exact registered original and fixed filename.')
    root = private_path(readback_dir)
    if not root.is_dir() or root.stat().st_mode & 0o077:
        raise TransferError('Readback directory must exist with mode 0700 outside Git.')
    folder, flags = _folder(d)
    remote = folder + ('' if folder.endswith(':') else '/') + filename
    items = _preflight(d, folder, flags)
    existing = _target(items, filename)
    action = 'uploaded'
    if existing:
        try:
            _readback(original, remote, flags, root)
        except ContentMismatch:
            if c['upload']['mode'] != 'replace':
                raise TransferError('Archive collision differs or cannot be verified; never overwrite.') from None
            # Name-based copyto cannot pin an ID for Drive/Box. Fail closed
            # instead of pretending a checked ID guarantees the mutation target.
            if d['provider'] in {'google_drive', 'box'}:
                raise TransferError('ID-addressed replacement is not implemented; use browser exact-file confirmation.') from None
            if replace_target != remote:
                raise TransferError('Replacement requires explicit confirmation of the exact remote object key.') from None
            action = 'replaced'
        else:
            action = 'skipped'
    elif replace_target is not None:
        raise TransferError('Replacement target is absent; preserve the run and inspect privately.')
    if action != 'skipped':
        # Re-enumerate immediately before mutation. The immutable archive flag
        # provides a second guard against races; no sync/delete/mkdir is used.
        current = _target(_listing(folder, flags), filename)
        if current != existing:
            raise TransferError('Destination changed before upload; no mutation attempted.')
        if fingerprint(original) != {k: metadata[k] for k in ('bytes', 'sha256')}:
            raise TransferError('Original changed before upload; start a new run.')
        write_flags = ['--immutable', '--ignore-times'] if action == 'uploaded' else ['--ignore-times']
        try:
            _run(['copyto', str(original), remote, *flags, *write_flags])
        except ValueError:
            # Mutation outcome may be ambiguous. Inspect once, never retry the
            # write and never call this verified based on command success alone.
            try:
                _target(_listing(folder, flags), filename)
            except ValueError:
                pass
            raise TransferError('Upload outcome is unverified; inspect remote state before retry.', unverified=True) from None
    try:
        after = _target(_listing(folder, flags), filename)
        if after is None or existing and after.get('ID') != existing.get('ID'):
            raise TransferError('Uploaded object identity is absent or changed.')
        match = _readback(original, remote, flags, root)
        final = _target(_listing(folder, flags), filename)
        if final != after:
            raise TransferError('Object changed during readback.')
        if fingerprint(original) != {k: metadata[k] for k in ('bytes', 'sha256')}:
            raise TransferError('Original changed during transfer.')
    except (ValueError, OSError):
        raise TransferError('Readback or object identity is unverified; preserve originals and inspect privately.', unverified=action != 'skipped') from None
    return {'provider': d['provider'], 'action': action, 'bytes': match['bytes'],
            'sha256': match['sha256'], 'verified': True}


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    for name in ['config', 'file', 'filename', 'kind', 'start-date', 'end-date', 'confirm-destination', 'readback-dir', 'state-dir']:
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--replace-target')
    args = parser.parse_args(argv)
    try:
        result = transfer(load_config(args.config), args.file, args.filename, args.kind,
                          args.start_date, args.end_date, args.confirm_destination,
                          args.readback_dir, args.state_dir, args.replace_target)
    except (ValueError, OSError):
        # Never echo raw errors, file paths, remote IDs, stderr or signed URLs.
        print(json.dumps({'verified': False, 'action': 'blocked_or_unverified',
                          'error': 'Transfer not verified; inspect private configuration and remote state. Do not blindly retry.'}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
