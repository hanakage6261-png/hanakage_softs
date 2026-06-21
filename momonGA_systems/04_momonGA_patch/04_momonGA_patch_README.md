# 04_momonGA_patch フォルダについて

このフォルダは、通常運用から外れる補修処理や、例外的な再取得支援のためのプログラムを置くフォルダです。

## 収納物

- [momonGA_metadata_manual_searching.py](./momonGA_metadata_manual_searching.py)

  URLを手入力して作品メタデータを登録・補修するためのプログラムです。

---

- [momonGA_authordata_eliminater.py](./momonGA_authordata_eliminater.py)

  作者名をファイル名から取り除きたい場合に使う、例外的な名前補修用プログラムです。

---

- [momonGA_pdf_to_cbz_redownload_helper.py](./momonGA_pdf_to_cbz_redownload_helper.py)

  旧PDFのファイル名を手掛かりにサイト検索を行い、再ダウンロード候補URLをJSONへ保存する補助プログラムです。
