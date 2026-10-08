# Cloud destinations and verification (optional transport)

GitHub report retrieval remains **browser-only**. This guide and `scripts/upload_report.py` cover storage only for original CSV files already retrieved and locally validated. rclone is optional; browser storage requires neither installation nor rclone authentication. Follow [local-workflow.md](local-workflow.md) for authentication, account matching, duplicate-request reservation, and state management. This adapter does not update the ledger.

## Service / transport support matrix

"Implemented" means local contract tests and procedures exist. **No row has been tested against a real cloud service for execution, authentication, or permissions**. Mock JSON is not evidence of real-service success.

| provider | browser | rclone backend | Destination / prerequisites | Execution verification |
|---|---|---|---|---|
| `google_drive` | Adaptive procedure below (default) | `drive` | browser: `folder_url` + `folder_id`; rclone: `remote` + `folder_id`, optional `shared_drive_id` | Unverified |
| `onedrive` | Not implemented | `onedrive` | `remote` + `folder_path`; verify target account beforehand | Unverified |
| `sharepoint` | Not implemented | `onedrive` | `remote` + `folder_path`; remote must already target the site/document library. Backend matching does not prove site identity | Unverified |
| `dropbox` | Not implemented | `dropbox` | `remote` + `folder_path`; check app visibility scope | Unverified |
| `box` | Not implemented | `box` | `remote` + non-root `folder_id` | Unverified |
| `s3` | Not implemented | `s3` | `remote` + `bucket` + nonempty `prefix`; verify endpoint/account beforehand | Unverified |
| `gcs` | Not implemented | `googlecloudstorage` | `remote` + `bucket` + nonempty `prefix`; verify project/account beforehand | Unverified |

All rclone providers implement new archive storage and readback verification for identical content. Replacement with different content is supported only for OneDrive/SharePoint/Dropbox/S3/GCS and requires explicit approval of the exact `remote:key`. Drive/Box reject replacement with different content because name-based `copyto` cannot guarantee an update to the approved ID. For Drive, check the target ID in the browser. Box browser automation is not implemented; manual judgment is required.

## Google Drive: browser storage adapted to the current screen

1. Open the personal configuration's `folder_url` and match the URL folder ID against `folder_id`. Reject root destinations, redirects to another folder, and ambiguous shortcut targets. Check the current Google account, shared drive, breadcrumbs, and write permissions on screen; the user must approve the exact destination. Stop for login/permission barriers. Do not guess another account.
2. Verify the original CSV download is complete; use a 0700 directory outside Git and set the file to 0600. Validate report kind, UTC range, and CSV structure with `report_artifact.py`. Retain the fixed filename registered for the run; do not generate new names on resume. Do not rewrite original bytes.
3. Observe the current screen for same-name files/folders. Drive permits duplicate names, so inspect details/IDs rather than selecting by name alone. Stop for multiple matches, a same-name folder, or an unverifiable target. Download the existing CSV by its **file ID** and perform the comparison below. Identical content permits skipping upload, but still requires readback evidence. With archive and different content, stop: no unsolicited overwrite or automatic renaming. For replace, obtain specific approval for the exact existing file ID, then inspect the UI's target-file update/version-management operation. A generic "yes" is insufficient.
4. Choose visible actions such as "New" -> "File upload" in the current UI. Do not rely solely on fixed coordinates or labels; observe language, viewport size, and menu state each time. When the native file dialog opens, use the OS file picker to select only the validated original CSV. If no available interaction tool supports the dialog, ask the user to select the file and stop/resume. Do not pretend the browser DOM alone controls OS dialogs.
5. Send only original CSV files. Keep YAML, ledgers, credentials, and SHA/metadata sidecars local by default. After upload completion is displayed, recheck the new file's name and ID in the target folder. No sharing, public links, permission changes, or folder creation.
6. Select the stored **exact file ID** and download through the browser into a fresh private readback directory. No preview, Google Sheets conversion, or similarly named substitute. After completion, set 0600 and compare. Browser transport uses browser readback and does not require rclone. Do not reuse the source file as readback.
7. Record verified only if byte count and SHA256 match. Even after upload, insufficient verification, timeout, or mismatch means uploaded_unverified; keep the original and stop. Record storage/verification results following the controller/local-workflow procedure.

Generic local commands (substitute actual paths from personal configuration; avoid symlink paths such as macOS `/tmp` and use resolved real paths):

```sh
chmod 700 "$PRIVATE_DIR" "$READBACK_DIR"
chmod 600 "$ORIGINAL_CSV" "$READBACK_CSV"
python scripts/report_artifact.py "$ORIGINAL_CSV" --kind summarized \
  --start-date 2026-01-01 --end-date 2026-01-31
```

The current CLI has no compare subcommand. Do not invent a CLI; use the existing local API (run from the skill directory):

```sh
python -c 'import sys; sys.path.insert(0, "scripts"); from report_artifact import compare_files; print(compare_files(sys.argv[1], sys.argv[2]))' \
  "$ORIGINAL_CSV" "$READBACK_CSV"
```

## rclone: optional safe adapter

The user must already have configured rclone and the target remote. This skill does not install software, perform OAuth, inspect authentication files, or run `rclone config show/dump`. rclone itself uses existing authentication. The user verifies the target account, site/shared drive/bucket, permissions, and absence of concurrent writes. Backend matching does not prove account identity.

Explicitly set `destination.transport: rclone` in personal YAML and specify only destinations from the table above. Reject unknown keys, root destinations, URIs embedded in remote names, tokens, arbitrary flags/env overrides. `--config` is the **skill's personal YAML**, not an option for passing an rclone authentication file. PyYAML is required in the runtime environment. Do not install missing dependencies automatically.

Preflight requires exact remote name/backend matches in `rclone listremotes --long`, a directory result from `lsjson --stat`, and independent `lsjson` enumeration. Path destinations require exactly one matching existing directory in the parent listing. For S3/GCS virtual prefixes, stat alone does not prove existence; reject empty prefixes absent from the parent listing. Drive/Box root stat can also be synthetic, so require user confirmation of the configured ID and independent actual enumeration rather than accepting stat alone. If stat provides an ID, it must match configuration. Stop if ID/root enumeration fails. Do not create folders automatically.

The destination confirmation value is the SHA256 returned by `upload_report.destination_identity(normalized_destination)`. Generate it after the user reviews personal configuration. A matching value alone does not prove account verification.

```sh
python -c 'import sys; sys.path.insert(0, "scripts"); from validate_config import load_config; from upload_report import destination_identity; print(destination_identity(load_config(sys.argv[1])["destination"]))' "$PERSONAL_CONFIG"
python scripts/upload_report.py --config "$PERSONAL_CONFIG" --state-dir "$STATE" \
  --file "$ORIGINAL_CSV" --filename "$REGISTERED_FILENAME" --kind summarized \
  --start-date 2026-01-01 --end-date 2026-01-31 \
  --confirm-destination "$CONFIRMED_IDENTITY" --readback-dir "$READBACK_DIR"
```

At ledger initialization, freeze `destination_id` to the normalized identity above and `upload_mode` to the configured value (CLI `--upload-mode archive|replace`, default archive). Transfer requires a validated/uploaded/uploaded_unverified ledger and the exact registered original path, fixed name, kind, and period. Python API: `transfer(config, file, filename, kind, start_date, end_date, confirm_destination, readback_dir, state_dir, replace_target=None)`. Changing only configuration from archive to replace is rejected before remote calls. The adapter reads the ledger but does not update it.

Replacement requires ledger `upload_mode: replace`, configuration `upload.mode: replace`, and `--replace-target "$EXACT_REMOTE_KEY"` identifying the target itself. Normally use archive. New archives use `copyto --immutable --ignore-times` to prevent overwriting on conflict. Enumerate immediately before and after upload to reject duplicates/different IDs/conflicts. Do not use `sync`, delete, mkdir, or sharing changes. rclone does not provide atomic folder matching plus storage, so no concurrent writers is a prerequisite. Treat races such as duplicate Drive objects as verification failures.

All subprocesses use argv and shell=False, a 120-second limit, and one rclone retry/low-level retry each. Do not output stderr, raw URLs, or target names. After a remote-operation error, do not retry writes; if possible, enumerate once more and stop with the result unverified. Even after success, use the same transport to read back the exact object into a fresh 0700/0600 private tempfile and compare byte count plus SHA256. Readback remains at `READBACK_DIR/readback-*/report.csv`; before controller integration it is not automatically registered in the ledger. Do not delete the original.

Exit 0 and `verified:true` indicate an actual readback match (tests exercise mock contracts only). Exit 2 and `verified:false` mean incomplete/unverified, not a guarantee that no transfer occurred. Missing rclone is a runtime blocker. CLI output contains only safe provider/action/bytes/sha256/verified fields or fixed errors; never claim success for unverified real-cloud work.

References (CLI specifications checked; no cloud connection executed): [listremotes](https://rclone.org/commands/rclone_listremotes/), [lsjson](https://rclone.org/commands/rclone_lsjson/), [copyto](https://rclone.org/commands/rclone_copyto/), [Drive root-folder-id / team-drive](https://rclone.org/drive/), [Box root-folder-id](https://rclone.org/box/).
