---
name: ht-gitignore-setup
description: "Inspect a local directory or GitHub repository, then create or improve the correctly scoped .gitignore from verified upstream templates and project evidence."
version: 1.0.0
author: Tadashi Shigeoka
license: MIT
platforms: [linux, macos, windows]
allowed-tools: [terminal, read_file, write_file, patch, search_files]
prerequisites:
  commands: [git]
metadata:
  hermes:
    tags: [git, gitignore, repository, setup, hygiene]
    requires_toolsets: [terminal, file]
---

# Set Up `.gitignore`

Create or improve a repository-appropriate `.gitignore` after inspecting the actual project. Use
verified upstream templates as evidence, not as an unquestioned concatenation service. Keep the
result focused, explainable, and safe for tracked source files.

## When to use

- The user asks to create, initialize, repair, review, or optimize a `.gitignore`.
- The target is the current directory, another local directory, a GitHub repository URL, or a
  directory within one of those targets.
- A monorepo or nested project needs a decision about root versus nested ignore scope.

Do not use this skill to remove files from Git history, purge secrets, configure a personal global
ignore file, or commit/push changes unless the user separately asks for that work.

## Input and defaults

Accept one optional target and one optional scope request.

- No target: use the current working directory.
- Local path: resolve it to an absolute path without changing unrelated directories.
- GitHub repository URL: accept `https://github.com/OWNER/REPOSITORY` with optional `.git`.
- GitHub tree URL: accept `https://github.com/OWNER/REPOSITORY/tree/REF/PATH` and treat `PATH` as
  the requested subdirectory after cloning. If the ref/path split is ambiguous, use GitHub APIs or
  `gh` to resolve the ref; do not guess where the branch name ends.
- Reject issue, pull-request, blob, non-GitHub, and syntactically ambiguous URLs unless the user
  clarifies the intended repository and path.
- Reject URLs containing userinfo or embedded credentials before passing them to any command,
  network client, log, or diagnostic.

When scope is not specified:

1. No target, an explicit repository root, or a repository URL means repository scope: inspect the
   whole worktree and place `.gitignore` at its root.
2. An explicit nested local directory or GitHub tree path means target scope: inspect the repository
   root for context, scan the requested subtree in detail, and place `.gitignore` in that requested
   directory. Rules in this file apply only at and below that directory.
3. A non-Git directory uses that directory as both scan root and placement scope.
4. An explicit user request for `repository` or `target` scope overrides these defaults.
5. If existing monorepo policy conflicts with the default placement, do not silently redirect the
   change. Explain the conflict and obtain the user's scope decision before writing.

Keep these concepts separate and state them before changing anything: repository context root,
detailed scan target, rule scope, and intended `.gitignore` path.
Capture the initial Git status and preserve all pre-existing changes; they are not part of this
skill's work and must not be reverted, reformatted, or reported as newly created changes.

## Template source policy

Read [template-sources.md](references/template-sources.md) before fetching any template.

The primary source is GitHub's `github/gitignore` repository. Resolve its current `main` commit,
then fetch every selected template from a raw URL pinned to that exact commit. Prefer root templates;
use `community/` only for a specialized technology proven by repository evidence. Do not place
`Global/` operating-system or editor rules into a shared project file by default.

Do not silently substitute remembered template text, search-result snippets, package defaults, or
AI-generated broad patterns when upstream retrieval fails. Either continue with narrowly justified
project-specific rules and disclose that no upstream template was used, or stop if a required
language/framework baseline cannot be verified.

## Procedure

### 1. Resolve and prepare the target

For a local target, verify that the path exists and is a directory. Record these when available:

```bash
git -C "<TARGET>" rev-parse --show-toplevel
git -C "<TARGET>" rev-parse --show-prefix
git -C "<TARGET>" status --short --branch
```

A failure from `rev-parse` means the target is not in a Git worktree; it does not make the directory
invalid.

For a GitHub URL:

1. Validate the URL syntax and reject userinfo or embedded credentials before any network or shell
   operation. Ask for a clean HTTPS GitHub URL instead of sanitizing and continuing silently.
2. Verify repository identity and default branch with `gh repo view` when authenticated `gh` is
   available, otherwise use GitHub's public repository API.
3. Clone into a fresh temporary directory with `gh repo clone` or `git clone`. Never reuse or
   overwrite an existing path.
4. For a tree URL, resolve `REF` to an exact commit, check out that commit in the clone (normally as
   a detached HEAD), and only then verify `PATH`. Inventory and modify that exact checkout, not the
   repository's default branch. Record both the supplied ref and resolved commit.
5. Modify only the local clone. Do not create a branch, commit, push, fork, or open a pull request
   unless explicitly requested.
6. Report the clone path so the user can find the result.

Do not print, normalize, or inspect credential values embedded in a rejected URL.

### 2. Inventory the project before choosing rules

Gather filenames and repository metadata first. Do not read secret file contents.

Inspect at least:

- existing root and nested `.gitignore` files;
- `.git/info/exclude` and the configured global excludes path, only to distinguish local behavior
  from repository policy;
- tracked paths from `git ls-files` when this is a repository;
- untracked and already ignored paths from `git status --short --untracked-files=all` and
  `git status --short --ignored`;
- top-level and workspace-level manifests, lockfiles, build configuration, tool-version files, and
  CI configuration;
- representative directory names at bounded depth, excluding `.git` and avoiding dependency/build
  trees that are already obviously large;
- existing repository instructions such as `AGENTS.md`, `CLAUDE.md`, and contribution docs.

Useful evidence includes:

- languages and build systems: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, solution or
  project files, Gradle files, and their lockfiles;
- generated output: framework config, compiler output settings, coverage/test config, docs builders,
  and deployment adapters;
- local state: caches, virtual environments, local databases, logs, PID files, and tool state;
- secret-bearing filename conventions: `.env`, local override files, keys, and credentials. Inspect
  names and documented conventions, never values.

Do not infer an ecosystem solely from an untracked generated directory. Require a manifest,
configuration file, tracked source extension, or repository documentation.

### 3. Select and retrieve upstream templates

Map only evidenced technologies to candidate templates. Verify each candidate path exists upstream
before using it. Resolve and record the upstream commit once per run so all templates come from one
snapshot.

Example retrieval flow:

```bash
UPSTREAM_SHA="$(curl -fsSL https://api.github.com/repos/github/gitignore/commits/main \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')"
curl -fsSL \
  "https://raw.githubusercontent.com/github/gitignore/${UPSTREAM_SHA}/Node.gitignore" \
  -o "<TEMP_DIR>/Node.gitignore"
```

If `python3` is unavailable, parse the API response with an installed JSON-aware tool such as `jq`,
or use `gh api`. Do not parse JSON with regular expressions. Check the HTTP failure status and reject
empty downloads.

Use templates as a reviewed baseline:

- retain rules relevant to the detected project;
- omit irrelevant package-manager, framework, IDE, and operating-system sections;
- add project-specific rules only when generated/local artifacts or configuration justify them;
- preserve ordering where negation (`!`) rules depend on earlier exclusions;
- avoid duplicate blocks, contradictory patterns, and speculative catch-all rules.

### 4. Design the candidate

A good project `.gitignore` normally covers reproducible or local-only artifacts while retaining
source, lockfiles, migrations, fixtures, examples, and intentionally committed configuration.

Use these principles:

1. Prefer directory-anchored patterns when only a known root output directory should be ignored
   (for example, `/dist/` rather than `dist/` everywhere).
2. Use recursive patterns only when the artifact can validly occur throughout a workspace.
3. Ignore secret-bearing local files conservatively, then add explicit sample-file exceptions such
   as `!.env.example` only when those samples exist or repository policy calls for them.
4. Do not ignore all files of a source-like extension merely because some generated files use it.
5. Do not ignore lockfiles by default. Follow the ecosystem and repository's established policy.
6. Do not add macOS, Windows, Linux, editor, or personal-tool noise solely because it exists on the
   current machine. Recommend a global excludes file for personal artifacts.
7. Preserve existing comments and intentional exceptions unless evidence proves they are stale or
   harmful.
8. Keep sections small and label their purpose. Include a short provenance comment naming selected
   upstream template paths and the pinned commit URL when template content materially shaped the
   file.

If an existing `.gitignore` is present, patch it instead of replacing it wholesale. Show material
behavior changes in the diff. If ownership or intent of an existing unusual rule is unclear, retain
it and flag it rather than deleting it speculatively.

### 5. Pre-write safety analysis

Before writing, evaluate the candidate in a temporary validation tree outside the target worktree.
Confirm that it does not unexpectedly match tracked files. `git check-ignore` normally suppresses
tracked paths, so include `--no-index` for this check:

```bash
git -C "<REPO_ROOT>" ls-files -z \
  | git -C "<REPO_ROOT>" check-ignore --stdin -z -v --no-index
```

Run the check against the candidate rules, not merely the unchanged worktree. Build a temporary
validation repository that preserves the candidate's repository-relative path, relevant ancestor
and descendant `.gitignore` files, and the original tracked path list. Use placeholder files when
content is unnecessary; never copy secret contents. Do not write the candidate into the real
worktree as a pre-validation shortcut, and do not rely on remembered content as rollback protection.

Review every matched tracked path. A tracked generated artifact may be intentional; do not assume it
should become untracked. This skill never runs `git rm --cached`.

Also test representative paths for every important rule and exception. Include both a path that
should be ignored and a nearby path that must remain visible.

### 6. Write the file

Create a new `.gitignore` with the file-writing tool. Modify an existing one with a targeted patch.
Use UTF-8, LF line endings, and one final newline. Do not modify global Git configuration,
`.git/info/exclude`, tracked files, or nested ignore files unless they are part of the explicitly
resolved scope.

### 7. Verify actual Git behavior

After writing, run all applicable gates:

```bash
git -C "<REPO_ROOT>" diff --check -- "<GITIGNORE_PATH_RELATIVE_TO_ROOT>"
git -C "<REPO_ROOT>" diff -- "<GITIGNORE_PATH_RELATIVE_TO_ROOT>"
git -C "<REPO_ROOT>" status --short --ignored
```

For a newly created, untracked `.gitignore`, ordinary `git diff` has no content to show. Review it
explicitly with a no-index diff and run its whitespace check. Distinguish an expected "different"
status from whitespace-error output:

```bash
git diff --no-index -- /dev/null "<ABSOLUTE_GITIGNORE_PATH>"
git diff --no-index --check -- /dev/null "<ABSOLUTE_GITIGNORE_PATH>"
```

Then:

1. Re-run the tracked-file check with `git check-ignore --no-index` and classify every match as
   intended or a defect.
2. Use `git check-ignore -v -n --no-index -- <IGNORED_PATH> <RETAINED_PATH>` for representative
   ignored and retained paths. `--non-matching` (`-n`) makes the retained-path result explicit;
   classify each output record rather than relying on command silence.
3. Verify generated/output directories evidenced during scanning are ignored.
4. Verify manifests, lockfiles, source directories, fixtures, migrations, examples, and sample
   configuration remain unignored unless the repository explicitly says otherwise.
5. Confirm the `.gitignore` itself is visible to Git.
6. Compare against the initial status: confirm no pre-existing change was altered and no new path
   other than the intended `.gitignore` was changed by this workflow.

For a non-Git directory, initialize only a temporary validation repository around a copy of the
candidate and representative paths. Never run `git init` in the user's target merely to validate.

If a check fails, fix the rule and repeat all affected checks. Do not report success from file
existence alone.

## Reporting

Report:

- the resolved local target, scan root, scope, and `.gitignore` path;
- whether the file was created or updated;
- detected technologies and the evidence used to identify them;
- exact upstream template paths, resolved commit SHA, and commit URL, or that no upstream template
  was used;
- important project-specific rules and deliberate omissions;
- tracked-file matches found during validation and how each was resolved;
- commands/checks run and their real outcomes;
- any remaining uncertainty or follow-up that requires user intent.

Do not call the GitHub repository updated when only a temporary/local clone changed.

## Pitfalls

- Copying a giant generated template without checking the project.
- Treating `Global/` editor and OS templates as shared repository policy.
- Scanning only the selected subdirectory while placing rules at the repository root.
- Overwriting an existing file and losing negation order or documented exceptions.
- Using `git check-ignore` without `--no-index` and falsely concluding tracked files do not match.
- Assuming a newly ignored tracked file stops being tracked.
- Reading `.env`, key, credential, or other secret contents during discovery.
- Running `git clean`, `git rm --cached`, `git init`, commit, or push as part of setup.
- Guessing how to split a GitHub tree URL whose branch contains slashes.
- Claiming remote completion after changing only a clone.

## Completion checklist

- [ ] Target, repository root, placement path, and scope were explicitly resolved.
- [ ] Existing ignore layers and repository instructions were inspected.
- [ ] Languages, tools, generated output, and local state were inferred from evidence.
- [ ] Every fetched template came from one verified, commit-pinned upstream snapshot.
- [ ] Existing rules and negation ordering were preserved where applicable.
- [ ] No tracked source/configuration file is unexpectedly matched by the candidate.
- [ ] Representative ignored and retained paths were behaviorally tested.
- [ ] Only the intended `.gitignore` changed.
- [ ] The final report identifies exact sources and real verification results.
