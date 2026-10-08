# 個人設定の契約と検証

`github-usage.example.yaml` は架空の設定例。**このテンプレート自体を実行設定として指定しない**（Git内パスなので拒否される）。個人用コピーはGit管理外へ保存する。実在する組織・リポジトリ・顧客ID・メール・帳票・認証情報を共有ファイルやテストへ転記しない。

## 設定の探索と型

- 明示パス > `HT_GITHUB_USAGE_CONFIG` > `~/.config/hermes-talaria/github-usage.yaml`。上位指定が無効でも下位へフォールバックしない。
- `load_config(explicit=None) -> dict` は指定された設定だけを読み、正規化する。`.env`、Cookie、rclone設定、認証ファイルは読まない。
- `validate_config(dict) -> dict` は元の辞書を変更せず、既定値を含むコピーを返す。
- `ConfigError(ValueError)` が検証エラー。エラー文に入力値を含めない。CLIは設定のURL・メール・remote名・パス・enterpriseを表示しない。
- YAMLは`SafeLoader`派生。重複キー（マージ後の重複も）、未知キー、秘密キー、誤った型を拒否する。整数項目にboolは不可。`version`は整数`1`だけ。
- 設定ファイルと`local.output_dir`はsymlinkを解決し、存在しない子パスは最寄りの既存親からGitリポジトリを探索する。無視対象でもGit内なら拒否する。ルート・上位参照も拒否。Gitコマンドが使えず安全を確認できない場合は停止する。保存直前にも同じ検証を行う（後からsymlink/リポジトリ状態が変わる可能性がある）。

## GitHub・取得・通知

- `github`の必須項目は`deployment: enterprise_cloud`、`enterprise`（slug）、`pages`。
- `pages.usage`と`pages.ai_usage`は`{url: 完全HTTPS URL}`またはnull。選択ページは必須。URLは資格情報を含めず、クエリを保持し、その意味を推測しない。URLの対象enterprise・表示ページはブラウザで照合する。
- `report.page`は`usage`が既定、`kind`は`detailed`が既定。usageでは`detailed`/`summarized`、ai_usageでは**明示的な**`kind: ai_usage`だけ。
- `acquisition.method`は`browser`のみ。API・HTTP取得は対象外。
- `notification.mode: user_link`が既定。ユーザーからダウンロードリンクを受け取る。
- `browser_mail`では`mail_url`（HTTPS）、`expected_recipient`（メール）、`expected_account`（画面で照合するアカウント文字列）が必須。承認済み転送先は`approved_forwarded_recipients`のメール配列。自動的に宛先を推測しない。
- メール待機間隔`wait_interval_seconds`は30〜60秒（既定30）、上限`wait_timeout_seconds`は1〜600秒（既定600）。どちらも整数のみ（bool不可）、間隔≦上限。user_linkにメール設定を混ぜない。

## 期間の確定と再開

API: `resolve_period(report, observed_start=None, observed_end=None, now=None) -> dict`。
エラーは`PeriodError(ValueError)`。`now`はタイムゾーン付きdatetime、省略時は現在UTC時刻。

`report.period`で許されるキーは`mode`、`timezone`、`reference_date`、`start_date`、`end_date`だけ。

- `timezone`は利用可能なIANA名、既定UTC。特定の地域を固定しない。
- `reference_date`は引用符付き`"YYYY-MM-DD"`。省略時はnowを設定timezoneへ変換した日付。明示した基準日がその日付より未来なら全モードで拒否する（UTCとの日付差だけでは拒否しない）。YAMLの日付オブジェクトは不可。
- `page_selection`（既定）: ブラウザで観測した両端を`observed_start`/`observed_end`へ渡す。URLやクエリから推測しない。片端だけでは失敗する。
- `previous_month`: 基準日の前暦月の初日〜末日。
- `current_month`: 基準日の暦月初日〜基準日。ただし終了日はUTCの今日を超えない。timezoneがUTCより先の月に入っていて、UTCでは前月の場合、取得可能な範囲がないので停止する。
- `custom`: 引用符付き`start_date`/`end_date`が必須。開始日≦終了日。他のモードにこの2キーを混ぜない。
- 両端を含め、detailed/ai_usageは最大31日。summarizedは最大1暦年（例: 2024-01-01〜2024-12-31）。閏日開始は翌年2月末まで。
- 観測・custom・前月を含め、UTCの今日より後の終了日は拒否する。現在月・今日のデータは未完了の場合がある。これは日付上限の検証であってデータ可用性の保証ではない。画面に該当期間・種類がなければ停止してユーザーに確認する。

戻り値は`start_date`、`end_date`、`reference_date`、`timezone`。初回にGit管理外へ保存し、再開時には`report.period`を`mode: custom`と保存済み4項目で構成する。初回の確定期間を再計算しない。page/kindは正規化済み`config['report']`に別途保持する。

期間上限・UTC記録の根拠: [GitHub Billing reports reference](https://docs.github.com/en/billing/reference/billing-reports)。メール取得の根拠: [Downloading usage reports](https://docs.github.com/en/billing/how-tos/products/view-productlicense-use#downloading-usage-reports)。現在月の切り詰めはこのスキルの安全な期間解決方針であり、画面の選択肢を保証しない。

## 保存先の対応表

`destination.provider`は明示必須。`transport`はbrowserが既定。

| transport | provider | 必須キー | 任意キー |
|---|---|---|---|
| browser | google_drive | `folder_id`, `folder_url` | なし |
| rclone | google_drive | `remote`, `folder_id` | `shared_drive_id` |
| rclone | onedrive / sharepoint / dropbox | `remote`, `folder_path` | なし |
| rclone | box | `remote`, `folder_id` | なし |
| rclone | s3 / gcs | `remote`, `bucket`, `prefix` | なし |

browserはGoogle Driveのみ。他のbrowser組み合わせは明示的に未対応。Google DriveのURLは`https://drive.google.com/drive/folders/<folder_id>`と一致する必要がある。HTTPや他ホスト、ルート保存は不可。

rcloneの`remote`は既存の名前参照のみ（英数字で開始、以後英数字・`_`・`-`）。コロン・パス・空白・フラグを禁止。remoteの設定・秘密情報は完全に外部へ置く。フォルダーパスとprefixは空でない相対パスで、`..`、`.`、空要素、先頭スラッシュ、バックスラッシュ、コロンを禁止。Boxのroot ID `0`、ID `root`を拒否する。互換性のない保存先キーを混在させない。

例（`destination`だけを置き換える）:

```yaml
destination:
  provider: s3
  transport: rclone
  remote: example_remote
  bucket: example-bucket
  prefix: reports/github-usage
```

`upload.mode`はarchiveが既定。replaceは明示指定だけ。`local.output_dir`の既定は`~/.local/share/hermes-talaria/github-usage/`で、Git管理外であることを検証する。

## 検証コマンドと実行証拠

リポジトリルートから実行。venvはGit管理外に作る。

```sh
python3 -m venv /tmp/ht-usage-sync-venv
/tmp/ht-usage-sync-venv/bin/pip install 'PyYAML>=6,<7'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=skills/ht-github-usage-sync/tests \
  /tmp/ht-usage-sync-venv/bin/python -m unittest test_config test_report_period -v
/tmp/ht-usage-sync-venv/bin/python skills/ht-github-usage-sync/scripts/validate_config.py \
  --config /path/outside/git/github-usage.yaml
```

合成テストを先に作り、実装前に`ModuleNotFoundError: No module named 'validate_config'`と`report_period`を確認した（RED）。Boxルート拒否の追加テストも実装前に`ConfigError not raised`を確認した。実装後の上記限定テストは`Ran 16 tests ... OK`（GREEN）。依存はPyYAML 6.0.3を外部venvに導入。CLI成功時の値非表示、失敗時のexit 2・メール/URL/パス非表示も実プロセスで検証済み。実際のユーザー設定・認証・クラウドにはアクセスしていない。
