# 03_momonGA_metadata_searching フォルダについて

このフォルダは、サイト上のメタデータ取得と、ローカル保存ファイルの状態確認を担当するフォルダです。

## 収納内容

- [momonGA_metadata_auto_searching.py](./momonGA_metadata_auto_searching.py)

  `mo0` から順に作品ページを調査し、`works` と `work_state` のメタデータ記録を更新する自動探索プログラムです。
---

- [momonGA_file_status_checker.py](./momonGA_file_status_checker.py)

  指定された保存先を走査し、CBZ の存在、現在のファイル名、重複数を `work_state` に反映する確認プログラムです。
---

- [momonGA_file_status_checker_paths.json](./momonGA_file_status_checker_paths.json)

  `momonGA_file_status_checker.py` 専用の設定ファイルです。走査対象の絶対パスと、未接続パスをエラー扱いにするかどうかを持ちます。
---

- [momonGA_searching_state.json](./momonGA_searching_state.json)

  自動探索の再開位置として使う `next_id` を保存する状態ファイルです。
