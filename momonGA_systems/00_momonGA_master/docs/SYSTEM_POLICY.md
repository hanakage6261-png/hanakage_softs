# SYSTEM_POLICY

## この文書の役割

このファイルは `momonGA_systems` の対象範囲、運用方針、基本理念をまとめる文書です。
構造や実装の説明は `PROJECT_CONTEXT.md` に分けます。

## 対象 URL と対象サイト

このシステムの対象は、[text](https://momon-ga.com/)です。

## このサイトの構成について

このサイトでは漫画作品が掲載されていて、各ページに唯一のIDが設定されています。
作品のURLの例→
このURLのIDは


## 運用の基本理念

- 法律と利用規約の範囲内で、安全にダウンロードをする
- URL、メタデータ、ダウンロード、ローカル保存状態を分けて管理する
- 例外処理は通常系に無理に混ぜず、必要なら `04_momonGA_patch` に分離する
- 旧版や使わなくなったものは `06_momonGA_legacies` に退避する

## 配置ルール

- `00_momonGA_master`
  - 全体共通のレジストリと全体文書だけを置く
- `01` から `07`
  - それぞれの役割に属するプログラム、状態ファイル、設定ファイルを置く
- `momonGA_systems` 直下
  - 基本的に最小限とし、入口 README と番号付きフォルダを中心に保つ

## 設定ファイルの置き方

設定ファイルは「誰が使うか」で置き場所を決めます。

- 全体共通で使う設定
  - `00_momonGA_master` に置く
- 特定機能専用の設定
  - その機能の担当フォルダに置く

この方針により、`momonGA_file_status_checker_paths.json` は `03_momonGA_metadata_searching` に置きます。


[def]: https://momon-ga.com/