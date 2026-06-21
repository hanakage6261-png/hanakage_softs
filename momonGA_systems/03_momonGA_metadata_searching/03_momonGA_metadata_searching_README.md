# 03_momonGA_metadata_searching フォルダについて

このフォルダは、サイト上の作品メタデータを収集する処理と、ローカル保存済みファイルの状態を確認する処理を置くフォルダです。

## 収納物

- [momonGA_metadata_auto_searching.py](./momonGA_metadata_auto_searching.py)

  `mo0` から順に作品ページを確認し、`works` と `work_state` のメタデータ確認情報を更新する自動探索プログラムです。

---

- [momonGA_file_status_checker.py](./momonGA_file_status_checker.py)

  設定された絶対パスを走査し、CBZの有無、現在のファイル名、重複数を `work_state` に反映するプログラムです。

---

- [momonGA_searching_state.json](./momonGA_searching_state.json)

  自動探索の再開位置である `next_id` を保存するファイルです。
