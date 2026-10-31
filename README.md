# hermes-talaria

Personal customizations for [Hermes Agent](https://github.com/NousResearch/hermes-agent): skills, plugins, hooks, and config templates — all without modifying the agent core.

The repository is named after the Talaria, the winged sandals of Hermes in Greek mythology—a fitting metaphor for extensions that empower Hermes Agent.

## Naming convention

Everything maintained in this repository uses the `ht` prefix so customizations are easy to identify and do not collide with other extensions. See [AGENTS.md](AGENTS.md) for the identifier-specific rules and examples.

This prefix replaces the former `omh` namespace. The migration is intentionally breaking: existing skill invocations, scheduled tasks, and configuration references must be updated from `omh-`/`omh_` to `ht-`/`ht_`.

## Layout

```
skills/    # SKILL.md-based knowledge/skills (tap-compatible)
plugins/   # Python plugins (custom tools, hooks, slash commands)
hooks/     # Gateway event hooks (HOOK.yaml + handler.py)
bundles/   # Skill bundles (YAML) exposed as slash commands
config/    # config.yaml template and SOUL.md persona (no secrets)
scripts/   # Setup helpers
```

## Install

### Skills (as a tap)

```sh
hermes skills tap add codenote-net/hermes-talaria
```

Alternatively, add this repo's `skills/` directory to `skills.external_dirs` in your `~/.hermes/config.yaml`:

```yaml
skills:
  external_dirs:
    - /path/to/hermes-talaria/skills
```

### Plugins

```sh
hermes plugins install codenote-net/hermes-talaria
```

Then enable them explicitly under `plugins.enabled` in `config.yaml`.

### Config

Run the repository installer to symlink each skill and plugin directory, and to create a config from the template when one does not already exist:

```sh
./scripts/install.sh
```

If Hermes is already running, refresh its in-process skill cache after installation:

```text
/reload-skills
```

Invoke an installed skill with its generated direct slash command, for example
`/ht-plan-epic-issue`. `/skills` manages the Skills Hub, so `/skills
ht-plan-epic-issue` is parsed as an unknown Hub action rather than a skill invocation.

Set `HERMES_DIR` to install into a location other than `~/.hermes`. You can also copy `config/config.example.yaml` to `~/.hermes/config.yaml` manually and fill in your own values.

Never commit secrets to this repository.

## Japan business-trip hotel research

`/ht-japan-hotel-research` searches hotel official sites in Japan, Yahoo! Travel, Rakuten
Travel, and [Jalan](https://www.jalan.net/biz/) through adaptive agent-driven browser interaction and compares prices
with trip-destination access. It uses the current page state rather than fixed
site-specific selectors and does not require a particular browser product.
Browser automation must be available; it does not book rooms.
Set `research.sites` to choose which supported sources to research:
`[official, yahoo, rakuten]` is the default; add `jalan` to opt in.
Unselected sites are skipped, including discovery and fallback searches.
The list must be non-empty, unique, and contain only supported source IDs.

The shareable settings template is
[`hotel-preferences.example.yaml`](skills/ht-japan-hotel-research/templates/hotel-preferences.example.yaml).
Copy it to `~/.config/hermes-talaria/hotel-preferences.yaml` and customize
domestic/international budgets (including currency and tax basis), airports,
preferred rail corridors, and an optional office. `HT_HOTEL_PREFERENCES` or an
explicit file path can override this location. Keep actual settings and research
reports outside Git. `hotel-preferences.yaml` and `hotel-research-results/` are
also ignored as a safeguard; the example never contains personal settings.

Provide check-in/out dates and the destination when invoking the skill. A visit
date alone does not determine whether to search the previous or following night.

## GitHub attachment reupload

`/ht-github-attachment-reupload` copies original attachments through authenticated
GitHub browser pages into another repository's issue, pull request, or Discussion.
Discussion bodies, top-level comments and replies are supported from the start,
including cross-type copies. PR inline review comments are excluded.

Provide the source URL, selected attachments, exact destination and whether to add
a comment/reply or edit existing content. The skill confirms the destination
audience before uploading, uses available browser automation (such as Agent Browser)
and Computer Use for native dialogs, and verifies saved links and original bytes.
There is no API/CLI file-transfer fallback. Local Python helpers only verify bytes;
actual downloads, private URLs and run ledgers stay outside Git.

Browser access to both repositories is required. Destination-only permission
verification requires a separate authorized user/session without source access;
without it the skill reports that check as unverified. See the
[validation checklist](skills/ht-github-attachment-reupload/references/validation.md)
for local tests and the separate live-browser acceptance matrix.

## GitHub usage report sync

`/ht-github-usage-sync` exports GitHub Enterprise Cloud billing reports through
adaptive, authenticated browser interaction and saves original CSV files to an
explicitly configured cloud folder. Metered usage is the default; AI usage is a
separate selectable page. GitHub report requests and downloads never use an API,
internal endpoint, or direct HTTP fallback.

Copy the shareable
[`github-usage.example.yaml`](skills/ht-github-usage-sync/templates/github-usage.example.yaml)
to `~/.config/hermes-talaria/github-usage.yaml` outside Git. Configure each billing
page's complete URL, enterprise, report period, and cloud destination. An explicit
config path takes precedence over `HT_GITHUB_USAGE_CONFIG`, then the default path.
Actual URLs, recipients, folder IDs, CSV files, and run ledgers must stay outside
Git; `github-usage.yaml` and `github-usage-results/` are also ignored as safeguards.

The initial browser upload procedure targets Google Drive. Optional rclone
transfers are separate from browser-only GitHub acquisition; see the
[destination matrix](skills/ht-github-usage-sync/references/cloud-destinations.md)
for supported combinations and account prerequisites. No destination is inferred,
no public sharing links are created, and no scheduled jobs or task issues are
registered by this skill.

The workflow can inspect a configured browser mailbox or resume from a user-supplied
download link. It preserves the original CSV, freezes the run's period and filename,
and verifies saved bytes by downloading the exact destination file again. Missing
mail, pending requests, incomplete uploads, and unverified read-backs are not success.
See the [manual validation checklist](skills/ht-github-usage-sync/references/manual-validation.md)
for live-browser gates, which are separate from synthetic local tests.

## GitHub issue rollout

`/ht-github-issue-rollout` scans every visible repository in an organization, or every
organization and repository in an enterprise, assesses a shared request, and creates
an approved native epic/sub-issue hierarchy. Full administrative coverage must be
verified separately from API pagination before claiming an all-repositories scan.

Provide an organization repositories URL or enterprise organizations URL, applicability
criteria, and approved tracking repositories. Not-applicable repositories receive no
issue by default; explicit opt-in creates clearly marked non-remediation issues.
Unknown applicability and inaccessible repositories are reported separately.

The documented native API requires parent and child repositories to have the same
owner. For an enterprise-wide native tree, the skill offers centralized tracking
issues in one approved repository; it never silently substitutes Markdown links or
relocates issues. Native child/depth limits and destination audiences are checked
before writes. The bundled Python/`gh` helper is read-only; assessment, approval,
creation and recovery are agent-driven procedures. See the
[skill](skills/ht-github-issue-rollout/SKILL.md) for the workflow and tests.

## Conditional PR approval

`/ht-pr-approve https://github.com/OWNER/REPO/pull/123 --condition "No P0 findings"`
runs three Claude slash-command reviews and a Codex review against pinned live
head/base commits in an automatically cleaned temporary detached worktree. Normal
authenticated CLIs are used; no container or separate read-only credential is required.
The worktree is not a security boundary: reviewers retain host tools and credentials.
The runner records raw results and per-reviewer exits but never submits approvals.
The parent agent must verify all four substantive reviews, freshness, duplicate
approval state, and the explicit policy before a separate commit-bound API approval.
The condition is agent input, not a standalone CLI flag. A no-P0 policy permits
P1 findings and discloses them rather than silently applying a stricter threshold.

Approval is bound to the reviewed commit and read back from GitHub. Incomplete
reviews, uncertain severity, stale head/base evidence, and self-authored PRs block
approval. The workflow neither fixes findings nor merges PRs. See the
[skill](skills/ht-pr-approve/SKILL.md) and its
[validation matrix](skills/ht-pr-approve/references/validation.md).

## License

[MIT](LICENSE)
