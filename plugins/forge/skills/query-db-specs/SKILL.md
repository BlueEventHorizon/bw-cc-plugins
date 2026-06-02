---
name: query-db-specs
description: |
  プロジェクトの様々な仕様書を、キーワード・機能名・自然文で、高速・高品位に、優先度をつけて検索する。
  設計・実装・コーディング・レビュー等、開発作業のあらゆる場面で仕様を参照したいときに使う。
user-invocable: false
argument-hint: "task description"
allowed-tools: Skill
---

仕様文書（key `specs`）を検索する read-only ラッパー。検索バックエンドは doc-advisor に一本化されており、
`doc-advisor:query-docs` へ転送する。

> ❌ 自己再帰禁止: `Skill` ツールで自分自身や他の `/forge:*-db-*` 抽象 SKILL を呼ばないこと（無限再帰）

## Procedure

`Skill` ツールで `doc-advisor:query-docs` を **1 回だけ** 呼ぶ:

```
/doc-advisor:query-docs --key specs <$ARGUMENTS>
```

`$ARGUMENTS`（検索タスク記述）をそのまま末尾に渡す。バックエンドの応答はそのまま親に返す（構造変換しない）。

## 前提・エラー処理

- `doc-advisor` プラグイン（外部 marketplace `BlueEventHorizon/DocAdvisor`）が未インストールで
  `doc-advisor:query-docs` が available-skills に存在しない場合は、その旨を報告して終了する。
- ToC（key `specs`）が未生成（`TOC_NOT_FOUND`）の場合は、`/forge:update-db-specs` で索引を生成するよう案内する。

## Output Format

応答の先頭は `Required documents:` 形式:

```
Required documents:

- docs/specs/xxx/requirements/yyy.md
- docs/specs/xxx/design/zzz.md
```

## Notes

- バックエンド間のフォールバックは存在しない（doc-advisor 単一）。
- key の意味（specs）は forge が決定し、doc-advisor へ opaque key として渡す。
