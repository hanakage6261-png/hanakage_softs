# momonGA Systems 引き継ぎ資料

この文書は、新しいCodexチャットや別PCでプロジェクトを開いた際に、過去の会話で決めた要件と設計判断を復元するための資料です。

先頭の `01` から `06` の番号は、重要度と使用頻度の順を表します。

## 最初に読むもの

1. `PROJECT_CONTEXT.md`
2. `README.md`
3. `momonGA_registry.py`
4. `02_momonGA_database/momonGA_metadata_store.py`
5. 作業対象の各プログラム

新しいCodexには、最初に次のように指示することを推奨します。

> `PROJECT_CONTEXT.md` と `README.md` を読み、現在の仕様・未実装事項・運用ルールを理解してから作業してください。正本はこの `momonGA_systems` フォルダです。

## 正本とフォルダ移行

- 今後の正本は `momonGA_systems` とする。
- 旧 `momonGA_downloader` フォルダとの二重運用は終了する。
- 最上位フォルダ名はコードから直接参照していないため、`momonGA_systems` への変更自体は問題ない。
- 新しいCodexプロジェクトは `momonGA_systems` をワークスペースとして開く。
- チャット履歴そのものは別プロジェクトへ自動移行できない。この文書を引き継ぎ元とする。

## プロジェクトの目的

`momon-ga.com` の作品をCBZで保存し、同じ作品ID空間を使ってメタデータをSQLite DBへ蓄積する。

システムは大きく分けて次の機能を持つ。

- URL指定のCBZダウンロード
- 作者・サークル・検索結果からの一括ダウンロード
- IDの連続巡回によるメタデータ収集
- URL指定のメタデータのみ登録
- not found IDの再調査
- DBを利用する検索・分析ツール
- 旧PDFからCBZへ移行する補助ツール

## ディレクトリ構成

```text
momonGA_systems/
  README.md
  PROJECT_CONTEXT.md
  momonGA_registry.py
  01_momonGA_downloader/
    momonGA_downloader.py
    momonGA_downloader_resume.json
  02_momonGA_database/
    __init__.py
    momonGA_metadata_store.py
    momonGA_metadata.db
  03_momonGA_metadata_searching/
    momonGA_metadata_auto_searching.py
    momonGA_searching_state.json
  04_momonGA_patch/
    momonGA_metadata_manual_searching.py
    momonGA_authordata_eliminater.py
  05_momonGA_utilize/
    random_select.py
    momonGA_database_search.py
    momonGA_database_mode_searching.py
    momonGA_database_elements_counter.py
    momonGA_ID_analyzing.py
    momonGA_timeline_analyzing.py
  06_momonGA_legacies/
    momonGA_metadata_researching_for_null_IDs.py
    momonGA_basis/
      README.md
      momonGA_pdf_to_cbz_redownload_helper.py
      recovered_pdf_work_urls.txt
      momonGA_searching_legacies/
        momonGA_researching_for_mistakes.py
        CLI_style.txt
        試験的一つだけDownloader.py
```

## URLと作品ID

- 作品URL:
  - `https://momon-ga.com/magazine/mo3945623/`
  - `https://momon-ga.com/fanzine/mo<ID>/`
- 作者URL:
  - `https://momon-ga.com/cartoonist/inuineko/`
- サークルURL:
  - `https://momon-ga.com/group/<name>/`
- 検索結果URL:
  - `https://momon-ga.com/?s=pegging`

`fanzine` と `magazine` は別ID空間ではない。同じ数値IDに対して、どちらか一方の分類が決まる。

## 共有DB

DB本体は `02_momonGA_database/momonGA_metadata.db`。

テーブル `works` の現在の列:

- `id INTEGER PRIMARY KEY`
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
- `downloaded INTEGER`

`parody`, `circle`, `author`, `characters`, `content` はJSON配列文字列。

DBの目的は詳細なダウンロード履歴ではなく、作品ID単位のメタデータと最低限の状態共有。

### UPSERTルール

- `upsert_work()` は通常の統合更新。
- `downloaded` は一度1になれば、通常のUPSERTでは0へ戻らない。
- `overwrite_work_metadata()` は文字化け等の訂正用で、メタデータを強制上書きする。
- `overwrite_work_metadata()` でも既存の `downloaded` は維持する。
- SQLiteはWALモード、`busy_timeout`、ロック時リトライを使用。

## ダウンローダー仕様

対象: `01_momonGA_downloader/momonGA_downloader.py`

- 作品URLは1作品を処理。
- 作者・サークル・検索結果URLは複数ページを巡回して作品URLへ展開。
- 展開後は作品URL単位の再開キューへ置き換える。
- 途中終了時、完了済み作品は再処理せず、処理中作品から再開。
- 作者・サークル等の候補で `downloaded = 1` があれば、まとめて除外するか確認。
- その後、ユーザーが番号指定で任意作品を除外できる。

### 重複判定

- 原則として全作品を候補にする。
- 同じタイトルが出た時だけ例外判定。
- 1枚目画像のピクセルハッシュが同じなら同一候補とみなす。
- 同一候補ではページ数が多い作品を優先。
- ページ数が同じなら更新日時を優先。
- さらに同じならIDが大きい方を優先。
- タイトルが同じでも1枚目画像が違えば両方残す。
- 1枚目画像が取得できない時は無理に同一扱いしない。
- 重複から外された作品も、取得済みメタデータはDBへ保存する。

### CBZ

- PDF出力は廃止済み。
- 元のWebPを再エンコードせず `ZIP_STORED` でCBZへ格納。
- 作者あり: `[作者] タイトル.cbz`
- 作者なし: `[] タイトル.cbz`
- 同名ファイルがある場合は現在 `(1)` 等を付けて別ファイルとして保存。
- ダウンロード成功後に `downloaded = 1`。

## メタデータ巡回

対象: `03_momonGA_metadata_searching/momonGA_metadata_auto_searching.py`

- `mo0` からIDを順に確認。
- 再開位置は `03_momonGA_metadata_searching/momonGA_searching_state.json` の `next_id`。
- DBの最大IDは再開位置に使用しない。
- ダウンローダーが高いIDを先に登録しても、巡回位置は飛ばない。
- DBに正常データが連続する部分はまとめてスキップ。
- 文字化け・不完全データは再取得対象。
- 文字化け行の補修時は強制上書きし、`downloaded` は保持。
- 通常ID間隔は0.12秒。
- 未発見IDが別IDへリダイレクトされる場合、リダイレクト先を取得せずnot found扱いにしている。

### 通信再試行

- `403`, `408`, `429`, `500`, `502`, `503`, `504` は指数バックオフ。
- `ConnectionError`, `HTTPSConnectionPool` 等も指数バックオフで無期限再試行。
- 最大待機時間は180秒。
- `404` はnot found。

## 補助プログラム

### `04_momonGA_patch/momonGA_metadata_manual_searching.py`

- URL入力からメタデータだけを登録。
- 作品、作者、サークル、検索結果URLに対応。
- 画像・CBZは取得しない。
- 現在はお気に入り機能なし。

### `06_momonGA_legacies/momonGA_metadata_researching_for_null_IDs.py`

- 通常巡回済み範囲内のnot foundだけ再調査。
- `03_momonGA_metadata_searching/momonGA_searching_state.json` の `next_id` を追い越さない。

### `06_momonGA_legacies/momonGA_basis/momonGA_searching_legacies/momonGA_researching_for_mistakes.py`

- IDを手入力してメタデータを強制再取得。
- 文字化け訂正用。
- `downloaded` は保持。

### `06_momonGA_legacies/momonGA_basis/momonGA_pdf_to_cbz_redownload_helper.py`

- `Downloads/momonGA_PDFs` の `[作者] タイトル.pdf` を処理。
- DBまたはサイト検索から作品URLを集める。
- URLをダウンローダーの再開キューへ登録。
- 作者検索で取得できなければタイトル検索へフォールバック。
- URLを取得できないPDFだけ残し、処理全体は継続。
- 既定ではPDFを `processed` フォルダへ移動。
- `--delete-pdfs` 指定時のみ削除。

### `04_momonGA_patch/momonGA_authordata_eliminater.py`

- `Downloads/momonGA_rename` を作成。
- そこへ入れた `[作者] タイトル.cbz` を `[] タイトル.cbz` に変更。

## 通信文字化け対策

- `response.text` と `apparent_encoding` 任せにしない。
- `response.content` をUTF-8優先で復号。
- 必要時にCP932、Shift_JIS、EUC-JPも試す。
- 以前、タイトルや日付がキリル文字風・拡張ラテン文字風に化けて登録されたため導入。

## 現在の既知の問題

- 一部のCLI表示文字列は過去の編集過程で文字化けしている。処理ロジックは構文チェック済みだが、表示文言の整理は今後必要。
- サイトHTML構造変更に弱い。
- 同タイトル重複判定は簡易判定で完全ではない。
- DBとCBZの実在状態は現在自動同期していない。
- `downloaded` は「過去にダウンロードしたことがある」という履歴で、現在ファイルが存在する意味ではない。
- DBを外付けHDDへ置く設定機能は未実装。

## 今後の設計候補

### DBをHDDへ移す

将来 `02_momonGA_database/momonGA_metadata_store.py` に設定ファイル読込を追加し、DB絶対パスを指定できるようにする。

例:

```json
{
  "database_path": "D:\\momonGA_data\\momonGA_metadata.db",
  "cbz_root": "D:\\momonGA_Download"
}
```

注意:

- SQLiteの `-wal` と `-shm` ファイルも同じHDDに作られる。
- プログラム起動中にHDDを外さない。
- ドライブ文字変更に備えるならボリューム名から探す方法も検討する。

### CBZ存在状態の同期

`downloaded` を0に戻すのではなく、次の列を追加する方針が望ましい。

- `downloaded`: 過去に一度でも取得した
- `file_present`: 現在CBZが存在する
- 将来必要なら `cbz_path`

CBZ名には作品IDを含める案:

```text
[mo3945623] [作者] タイトル.cbz
```

起動時または専用同期ツールでHDDを走査し、IDから `file_present` とパスを更新する。

### お気に入り

未実装。想定案:

- `works.favorite INTEGER NOT NULL DEFAULT 0`
- メタデータ専用登録後にお気に入り確認
- 利用ツール側でお気に入り一覧・検索

### not foundの3回目以降の再調査

未実装。想定列:

- `not_found_checked_count`
- `last_rechecked_at`
- `next_recheck_after`

再調査間隔案:

- 2回目: 通常巡回終了後
- 3回目: 30日後
- 4回目: 90日後
- 以後: 半年または1年ごと

## 依存関係

主なPythonパッケージ:

- `requests`
- `beautifulsoup4`
- `pillow`

標準ライブラリ:

- `sqlite3`
- `zipfile`
- `tkinter` をGUI化で利用する可能性あり

## 検証時の基本コマンド

```powershell
python -m py_compile .\02_momonGA_database\momonGA_metadata_store.py
python -m py_compile .\01_momonGA_downloader\momonGA_downloader.py
python -m py_compile .\03_momonGA_metadata_searching\momonGA_metadata_auto_searching.py
python -m py_compile .\04_momonGA_patch\momonGA_metadata_manual_searching.py
```

実サイト検証はサーバー負荷を避け、少数URLで行う。

## 新しいCodexへの注意

- 既存DBや進捗JSONを削除・初期化しない。
- `03_momonGA_metadata_searching/momonGA_searching_state.json` の値をDB最大IDから作り直さない。
- `downloaded` をメタデータ更新だけで0へ戻さない。
- 手動補修では `overwrite_work_metadata()` を使う。
- ユーザーが明示しない限り、既存PDF・CBZ・DBを破壊的に削除しない。
- `momonGA_systems` を正本として編集し、旧複製フォルダと同期運用しない。
