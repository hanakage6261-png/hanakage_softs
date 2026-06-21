# 01_momonGA_downloader フォルダについて

このフォルダは、作品URLや作者URLなどを入力して作品をダウンロードし、CBZとして保存するためのプログラムを置くフォルダです。

## 収納物

- [momonGA_downloader.py](./momonGA_downloader.py)

  ダウンロード本体です。作品メタデータの記録と `work_state` の更新もここで行います。

---

- [momonGA_downloader.spec](./momonGA_downloader.spec)

  `momonGA_downloader.py` を実行ファイル化するときの PyInstaller 設定ファイルです。

---

- [momonGA_downloader_resume.json](./momonGA_downloader_resume.json)

  ダウンロード中断時に、再開対象のURLキューを保存しておくファイルです。
