#!/usr/bin/env python3
"""Private local execution ledger. Browser actions are operator observations only."""

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit

from report_artifact import PROFILES, PARTIAL_SUFFIXES, SafeArgumentParser, compare_files, iso_date, private_path, validate

VERSION = 1
PAYLOAD_KEYS = {'run_id', 'github_account', 'enterprise', 'page', 'kind', 'start_date', 'end_date', 'destination_id', 'upload_mode', 'required_ids'}
STATE_KEYS = {'version', 'run_key', 'payload', 'account_lock_dir', 'filenames', 'state', 'evidence', 'artifacts', 'destinations', 'readbacks'}
TIMESTAMP_KEYS = {'request_attempted_at', 'request_accepted_at', 'request_resolved_at'}
EVIDENCE_KEYS = {'user_link', 'notification_verified', 'source_correspondence', 'request_observed', 'link_observed', 'pending_ids', 'request_cancelled_observed', 'request_expired_observed'} | TIMESTAMP_KEYS
TRANSITIONS = {
    'prepared': {'request_attempted', 'downloaded', 'blocked_by_pending'},
    'request_attempted': {'requested', 'blocked_by_pending', 'expired', 'cancelled'},
    'requested': {'waiting_for_link', 'downloaded', 'blocked_by_pending', 'expired', 'cancelled'},
    'waiting_for_link': {'downloaded', 'blocked_by_pending', 'expired', 'cancelled'},
    'blocked_by_pending': {'request_attempted', 'requested', 'waiting_for_link', 'downloaded', 'expired', 'cancelled'},
    'downloaded': {'validated', 'blocked_by_pending'},
    'validated': {'uploaded', 'uploaded_unverified', 'blocked_by_pending'},
    'uploaded': {'verified', 'uploaded_unverified', 'blocked_by_pending'},
    'uploaded_unverified': {'uploaded', 'verified', 'blocked_by_pending'},
    'verified': set(),
    'expired': set(),
    'cancelled': set(),
}


def _unsigned_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value):
        raise ValueError('Use a bounded unsigned HTTPS identity URL.')
    try:
        parts = urlsplit(value)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError
    except ValueError:
        raise ValueError('Use an unsigned HTTPS identity URL without query or fragment.') from None
    return value


def _payload(payload):
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_KEYS:
        raise ValueError('Supply exactly the documented run payload keys.')
    for key in PAYLOAD_KEYS - {'required_ids'}:
        value = payload[key]
        if not isinstance(value, str) or not value.strip() or len(value) > 2048 or any(ord(c) < 32 for c in value):
            raise ValueError('Run payload fields must be bounded nonempty strings.')
    if payload['upload_mode'] not in {'archive', 'replace'}:
        raise ValueError('Select archive or replace upload mode.')
    if payload['kind'] not in PROFILES:
        raise ValueError('Select a supported billing report kind.')
    if iso_date(payload['start_date']) > iso_date(payload['end_date']):
        raise ValueError('Start date must not follow end date.')
    if payload['page'] != ('ai_usage' if payload['kind'] == 'ai_usage' else 'usage'):
        raise ValueError('Use symbolic page usage for billing or ai_usage for AI usage; no page URLs.')
    ids = payload['required_ids']
    if not isinstance(ids, list) or not ids or len(ids) > 100 or any(not isinstance(i, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', i) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Use unique safe required file IDs (letters, digits, underscore, hyphen).')
    # Copy caller data so subsequent mutation cannot change the original payload.
    return json.loads(json.dumps(payload))


def _key(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _root(value, create=False):
    root = private_path(value)
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not root.is_dir() or root.stat().st_mode & 0o077:
        raise ValueError('Use a private ledger directory with mode 0700 outside Git.')
    return root


@contextmanager
def _lock(root):
    lock = root / '.lock'
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError('Ledger is locked. Confirm no active writer before manual stale-lock removal.') from None
    try:
        os.write(fd, b'Exclusive local ledger writer; stale recovery is manual.\n')
        os.fsync(fd)
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        lock.unlink()


def _atomic(root, data):
    fd, name = tempfile.mkstemp(prefix='.state-', suffix='.tmp', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, ensure_ascii=True, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, root / 'state.json')
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _evidence(value, ids):
    if not isinstance(value, dict) or not set(value) <= EVIDENCE_KEYS:
        raise ValueError('Only documented bounded observation fields are accepted; never store links or message bodies.')
    for key, item in value.items():
        if key == 'pending_ids':
            if not isinstance(item, list) or any(not isinstance(i, str) or i not in ids for i in item) or len(item) != len(set(item)):
                raise ValueError('Pending IDs must be unique required file IDs.')
        elif key in TIMESTAMP_KEYS:
            _timestamp(item)
        elif type(item) is not bool:
            raise ValueError('Observation evidence fields must be explicit booleans.')


def _timestamp(value):
    try:
        if not isinstance(value, str) or len(value) > 64 or 'T' not in value:
            raise ValueError
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise ValueError('Supply a bounded timezone-aware ISO timestamp.') from None


def _stable_target(value):
    if isinstance(value, str) and value.startswith('https://'):
        return _unsigned_url(value)
    if not isinstance(value, str) or len(value) > 2048 or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}:[A-Za-z0-9_./-]+', value):
        raise ValueError('Use unsigned HTTPS or stable remote:key with no tokens, flags, or control characters.')
    remote, key = value.split(':', 1)
    if remote.lower() in {'http', 'https', 's3'} and key.startswith('/'):
        raise ValueError('Use a configured remote name and stable relative file key.')
    if key.startswith('/') or any(part in {'', '.', '..'} for part in key.split('/')):
        raise ValueError('Use a stable relative file key without traversal.')
    return value


def _source_gate(data):
    ev = data['evidence']
    if ev.get('source_correspondence') is not True:
        raise ValueError('Record explicit source correspondence observation.')
    if 'request_attempted_at' in ev:
        _accepted_gate(data)
    elif ev.get('user_link') is not True or ev.get('notification_verified') is not False:
        raise ValueError('Direct route requires user_link=true and notification_verified=false.')


def _accepted_gate(data):
    ev = data['evidence']
    if ev.get('request_observed') is not True or not TIMESTAMP_KEYS - {'request_resolved_at'} <= set(ev):
        raise ValueError('Request requires observed acceptance and attempt/acceptance timestamps.')
    if _timestamp(ev['request_accepted_at']) < _timestamp(ev['request_attempted_at']):
        raise ValueError('Acceptance must not precede the recorded attempt.')


def _account_file(data):
    root = _root(data['account_lock_dir'])
    digest = hashlib.sha256(data['payload']['github_account'].encode()).hexdigest()
    return root / (digest + '.json')


def _reservation(data, action, root):
    file = _account_file(data)
    owner = {'run_key': data['run_key'], 'ledger_path': str(root / 'state.json')}
    # A shared writer lock serializes ownership checks and release across runs.
    with _lock(file.parent):
        if file.exists() or file.is_symlink():
            if file.is_symlink() or not file.is_file() or file.stat().st_mode & 0o077 or file.stat().st_size > 1024:
                raise ValueError('Invalid account reservation; recover manually without overwriting.')
            try:
                current = json.loads(file.read_text())
            except (ValueError, UnicodeError):
                raise ValueError('Invalid account reservation; recover manually.') from None
            if (not isinstance(current, dict) or set(current) != {'run_key', 'ledger_path'}
                    or not isinstance(current['run_key'], str) or not re.fullmatch(r'[0-9a-f]{64}', current['run_key'])
                    or not isinstance(current['ledger_path'], str) or len(current['ledger_path']) > 4096
                    or not Path(current['ledger_path']).is_absolute()
                    or Path(current['ledger_path']).name != 'state.json'
                    or str(Path(current['ledger_path']).resolve()) != current['ledger_path']):
                raise ValueError('Invalid account reservation owner; recover manually.')
            if current != owner:
                raise ValueError('Account has a different outstanding run; resolve it before another request.')
            if action == 'release':
                file.unlink()
            return
        if action == 'check':
            raise ValueError('Pending request reservation is missing; recover manually.')
        if action == 'reserve':
            fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(owner, stream)
                stream.flush()
                os.fsync(stream.fileno())
        directory = os.open(file.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _read(root):
    file = root / 'state.json'
    if file.is_symlink() or not file.is_file() or file.stat().st_mode & 0o077 or file.stat().st_size > 1024 * 1024:
        raise ValueError('Ledger must be a bounded private regular file (0600).')
    try:
        data = json.loads(file.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError):
        raise ValueError('Ledger JSON is invalid; preserve it and recover manually.') from None
    if not isinstance(data, dict) or set(data) != STATE_KEYS or type(data['version']) is not int or data['version'] != VERSION or not isinstance(data['state'], str) or data['state'] not in TRANSITIONS:
        raise ValueError('Unknown ledger version, keys, or state; recover manually.')
    payload = _payload(data['payload'])
    ids = payload['required_ids']
    if data['run_key'] != _key(payload) or data['filenames'] != {i: 'usage-' + data['run_key'][:12] + '-' + i + '.csv' for i in ids}:
        raise ValueError('Ledger original run identity was changed; recover manually.')
    _evidence(data['evidence'], ids)
    _root(data['account_lock_dir'])
    if data['state'] in {'request_attempted', 'requested', 'waiting_for_link'}:
        if 'request_attempted_at' not in data['evidence']:
            raise ValueError('Pending state requires recorded attempt evidence.')
        _reservation(data, 'check', root)
    if data['state'] in {'requested', 'waiting_for_link'}:
        _accepted_gate(data)
    schemas = {'artifacts': {'path', 'metadata'}, 'destinations': {'identity', 'url', 'confirmed'}, 'readbacks': {'path', 'bytes', 'sha256'}}
    for bucket, keys in schemas.items():
        records = data[bucket]
        if not isinstance(records, dict) or not set(records) <= set(ids) or any(not isinstance(r, dict) or set(r) != keys for r in records.values()):
            raise ValueError('Unknown ledger record keys; recover manually.')
    metadata_keys = {'bytes', 'sha256', 'rows', 'min_date_utc', 'max_date_utc', 'kind', 'start_date', 'end_date'}
    if payload['kind'] == 'detailed':
        metadata_keys.add('workflow_rows')
    for record in data['artifacts'].values():
        meta = record['metadata']
        if not isinstance(record['path'], str) or not isinstance(meta, dict) or set(meta) != metadata_keys:
            raise ValueError('Unknown artifact metadata; recover manually.')
        _hash_record(meta)
        if type(meta['rows']) is not int or meta['rows'] < 1 or any(meta[k] != payload[k] for k in ('kind', 'start_date', 'end_date')):
            raise ValueError('Artifact metadata does not match this frozen run.')
        if not iso_date(payload['start_date']) <= iso_date(meta['min_date_utc']) <= iso_date(meta['max_date_utc']) <= iso_date(payload['end_date']):
            raise ValueError('Artifact date metadata is outside the explicit bounds.')
        if 'workflow_rows' in meta and (type(meta['workflow_rows']) is not int or not 0 <= meta['workflow_rows'] <= meta['rows']):
            raise ValueError('Invalid workflow row metadata.')
    for file_id in data['destinations']:
        _destination(data, file_id)
    for record in data['readbacks'].values():
        if not isinstance(record['path'], str):
            raise ValueError('Invalid readback path record.')
        _hash_record(record)
    return data


def _hash_record(record):
    if type(record['bytes']) is not int or record['bytes'] < 1 or not isinstance(record['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', record['sha256']):
        raise ValueError('Invalid artifact byte or SHA256 evidence.')


def _public(data):
    """Python integration view, not safe for stdout; use the CLI summary instead."""
    result = json.loads(json.dumps(data))
    for bucket in ('artifacts', 'readbacks'):
        for record in result[bucket].values():
            record.pop('path', None)
    for record in result['destinations'].values():
        record.pop('url', None)
    return result


def _summary(data):
    return {'state': data['state'], 'run_key': data['run_key'],
            'required_count': len(data['payload']['required_ids']),
            'artifact_count': len(data['artifacts']), 'destination_count': len(data['destinations']),
            'readback_count': len(data['readbacks']), 'pending_count': len(data['evidence'].get('pending_ids', [])),
            'mail_verified': data['evidence'].get('notification_verified') is True,
            'sha256': sorted({r['metadata']['sha256'] for r in data['artifacts'].values()})}


def init(directory, payload, account_lock_dir=None):
    """Create one run directory, or resume only with exactly its frozen payload."""
    payload = _payload(payload)
    root = _root(directory, create=True)
    accounts = _root(account_lock_dir if account_lock_dir is not None else root.parent / '.accounts', create=True)
    if accounts == root or root in accounts.parents:
        raise ValueError('Account reservations must be shared outside the per-run ledger directory.')
    with _lock(root):
        if (root / 'state.json').exists() or (root / 'state.json').is_symlink():
            data = _read(root)
            if data['payload'] != payload:
                raise ValueError('Resume payload differs; use the original configuration or a new run directory.')
            if data['account_lock_dir'] != str(accounts):
                raise ValueError('Resume must use the frozen account reservation directory.')
            if data['state'] == 'verified':
                _gate(data, verified=True)
        else:
            run_key = _key(payload)
            # Generate names once. Resume reads these names; it never renames files.
            data = dict(version=VERSION, run_key=run_key, payload=payload, account_lock_dir=str(accounts), filenames={i: 'usage-' + run_key[:12] + '-' + i + '.csv' for i in payload['required_ids']}, state='prepared', evidence={'pending_ids': []}, artifacts={}, destinations={}, readbacks={})
            _atomic(root, data)
        return _public(data)


def show(directory):
    return _public(read_private(directory))


def read_private(directory):
    """Explicit private API: paths, filenames, targets; never print its return value."""
    root = _root(directory)
    with _lock(root):
        data = _read(root)
        if data['state'] == 'verified':
            _gate(data, verified=True)
        return data


def _id(data, file_id):
    if file_id not in data['payload']['required_ids']:
        raise ValueError('File ID is not part of this frozen run.')


def _artifact(data, file_id):
    if file_id not in data['artifacts']:
        raise ValueError('Register and validate every required artifact first.')
    record = data['artifacts'][file_id]
    payload = data['payload']
    current = validate(record['path'], payload['kind'], payload['start_date'], payload['end_date'])
    if current != record['metadata']:
        raise ValueError('Original artifact changed; preserve it and start a new run.')
    return record


def _destination(data, file_id):
    record = data['destinations'].get(file_id)
    if not record or record['identity'] != data['payload']['destination_id'] or record['confirmed'] is not True:
        raise ValueError('Confirm the explicit configured destination identity for every file.')
    _stable_target(record['url'])


def _gate(data, uploaded=False, verified=False):
    _source_gate(data)
    if data['evidence'].get('pending_ids'):
        raise ValueError('Pending downloads remain; do not proceed.')
    for file_id in data['payload']['required_ids']:
        artifact = _artifact(data, file_id)
        # Browser partial downloads beside an original are a fail-closed gate.
        if any(p.suffix.lower() in PARTIAL_SUFFIXES for p in Path(artifact['path']).parent.iterdir()):
            raise ValueError('Pending download files remain in the artifact directory.')
        if uploaded or verified:
            _destination(data, file_id)
        if verified:
            readback = data['readbacks'].get(file_id)
            if not readback:
                raise ValueError('Read back and compare every uploaded file before verification.')
            _independent_readback(artifact['path'], readback['path'])
            if any(p.suffix.lower() in PARTIAL_SUFFIXES for p in Path(readback['path']).parent.iterdir()):
                raise ValueError('Pending download files remain in the readback directory.')
            match = compare_files(artifact['path'], readback['path'])
            if any(match[key] != readback[key] for key in ('bytes', 'sha256')):
                raise ValueError('Readback evidence changed; do not mark verified.')


def advance(directory, state, evidence=None):
    root = _root(directory)
    with _lock(root):
        data = _read(root)
        if state not in TRANSITIONS or state not in TRANSITIONS[data['state']]:
            raise ValueError('Invalid state transition; use the documented execution sequence.')
        evidence = {} if evidence is None else evidence
        _evidence(evidence, data['payload']['required_ids'])
        if 'request_attempted_at' in evidence and state != 'request_attempted':
            raise ValueError('Record the request attempt only before browser submission.')
        if any(k in data['evidence'] and data['evidence'][k] != evidence[k] for k in TIMESTAMP_KEYS & set(evidence)):
            raise ValueError('Request timestamps are immutable.')
        if 'request_accepted_at' in evidence and state != 'requested':
            raise ValueError('Record acceptance only when advancing to requested.')
        already_attempted = 'request_attempted_at' in data['evidence']
        data['evidence'].update(evidence)
        if data['state'] == 'blocked_by_pending' and state != 'blocked_by_pending' and evidence.get('pending_ids') != []:
            raise ValueError('Explicitly resolve pending IDs before leaving blocked_by_pending.')
        if state == 'request_attempted':
            if data['evidence'].get('pending_ids'):
                raise ValueError('Do not submit a request while downloads are pending.')
            if 'request_attempted_at' not in evidence or already_attempted:
                raise ValueError('A request may be attempted only once per run.')
            _reservation(data, 'reserve', root)
        elif state in {'requested', 'waiting_for_link'}:
            _accepted_gate(data)
            _reservation(data, 'check', root)
        if state == 'downloaded':
            _source_gate(data)
            if data['evidence'].get('pending_ids'):
                raise ValueError('Resolve pending downloads before downloaded.')
        if state in {'expired', 'cancelled'}:
            if not already_attempted or data['evidence'].get('request_' + state + '_observed') is not True or 'request_resolved_at' not in evidence:
                raise ValueError('Manual resolution requires an attempted request, explicit observation and resolution timestamp.')
            if _timestamp(evidence['request_resolved_at']) < _timestamp(data['evidence']['request_attempted_at']):
                raise ValueError('Resolution must not precede the request attempt.')
            _reservation(data, 'check', root)
        if state == 'blocked_by_pending' and not data['evidence'].get('pending_ids'):
            raise ValueError('Record the pending required file IDs.')
        if state in {'validated', 'uploaded', 'uploaded_unverified', 'verified'}:
            _gate(data, uploaded=state in {'uploaded', 'uploaded_unverified'}, verified=state == 'verified')
        data['state'] = state
        _atomic(root, data)
        if state in {'downloaded', 'expired', 'cancelled'} and 'request_attempted_at' in data['evidence']:
            _reservation(data, 'release', root)
        return _public(data)


def register_artifact(directory, file_id, path):
    root = _root(directory)
    with _lock(root):
        data = _read(root)
        _id(data, file_id)
        if data['state'] not in {'downloaded', 'validated'}:
            raise ValueError('Register artifacts only after downloaded and before upload.')
        payload = data['payload']
        resolved = private_path(path)
        record = {'path': str(resolved), 'metadata': validate(resolved, payload['kind'], payload['start_date'], payload['end_date'])}
        old = data['artifacts'].get(file_id)
        if old and old != record:
            raise ValueError('Original artifact is immutable; use a new run for replacements.')
        data['artifacts'][file_id] = record
        _atomic(root, data)
        return _public(data)


def record_destination(directory, file_id, identity, url, confirmed):
    root = _root(directory)
    with _lock(root):
        data = _read(root)
        _id(data, file_id)
        if data['state'] not in {'validated', 'uploaded', 'uploaded_unverified'}:
            raise ValueError('Record destination observations only after validation and before verification.')
        _artifact(data, file_id)
        if identity != data['payload']['destination_id'] or confirmed is not True:
            raise ValueError('Explicit configured destination identity and confirmation are required.')
        record = {'identity': identity, 'url': _stable_target(url), 'confirmed': True}
        if file_id in data['destinations'] and data['destinations'][file_id] != record:
            raise ValueError('Destination evidence is immutable; use a new run for changes.')
        data['destinations'][file_id] = record
        _atomic(root, data)
        return _public(data)


def _independent_readback(original, readback):
    source, target = private_path(original), private_path(readback)
    if source.samefile(target):
        raise ValueError('Readback must be a separate downloaded file, not the original or a hardlink.')


def record_readback(directory, file_id, path):
    root = _root(directory)
    with _lock(root):
        data = _read(root)
        _id(data, file_id)
        if data['state'] not in {'validated', 'uploaded', 'uploaded_unverified'}:
            raise ValueError('Record readback only after validation and before verification.')
        original = _artifact(data, file_id)
        _destination(data, file_id)
        resolved = private_path(path)
        _independent_readback(original['path'], resolved)
        match = compare_files(original['path'], resolved)
        data['readbacks'][file_id] = {'path': str(resolved), 'bytes': match['bytes'], 'sha256': match['sha256']}
        _atomic(root, data)
        return _public(data)


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('init')
    create.add_argument('--account-lock-dir', help='Frozen shared private reservations; default sibling .accounts')
    for name in sorted(PAYLOAD_KEYS - {'required_ids', 'upload_mode'}):
        create.add_argument('--' + name.replace('_', '-'), required=True)
    create.add_argument('--upload-mode', choices=['archive', 'replace'], default='archive')
    create.add_argument('--required-id', dest='required_ids', action='append', required=True)
    commands.add_parser('show')
    step = commands.add_parser('advance')
    step.add_argument('state', choices=TRANSITIONS)
    step.add_argument('--evidence', default='{}', help='JSON containing only documented boolean observations and pending_ids')
    artifact = commands.add_parser('register-artifact')
    artifact.add_argument('file_id')
    artifact.add_argument('file')
    destination = commands.add_parser('record-destination')
    destination.add_argument('file_id')
    destination.add_argument('--identity', required=True)
    destination.add_argument('--url', required=True, help='Unsigned stable HTTPS or configured remote:key file identity')
    destination.add_argument('--confirmed', action='store_true', required=True)
    readback = commands.add_parser('record-readback')
    readback.add_argument('file_id')
    readback.add_argument('file')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            result = init(args.state_dir, {key: getattr(args, key) for key in PAYLOAD_KEYS}, args.account_lock_dir)
        elif args.command == 'show':
            result = show(args.state_dir)
        elif args.command == 'advance':
            try:
                evidence = json.loads(args.evidence)
            except ValueError:
                raise ValueError('Observation evidence must be valid JSON.') from None
            result = advance(args.state_dir, args.state, evidence)
        elif args.command == 'register-artifact':
            result = register_artifact(args.state_dir, args.file_id, args.file)
        elif args.command == 'record-destination':
            result = record_destination(args.state_dir, args.file_id, args.identity, args.url, args.confirmed)
        else:
            result = record_readback(args.state_dir, args.file_id, args.file)
        print(json.dumps(_summary(result), sort_keys=True))
        return 0
    except (ValueError, OSError) as error:
        print(json.dumps({'error': str(error) if isinstance(error, ValueError) else 'Local ledger operation failed; check private paths and retry safely.'}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
