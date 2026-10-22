# Issue templates

Replace placeholders with approved, evidence-backed prose in the chosen publication language.
Do not post placeholders. Keep keys stable across retries. The represented repository and hosting
repository can differ only after explicit placement/audience approval.

## Enterprise or organization epic

Title: `[Rollout] <request> — <enterprise or organization>`

```markdown
<!-- ht-issue-rollout: ROLLOUT_KEY NODE_KEY -->
## Objective
<Shared request, reason, advisory or policy reference>

## Scope and coverage
<Represented enterprise/organization; scan timestamp; independently verified coverage>
<Applicable, not-applicable, unknown and blocked counts, without leaking restricted names>
<Approved issue placement and any explicit partial-rollout exclusions>

## Completion criteria
- [ ] Every selected repository has a verified native tracking issue.
- [ ] Each applicable repository meets its own remediation acceptance criteria.
- [ ] Unresolved or blocked repositories are explicitly accounted for.

## Hierarchy
<Native sub-issues are authoritative; links here are supplementary only.>
```

Do not mark remediation complete merely because child issues were created. Do not publish private
assessment rows in an epic unless its audience is authorized to see them.

## Applicable repository

Title: `[Action required] <request> — <owner/repository>`

```markdown
<!-- ht-issue-rollout: ROLLOUT_KEY NODE_KEY -->
## Applicability
Applicable to this request.
Repository: <exact represented repository URL and stable ID>
Evidence: <commit SHA, paths, observed versions/configuration, authoritative advisory>

## Requested change
<Repository-specific remedy; supported target version/configuration; deadline if approved>

## Acceptance criteria
- [ ] <Concrete repository-specific fix>
- [ ] <Relevant tests or validation>
- [ ] <Deployment/runtime verification if required, not assumed complete>

## Coordination
<Rollout reference and approved dependencies; native parent verified separately>
```

## Not-applicable repository — explicit opt-in only

Title: `[Not applicable] <request> — <owner/repository>`

```markdown
<!-- ht-issue-rollout: ROLLOUT_KEY NODE_KEY -->
**Not applicable to this request — no remediation required.**

## Assessment
Repository: <exact represented repository URL and stable ID>
Evidence: <commit SHA, paths and relevant observed facts>
Reason: <Why the supplied applicability criteria do not match>

## Tracking purpose
Created at the user's explicit request for administrative coverage only.
This issue does not indicate an affected or vulnerable repository.
```

Do not substitute this template for unknown applicability or missing access. Do not add remediation
checkboxes, affected labels or remediation deadlines. Do not automatically close the issue.
