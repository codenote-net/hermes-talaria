# Template source policy

## Primary source: GitHub's official collection

Use [`github/gitignore`](https://github.com/github/gitignore) as the primary upstream collection.
GitHub's own documentation describes it as GitHub's official list of recommended `.gitignore`
files for popular operating systems, environments, and languages:

- Documentation: <https://docs.github.com/en/get-started/git-basics/ignoring-files>
- Collection: <https://github.com/github/gitignore>
- License: [CC0-1.0](https://github.com/github/gitignore/blob/main/LICENSE)

The upstream README states that GitHub uses this collection to populate the template chooser on
GitHub.com. It divides templates into three groups:

- repository root: common mainstream languages and technologies;
- `Global/`: editors, tools, and operating systems, recommended primarily for a user's global
  excludes file;
- `community/`: specialized languages, frameworks, tools, and older version-specific templates.

This skill therefore prefers root templates, uses `community/` only with explicit project evidence,
and does not merge `Global/` templates into a shared project file by default.

## Reproducible retrieval

Resolve the current upstream `main` SHA once at the start of a run:

```bash
curl -fsSL https://api.github.com/repos/github/gitignore/commits/main
```

Parse the JSON `sha` with `python3`, `jq`, or `gh api`. Fetch all selected templates through URLs
pinned to that SHA:

```text
https://raw.githubusercontent.com/github/gitignore/<SHA>/<TEMPLATE_PATH>
```

Record all of the following in the final report:

- the full 40-character SHA;
- `https://github.com/github/gitignore/commit/<SHA>`;
- every selected template path, such as `Node.gitignore` or
  `community/JavaScript/NextJS.gitignore`.

Check HTTP status, reject empty content, and use the same SHA for all templates in one run. A mutable
`main` raw URL is acceptable for initial discovery but not as the recorded source of generated
content.

Unauthenticated GitHub API calls are rate-limited. If an authenticated `gh` client is available,
prefer:

```bash
gh api repos/github/gitignore/commits/main --jq .sha
```

Do not expose authentication tokens in commands or output.

## Secondary source considered but not automatic

GitHub's documentation also links to [gitignore.io](https://www.gitignore.io/), which currently
redirects to Toptal's gitignore generator. Do not use it automatically in this skill. Its generated
output is a dynamic aggregation, is less straightforward to pin as one reviewed source snapshot,
and may be unavailable to automated clients. It can be used only when the user explicitly requests
it; in that case, record the exact request URL and response retrieval time and still review every
rule against repository evidence.

## Project-specific rules

Rules derived from manifests, compiler/build settings, framework configuration, generated files, or
repository documentation are project-specific rather than copied templates. Explain the evidence
for each non-obvious project-specific section. Never claim that such rules came from GitHub's
collection.

If upstream access fails, do not reconstruct a template from memory. Either:

1. create only narrow project-specific rules supported by local evidence and disclose that no
   upstream template was used; or
2. stop when a verified upstream baseline is necessary for a safe result.
