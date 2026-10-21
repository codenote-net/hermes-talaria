# Local execution ledger (schema version 1, version 2 and version 3)

The ledger records operator observations, not browser or cloud API proof. It never
requests a report, reads mail, uploads, or downloads anything itself. Full billing
page URLs (including query tabs), report links, signed URLs, and email bodies stay
in private configuration/browser context, never in ledger evidence.

## Deployment, payload and legacy compatibility

Configuration remains version 1, independently of the ledger version. New
Enterprise Cloud and Organization runs should use explicit `deployment`:
`enterprise_cloud` requires only `enterprise`; `organization` requires only
`organization`. The selected slug uses letters/digits and internal hyphens;
the unused slug key is prohibited even when null. New cloud ledgers are version 2.

Common cloud payload keys are exactly `run_id`, `github_account`, `page`, `kind`,
`start_date`, `end_date`, `destination_id`, `upload_mode`, and `required_ids`.
Version 2 adds `deployment` and exactly its selected slug key. Version 1 adds
only `enterprise`, with no `deployment`. The Python `init` API accepts both
shapes; all other keys are rejected. All fields except the unique nonempty
`required_ids` array are bounded nonempty strings. Dates and page/kind pairing
remain unchanged. Do not add unused null keys to a Python or CLI payload.

CLI: `init --deployment organization --organization example-org` creates
version 2; `init --deployment enterprise_cloud --enterprise example-enterprise`
also creates version 2. `--enterprise` and `--organization` are mutually
exclusive and must match deployment. Organization requires explicit deployment.
The old `init --enterprise example-enterprise` command without `--deployment`
and the old Python payload remain version 1 for legacy compatibility.

Read/resume a legacy ledger as Enterprise Cloud without injecting deployment
into its payload or migrating its version, hash, filenames or reservation.
The canonical payload SHA256 algorithm and filename derivation stay unchanged.
Changing target or deployment requires a new run, not edited ledger/config.
The shared reservation filename still depends only on `github_account`, never
deployment/slug. All Enterprise and Organization runs for the same account
must use the same spelling and reservation directory across both versions.
Console summaries never expose organization/enterprise identifiers.

## Explicit local-only mode

Configuration version 1 adds top-level `mode: local_only` (default: `cloud`).
Omit both `destination` and `upload`, even null/empty mappings. Local-only is not
a storage provider and does not create a fake cloud destination. The default
cloud configuration still requires a destination. Obtain user approval before
changing mode, and use a new run rather than altering a frozen payload.

Local-only ledger version 3 has exactly these payload keys: `mode` (only
`local_only`), `run_id`, `github_account`, `deployment`, exactly its selected
`enterprise` or `organization` slug, `page`, `kind`, `start_date`, `end_date`, and
`required_ids`. It prohibits `destination_id` and `upload_mode`, even null.
Explicit deployment is mandatory. CLI `init --mode local_only` accepts no
`--destination-id` or `--upload-mode`. Default/explicit `--mode cloud` retains
the old version 1/2 payload shapes; no mode key is injected into cloud payloads.
Old payload/hash/filenames and on-disk bytes remain unchanged on read/resume.

Reservation, request acceptance, user_link/browser_mail, download, pending and
CSV gates are identical in both modes. Share the same account reservation root
across modes as well as deployments. After registering every original, advance
to `validated`, then `local_validated`. This local-only terminal state rechecks
source evidence, all original bytes and CSV validity, and no pending IDs/partial
files; `show` and resumed `init` recheck it too. Cloud runs cannot use this state.
Do not call record-destination, record-readback, or advance uploaded,
uploaded_unverified or verified in local-only mode: these operations are rejected,
as are persisted cloud states/evidence in a local ledger. The upload adapter
rejects either local-only configuration or a local-only ledger before remote calls.

Console summaries include `mode` and `cloud_verified`; local-only always reports
`cloud_verified=false`. Report cloud storage as out of scope, not verified.
Local validation does not establish browser E2E, email verification, every-day
coverage, or finalized billing. With user_link, preserve
`user_link=true, notification_verified=false` even after an accepted request.

## Executable synthetic smoke test

Run from this repository root. This exercises only local CSV validation with no
destination or readback. All identifiers and records below are synthetic.
Nothing contacts GitHub or cloud storage; it is not real browser evidence.

```bash
set -euo pipefail
umask 077
export SCRIPTS="$PWD/skills/ht-github-usage-sync/scripts"
export DEMO="$(mktemp -d "${TMPDIR:-/tmp}/usage-ledger.XXXXXXXX")"
export STATE="$DEMO/run"
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" init \
  --run-id synthetic-january --github-account synthetic-account \
  --deployment organization --organization example-org --page usage --kind detailed \
  --start-date 2026-01-01 --end-date 2026-01-31 \
  --mode local_only --required-id first
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

# Local smoke test only: these booleans represent synthetic observations.
run_state.advance(os.environ['STATE'], 'downloaded', {'user_link': True, 'notification_verified': False, 'source_correspondence': True})
run_state.register_artifact(os.environ['STATE'], 'first', original)
PY
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" advance validated
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" advance local_validated
python3 "$SCRIPTS/run_state.py" --state-dir "$STATE" show
# Temporary private data remains at $DEMO; remove it when no longer needed.
```

Successful console output contains only state, run SHA256, counts, artifact hashes
and `mail_verified`, `mode`, `cloud_verified`. It contains no account, enterprise, run ID, file IDs,
generated names, paths, destination identity, or cloud target.

## Real browser request route (operator-controlled)

Create a **new** run with the init command above, using the operator-confirmed
logged-in GitHub account and actual private configuration. `page=usage` pairs
with `detailed` or `summarized`; `page=ai_usage` pairs only with `kind=ai_usage`.
Use the exact confirmed account spelling consistently across all Enterprise and Organization runs.
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
then `advance validated`; for local-only finish with `advance local_validated`.
For user_link delivery after a request, use the downloaded evidence example below
with `notification_verified=false`, not the browser-mail example above.
Originals and containing directories must be private
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

This section applies only to cloud mode. Skip it entirely for local-only.
The cloud payload requires `upload_mode=archive|replace` and includes it in the run hash.
CLI `init --upload-mode` defaults to archive; resume must keep the original mode.
For rclone, freeze `destination_id` as
`upload_report.destination_identity(normalized_destination)` when initializing.
`upload_report.transfer(..., readback_dir, state_dir, replace_target=None)` reads
that private ledger and requires validated/uploaded/uploaded_unverified state,
no pending IDs, matching deployment/slug and page/kind/dates, frozen destination and mode, and the
exact registered original bytes/path plus generated filename. It never updates
the ledger. Legacy payloads are interpreted as Enterprise Cloud for the target
gate without mutation. Target mismatch fails before any remote call. Changing
archive to replace requires a new run, not edited config.

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
