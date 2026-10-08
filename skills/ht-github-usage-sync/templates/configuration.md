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

- Required `github` fields are `deployment: enterprise_cloud`, `enterprise` (slug), and `pages`.
- `pages.usage` and `pages.ai_usage` are `{url: full HTTPS URL}` or null. The selected page is required. URLs must not contain credentials; preserve queries without inferring their meaning. Match the URL Enterprise and displayed page in the browser.
- `report.page` defaults to `usage`; `kind` defaults to `detailed`. usage supports `detailed`/`summarized`; ai_usage requires **explicit** `kind: ai_usage`.
- `acquisition.method` supports only `browser`. API/HTTP retrieval is out of scope.
- `notification.mode: user_link` is the default. Receive the download link from the user.
- `browser_mail` requires `mail_url` (HTTPS), `expected_recipient` (email), and `expected_account` (account string to match on screen). Approved forwarding recipients are an email array in `approved_forwarded_recipients`. Do not infer recipients automatically.
- Mail `wait_interval_seconds` is 30-60 seconds (default 30); `wait_timeout_seconds` is 1-600 seconds (default 600). Both are integers only (no bool), and interval <= timeout. Do not mix mail settings into user_link.

## Resolving periods and resuming

API: `resolve_period(report, observed_start=None, observed_end=None, now=None) -> dict`。
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

`destination.provider` is explicitly required. `transport` defaults to browser.

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

Run from the repository root. Create the venv outside Git.

```sh
python3 -m venv /tmp/ht-usage-sync-venv
/tmp/ht-usage-sync-venv/bin/pip install 'PyYAML>=6,<7'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=skills/ht-github-usage-sync/tests \
  /tmp/ht-usage-sync-venv/bin/python -m unittest test_config test_report_period -v
/tmp/ht-usage-sync-venv/bin/python skills/ht-github-usage-sync/scripts/validate_config.py \
  --config /path/outside/git/github-usage.yaml
```

Synthetic tests were written first; before implementation they produced `ModuleNotFoundError: No module named 'validate_config'` and `report_period` (RED). An additional Box-root rejection test also produced `ConfigError not raised` before implementation. After implementation, the focused tests above reported `Ran 16 tests ... OK` (GREEN). PyYAML 6.0.3 was installed in an external venv. Real subprocess tests verified that CLI success does not display values, and failure returns exit 2 without exposing emails/URLs/paths. No real user configuration, authentication, or cloud service was accessed.
