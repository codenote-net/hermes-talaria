# Validation checklist

## Local package checks

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/ht-github-attachment-reupload/tests -v
bash -n scripts/install.sh
git diff --check
```

Also parse frontmatter, confirm name matches directory, check all relative links,
and exercise the installer with a temporary `HERMES_DIR` rather than modifying an
active profile. Local tests validate the helper/package, not the browser workflow.

## Live browser acceptance (requires authorized test targets)

Use harmless original image and PDF/ZIP fixtures. Obtain permission for test posts
and uploads in the chosen repositories first. Never copy real company data merely
to test this skill. Do not create test repositories or change permissions implicitly.

Record each case as passed, failed or not run with evidence; all start **not run**.

- Issue body/comment as source and destination; PR body/conversation comment as
  source and destination; Discussion body/top-level comment/reply as source and
  destination. Cover each surface, new-post and permitted-edit modes.
- Cross-type copies: Issue to Discussion, Discussion to PR, PR to Issue.
- Image and general-file browser download, original-byte inspection, browser upload,
  saved permalink, reload, rendering and browser re-download digest comparison.
- Discussion top-level vs reply routing and correct parent after saving.
- Multiple attachments, repeated source URL, identical basenames and unrelated
  Markdown/HTML/code examples preserved. Reconcile requested occurrence counts.
- Native Save/Open dialog path where needed; remote-browser file locality where used.
- Destination-only user can view/download; session confirmed not to access source.
- No source edits, answer/category changes, permission changes or unrelated posts.

Exercise failure paths only in an authorized sandbox or controlled fixture:
login/SSO pause, unavailable editor, locked/archived target, unsupported type/size,
partial download, HTML login response, upload error, concurrent edit, interrupted
upload and uncertain submission. Verify no silent fallback, unintended overwrite,
blind reupload or duplicate post. Synthetic tests are not live GitHub evidence.

Report untested environments explicitly. One tested Cloud host does not establish
compatibility with all Enterprise Server versions. No suitable repositories,
authenticated browser or restricted-access test identity means these live checks
remain not run, even if every local test passes.
