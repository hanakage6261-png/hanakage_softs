# momonGA legacies

このフォルダは、通常運用の本体ではない補助スクリプトや旧試作物を置く場所です。

## Files

- `momonGA_searching_legacies/`
  - メタデータ収集プログラムを作る過程で使った旧ファイルと、手動補修用スクリプト置き場です。
- `momonGA_searching_legacies/momonGA_researching_for_mistakes.py`
  - IDを手入力し、そのIDのメタデータをサイトから再取得してDBへ強制上書きします。
  - `downloaded` フラグは変更しません。
- `momonGA_pdf_to_cbz_redownload_helper.py`
  - `~/Downloads/momonGA_PDFs` にある旧PDF名から作者名を読み取り、DBまたはサイト検索で作品URLを集めます。
  - 取得したURLは `recovered_pdf_work_urls.txt` に保存し、ダウンローダーの再開キューにも登録します。
  - 処理済みPDFは既定では `momonGA_PDFs/processed/` へ移動します。
  - `--delete-pdfs` を付けた場合だけ、処理済みPDFを削除します。

## Usage

```powershell
python .\momonGA_legacies\momonGA_searching_legacies\momonGA_researching_for_mistakes.py
```

```powershell
python .\momonGA_legacies\momonGA_pdf_to_cbz_redownload_helper.py --enqueue-only
```

```powershell
python .\momonGA_legacies\momonGA_pdf_to_cbz_redownload_helper.py
```
