# Browser transfer runbook

## Tool selection and locality

Inspect the live browser tool schema or Agent Browser CLI help before choosing
commands. Navigate and inspect current DOM/accessibility state; do not ship fixed
GitHub CSS selectors, coordinates, guessed endpoints or command flags. Refresh
observations after navigation, modal changes and each mutation.

A browser file-input selection API is allowed when it selects existing bytes in
the observed destination editor. Browser download-event capture is allowed when
triggered by the normal page action. Neither permits synthesizing HTTP requests.
Use Computer Use for native file choosers, context menus and Save dialogs; load its
skill first. Capture the specific app, use fresh element references, start with
background interaction, verify effects before retries, and request approval before
foreground escalation. Do not take over unrelated tabs or the user's desktop.

Identify browser host, download directory and chooser filesystem first. Test path
visibility with a harmless local fixture if needed; it proves locality only, not
GitHub upload support. If remote browser bytes cannot be inspected with local tools,
use tools in that same environment or pause for a user-approved handoff. Never
assume a browser-returned remote path is readable on the agent host.

## Target distinctions

| Target | Required identity check |
| --- | --- |
| Issue body / PR body / Discussion body | Repository, number, title, body editor |
| Issue / PR conversation comment | Exact permalink and comment author; not PR inline review |
| Discussion top-level comment | Discussion and top-level composer |
| Discussion reply | Discussion, parent comment and reply composer; verify nesting after save |

Expand hidden comments/replies to resolve the requested permalink. If a fragment
resolves to a body, do not treat it as a comment. For editing, require the edit
control for that exact object; no permission means blocked, not a new-post fallback.
GitHub Server versions and Discussion categories can differ. Observe allowed file
types, size limits, upload affordances, locked/archived state and errors live.

## Download and upload evidence

- Download: normal attachment action, browser completion event/download UI, unique
  on-disk file, expected type and plausible metadata, local digest. Reject login
  HTML, page saves and previews. For images choose the original, not its thumbnail.
- Upload: destination identity and audience approval before selecting bytes; UI
  completion and newly inserted permanent URL for each file; no error banner.
- Publication: exact permalink and fresh read-back of content after submission.
- Verification: browser rendering/playback where applicable, browser re-download
  of original bytes and matching digest. Permission verification is separate.

Different URLs on the same asset CDN do not prove repository association. The
upload action must occur in the destination's editor, and destination-only access
must still be tested. Do not claim a hostname comparison proves authorization.

## Ledger discipline

Copy the template outside Git into the private run directory. Store evidence paths
there as well, not in this package. Never store cookies or temporary signed URLs.
Assign a run-local item ID independent of filename. Deduplicate identical source
URLs but retain every approved occurrence; do not deduplicate solely by basename.
Record distinct downloads when URL identity is uncertain.

| State | Evidence required |
| --- | --- |
| pending | Source context, selected occurrences and destination scope |
| downloaded | Browser completion and local name/size/SHA-256 |
| uploaded | Exact destination editor and observed new permanent asset URL |
| published | Exact saved body/comment/reply permalink and read-back |
| verified | Rendering/download check and matching re-download digest |
| blocked | Reason plus last verified state; never erase successful evidence |

Permission status: `not_verified`, `verified`, or `failed`, with evidence describing
which permissions the test session had (no credentials). An agent-authored ledger
is a record of observations, not independent proof that they occurred.

If ambiguous upload/submission outcomes cannot be reconciled against the live
editor/thread, pause instead of creating another copy. Uploaded-but-unpublished
assets may remain on GitHub: closing a draft or removing a local file is not proof
of remote deletion. Ask before removing a published comment or changing existing
content as rollback, and verify only the operation actually performed.

## Sources

- [GitHub attachment documentation](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files)
- [Discussion collaboration documentation](https://docs.github.com/en/discussions/collaborating-with-your-community-using-discussions)

Consult the matching Enterprise Server documentation for the actual host version
when needed. Documentation is a reference; runtime UI evidence and authorization
remain mandatory. CLI attachment support does not change this skill's browser-only
transfer contract.
