# Phase 3: 実装ルール調査ルール

`/forge:query-db-rules` を使い、タスクに関連するルール文書を特定する。`args` は Issue 本文から **抽出した検索キーワード** または **短い自然文のタスク記述** に限定し、Issue 本文・実装手順をそのまま貼り付けない。

## 必須ルール

- 特定したルール文書は**すべて**実際に Read tool で読み込む
- CLAUDE.md に記載されているプロジェクト構造・アーキテクチャの説明を確認する
- `/forge:query-db-rules` で「architecture」「coding」「layer」「ディレクトリ構造」等をクエリして重要文書を特定する
