# PROJECT_CONTEXT

## この文書の役割

このファイルは `momonGA_systems` 全体の構造と動作を説明する設計文書です。
短い入口はルートの `README.md`、運用方針と対象範囲は `SYSTEM_POLICY.md`、各フォルダ README の書式は `README_style_model.md` で管理します。

## システム全体

`momonGA_systems` は、作品 URL の収集、メタデータ記録、CBZ ダウンロード、ローカル保存状態の追跡、分析、例外処理、旧版保管を分担して運用する一式のプログラム群です。

フォルダ順は次の通りです。

1. `00_momonGA_master`
2. `01_momonGA_downloader`
3. `02_momonGA_database`
4. `03_momonGA_metadata_searching`
5. `04_momonGA_patch`
6. `05_momonGA_utilize`
7. `06_momonGA_legacies`
8. `07_momonGA_systems_projects`

## 共通参照

全スクリプトの共通パス参照は `00_momonGA_master/momonGA_registry.py` に集約します。
ファイル名やフォルダ構造が変わっても、各スクリプトはできるだけこのレジストリ経由で主要パスを参照します。

## 00 の扱い

`00_momonGA_master` は全体共通のものだけを置くフォルダです。

- `momonGA_registry.py`
  - 共通の場所参照を管理する
- `docs/`
  - 全体仕様、運用方針、README 書式見本を管理する

個別機能専用の設定ファイルは、その機能を担当するフォルダに置きます。
そのため `momonGA_file_status_checker_paths.json` は `03_momonGA_metadata_searching` に置きます。

## フォルダ役割

### `00_momonGA_master`

- 全体共通レジストリ
- 全体文書

### `01_momonGA_downloader`

- URL から作品をダウンロードする
- ダウンロード時に `work_state.downloaded` と `work_state.download_count` を更新する
- 出力ファイル名は `[作者名] タイトル ID.cbz`

### `02_momonGA_database`

- `momonGA_metadata.db`
- `momonGA_metadata_store.py`
- DB 操作と共通 API

### `03_momonGA_metadata_searching`

- `momonGA_metadata_auto_searching.py`
  - サイト上の ID を調べてメタデータを記録する
  - `work_state.metadata_check_count` と `work_state.last_metadata_checked_at` を更新する
- `momonGA_file_status_checker.py`
  - 保存先を走査して `work_state.file_present` などを更新する
- `momonGA_file_status_checker_paths.json`
  - file status checker 専用の走査先設定
- `momonGA_searching_state.json`
  - 自動探索の再開位置

### `04_momonGA_patch`

- 例外処理や補助的な再取得処理
- 手動メタデータ取得
- PDF から CBZ への再ダウンロード支援

### `05_momonGA_utilize`

- DB を使った分析や調査
- 基本的に `works_with_state` ビュー経由で扱う

### `06_momonGA_legacies`

- 旧スクリプトの保管
- `momonGA_basis` を含むアーカイブ置き場

### `07_momonGA_systems_projects`

- アイデアメモ
- todo
- bugs

## DB 設計

DB ファイルは `02_momonGA_database/momonGA_metadata.db` です。

### `works`

サイト上の状態とメタデータを記録します。

- `id`
- `title`
- `date`
- `type`
- `pages`
- `parody`
- `circle`
- `author`
- `characters`
- `content`
- `url`
- `final_url`
- `status`

### `work_state`

ローカル保存状態を記録します。主キーは `id` です。

- `downloaded`
- `download_count`
- `file_present`
- `current_file_name`
- `file_count`
- `metadata_check_count`
- `last_metadata_checked_at`
