# momonGA Systems

`momonGA_systems` 全体の運用入口です。  
ここは「何をどこで管理するか」を把握するための概要書です。  
詳細仕様は `PROJECT_CONTEXT.md` を参照してください。

## フォルダの役割

- `00_momonGA_master`
  - 全体運用の基準点
  - `momonGA_registry.py` と共通設定を置く
- `01_momonGA_downloader`
  - URLから作品をCBZで取得する
- `02_momonGA_database`
  - SQLite DB と DBアクセス層
- `03_momonGA_metadata_searching`
  - メタデータ自動収集
  - ファイル状態確認
- `04_momonGA_patch`
  - 手動補修、例外処理、再取得補助
- `05_momonGA_utilize`
  - DBを使った分析・検索
- `06_momonGA_legacies`
  - 旧式スクリプトと原型アーカイブ

## 主要スクリプト

- `01_momonGA_downloader/momonGA_downloader.py`
  - ダウンロード本体
  - 保存名は `[作者名] タイトル ID.cbz`
- `03_momonGA_metadata_searching/momonGA_metadata_auto_searching.py`
  - `mo0` から順にメタデータ取得
- `03_momonGA_metadata_searching/momonGA_file_status_checker.py`
  - 保存済みCBZを走査して `work_state` を更新
  - 設定ファイルは `00_momonGA_master/momonGA_file_status_checker_paths.json`
- `04_momonGA_patch/momonGA_metadata_manual_searching.py`
  - URL指定でメタデータ登録
- `04_momonGA_patch/momonGA_pdf_to_cbz_redownload_helper.py`
  - 旧PDF名から候補URLを再取得してJSONへ保存
- `04_momonGA_patch/momonGA_authordata_eliminater.py`
  - 作者名除去の例外処理

## 実行例

```powershell
python .\01_momonGA_downloader\momonGA_downloader.py
python .\03_momonGA_metadata_searching\momonGA_metadata_auto_searching.py
python .\03_momonGA_metadata_searching\momonGA_file_status_checker.py
python .\04_momonGA_patch\momonGA_metadata_manual_searching.py
python .\04_momonGA_patch\momonGA_pdf_to_cbz_redownload_helper.py
```

## DBの考え方

`02_momonGA_database/momonGA_metadata.db` には2つの役割を分けて保存します。

- `works`
  - サイト上のメタデータと存在状態
- `work_state`
  - ダウンロード履歴と現在ファイル状態

## 動かしてはいけないもの

次は場所を変えると影響が大きいです。

- `00_momonGA_master/momonGA_registry.py`
  - 全体の参照起点
- `02_momonGA_database/momonGA_metadata.db`
  - 運用DB本体
- `01_momonGA_downloader/momonGA_downloader_resume.json`
  - ダウンロード再開状態
- `03_momonGA_metadata_searching/momonGA_searching_state.json`
  - 自動探索の再開ID
- `00_momonGA_master/momonGA_file_status_checker_paths.json`
  - ファイル状態確認の絶対パス設定

フォルダ名を変える場合は、まず `00_momonGA_master/momonGA_registry.py` を更新してください。
