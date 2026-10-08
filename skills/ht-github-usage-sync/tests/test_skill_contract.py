"""Offline documentation contracts; these are NOT native-browser E2E tests."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SkillContract(unittest.TestCase):
    def test_package_contains_no_japanese_text(self):
        japanese = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f\U00020000-\U0002fa1f]")
        paths = [ROOT / "SKILL.md"]
        for directory in ("references", "scripts", "templates", "tests"):
            paths.extend(path for path in (ROOT / directory).rglob("*")
                         if path.is_file() and path.suffix in {".md", ".py", ".yaml", ".yml", ".txt"})
        for path in sorted(paths):
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertNotRegex(path.read_text(encoding="utf-8"), japanese)

    def setUp(self):
        self.skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.export = (ROOT / "references/github-export.md").read_text(encoding="utf-8")
        self.manual = (ROOT / "references/manual-validation.md").read_text(encoding="utf-8")
        self.all_docs = "\n".join((self.skill, self.export, self.manual))

    def require(self, text, *terms):
        for term in terms:
            with self.subTest(term=term):
                self.assertIn(term, text)

    def test_frontmatter(self):
        self.assertTrue(self.skill.startswith("---\n"))
        front = self.skill.split("\n---\n", 1)[0]
        self.require(front, "name: ht-github-usage-sync", "version: 0.1.0",
                     "author: Tadashi Shigeoka", "license: MIT",
                     "tags: [billing, browser, cloud]", "requires_toolsets: [browser, terminal]")
        match = re.search(r'^description: "([^"]+)"$', front, re.M)
        self.assertIsNotNone(match)
        assert match is not None
        desc = match.group(1)
        self.assertTrue(desc.startswith("Use when "))
        self.assertLessEqual(len(desc), 60)
        self.assertEqual(ROOT.name, "ht-github-usage-sync")
        self.assertNotIn("codex", front.lower())

    def test_selection_and_configuration(self):
        self.require(self.skill, "The default is `usage` + `Detailed`", "Process `ai_usage` only when explicitly selected",
                     "`report.page`", "unselected pages", "Completely skip discovery, access, retries, and fallback",
                     "HT_GITHUB_USAGE_CONFIG", "~/.config/hermes-talaria/github-usage.yaml",
                     "Unknown", "configuration errors", "approval", "query", "numeric")

    def test_browser_and_request_contract(self):
        self.require(self.export, "observe -> decide -> act -> observe again", "fixed selectors", "stale element",
                     "gh API", "curl", "urllib", "fetch", "Normal native communication",
                     "by account", "Enterprise", "Email me report", "exactly once",
                     "pending", "not accepted", "SSO", "MFA", "CAPTCHA")

    def test_mail_download_resume(self):
        self.require(self.export, "user_link", "browser_mail", "primary", "forwarding",
                     "individual message", "sender", "receipt time", "untrusted",
                     "mail_verified=false", "30-60 seconds", "10 minutes", "resume",
                     "before clicking/navigating", "download event", "aborted",
                     ".crdownload", "HTTP fallback", "start and end dates", "fixed")

    def test_artifact_and_cloud_contract(self):
        self.require(self.all_docs, "UTC", "reference date", "start of a month", "every day", "31 days", "1 year",
                     "scripts/report_artifact.py", "--kind detailed", "--kind summarized",
                     "--kind ai_usage", "--start-date", "--end-date", "--help",
                     "standard-library", "empty", "original", "SHA256", "all files",
                     "uploaded_unverified", "folder_url", "folder_id", "rclone",
                     "archive", "replace", "sharing-setting", "public-link", "0700", "0600")

    def test_single_page_per_run(self):
        for doc in (self.skill, self.export, self.manual):
            self.require(doc, "`report.page`", "one page per run", "Page arrays are not allowed",
                         "separate runs", "same account", "serially")
        self.assertNotIn("supports explicit selection of both pages", self.all_docs)
        self.assertNotIn("selection of both pages in synthetic state", self.manual)
        self.assertNotIn("for both pages at account level", self.manual)

    def test_private_metadata_and_csv_only_default_manifest(self):
        for doc in (self.skill, self.manual):
            self.require(doc, "The default cloud manifest contains only original CSV files",
                         "Keep metadata private and local", "additional artifact", "explicit approval")
        self.assertNotIn("save the original CSV and validation metadata to the specified cloud", self.skill)
        self.assertNotIn("also include metadata in the delivery manifest", self.skill)
        self.assertNotIn("all files (original CSV and metadata, etc.)", self.manual)

    def test_zero_rows_hold_before_adoption(self):
        for doc in (self.skill, self.export, self.manual):
            self.require(doc, "validator rejects zero rows", "hold", "manual check of the source screen",
                         "before adoption", "Automatic success or upload of zero-row results is prohibited")
        self.assertNotIn("valid empty result", self.all_docs)

    def test_fixed_original_names_and_transport_specific_readback(self):
        for doc in (self.skill, self.manual):
            self.require(doc, "Even in archive mode, the initial filename is immutable", "automatic renaming is prohibited",
                         "same name with different content", "stop", "Use browser re-download only when browser transport is selected",
                         "when rclone is selected, use the selected rclone route", "all original CSV files",
                         "SHA256", "byte count")
        self.assertNotIn("names on collision too", self.skill)
        self.assertNotIn("archive preserves existing files by saving under a different name", self.manual)
        self.assertNotIn("never skip browser readback/byte comparison after saving", self.manual)

    def test_cloud_reference_and_exact_schema(self):
        # Task4 owns the destination guide; assert the link, not its creation here.
        self.require(self.skill, "references/cloud-destinations.md", "`folder_url`", "`folder_id`")
        self.assertNotIn("references/cloud-storage.md", self.skill)
        self.assertNotRegex(self.all_docs, r"folderURL|folderID")

    def test_executable_examples_are_local_only(self):
        blocks = re.findall(r"```(?:sh|bash|python)?\n(.*?)```", self.all_docs, re.S)
        self.assertTrue(blocks, "Executable local verification examples must exist")
        for block in blocks:
            with self.subTest(block=block):
                self.assertNotRegex(block, r"\b(?:curl|wget|rclone|gh)\b|urllib|requests|fetch\(")
                self.assertNotRegex(block, r"https?://|--yolo|cron|\.env")
        artifact_examples = [line for block in blocks for line in block.splitlines()
                             if "report_artifact.py" in line and "--kind" in line]
        self.assertEqual(len(artifact_examples), 3)
        for kind in ("detailed", "summarized", "ai_usage"):
            lines = [line for line in artifact_examples if f"--kind {kind} " in line]
            self.assertEqual(len(lines), 1)
            self.require(lines[0], "--start-date 2025-01-01", "--end-date 2025-01-31")

    def test_owned_reference_links_and_no_completed_e2e_boxes(self):
        self.require(self.skill, "references/github-export.md", "references/manual-validation.md")
        for name in ("github-export.md", "manual-validation.md"):
            self.assertTrue((ROOT / "references" / name).is_file())
        self.assertNotIn("[x]", self.manual.lower())
        self.assertNotRegex(self.all_docs, r"https://github\.com/(?!<)[^\s`)>]+")
        self.assertNotRegex(self.all_docs, r"https://(?:mail|drive)\.[^\s`)>]+")

    def test_privacy_and_unverified_claims(self):
        self.require(self.manual, "mock", "unverified", "Native", "usage", "ai_usage",
                     "browser_mail", "Google Drive", "candidate", "implemented", "execution-verified")
        self.require(self.skill, "signed", "email bodies", "CSV contents", "outside Git",
                     "cron", "Issue", "installation", "profile")
        self.assertNotRegex(self.all_docs, r'/Users/|github\.com/(?:enterprises|orgs)/[^<\s`]+')
        self.assertNotRegex(self.all_docs, r'https://drive\.google\.com/[^\s`]*folders/[^<\s`]+')
        self.assertNotRegex(self.all_docs, r'[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
        self.assertNotRegex(self.all_docs, r'https://github\.com/[^\s`]+/(?:issues|pull)/\d+')


if __name__ == "__main__":
    unittest.main()
