# Personal configuration contract and validation

`github-usage.example.yaml` is a fictional configuration example. **Do not use the template itself as runtime configuration** (its path is inside Git and will be rejected). Store personal copies outside Git. Do not copy real organizations, repositories, customer IDs, emails, reports, or credentials into shared files or tests.

## Configuration discovery and types

- Explicit path > `HT_GITHUB_USAGE_CONFIG` > `~/.config/hermes-talaria/github-usage.yaml`. An invalid higher-priority path does not fall back to a lower-priority one.
- `load_config(explicit=None) -> dict` reads and normalizes only the selected configuration. It does not read `.env`, cookies, rclone configuration, or authentication files.
- `validate_config(dict) -> dict` returns a copy including defaults without modifying the original dictionary.
- Validation errors use `ConfigError(ValueError)`. Errors do not include input values. The CLI does not display configured URLs, emails, remote names, paths, or Enterprise values.
- YAML uses a `SafeLoader` subclass. Reject duplicate keys (including after merges), unknown keys, secret keys, and incorrect types. Booleans are not valid integer values. `version` must be integer `1`.
- Resolve symlinks for the configuration file and `local.output_dir`; for nonexistent child paths, search for Git repositories from the nearest existing ancestor. Reject paths inside Git even if ignored. Also reject root paths and parent traversal. Stop if Git is unavailable and safety cannot be established. Repeat validation immediately before saving, since symlinks/repository state may change.

## GitHub, retrieval, and notifications

- Configuration version remains integer `1` for Enterprise Cloud and Organization. Required `github` fields are `deployment`, exactly the selected slug key, and `pages`. `deployment: enterprise_cloud` requires `enterprise`; `deployment: organization` requires `organization`. The other slug key is prohibited even when null. Slugs match `[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?`; no whitespace, underscores, separators, escapes or leading/trailing hyphens. Do not repair identifiers.
- `pages.usage` and `pages.ai_usage` are `{url: full HTTPS URL}` or null. The selected page is required. Every nonnull entry, including an unselected page, must use HTTPS github.com, port absent or 443, no credentials, and a matching billing entrypoint or selected report path. Enterprise bases are `/enterprises/<slug>/billing` and the legacy `/enterprises/<slug>/settings/billing`; the Organization base is `/organizations/<slug>/settings/billing`. A base or `/<page>` suffix accepts one optional trailing slash. Other subpages or extra segments are rejected. At an entrypoint, follow the visible selected-report link and verify the target/page before requesting; the overview alone is not report evidence. Do not decode or normalize paths. Preserve the full query literally without parsing or inferring its meaning. Match the selected target and displayed page in the browser; validating an unselected entry does not authorize opening it.
- See `github-usage.organization.example.yaml` for a synthetic Organization example. Do not copy real identifiers into it. CSV Detailed, Summarized and AI profiles are unchanged across deployments.
- New explicit-deployment ledgers use version 2 and exactly the selected slug key. Legacy enterprise-only Python payloads and CLI `--enterprise` without `--deployment` retain ledger version 1; read/resume without rewriting payload/hash/names. Configuration version and ledger version are separate. The upload adapter checks deployment and slug against the ledger before remote calls. See [local-workflow.md](../references/local-workflow.md) for the exact payload and shared account reservation contract.
- `report.page` defaults to `usage`; `kind` defaults to `detailed`. usage supports `detailed`/`summarized`; ai_usage requires **explicit** `kind: ai_usage`.
- `acquisition.method` supports only `browser`. API/HTTP retrieval is out of scope.
- `notification.mode: user_link` is the default. Receive the download link from the user.
- `browser_mail` requires `mail_url` (HTTPS), `expected_recipient` (email), and `expected_account` (account string to match on screen). Approved forwarding recipients are an email array in `approved_forwarded_recipients`. Do not infer recipients automatically.
- Mail `wait_interval_seconds` is 30-60 seconds (default 30); `wait_timeout_seconds` is 1-600 seconds (default 600). Both are integers only (no bool), and interval <= timeout. Do not mix mail settings into user_link.

## Resolving periods and resuming

API: `resolve_period(report, observed_start=None, observed_end=None, now=None) -> dict`.
Errors use `PeriodError(ValueError)`. `now` is a timezone-aware datetime; when omitted, use current UTC time.

Allowed `report.period` keys are only `mode`, `timezone`, `reference_date`, `start_date`, and `end_date`.

- `timezone` is an available IANA name, default UTC. Do not fix a particular region.
- `reference_date` is a quoted `"YYYY-MM-DD"` string. When omitted, use the date obtained by converting now to the configured timezone. Reject an explicit reference date later than that date in every mode (a date difference from UTC alone is not grounds for rejection). YAML date objects are not allowed.
- `page_selection` (default): pass both browser-observed endpoints as `observed_start`/`observed_end`. Do not infer them from URLs or queries. One endpoint alone fails.
- `previous_month`: first through last day of the calendar month preceding the reference date.
- `current_month`: first day of the reference calendar month through the reference date, capped at today in UTC. If the timezone has entered a new month while UTC remains in the previous month, stop because no retrievable range exists.
- `custom`: quoted `start_date`/`end_date` are required, with start <= end. Do not mix these keys into other modes.
- Inclusive limits: detailed/ai_usage at most 31 days; summarized at most 1 calendar year (example: 2024-01-01 through 2024-12-31). A leap-day start runs through the end of February the following year.
- Reject end dates after today in UTC, including observed/custom/previous-month periods. Current-month/today data may be incomplete. This validates date limits, not data availability. Stop and ask the user if the screen lacks the requested period/kind.

The return value contains `start_date`, `end_date`, `reference_date`, and `timezone`. Save it outside Git on the first run; on resume, construct `report.period` with `mode: custom` and these four persisted fields. Do not recalculate the initial resolved period. Keep page/kind separately in normalized `config['report']`.

Sources for period limits and UTC recording: [GitHub Billing reports reference](https://docs.github.com/en/billing/reference/billing-reports). Source for email retrieval: [Downloading usage reports](https://docs.github.com/en/billing/how-tos/products/view-productlicense-use#downloading-usage-reports). Capping the current month is this skill's safe period-resolution policy, not a guarantee of UI options.

## Destination support matrix

Top-level `mode` accepts only `cloud` (default) or `local_only`. Configuration
version remains 1. In cloud mode, `destination.provider` is explicitly required;
`transport` defaults to browser. Missing destination does not imply local-only.

For `mode: local_only`, omit the entire `destination` and `upload` keys, including
empty mappings or null. No provider, transport, remote, destination ID or upload
policy is synthesized. All GitHub, period, notification, acquisition and private
output rules remain unchanged. `notification.mode: user_link` remains the default;
mail is not verified by a user-supplied link. See
`github-usage.local-only.example.yaml` for a synthetic configuration. Validate a
private copy with the CLI below, then initialize a ledger using `--mode local_only`
and explicit deployment; do not pass destination or upload flags. Ledger version 3
is reserved for local-only; cloud version 1/2 payloads, hashes and names are unchanged.
Local completion is `local_validated`, never cloud `verified`. For the full
request/download/register/completion sequence see [local-workflow.md](../references/local-workflow.md).

| transport | provider | Required keys | Optional keys |
|---|---|---|---|
| browser | google_drive | `folder_id`, `folder_url` | None |
| rclone | google_drive | `remote`, `folder_id` | `shared_drive_id` |
| rclone | onedrive / sharepoint / dropbox | `remote`, `folder_path` | None |
| rclone | box | `remote`, `folder_id` | None |
| rclone | s3 / gcs | `remote`, `bucket`, `prefix` | None |

Browser transport supports only Google Drive; other browser combinations are explicitly unsupported. The Google Drive URL must match `https://drive.google.com/drive/folders/<folder_id>`. HTTP, other hosts, and root storage are not allowed.

rclone `remote` only references an existing name (starts with an alphanumeric character, followed by alphanumerics, `_`, or `-`). No colons, paths, spaces, or flags. Keep remote configuration/secrets entirely external. Folder paths and prefixes must be nonempty relative paths without `..`, `.`, empty components, leading slash, backslash, or colon. Reject Box root ID `0` and ID `root`. Do not mix incompatible destination keys.

Example (replace only `destination`):

```yaml
destination:
  provider: s3
  transport: rclone
  remote: example_remote
  bucket: example-bucket
  prefix: reports/github-usage
```

`upload.mode` defaults to archive. replace requires explicit selection. `local.output_dir` defaults to `~/.local/share/hermes-talaria/github-usage/` and is validated to be outside Git.

## Validation commands and execution evidence

Run from the repository root using the approved uv command; no fixed temporary venv is required.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=skills/ht-github-usage-sync/tests \
  uv run --with pyyaml python -m unittest test_config test_report_period -v
PYTHONDONTWRITEBYTECODE=1 uv run --with pyyaml python skills/ht-github-usage-sync/scripts/validate_config.py \
  --config /path/outside/git/github-usage.yaml
```

Run the complete offline suite after changes:

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --with pyyaml python \
  -m unittest discover -s skills/ht-github-usage-sync/tests -v
git diff --check
```

The synthetic Organization tests cover both deployments, literal URL preservation,
exclusive target keys, legacy/new ledgers, shared account reservations, CLI
redaction, unchanged CSV profiles and pre-remote upload target gates. Passing
these tests verifies local/mock contracts only. Real subprocess tests verify CLI redaction and private local
state, not GitHub or cloud success. No test requires personal configuration,
authentication, a browser or a live cloud service. Real E2E remains unverified.
