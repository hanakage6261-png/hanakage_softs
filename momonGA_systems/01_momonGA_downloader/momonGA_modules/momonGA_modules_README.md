# momonGA_modules について

このフォルダは `momonGA_downloader.py` が利用する補助モジュール群を置く場所です。
`momonGA_downloader.py` 本体は全体制御の入口として残し、実際の処理はこの下の各モジュールへ分けています。

## サブフォルダ

- `momonGA_downloader_modules_shared`

  共通定数、共通データ型、保存先パス、URL関連の共通補助を扱います。

- `momonGA_downloader_modules_network`

  セッション作成、HTTP取得、再試行、HTMLデコードなど通信処理を扱います。

- `momonGA_downloader_modules_targets`

  作品ページの解析、作者/サークルURLの巡回、作品URL展開、メタデータ抽出を扱います。

- `momonGA_downloader_modules_queue`

  URL入力、再開キュー、除外選択、`momonGA_downloader_resume.json` を扱います。

- `momonGA_downloader_modules_archive`

  画像取得、CBZ作成、保存処理を扱います。

## 再開キューについて

現在の正本の再開キューファイルは次です。

- `01_momonGA_downloader/momonGA_modules/momonGA_downloader_modules_queue/momonGA_downloader_resume.json`

旧来の root 直下の `momonGA_downloader_resume.json` は今後の正本ではありません。
古い配置に再開キューが残っている場合だけ、初回読込時に新しい場所へ移行するための読み込み元として扱います。
つまり、常用する再開キューは 1 つだけです。
