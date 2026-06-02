---
name: query-db-rules
description: |
  プロジェクトの様々なルールを、キーワード・機能名・自然文で、高速・高品位に、優先度をつけて検索する。
  設計・実装・コーディング・レビュー等、開発作業のあらゆる場面でルールを参照したいときに使う。
user-invocable: false
argument-hint: "task description"
allowed-tools: Skill
---

ルール文書（key `rules`）を検索する read-only ラッパー。`doc-advisor:query-docs` へ転送する。

> ❌ 自己再帰禁止: `Skill` ツールで自分自身や他の `/forge:*-db-*` 抽象 SKILL を呼ばないこと（無限再帰）

## Procedure

`Skill` ツールで `doc-advisor:query-docs` を **1 回だけ** 呼ぶ:

```
/doc-advisor:query-docs --key rules <$ARGUMENTS>
```

`$ARGUMENTS`（検索タスク記述）をそのまま末尾に渡す。バックエンドの応答はそのまま親に返す（構造変換しない）。

## 前提・エラー処理

- `doc-advisor` プラグイン（外部 marketplace `BlueEventHorizon/DocAdvisor`）が未インストールで
  `doc-advisor:query-docs` が available-skills に存在しない場合は、その旨を報告して終了する。
- ToC（key `rules`）が未生成（`TOC_NOT_FOUND`）の場合は、`/forge:update-db-rules` で索引を生成するよう案内する。

## Output Format

応答の先頭は `Required documents:` 形式:

```
Required documents:

- docs/rules/xxx.md
- docs/rules/yyy.md
```

## Notes

- バックエンド間のフォールバックは存在しない（doc-advisor 単一）。
- key の意味（rules）は forge が決定し、doc-advisor へ opaque key として渡す。
