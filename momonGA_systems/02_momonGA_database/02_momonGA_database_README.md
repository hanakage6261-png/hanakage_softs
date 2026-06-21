# 02_momonGA_database フォルダについて

このフォルダは、作品メタデータとローカルファイル状態を記録するデータベース、およびそのアクセス処理を置くフォルダです。

## 収納物

- [momonGA_metadata.db](./momonGA_metadata.db)

  `works` と `work_state` を保存する SQLite データベース本体です。

---

- [momonGA_metadata_store.py](./momonGA_metadata_store.py)

  DB接続、スキーマ初期化、メタデータ更新、ダウンロード状態更新などをまとめた共通DBアクセス層です。

---

- [__init__.py](./__init__.py)

  `02_momonGA_database` を Python パッケージとして扱うためのファイルです。

---

- [データベースファイルの見方について.md](./データベースファイルの見方について.md)

  データベースファイルを手作業で確認するときの見方を説明する補助文書です。
