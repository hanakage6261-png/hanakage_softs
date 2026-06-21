# momonGA Systems

このフォルダは `momon-ga.com` 向けのダウンローダー群とメタデータ収集プログラムをまとめた作業用ルートです。

今後フォルダ名を `momonGA_systems` に変更しても、**最上位フォルダ名だけの変更であれば相対パス前提のためそのまま動作します。**

## 構成

- `momonGA_downloader/`
  - `momonGA_downloader.py`
  - 作品URL / 作者URL / サークルURLから作品を取得して `CBZ` を作る
- `momonGA_searching/`
  - `momonGA_searching.py`
  - `mo0`, `mo1`, `mo2`... とIDを順に見てメタデータを収集する
  - `momonGA_searching_state.json`
  - メタデータ巡回の再開位置
- `momonGA_utilize/`
  - `random_select.py`
  - DBから作品をランダムに表示する補助スクリプト
- `momonGA_metadata_store.py`
  - 共有DBアクセス層
- `momonGA_metadata.db`
  - 共有メタデータDB本体
- `momon.db`
  - 旧DBバックアップ。通常運用では使わない

## 役割

### 1. ダウンローダー

ファイル: `momonGA_downloader/momonGA_downloader.py`

- 作品URLを直接入力すると、その作品をダウンロード
- 作者URL / サークルURL / 検索結果URLを入力すると、掲載作品を一覧展開してダウンロード候補化
- 同タイトル候補は「1枚目画像ハッシュ + ページ数」で簡易重複整理
- `downloaded = 1` の作品が候補にあれば、まとめて除外するか確認
- 一覧展開後に不要作品の番号除外が可能
- ダウンロード成功時に `works.downloaded = 1`
- 出力形式は **CBZのみ**
- 元の `webp` をそのままZIPへ入れるため、旧PDF方式の再圧縮劣化はない
- 作者情報がない場合のファイル名は `[] タイトル.cbz`

### 2. メタデータ巡回

ファイル: `momonGA_searching/momonGA_searching.py`

- `mo<ID>` を順番に取得してメタデータをDBへ入れる
- `fanzine` で叩いても `magazine` へリダイレクトされたら同一ID作品として扱う
- DBに正常データが既にあるIDはまとめてスキップ
- 文字化けや不完全データらしき既存レコードは再取得対象に戻す
- 再開位置は `momonGA_searching_state.json` で管理
- DBの最大IDには依存しない

### 3. 共有DB

ファイル: `momonGA_metadata.db`

テーブル: `works`

主な列:

- `id`
- `title`
- `date`
- `type`
- `pages`
- `parody`
- `circle`
- `author`
- `characters`
- `content`
- `url`
- `final_url`
- `status`
- `downloaded`

設計方針:

- 作品IDが主キー
- ダウンローダーとメタデータ巡回の両方が同じ `id` に対して `UPSERT`
- 目的は「作品ID単位で状態を共有すること」であり、詳細ダウンロード履歴DBではない
- `downloaded` は最低限のダウンロード済みフラグ

## 再開仕様

### ダウンローダー

- 再開ファイル: `momonGA_downloader/momonGA_downloader_resume.json`
- 再開単位は作品URLキュー
- 作者URL / サークルURLは一度作品URL群へ展開してからキュー化
- 途中中断時は未完了作品URLから再開
- 進捗ファイル保存で一時ロックが起きても数回リトライする

### メタデータ巡回

- 再開ファイル: `momonGA_searching/momonGA_searching_state.json`
- `next_id` を保持
- `KeyboardInterrupt` や進行中例外でも次回位置を残す
- 進捗ファイル保存で一時ロックが起きても数回リトライする

## リトライ方針

両プログラムとも次の方針で通信する。

- `HTTP 403 / 408 / 429 / 500 / 502 / 503 / 504` は指数バックオフで再試行
- `HTTPSConnectionPool` 系や `ConnectionError` 系などの `requests.RequestException` も終了せず、通るまで指数バックオフで再試行
- `404` は通常どおり not found 扱い
- 一時拒否や回線瞬断で勝手に終了しない

## 速度方針

### ダウンローダー

- 画像取得は逐次処理
- 作品保存はCBZのみ

### メタデータ巡回

- `requests.Session` を再利用
- 各IDの通常間隔は `0.12` 秒
- 拒否や接続不良時のみバックオフ
- DBに既に正常データが連続している区間はまとめてスキップ

## 文字化け対策

- HTMLは `response.text` 任せにせず、`response.content` を候補エンコーディングで順に復号する
- `utf-8` を優先し、必要に応じて `cp932 / shift_jis / euc_jp` も試す
- 巡回側は既存レコードに文字化けらしき値があれば再取得対象に戻す

## DB競合対策

- `momonGA_metadata_store.py` 側で `PRAGMA journal_mode = WAL`
- `busy_timeout` を設定
- `database is locked` は短時間待機して複数回リトライ

## 起動方法

### ダウンローダー

```powershell
python .\momonGA_downloader\momonGA_downloader.py
```

### メタデータ巡回

```powershell
python .\momonGA_searching\momonGA_searching.py
```

### URL指定のメタデータ登録

```powershell
python .\momonGA_searching\momonGA_metadataonly_searching.py
```

作品URL、作者URL、サークルURL、検索結果URLに対応します。画像やCBZは取得しません。

### ランダム表示

```powershell
python .\momonGA_utilize\random_select.py
```

### CBZファイル名から作者名を除去

```powershell
python .\momonGA_authordata_eliminater.py
```

`Downloads\momonGA_rename` 内の `[作者] タイトル.cbz` を `[] タイトル.cbz` に変更します。

### 文字化けメタデータの手動補修

```powershell
python .\momonGA_legacies\momonGA_searching_legacies\momonGA_researching_for_mistakes.py
```

### 旧PDFからCBZ再ダウンロード用URLを復旧

```powershell
python .\momonGA_legacies\momonGA_pdf_to_cbz_redownload_helper.py --enqueue-only
```

```powershell
python .\momonGA_legacies\momonGA_pdf_to_cbz_redownload_helper.py
```

## 運用メモ

- `momonGA_downloader` と `momonGA_systems` のような複製フォルダを並行運用すると正本が曖昧になりやすい
- 正本は1つに決めること
- 最上位フォルダ名だけ変えるのは問題ない
- 旧 `momon.db` はバックアップ扱いで、実運用は `momonGA_metadata.db`

## 未対応 / 今後の候補

- Google Keep等からのURL取り込み
- 重複判定精度の改善
- 既存CBZの再構築支援
- DBを利用した高度な検索系スクリプト追加
- DBファイルの保存先を設定ファイルで変更する機能
- お気に入りフラグ
- CBZの実在状態をDBへ同期する `file_present` 管理
- CBZファイル名へ作品IDを付ける新命名規則

## 注意点

- サイトのHTML構造が変わると抽出ロジックは壊れうる
- 同タイトル重複判定は簡易版であり、完全一致保証ではない
- 既存の不良レコードは巡回が再訪した時点で順次上書き修復される
