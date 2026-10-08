# クラウド保存先と検証（任意の転送）

GitHubレポートの取得は引き続き**ブラウザーのみ**。このガイドと `scripts/upload_report.py` は、取得済み・ローカル検証済みの原本CSVの保存だけを扱う。rcloneは任意であり、ブラウザー保存にインストールやrclone認証は不要。認証、アカウント対応確認、重複リクエストの予約・状態管理は [local-workflow.md](local-workflow.md) に従う。本アダプターは台帳を更新しない。

## サービス / transport 対応表

「実装」はローカル契約テストと手順の存在を意味する。**全行とも実クラウドでの実行・認証・権限検証は未実施**。mockのJSONを実サービス成功の証拠にしない。

| provider | browser | rclone backend | 保存先指定 / 前提 | 実行検証 |
|---|---|---|---|---|
| `google_drive` | 以下の適応手順（既定） | `drive` | browser: `folder_url` + `folder_id`。rclone: `remote` + `folder_id`、任意の `shared_drive_id` | 未検証 |
| `onedrive` | 未実装 | `onedrive` | `remote` + `folder_path`、対象アカウントの事前確認 | 未検証 |
| `sharepoint` | 未実装 | `onedrive` | `remote` + `folder_path`。対象サイト・ドキュメントライブラリを設定済みのremoteが必要。backend一致だけではサイトを証明しない | 未検証 |
| `dropbox` | 未実装 | `dropbox` | `remote` + `folder_path`、アプリの可視範囲を確認 | 未検証 |
| `box` | 未実装 | `box` | `remote` + 非ルート `folder_id` | 未検証 |
| `s3` | 未実装 | `s3` | `remote` + `bucket` + 非空 `prefix`、対象エンドポイント/アカウントを事前確認 | 未検証 |
| `gcs` | 未実装 | `googlecloudstorage` | `remote` + `bucket` + 非空 `prefix`、対象プロジェクト/アカウントを事前確認 | 未検証 |

全rcloneプロバイダーにarchive新規保存と同一内容のreadback検証を実装。異なる内容のreplaceはOneDrive/SharePoint/Dropbox/S3/GCSのみ、正確な `remote:key` の明示承認が必須。Drive/Boxは名前による `copyto` で承認済みIDへの更新を保証できないため、異なる内容のreplaceを拒否する。Driveはブラウザーで対象IDを確認する。Boxのブラウザー自動化は未実装であり、手動判断が必要。

## GoogleDrive: 現在画面に応じたブラウザー保存

1. 個人設定の `folder_url` を開き、URLのフォルダーIDと `folder_id` の一致を確認する。ルート、別フォルダーへのリダイレクト、ショートカットの曖昧な対象は不可。現在のGoogleアカウント、共有ドライブ、パンくず、書き込み権限を画面で確認し、利用者が正確な保存先を承認する。ログイン/権限不足では停止。別アカウントを推測しない。
2. 原本CSVのダウンロード完了を確認し、Git外の0700ディレクトリで0600にする。レポート種別・UTC範囲・CSV構造を `report_artifact.py` で検証する。ファイル名はrunに登録した固定名を維持し、再開時に新しい名前を生成しない。元のバイト列は書き換えない。
3. 現在の画面を観察して同名ファイル/フォルダーを調べる。Driveは同名複数ファイルがあり得るため、名前だけで対象を選ばず詳細・IDを確認する。同名が複数、同名フォルダー、確認できない対象は停止。既存CSVをその**ファイルID**からダウンロードし、下記の比較を実行。同じならアップロードを省略できるが、readback証拠は必要。archiveで異なる内容なら停止し、勝手な上書きや自動改名はしない。replaceは正確な既存ファイルIDについて個別承認を得てから、画面の対象ファイル更新/バージョン管理操作を確認する。一般的な「はい」だけで置換しない。
4. 現在のUIから「新規」→「ファイルをアップロード」等の可視操作を選択する。固定座標、固定ラベルだけに依存せず、言語・画面サイズ・メニュー状態を毎回観察する。ネイティブファイル選択ダイアログを開いたら、OSのファイルピッカーで検証済み原本CSVだけを指定する。ダイアログに対応する操作ツールがない場合は利用者に選択を依頼して停止/再開する。ブラウザーDOMだけでOSダイアログを操作できたと偽らない。
5. 原本CSVのみを送る。YAML、台帳、認証情報、SHA/metadataのサイドカーは既定でローカルに保持する。アップロード完了表示の後、対象フォルダーの新規ファイルの名前・IDを再確認する。共有、公開リンク、権限変更、フォルダー作成は行わない。
6. 保存された**正確なファイルID**を選び、ブラウザーで新しいprivate readbackディレクトリへダウンロードする。プレビュー、Google Sheets変換、名前が似た別ファイルは不可。ダウンロード完了後に0600へ変更して比較する。browser transportのreadbackはブラウザーで行い、rcloneを必須にしない。元ファイルをreadbackとして再使用しない。
7. byte数とSHA256が一致した場合だけ verified を記録する。アップロード済みでも確認不足・タイムアウト・不一致なら uploaded_unverified とし、原本を残して停止する。保存/確認結果の記録はcontroller/local-workflow手順に従う。

汎用ローカルコマンド（実際のパスは個人設定で置換する。macOSの `/tmp` などsymlink経由を避け、解決済み実パスを使う）：

```sh
chmod 700 "$PRIVATE_DIR" "$READBACK_DIR"
chmod 600 "$ORIGINAL_CSV" "$READBACK_CSV"
python scripts/report_artifact.py "$ORIGINAL_CSV" --kind summarized \
  --start-date 2026-01-01 --end-date 2026-01-31
```

現在のCLIにcompareサブコマンドはない。存在しないCLIを捏造せず、実在するローカルAPIを使う（skillディレクトリから実行）：

```sh
python -c 'import sys; sys.path.insert(0, "scripts"); from report_artifact import compare_files; print(compare_files(sys.argv[1], sys.argv[2]))' \
  "$ORIGINAL_CSV" "$READBACK_CSV"
```

## rclone: オプションの安全なアダプター

事前に利用者自身がrcloneと対象remoteを構成済みであることが必要。このskillはインストール、OAuth、認証ファイル参照、`rclone config show/dump` を行わない。rclone本体は既存認証を使う。利用者は対象アカウント・サイト/共有ドライブ/バケット・権限、同時書き込みがないことを確認する。backend一致はアカウント一致の証明ではない。

個人YAMLに `destination.transport: rclone` を明示し、上表の対象だけを指定する。未知キー、ルート、URIをremote名に埋め込む指定、トークン、任意flags/env overridesは拒否。`--config` は**skillの個人YAML**であり、rclone認証ファイルを渡すオプションではない。PyYAMLが実行環境に必要。依存不足でも自動インストールしない。

事前検証は `rclone listremotes --long` の名前/backend型の完全一致、`lsjson --stat` のディレクトリ判定、独立した `lsjson` 列挙。パス指定では親列挙に正確な既存ディレクトリが1件存在することが必須。S3/GCSの仮想prefixはstatだけでは存在証明にならず、親に列挙されない空prefixを拒否する。Drive/Boxのroot statも合成され得るため、それ単独で成功扱いにせず、設定したIDの利用者確認と独立した実際の列挙を要求する。statにIDがあれば設定と一致が必要。ID/root列挙が失敗したら停止する。フォルダーを自動作成しない。

保存先確認値は `upload_report.destination_identity(normalized_destination)` のSHA256。利用者が個人設定を確認してから生成する。値が一致するだけでアカウント確認済みとは主張しない。

```sh
python -c 'import sys; sys.path.insert(0, "scripts"); from validate_config import load_config; from upload_report import destination_identity; print(destination_identity(load_config(sys.argv[1])["destination"]))' "$PERSONAL_CONFIG"
python scripts/upload_report.py --config "$PERSONAL_CONFIG" --state-dir "$STATE" \
  --file "$ORIGINAL_CSV" --filename "$REGISTERED_FILENAME" --kind summarized \
  --start-date 2026-01-01 --end-date 2026-01-31 \
  --confirm-destination "$CONFIRMED_IDENTITY" --readback-dir "$READBACK_DIR"
```

台帳のinit時に `destination_id` を上記の正規化済みidentity、`upload_mode` を設定と同じ値で凍結する（CLI `--upload-mode archive|replace`、既定archive）。転送には validated/uploaded/uploaded_unverified の台帳と、登録済みの正確な原本パス・固定名・種別・期間が必要。Python APIは `transfer(config, file, filename, kind, start_date, end_date, confirm_destination, readback_dir, state_dir, replace_target=None)`。設定だけのarchive→replace変更はリモート呼出前に拒否される。本アダプターは台帳を読むが更新しない。

replaceの場合は台帳の `upload_mode: replace`、設定 `upload.mode: replace` と、対象そのものの `--replace-target "$EXACT_REMOTE_KEY"` が必要。通常はarchiveを使う。新規archiveは `copyto --immutable --ignore-times` で競合時の上書きを防ぐ。upload直前と直後にも列挙して、重複/別ID/競合を拒否する。`sync`、delete、mkdir、共有変更は使用しない。rcloneは原子的なフォルダー照合+保存を提供しないため、同時書き込み禁止が前提。Driveの重複生成競合などは検証失敗として扱う。

全subprocessはargv・shell=False、120秒上限、rcloneのretry/low-level-retry各1回。stderr・raw URL・対象名は出力しない。リモート操作エラーの後にwriteを再試行せず、可能なら1回再列挙し、結果を未検証として停止する。成功後も同じtransportで新しい0700/0600 private tempfileへ正確なオブジェクトをreadbackし、byte数+SHA256を比較する。readbackは `READBACK_DIR/readback-*/report.csv` に残り、controller統合前は台帳への自動登録はしない。原本を削除しない。

終了0と `verified:true` は実際のreadback一致を示す（テストではmock契約のみ）。終了2と `verified:false` は未完了/未検証であり、「転送されなかった」という保証ではない。rclone不在はruntime blocker。CLI出力は安全なprovider/action/bytes/sha256/verifiedまたは固定エラーだけで、実クラウド未検証を成功と偽らない。

参考（CLI仕様を確認、クラウド接続は未実行）：[listremotes](https://rclone.org/commands/rclone_listremotes/)、[lsjson](https://rclone.org/commands/rclone_lsjson/)、[copyto](https://rclone.org/commands/rclone_copyto/)、[Drive root-folder-id / team-drive](https://rclone.org/drive/)、[Box root-folder-id](https://rclone.org/box/)。
