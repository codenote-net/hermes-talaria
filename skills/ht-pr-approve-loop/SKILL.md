---
name: ht-pr-approve-loop
description: "Use when approving a frozen batch of directly requested GitHub PR reviews. Discover oldest-first within one explicit repository, reuse ht-pr-approve, and approve only complete no-P0 reviews with an exact emoji body."
---

# One-pass requested-review approval loop

This is an **agent-driven procedure**, not an executable model orchestration loop.
Load `ht-pr-approve` and its required `ht-pr-multi-review` skill. Reuse the existing
`ht-pr-approve/scripts/review_pr.py` four-review runner unchanged. The bundled
[discovery helper](scripts/discover_prs.py) only reads GitHub and writes a local
snapshot. It cannot review, adjudicate severity, or submit an approval.

## Invocation and fixed authorization

Accept one explicitly supplied repository URL or exact GitHub pulls search URL:

```text
/ht-pr-approve-loop https://github.com/OWNER/REPO
/ht-pr-approve-loop https://github.com/OWNER/REPO/pulls?q=is%3Apr%20state%3Aopen%20user-review-requested%3A%40me%20sort%3Acreated-asc
```

Invoking this skill with either target explicitly authorizes conditional batch
approvals for the initial snapshot under this policy; no second confirmation is
required. Without an explicit repository target, ask rather than inferring one
from the current directory, organization, or account. Never expand the scope.

The literal fixed filter is:

```text
is:pr state:open user-review-requested:@me sort:created-asc
```

Search only within `repo:OWNER/REPO`. `user-review-requested:@me` means a request
addressed directly to the authenticated user, not a team request. Never replace it
with `review-requested`, `team-review-requested`, `is:open`, or a guessed username.
Search URLs must have exactly one `q` parameter whose decoded value equals the
filter above, in that order and spacing. Reject extra parameters, duplicate tokens,
wrong qualifiers, alternate hosts, fragments, or additional scopes; do not silently
repair or normalize them. Ordinary percent encoding and `+` spaces are accepted.
Repository URLs have no trailing slash or query. Preserve the original input.

The approval predicate is **zero accepted P0 findings**, with complete evidence and
all eligibility/freshness gates satisfied. P1/P2/P3 findings do not block approval;
record and disclose them privately. Do not add CI requirements or fix findings.
The only authorized public content is one commit-bound `APPROVE` review with body
exactly `👌` (one character, no newline, whitespace, explanation, or suffix).
No separate PR comment, inline comment, request-changes review, commit, push, merge,
issue, recurring job, or automatic second pass is authorized.

## 1. Prepare source and external records

Require normally authenticated `gh`, `git`, `claude`, and `codex`. Check `gh auth
status`; resolve `gh api --hostname github.com user` and freeze its login as reviewer.
Do not switch identities to bypass self-review. Authentication and rate-limit
failures stop the entire run, including remaining candidates.

If a selected existing checkout matches the explicit target (verify GitHub
`nameWithOwner`, not just its directory name), use it without changing its branch,
stashing, or editing source. Otherwise create a temporary source directory outside
all report directories using the configured scratch location (`$TMPDIR`, explicitly
set to `$HOME/.hermes/cache/scratch` on this host), and acquire the validated target:

```sh
gh repo clone OWNER/REPO /absolute/scratch/source -- --no-checkout
```

Resolve placeholders from validated input, pass arguments without shell-evaluating
PR content, and verify repository identity before review. Keep the temporary clone
until all runner worktrees are removed; clean up only directories created by this
run, including on errors. Never clean or delete a user's selected checkout.

Create a unique external run directory outside **every** source checkout, including
this skills repository. Keep the immutable snapshot, policy ledger, raw review
reports, adjudication, API payloads/responses, timestamps, and outcomes there. Do not
put private records in Git or inside any checkout. Keep source and evidence as sibling
rather than nested directories. The helper enforces the supplied `--repo` boundary;
the agent must additionally check all other checkout boundaries.

Disclose locally before running reviewers: detached host worktrees are **not a
security boundary**. Authenticated reviewer tools retain filesystem, network, and
credential access; repository instructions, filters, and permissive tools can execute
code. No-publication prompts are best effort, not enforced denial of remote writes.
Use only trusted repositories and CLI configurations; no container or separate
read-only credential is required by this workflow.

## 2. Freeze one complete candidate snapshot

Resolve `LOOP_SKILL_DIR` to this skill's directory and run once:

```sh
python3 "$LOOP_SKILL_DIR/scripts/discover_prs.py" \
  'EXACT_USER_SUPPLIED_URL' --repo /absolute/source \
  --output /external/run/snapshot.json
```

The helper checks authentication and identity, uses `gh api --method GET
search/issues` with `per_page=100`, checks each page's `incomplete_results` and stable
`total_count`, and rejects totals at or above the API's 1000-result cap. No truncated
snapshot is valid. It validates returned repository/PR scope, deduplicates by PR
number, rejects conflicting duplicate metadata, and sorts by `created_at` ascending
with PR number as a deterministic tie-breaker. Output is exclusive JSON creation;
no overwrite. Search duplicates may make the unique count smaller than the raw
search count; record both. Zero candidates is a successful no-op, with zero writes.
An incomplete/error result stops discovery without an actionable snapshot.

Read back the saved JSON and freeze its exact ordered URLs and reviewer in the local
ledger. A paginated search is not an atomic server snapshot: changes can race search,
and equal totals cannot prove an unchanged result set. The artifact freezes only the
observed candidates, not a claim of exhaustive continuous coverage. Recheck each
candidate live. Never rediscover, add newly arriving PRs, or retry the queue forever.

## 3. Process each frozen PR once, sequentially

Maintain one outcome record per URL. Before any review, and again immediately before
submission, read the exact PR and paginate all requested reviewers and reviews:

```text
GET repos/OWNER/REPO/pulls/NUMBER
GET repos/OWNER/REPO/pulls/NUMBER/requested_reviewers?per_page=100&page=N
GET repos/OWNER/REPO/pulls/NUMBER/reviews?per_page=100&page=N
```

Follow pagination to completion even when a request/review is absent on the first
page. Require the original repository and reviewer identity, open state, `draft ==
false`, author different from reviewer, and a current direct reviewer entry in
`users` matching that login. A matching `teams` entry is insufficient. Search index
membership alone is never eligibility. Freeze exact head SHA and base SHA for this
PR and retain the relevant metadata. A removed request, draft, closed/self-authored
PR, inaccessible PR-specific resource, or stale pair skips this PR and continues to
the next frozen URL; do not substitute a different PR. Global auth/rate failures
stop all remaining work instead of masquerading as PR-specific skips.

### Existing approvals and duplicate prevention

Inspect all pages of reviews by this reviewer and the saved external policy ledger
before invoking the runner and again before POST. Never accept an arbitrary historic
`APPROVED`: account for later effective `CHANGES_REQUESTED`, dismissal, or other
superseding decision state. Comments alone are not a new approval decision. Require
a currently effective, non-dismissed approval for the same head, and a local verified
record linking its exact review ID, reviewer, body, reviewed head/base pair, completed
four-review evidence, no-P0 adjudication, and this policy. Read the exact review ID
back and verify the current pair before recording `already_approved`.

The emoji alone proves neither policy equivalence nor review completion. If the
ledger is missing, inconsistent, or cannot establish equivalence/effective state,
record `duplicate_ambiguous` and skip without a blind duplicate. Preserve ambiguity
and all existing reviews; do not dismiss or overwrite them. A later effective
changes-requested/dismissed state prevents a no-op success. Do not automatically
reverse that decision or repeat approval; record it for private assessment.

### Reuse the single-PR workflow

Invoke `ht-pr-approve` for this exact PR with policy `No P0 findings` and explicitly
supplied exact custom approval body `👌`. Resolve `APPROVE_SKILL_DIR` to that sibling
skill's installed directory; do not copy or change its runner:

```sh
python3 "$APPROVE_SKILL_DIR/scripts/review_pr.py" \
  'https://github.com/OWNER/REPO/pull/NUMBER' --repo /absolute/source \
  --head FULL_HEAD_SHA --base FULL_BASE_SHA \
  --output /external/run/pr-NUMBER-evidence.json
```

Require all three Claude reviews and the Codex review to be complete, substantive,
and about the pinned pair. Runner exit zero is not a policy PASS. Inspect raw outputs
for refusals, embedded errors, wrong revisions, and missing evidence. Parent-agent
adjudication must form the union of findings, preserve minority and rejected findings,
deduplicate, classify every finding P0/P1/P2/P3 with evidence, and resolve disputed or
unlabeled severity. Never use token scanning or “no P0 string” as the approval gate.
Record accepted counts and PASS/FAIL/UNKNOWN privately. Zero P0 with P1/P2/P3 is PASS;
P0 is FAIL; incomplete reviews or unresolved severity is UNKNOWN. Failures/unknowns
skip this PR and continue, except global auth/rate failure stops the loop. Do not fix
code, rerun indefinitely, or publish findings.

## 4. Submit and verify one exact review

After policy PASS, refresh identity, direct request, state/draft/author, full review
history and head/base immediately before writing. A changed head **or base** skips
the PR as stale; do not automatically review and approve the new pair in this pass.
Record submission intent and the policy/evidence binding in the external ledger
before the write, so an interrupted run cannot blindly duplicate a submission.
Serialize the exact payload outside Git (do not shell-interpolate the body):

```json
{"commit_id": "REVIEWED_HEAD_SHA", "event": "APPROVE", "body": "👌"}
```

Submit exactly once via `gh api --method POST
repos/OWNER/REPO/pulls/NUMBER/reviews --input /external/run/pr-NUMBER-approval.json`.
Never use an unbound `gh pr review --approve`. Save the returned ID and response.
Read back `repos/OWNER/REPO/pulls/NUMBER/reviews/REVIEW_ID`; require `APPROVED`, exact
reviewer, exact head `commit_id`, and body equality to `👌`. Then refresh the PR and
require the same reviewed head/base before reporting current-pair approval success.
Persist the verified ID/permalink and evidence/policy binding for future no-op checks.
A changed pair after actual submission means **old-pair approval only**; record that
fact, continue to the next frozen candidate, and never submit for the new head.

If POST times out or returns an ambiguous result, do not retry blindly. Paginate
reviews and reconcile the exact reviewer, commit, body, review ID, time/intent, and
previously recorded review IDs. An emoji from some earlier run is insufficient.
If a unique new review is established, read that exact ID and verify it as above.
If acceptance or read-back cannot be established, persist `submission_unknown` and
stop the entire loop; leave remaining candidates unattempted. Global auth/rate errors
likewise stop remaining work, retaining any possibly accepted submission for later
reconciliation. Do not claim approval from POST success alone.

## 5. Private final report

Read all persisted outcomes and aggregate counts programmatically against the frozen
candidate count. Include unattempted entries when a global stop occurs. Distinguish
`approved`, `already_approved`, `policy_failed`, `review_incomplete`, `severity_unknown`,
`ineligible`, `stale`, `old_pair_approved`, `duplicate_ambiguous`, `api_failure`,
`submission_unknown`, and `unattempted`. Include per-PR URL, reviewed pair, findings,
reason, and verified review permalink when available. Keep P1/P2/P3 details, raw
reports, policy interpretation, and host-access risk in the private report/ledger,
not in GitHub. Approval is not merging or a guarantee of branch-protection acceptance.

See [validation](references/validation.md). Fixture helper tests do not execute or
verify this agent procedure, real reviewers, or GitHub writes.
