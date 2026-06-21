# PROJECT_CONTEXT

## この文書の役割

このファイルは `momonGA_systems` 全体の仕様書です。  
`README.md` が運用入口、`PROJECT_CONTEXT.md` が全体仕様と責務整理、という役割です。

各番号付きフォルダの直下には、`01_momonGA_downloader_README.md` のような  
`_README.md` を置き、そのフォルダの役割と収納物を説明する方針です。  
書式見本は `README_style_model.md` で管理します。

## システム全体

`momonGA_systems` は、作品URLの取得、メタデータ収集、CBZダウンロード、補修、分析までを分担したプログラム群です。  
フォルダ順は重要度と使用頻度に基づき固定しています。

1. `00_momonGA_master`
2. `01_momonGA_downloader`
3. `02_momonGA_database`
4. `03_momonGA_metadata_searching`
5. `04_momonGA_patch`
6. `05_momonGA_utilize`
7. `06_momonGA_legacies`
8. `07_momonGA_systems_projects`

## 依存の基準点

全スクリプトの共通参照起点は `00_momonGA_master/momonGA_registry.py` です。  
ルートの `momonGA_registry.py` は互換用の入口で、実体は `00_momonGA_master` にあります。

## フォルダ責務

### `00_momonGA_master`

- レジストリ
- 全体説明文書
- 共通設定

### `01_momonGA_downloader`

- URLから作品を取得する
- ダウンロード成功時に `work_state.downloaded` と `work_state.download_count` を更新する
- 保存ファイル名は `[作者名] タイトル ID.cbz`

### `02_momonGA_database`

- `momonGA_metadata.db`
- `momonGA_metadata_store.py`
- DBスキーマ移行と共通DB API

### `03_momonGA_metadata_searching`

- `momonGA_metadata_auto_searching.py`
  - サイトのID順メタデータ収集
  - 成功時に `work_state.metadata_check_count` と `work_state.last_metadata_checked_at` を更新
- `momonGA_file_status_checker.py`
  - 設定された絶対パス群を走査し、`work_state.file_present` などを更新
- `momonGA_searching_state.json`
  - 自動探索の再開位置

### `04_momonGA_patch`

- `momonGA_metadata_manual_searching.py`
  - URL指定でメタデータ登録
  - 成功時に `metadata_check_count` / `last_metadata_checked_at` を更新
- `momonGA_authordata_eliminater.py`
  - 例外的なファイル名修正
- `momonGA_pdf_to_cbz_redownload_helper.py`
  - 旧PDF名からサイト検索し、候補URL群をJSONへ保存
  - DBにもダウンローダー再開JSONにも書かない

### `05_momonGA_utilize`

- DB検索、集計、分析
- `works_with_state` ビュー経由で両表をまとめて参照する

### `06_momonGA_legacies`

- 旧スクリプトの保管
- `momonGA_basis` はアーカイブ扱い

### `07_momonGA_systems_projects`

- 将来案
- todo
- bugs

## DB設計

DBファイル: `02_momonGA_database/momonGA_metadata.db`

### `works`

サイト上のメタデータと存在状態を持つ表です。

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

ローカル運用状態を持つ表です。主キーは `id` です。

- `downloaded`
- `download_count`
- `file_present`
- `current_file_name`
- `file_count`
- `metadata_check_count`
- `last_metadata_checked_at`
