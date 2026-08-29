# 文書構造ガイド

`.doc_structure.yaml` はプロジェクトのドキュメント配置場所と種別を宣言する設定ファイルで、forge がドキュメントのパス解決に用いる。

## Feature（フィーチャー）

forge は **Feature（フィーチャー）** 単位で文書を管理することもできる。Feature とは、関連する仕様をグループ化した開発単位。Feature なしでも動作する。

| 開発パターン                           | Feature の使い方                                                |
| -------------------------------------- | --------------------------------------------------------------- |
| [追加開発](guide_sdd_ja.md#6-追加開発) | 既存のメイン仕様に後から追加する機能群を Feature として分割する |
| アジャイル開発                         | イテレーションごとに Feature 単位で開発・デリバリーする         |
| 小規模プロジェクト                     | プロジェクト全体を1つの Feature として扱ってもよい              |

Feature を使う場合、各 Feature は共通のディレクトリ構造で管理する:

```
specs/
  {feature}/
    requirements/   # 要件定義書
    design/         # 設計書
    plan/           # 計画書
```

## .doc_structure.yaml

### 役割

プロジェクトのドキュメント配置場所と種別を宣言するファイル。以下のツールが共通で参照する:

- **forge** — レビュー対象の解決、Feature ディレクトリ検出、ドキュメント作成先の特定、検索インデックス対象パスの解決（解決結果を選択した文書検索 backend（doc-advisor / doc-db）に渡す）

プロジェクトルート（`.git/` と同階層）に配置する。

### スキーマ概要

`rules` と `specs` の2カテゴリで構成され、各カテゴリに `root_dirs`（対象ディレクトリ。glob 対応）・`doc_types_map`（パス→doc_typeのマッピング）・`patterns`（検索パターン・除外設定）を持つ。Feature ごとに個別設定を追加する必要はなく、`docs/specs/*/design/` のような glob パターン1つで全 Feature を横断できる（`**` を使えばネストした Feature も一括対応する。例: `docs/specs/forge/design/` と `docs/specs/forge/review-PR/design/` の両方が自動検出される）。Feature 追加時に `.doc_structure.yaml` 自体の変更は不要で、対象ディレクトリを作成するだけで自動的に検出される。

フィールドの詳細・具体的な yaml 例（シンプル構成・Feature ベース構成・ネスト Feature 構成）は [doc_structure_format.md](../../plugins/forge/docs/doc_structure_format.md) を参照。

## /forge:setup-doc-structure

```
/forge:setup-doc-structure
```

引数なし。

### 何をするか

- プロジェクトをスキャンして `.doc_structure.yaml` を対話的に生成・更新する
- 既存 Feature ディレクトリを自動検出し glob パターンで設定する
- 推奨構成（specs / rules / reference / adr）を提示し、不足ディレクトリを `.gitkeep` 付きで作成する

### いつ実行するか

- プロジェクトで forge を初めて使うとき
- ディレクトリ構造を大きく変更したとき
- Feature を手動で追加したとき

## スキーマ仕様リファレンス

詳細なフォーマット仕様は [doc_structure_format.md](../../plugins/forge/docs/doc_structure_format.md) を参照。
