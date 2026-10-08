# Local execution ledger (schema version 1)

The ledger records operator observations, not browser or cloud API proof. It never
requests a report, reads mail, uploads, or downloads anything itself. Full billing
page URLs (including query tabs), report links, signed URLs, and email bodies stay
in private configuration/browser context, never in ledger evidence.

## Executable synthetic smoke test

Run from this repository root. This exercises only local CSV validation and
readback comparison; the synthetic destination is **not** a cloud upload claim.
All identifiers and records below are synthetic. Nothing contacts GitHub or S3.

```bash
set -euo pipefail
umask 077
export SCRIPTS="$PWD/skills/ht-github-usage-sync/scripts"
export DEMO="$(mktemp -d "${TMPDIR:-/tmp}/usage-ledger.XXXXXXXX")"
export STATE="$DEMO/run"
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" init \
  --run-id synthetic-january --github-account synthetic-account \
  --enterprise synthetic-enterprise --page usage --kind detailed \
  --start-date 2026-01-01 --end-date 2026-01-31 \
  --destination-id synthetic-destination --upload-mode archive --required-id first
# Python integration can use generated names without printing them.
PYTHONPATH="$SCRIPTS" python3 - <<'PY'
import csv, os
from pathlib import Path
import run_state
base = Path(os.environ['DEMO'])
data = run_state.show(os.environ['STATE'])
original = base / data['filenames']['first']
with original.open('w', newline='') as stream:
    writer = csv.writer(stream)
    writer.writerow(['date','product','sku','quantity','gross_amount','net_amount','organization','repository','username','workflow_path'])
    writer.writerow(['2026-01-03','Actions','synthetic-sku','1','1','1','synthetic-org','synthetic-repo','synthetic-user','.github/workflows/synthetic.yml'])
original.chmod(0o600)
readback = base / 'readback.csv'
readback.write_bytes(original.read_bytes())
readback.chmod(0o600)
# Local smoke test only: these booleans represent synthetic observations.
run_state.advance(os.environ['STATE'], 'downloaded', {'user_link': True, 'notification_verified': False, 'source_correspondence': True})
run_state.register_artifact(os.environ['STATE'], 'first', original)
PY
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" advance validated
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" record-destination first \
  --identity synthetic-destination --url synthetic-s3:reports/january.csv --confirmed
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" advance uploaded
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" record-readback first "$DEMO/readback.csv"
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" advance verified
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" show
# Temporary private data remains at $DEMO; remove it when no longer needed.
```

Successful console output contains only state, run SHA256, counts, artifact hashes
and `mail_verified`. It contains no account, enterprise, run ID, file IDs,
generated names, paths, destination identity, or cloud target.

## Real browser request route (operator-controlled)

Create a **new** run with the init command above, using the operator-confirmed
logged-in GitHub account and actual private configuration. `page=usage` pairs
with `detailed` or `summarized`; `page=ai_usage` pairs only with `kind=ai_usage`.
Use the exact confirmed account spelling consistently across all enterprise runs.
The account key is an identity, not a token or credential.

All runs for the account must use one shared account reservation directory. The
default is sibling `.accounts`, mode 0700; account filenames are SHA256(account)
and files are mode 0600, outside Git. For different parent directories, supply the
same `init --account-lock-dir /private/shared/.accounts` explicitly. Its path is
frozen; resuming init requires the same selection. Never use separate reservation
directories to evade an outstanding request. Reservation ownership is the canonical
`state.json` path plus run hash, not the payload hash alone. Identical payloads in
another directory and copied pending ledgers cannot claim that reservation;
resume only in the exact original directory. Malformed/legacy owners fail closed
and require manual recovery.

Before clicking Submit/Request in the browser, record and reserve the attempt:

```bash
ATTEMPT="$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')"
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" advance request_attempted \
  --evidence "{\"request_attempted_at\":\"$ATTEMPT\"}"
```

Only after that succeeds may the operator click **once**. If the browser outcome
is unknown, stop in `request_attempted`; the reservation survives CLI exit and
blocks another run for that account, even for another enterprise. Do not click
again. A crash after reservation but before ledger write deliberately leaves an
orphan reservation requiring manual inspection; never overwrite it automatically.

After observing accepted submission, record the actual observation timestamp:

```bash
ACCEPTED="$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')"
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" advance requested \
  --evidence "{\"request_observed\":true,\"request_accepted_at\":\"$ACCEPTED\"}"
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" advance waiting_for_link
```

Missing acceptance fails without discarding the attempt or reservation. Timestamps
must be timezone-aware; acceptance cannot precede attempt. These are observed
browser facts, not server proofs. Record `notification_verified=true` only after
checking the authenticated notification, account, enterprise, report kind and
period. Download in the browser; do not persist the link or message body.

```bash
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" advance downloaded \
  --evidence '{"source_correspondence":true,"notification_verified":true}'
```

This releases the account reservation only after persisting the downloaded state.
Register every completed original with `register-artifact FILE_ID PRIVATE_FILE`,
then `advance validated`. Originals and containing directories must be private
(0600 files, 0700 directories) outside Git. Use `show()` in Python for the stable
names, and do not rename on resume.

A direct operator-supplied report link can instead go from prepared to downloaded:

```bash
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" advance downloaded \
  --evidence '{"user_link":true,"notification_verified":false,"source_correspondence":true}'
```

No request reservation is made on that direct route. Source correspondence and
its route proof remain required at validation/verification and on verified reads.

## Pending, cancellation and recovery

```bash
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" advance blocked_by_pending \
  --evidence '{"pending_ids":["first"]}'
# After the browser download completes; preserve the existing route evidence:
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" advance downloaded \
  --evidence '{"pending_ids":[],"source_correspondence":true}'
```

The last example assumes accepted-request proof already exists; a direct route
must also supply/preserve `user_link=true, notification_verified=false`. Leaving
blocked requires explicit `pending_ids=[]`; it cannot bypass request acceptance
or direct proof. Reservations are not released by blocking. A resumed accepted
request must not be submitted again.

Only explicit observed expiry/cancellation resolves an unknown/pending request:

```bash
RESOLVED="$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')"
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" advance cancelled \
  --evidence "{\"request_cancelled_observed\":true,\"request_resolved_at\":\"$RESOLVED\"}"
# For observed expiry use state expired and request_expired_observed=true.
# If currently blocked, include pending_ids=[] only after resolving those files.
```

Expired/cancelled are terminal; create a new run to request again. Do not infer
expiry from wall-clock passage. Writer `.lock` recovery is separate from persistent
account reservation recovery: inspect private owner ledger, browser outcome and
active writers first. Never remove/replace a reservation belonging to another run.
If a release was interrupted after a terminal/downloaded write, manually reconcile
that exact owner reservation only after confirming the persisted evidence.

## Destination and readback contract

The payload requires `upload_mode=archive|replace` and includes it in the run hash.
CLI `init --upload-mode` defaults to archive; resume must keep the original mode.
For rclone, freeze `destination_id` as
`upload_report.destination_identity(normalized_destination)` when initializing.
`upload_report.transfer(..., readback_dir, state_dir, replace_target=None)` reads
that private ledger and requires validated/uploaded/uploaded_unverified state,
no pending IDs, matching page/kind/dates, frozen destination and mode, and the
exact registered original bytes/path plus generated filename. It never updates
the ledger. Changing archive to replace requires a new run, not edited config.

Actually upload every validated original through the configured cloud integration,
then record its **exact** stable identity using `record-destination FILE_ID
--identity DESTINATION_ID --url TARGET --confirmed`. `url` remains the API/CLI
parameter name but accepts either unsigned HTTPS without query/fragment/userinfo,
or `remote:key` (for example `synthetic-s3:reports/january.csv`). Remote keys are
bounded relative paths of letters/digits/underscore/dot/slash/hyphen; no traversal,
encoded query strings, token flags, whitespace or control characters. Target and
identity are stored privately, unchanged, never printed. Signed download URLs
are not stable destination identities.

After `advance uploaded`, download each stored object again into a separate private
file; `record-readback FILE_ID PRIVATE_READBACK` compares bytes and SHA256.
Originals/hardlinks cannot serve as readbacks. `advance verified` requires all
originals, destination confirmations, independent matching readbacks, source
proof and no pending IDs/files. Use `uploaded_unverified` if upload exists but
readback proof is not yet complete. `show` rechecks verified evidence and files.

Python API: `init(directory, payload, account_lock_dir=None)`, `show(directory)`,
`advance(directory, state, evidence=None)`, `register_artifact(directory, file_id,
path)`, `record_destination(directory, file_id, identity, url, confirmed)`,
`record_readback(directory, file_id, path)`. Returns are integration data, **not**
console-safe. `show()` preserves generated filenames but strips original/readback
paths and target URL; deliberate `read_private(directory)` includes all private
records. Never log either return value. CLI emits only the redacted summary.
