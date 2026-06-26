# 05_momonGA_utilize フォルダについて

このフォルダは、`02_momonGA_database/momonGA_metadata.db` の内容を利用して検索、分析、集計を行うプログラム群を置くフォルダです。

## 収納物

- [momonGA_database_elements_counter.py](./momonGA_database_elements_counter.py)

  各列の非空件数や重複数などを数えて、DBの埋まり具合を確認するプログラムです。

---

- [momonGA_database_mode_searching.py](./momonGA_database_mode_searching.py)

  author や circle などの項目ごとの頻出値またはワードをカウントして表示するプログラムです。

---

- [momonGA_database_search.py](./momonGA_database_search.py)

  ユーザーが入力したキーワードをDBで検索し、`works_with_state` の内容を一覧表示するプログラムです。

---

- [momonGA_ID_analyzing.py](./momonGA_ID_analyzing.py)

  ID帯ごとの件数、found件数、downloaded件数を集計するプログラムです。
  どのID帯にどのくらい作品が存在しているのかを調べます。

---

- [momonGA_timeline_analyzing.py](./momonGA_timeline_analyzing.py)

  作品の日付情報を月単位で集計し、作品の時系列分布を見るためのプログラムです。

---

- [random_select.py](./random_select.py)

  DBからランダムに1件選び、作品情報を簡易的に抽出するためのプログラムです。
  適当に作品をおすすめするためのプログラムです。
