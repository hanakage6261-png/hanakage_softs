# momonGA Systems

`momonGA_systems` 全体の運用入口です。  
ここは「何をどこで管理するか」を把握するための概要書です。  
詳細仕様は `PROJECT_CONTEXT.md` を参照してください。

番号付きフォルダの直下には、各フォルダ専用の `_README.md` を置きます。  
それぞれの `_README.md` は、そのフォルダの役割と収納物を説明するための説明書です。  
書式見本は [../README_style_model.md](../README_style_model.md) を参照します。

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
  - 旧スクリプトと原型アーカイブ
- `07_momonGA_systems_projects`
  - 将来案、todo、bugs の保管

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
