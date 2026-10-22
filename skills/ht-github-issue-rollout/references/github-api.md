# GitHub API and hierarchy runbook

## Authoritative references

Recheck before publication, especially on a resumed run:

- [Enterprise GraphQL object](https://docs.github.com/en/graphql/reference/objects#enterprise)
- [Organization GraphQL object](https://docs.github.com/en/graphql/reference/objects#organization)
- [GraphQL pagination](https://docs.github.com/en/graphql/guides/using-pagination-in-the-graphql-api)
- [Sub-issue REST API](https://docs.github.com/en/rest/issues/sub-issues)
- [Native sub-issue limits](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/adding-sub-issues)
- [Issue REST API](https://docs.github.com/en/rest/issues/issues)

The documented Add sub-issue parameter requires the child to belong to the same repository owner
as its parent. Enterprise membership does not remove that documented requirement. Use approved
centralized issue placement for a full enterprise tree; do not infer support from third-party
reports of successful cross-owner requests. Never perform unauthorized test writes to probe it.

## Discovery

The helper uses `enterprise(slug).organizations(first:100,after:cursor)` and, independently for each
organization, `organization(login).repositories(first:100,after:cursor)`. It passes no visibility,
fork, archive or issues-enabled filter. Each connection requests `totalCount` and `pageInfo`.
`gh api graphql --input -` takes a JSON query/variables object; GraphQL queries use HTTP POST but
these operations are read-only. No mutations exist in the helper.

A connection total is scoped to the principal's visibility. Independently confirm full coverage.
Enterprise discovery may require enterprise-level access such as `read:enterprise` on an appropriate
classic token; repository access and SSO authorization remain separate. Fine-grained/App tokens may
not support the required enterprise query. If access is missing, stop and ask for authorized setup;
never dump a token, silently change credentials, or replace the scope with the viewer's memberships.
Inspect GraphQL `errors` even when HTTP succeeds. Respect rate limits; do not bypass them by switching
accounts. An inaccessible organization, null node, repeated cursor, or changed count is not empty.

## Native writes (only after approved plan)

Use `--hostname github.com` explicitly. Validate every owner/repository/number from the frozen plan
before constructing endpoints. Save issue text in JSON files, never shell fragments.

```sh
# payload.json explicitly contains title, body, labels and assignees.
gh api --hostname github.com --method POST repos/OWNER/REPO/issues --input /private/run/payload.json
# Read back the exact created issue and obtain its REST integer id.
gh api --hostname github.com repos/OWNER/REPO/issues/NUMBER
# attachment.json: {"sub_issue_id": INTEGER_REST_ID, "replace_parent": false}
gh api --hostname github.com --method POST repos/PARENT_OWNER/PARENT_REPO/issues/PARENT_NUMBER/sub_issues --input /private/run/attachment.json
# Verify both directions, collecting every page.
gh api --hostname github.com repos/CHILD_OWNER/CHILD_REPO/issues/CHILD_NUMBER/parent
gh api --hostname github.com --paginate --slurp 'repos/PARENT_OWNER/PARENT_REPO/issues/PARENT_NUMBER/sub_issues?per_page=100'
# Exact-marker reconciliation must include open AND closed issues, excluding pull requests.
gh api --hostname github.com --paginate --slurp 'repos/OWNER/REPO/issues?state=all&per_page=100'
```

Flatten slurped page arrays in code before comparing IDs or counts. Exclude objects containing
`pull_request`. Compare the complete hidden marker literally, not just a title or search substring.
A 404 from the parent endpoint alone is not evidence of an unattached issue: first establish that
the issue, repository, endpoint and permissions are accessible, and reconcile the parent's children.
Uncertainty blocks attachment. A successful POST is not read-back verification.

Each issue has only one native parent. Do not send `replace_parent: true`. Existing same-parent
attachments are no-ops only after verified reconciliation. Check all ancestors and proposed
children for cycles and nesting limits. Cross-repository edges within one owner still require
suitable access to both repositories; confirm issue write/triage permissions before mutation.

For approved order, `PATCH /repos/{owner}/{repo}/issues/{number}/sub_issues/priority` takes integer
`sub_issue_id` and one of `after_id` or `before_id`. Walk the intended sequence from its second
item, moving it after its predecessor. Before and after each call, read every child page and require
the ID set to match the approved set. Stop on concurrent changes, and verify final ID order.

## Recovery and acceptance

The private ledger must include the approved plan revision/hash, authenticated identity, coverage
attestation, scan timestamp, each node's marker and destination, submitted body/hash, issue URL,
number and REST ID, intended parent, request outcome and separate read-back status. Preserve it on
failure. A restart resumes this ledger, not a new rollout key.

A timeout can happen after GitHub created an issue. Do not retry creation unless exhaustive
reconciliation establishes no matching issue and no unresolved request. If that cannot be proved,
stop for operator review. Parent attachment recovery independently checks existing relationships.

Manual live acceptance, only in an authorized sandbox:

- Organization tree: two repository issues in different repositories under the same owner; verify
  exact bodies, metadata and both native parents.
- Enterprise-shaped tree: root, two organization epics and repository leaves in the explicitly
  approved centralized destination; verify every edge and represented source ID.
- Applicable, not-applicable and unknown inputs: default omissions; explicit not-applicable opt-in
  yields visibly non-remediation issues. Unknown remains unresolved, never marked unaffected.
- Rerun and interrupted write: no duplicate markers; recover a created-but-unattached issue.
- Permissions, issue-disabled/archived targets and native limits: stop without silent relocation,
  partial-success claims, parent replacement or destructive rollback.

Synthetic tests verify helper control flow only. Do not describe them as a live enterprise scan or
successful issue publication. Keep all actual organization names and security findings out of the
skill's source and public validation report.
