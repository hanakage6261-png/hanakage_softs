# PROJECT_CONTEXT

## この文書の役割

このファイルは `momonGA_systems` 全体の仕様書です。  
`README.md` が運用入口、`PROJECT_CONTEXT.md` が全体仕様と責務整理、という役割です。

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

## 依存の基準点

全スクリプトの共通参照起点は `00_momonGA_master/momonGA_registry.py` です。  
ルートの `momonGA_registry.py` は互換用の入口で、実体は `00_momonGA_master` にあります。

このため、次を変えるときは必ず `momonGA_registry.py` 側も合わせます。

- トップレベルの番号付きフォルダ名
- 主要スクリプトのファイル名
- `00_momonGA_master` 配下の共通設定ファイル位置

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

## DB設計

DBファイル: `02_momonGA_database/momonGA_metadata.db`

### 1. `works`

サイト上の作品状態とメタデータを持つ表です。

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

`status` はサイト上の存在確認です。  
`downloaded` はこの表には置きません。

### 2. `work_state`

ローカル運用状態を持つ表です。主キーは `id` です。

- `downloaded`
  - 過去に一度でもダウンロードしたら `1`
- `download_count`
  - 総ダウンロード回数
- `file_present`
  - 現在の走査対象ルート内にファイルがあれば `1`
- `current_file_name`
  - 現在採用中のファイル名
- `file_count`
  - 同じIDで見つかったファイル数
- `metadata_check_count`
  - 自動探索と手動探索で確認した回数
- `last_metadata_checked_at`
  - 最後にメタデータ確認した日時

### 3. `works_with_state`

`works` と `work_state` を結合した参照用ビューです。  
利用系スクリプトは基本的にこのビューを読む想定です。

## 各更新責務

### ダウンローダー

`01_momonGA_downloader/momonGA_downloader.py`

- `works` へ作品メタデータをUPSERT
- `work_state.downloaded = 1`
- `work_state.download_count += 1`

### メタデータ自動探索

`03_momonGA_metadata_searching/momonGA_metadata_auto_searching.py`

- `works` の追加・更新
- `work_state.metadata_check_count += 1`
- `work_state.last_metadata_checked_at = 実行日時`

### メタデータ手動探索

`04_momonGA_patch/momonGA_metadata_manual_searching.py`

- `works` の追加・更新
- `work_state.metadata_check_count += 1`
- `work_state.last_metadata_checked_at = 実行日時`

### ファイル状態確認

`03_momonGA_metadata_searching/momonGA_file_status_checker.py`

- `work_state.file_present`
- `work_state.current_file_name`
- `work_state.file_count`

## ファイル状態確認の前提

ファイル保存先は今の段階では固定できないため、  
`00_momonGA_master/momonGA_file_status_checker_paths.json` に絶対パスを書いて管理します。

```json
{
  "search_roots": [
    "C:\\Users\\owner\\Downloads\\momonGA_Download"
  ],
  "require_all_roots": true
}
```

注意:

- `search_roots` に書いた場所だけを真実として走査します
- 外付けHDDやNASも対象なら、実行前にその絶対パスを `search_roots` に入れてください
- `require_all_roots=true` のとき、書かれたパスが見つからなければ更新を中止します

## ファイル名規則

新しいCBZ保存名:

```text
[作者名] タイトル ID.cbz
```

ここでの `ID` は整数値のみです。`mo` は付けません。

`momonGA_authordata_eliminater.py` で作者名を消した場合も、  
末尾の `ID` は残す前提です。

## PDFからCBZへの再取得補助

`04_momonGA_patch/momonGA_pdf_to_cbz_redownload_helper.py` の責務:

- `Downloads/momonGA_PDFs` の PDF 名を読む
- `[作者名] タイトル.pdf` から候補検索する
- `Unknownauthor` は検索材料に使わない
- タイトル重複時は候補URLを全部残す
- `04_momonGA_patch/momonGA_pdf_to_cbz_redownload_candidates.json` に保存する
- この段階では DB 更新しない
- ダウンローダー再開キューにも書かない

## フォルダ移動の注意

### 基本的に動かさない方がよいもの

- `00_momonGA_master`
  - 基準点フォルダ
- `01_momonGA_downloader/momonGA_downloader_resume.json`
  - 再開情報
- `03_momonGA_metadata_searching/momonGA_searching_state.json`
  - 探索再開情報
- `00_momonGA_master/momonGA_file_status_checker_paths.json`
  - 絶対パス設定
- `02_momonGA_database/momonGA_metadata.db`
  - 本番DB

### 比較的動かしやすいもの

- `05_momonGA_utilize`
  - ただし `momonGA_registry.py` のパス更新は必要
- `06_momonGA_legacies`
  - 基本はアーカイブ

## 今回の判断

- `README.md`
  - 入口文書
- `PROJECT_CONTEXT.md`
  - `momonGA_systems` 全体の仕組みを説明する文書

したがって、正本を `00_momonGA_master` に置く構成は妥当です。
