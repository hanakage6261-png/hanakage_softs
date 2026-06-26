# 03_momonGA_metadata_searching フォルダについて

このフォルダは、サイト上のメタデータ取得と、ローカル保存ファイルの状態確認を担当するフォルダです。

## 収納内容

### file_status_checker


- [momonGA_file_status_checker.py](./file_status_checker/momonGA_file_status_checker.py)

  指定された保存先を走査して、作品のCBZファイルの存在を確認し、現在のファイル名、重複数を `work_state` に反映する確認プログラムです。
  作品ファイルであることはダウンロードしたファイルの末尾にIDが付与されているのでそこで確認できます。
---

- [momonGA_file_status_checker_paths.json](./file_status_checker/momonGA_file_status_checker_paths.json)

  `momonGA_file_status_checker.py` 専用の設定ファイルです。走査対象の絶対パスと、未接続パスをエラー扱いにするかどうかを持ちます。
---


### site_metadata_searcher

- [momonGA_metadata_auto_searching.py](./site_metadata_searcher/momonGA_metadata_auto_searching.py)

  `mo0` から順に、整数値を1個づつ増やして、mo(整数値)で構成されるIDを作成し、そのIDのURLにアクセスして、作品ページを調査し、`works` と `work_state` のメタデータ記録を更新する自動探索プログラムです。
  作品が存在していなければこのページは存在しません。　と表示されるか、入力したURLとは別のIDを持つ作品ページへリダイレクトされます。
  リダイレクトされた場合は作品が存在しないIDとします。

  #### 補足（URLとIDについて）
  これは00_momonGA_masterにあるMDファイルでも説明があると思いますが、簡単のためにここでもう一度説明します。
  新しいことは説明していないのでこのサイトの基本的な構成を理解していれば読む必要はありません。

  https://momon-ga.com/
  このサイトでは作品が存在しますが、各作品ページごとに固有のIDが割り振られています。
  （具体例）
  -https://momon-ga.com/fanzine/mo3998769/
  -https://momon-ga.com/magazine/mo4010030/

  このような作品URLが存在しています。
  URLの構成は、
  ①https://momon-ga.com/  
  ②fanzineまたはmagazine
  ③mo(自然数値)
  となっています。
  ③は作品のIDであり、作品ごとに固有の自然数が割り振られています。
  momonGA_systems群ではこのIDを利用して作品の管理やメタデータの収集を行っています。

  また、②の　magazine fanzineについてですが、これは各作品が商業誌または同人誌のどちらかにカテゴライズされており、それを示しているものです。
  
  ただし、ここで注意すべきはこの二つによって別々のID空間が設けられているというわけではないということです。
  具体的に説明しますと、例えば、
  https://momon-ga.com/magazine/mo4010030/
  というURLが存在していますが、
  https://momon-ga.com/fanzine/mo4010030/
  とアドレスバーに入力しても 
  https://momon-ga.com/magazine/mo4010030/
  へとリダイレクトされます。

  このことから、fanzine magazineはID空間を分けるものではなく、単なるラベリングであり、このサイトにおける作品ページはIDによってのみ一意に定まると分かります。
  以上がこのサイトの作品のURLとIDについての説明です。


---

- [momonGA_searching_state.json](./site_metadata_searcher/momonGA_searching_state.json)

  momonGA_metadata_auto_searching.pyのメタデータの自動探索の再開位置を記録する `next_id` を保存する状態ファイルです。
