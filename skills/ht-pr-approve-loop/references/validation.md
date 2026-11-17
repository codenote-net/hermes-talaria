# Validation and evidence boundaries

## Automated fixture-only discovery tests

Run from the repository root, explicitly setting the scratch location:

```sh
TMPDIR="$HOME/.hermes/cache/scratch" PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s skills/ht-pr-approve-loop/tests -v
TMPDIR="$HOME/.hermes/cache/scratch" PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s skills/ht-pr-approve/tests -v
git diff --check
```

The new suite uses stdlib unittest and an injected fake `gh` executor. It checks
literal URL/query validation, repository scoping, exact direct-user search qualifier,
identity resolution, empty results, numbered pagination, oldest-first ordering,
deduplication, incomplete results, cap rejection, changing totals, malformed metadata,
API/auth failure propagation, and external exclusive JSON output including symlinks.
It does **not** establish live direct-user request semantics from GitHub responses;
that eligibility check belongs to the agent procedure below. Temporary files use
`TMPDIR`; tests never call real GitHub/model APIs or submit approvals. The existing
single-PR suite separately exercises its runner using fake reviewer CLIs.

Document/contract inspection (frontmatter, relative links, English prose, exact
payload examples, and presence of workflow gates) validates packaging and documented
coverage only. It is not a programmatic test of agent judgment or API behavior.

## Agent workflow acceptance matrix (not automated)

Use controlled evidence or separately authorized live targets to assess these cases.
Do not claim any passed merely because helper or document tests passed.

| Case | Required outcome |
| --- | --- |
| Repository URL or exact encoded pulls query | Freeze the explicit scope and current identity; invocation authorizes this one conditional batch |
| Missing repository, wrong query token, duplicate q, extra scope | Ask/reject; do not repair or infer a repository |
| More than one search page | Read all pages and freeze deduplicated oldest-first candidates outside Git |
| Zero candidates | Successful no-op, zero approvals |
| Incomplete search, changing total, API cap at/above 1000 | No actionable snapshot and no review loop |
| Search result is no longer directly requested | Skip after live requested-reviewer pagination; team membership is insufficient |
| Request exists only on a later requested-reviewers page | Recognize the direct user after full pagination |
| Closed, draft, self-authored, or inaccessible PR | Record PR-specific skip; continue next frozen URL |
| Source target is not currently checked out | Acquire and verify a temporary matching clone outside report directories; never edit source |
| Matching dirty selected checkout | Preserve local changes; runner reviews exact Git objects in a detached worktree |
| Host worktree review | Disclose host access and trust risk privately; do not claim a sandbox |
| Four exit-zero reviews but one refusal/wrong revision/embedded failure | INCOMPLETE, no approval; continue next PR |
| Only one reviewer reports a P0 | Parent adjudicates the union; no consensus or token-scan shortcut |
| Unlabeled/disputed finding | Resolve severity with exact-source evidence or UNKNOWN, skip |
| Accepted P0 | Policy FAIL; no public write; continue |
| No accepted P0, accepted P1/P2/P3 | PASS if all other gates pass; lower-severity details remain private |
| Runner returns complete | Parent still verifies substantive reviews and adjudicates; exit zero alone does not approve |
| Head or base changes before POST | Stale skip; do not re-review the new pair in this pass |
| Direct request removed before POST | Skip; no approval |
| Verified effective same-head approval with equivalent saved policy/evidence and current pair | Read exact review back, record already-approved no-op |
| Same emoji but no policy ledger or ambiguous evidence | Preserve ambiguity; no policy inference and no blind duplicate |
| Historic approval followed by effective changes requested or dismissal | Do not report already-approved or automatically reverse decision |
| Same-head review on a later reviews page | Find it through complete pagination before deciding to POST |
| Approval submission | One API review with event APPROVE, commit_id exact head, body exactly `👌`; no separate comment |
| Body has extra whitespace, text, or newline | Reject payload/read-back equality; do not claim success |
| Read-back reviewer, state, commit, or body differs | Persist uncertainty; stop remaining loop if submission cannot be reconciled |
| POST accepted but response lost | Reconcile exact new review ID, reviewer, commit, body, intent/time and preexisting IDs before any retry |
| Ambiguous or multiple reconciliation candidates | Save submission_unknown and stop remaining PRs; no blind retry |
| Head/base changes after actual approval | Record old-pair approval only; no new-head submission |
| Global authentication/rate-limit failure | Stop remaining candidates; preserve potentially submitted intent for reconciliation |
| A new requested PR appears during the run | Do not add it; initial snapshot only |
| Final report | Read persisted outcomes and compute counts against the snapshot, including unattempted entries |

## Known limitations

- P2: Discovery compares returned repository URLs case-sensitively with the input.
  GitHub accepts differently cased repository identifiers, but a mixed-case input
  such as `https://github.com/Example/Project` is rejected when results use canonical
  `example/project`. Use the repository's canonical spelling for now. The fixture
  reproduction confirms rejection, not an out-of-scope approval. This finding is
  recorded without an automatic P2 fix.

## Separate live validation

Real model reviews incur cost and execute with normal host access. Any live smoke
test must name a trusted repository/PR and record exact head/base and substantive
outputs outside Git. A live approval additionally requires explicit authorization
for the exact account and target set; never submit just to validate these documents.
No live models, remote approval writes, effective GitHub decision-state semantics,
rate-limit recovery, or full agent loop are proven by the fixture suite.
