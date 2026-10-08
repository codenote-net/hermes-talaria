"""Offline documentation contracts; these are NOT native-browser E2E tests."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SkillContract(unittest.TestCase):
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
        self.require(self.skill, "既定は `usage` + `Detailed`", "`ai_usage` は明示選択時だけ",
                     "`report.page`", "非選択ページ", "探索・アクセス・再試行・フォールバックも完全に省略",
                     "HT_GITHUB_USAGE_CONFIG", "~/.config/hermes-talaria/github-usage.yaml",
                     "未知", "設定エラー", "承認", "クエリ", "数値")

    def test_browser_and_request_contract(self):
        self.require(self.export, "観察→判断→操作→再観察", "固定セレクタ", "古い要素",
                     "gh API", "curl", "urllib", "fetch", "通常のネイティブ通信",
                     "アカウント単位", "Enterprise", "Email me report", "一度だけ",
                     "pending", "未受理", "SSO", "MFA", "CAPTCHA")

    def test_mail_download_resume(self):
        self.require(self.export, "user_link", "browser_mail", "primary", "転送",
                     "個々のメッセージ", "送信者", "受信時刻", "未信頼",
                     "mail_verified=false", "30〜60秒", "10分", "再開",
                     "クリック/遷移前", "ダウンロードイベント", "aborted",
                     ".crdownload", "HTTPフォールバック", "開始日・終了日", "固定")

    def test_artifact_and_cloud_contract(self):
        self.require(self.all_docs, "UTC", "参照日", "月初", "全日", "31日", "1年",
                     "scripts/report_artifact.py", "--kind detailed", "--kind summarized",
                     "--kind ai_usage", "--start-date", "--end-date", "--help",
                     "標準ライブラリ", "空", "原本", "SHA256", "全ファイル",
                     "uploaded_unverified", "folder_url", "folder_id", "rclone",
                     "archive", "replace", "共有設定", "公開リンク", "0700", "0600")

    def test_single_page_per_run(self):
        for doc in (self.skill, self.export, self.manual):
            self.require(doc, "`report.page`", "1実行1ページ", "ページ配列は不可",
                         "別run", "同一アカウント", "直列")
        self.assertNotIn("両ページの明示選択に対応", self.all_docs)
        self.assertNotIn("両ページの選択を合成状態", self.manual)
        self.assertNotIn("両ページならアカウント単位", self.manual)

    def test_private_metadata_and_csv_only_default_manifest(self):
        for doc in (self.skill, self.manual):
            self.require(doc, "既定のクラウドmanifestは原本CSVのみ",
                         "メタデータは私的ローカル", "追加成果物", "明示承認")
        self.assertNotIn("元CSVと検証用メタデータを指定クラウドへ保存", self.skill)
        self.assertNotIn("メタデータも配送対象manifestへ含める", self.skill)
        self.assertNotIn("全ファイル（原本CSVとメタデータ等）", self.manual)

    def test_zero_rows_hold_before_adoption(self):
        for doc in (self.skill, self.export, self.manual):
            self.require(doc, "ゼロ行はvalidatorが拒否", "保留", "元画面の手動確認",
                         "採用前", "自動成功・アップロードは禁止")
        self.assertNotIn("有効な空結果", self.all_docs)

    def test_fixed_original_names_and_transport_specific_readback(self):
        for doc in (self.skill, self.manual):
            self.require(doc, "archiveでも初回ファイル名は不変", "自動改名は禁止",
                         "同名異内容", "停止", "browser選択時だけブラウザ",
                         "rclone選択時は選択済みrclone経路", "全原本CSV",
                         "SHA256", "バイト数")
        self.assertNotIn("衝突時の名前も", self.skill)
        self.assertNotIn("archiveは既存を残す別名保存", self.manual)
        self.assertNotIn("保存後のブラウザ読戻し/バイト比較も省略しない", self.manual)

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
        self.require(self.manual, "mock", "未検証", "ネイティブ", "usage", "ai_usage",
                     "browser_mail", "Google Drive", "候補", "実装済み", "実行確認済み")
        self.require(self.skill, "署名付き", "メール本文", "CSV本文", "Git管理外",
                     "cron", "Issue", "インストール", "プロファイル")
        self.assertNotRegex(self.all_docs, r'/Users/|github\.com/(?:enterprises|orgs)/[^<\s`]+')
        self.assertNotRegex(self.all_docs, r'https://drive\.google\.com/[^\s`]*folders/[^<\s`]+')
        self.assertNotRegex(self.all_docs, r'[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
        self.assertNotRegex(self.all_docs, r'https://github\.com/[^\s`]+/(?:issues|pull)/\d+')


if __name__ == "__main__":
    unittest.main()
