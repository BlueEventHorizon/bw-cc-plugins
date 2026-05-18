---
name: update-db-specs
description: |
  要件定義書・設計書の追加・改訂後に検索インデックスを最新化する。
  新しい仕様文書を /forge:query-db-specs で検索可能にしたいときに実行する。
  トリガー: "仕様検索インデックス更新", "仕様検索インデックス再構築", "設計書インデックス更新"
user-invocable: false
argument-hint: "[--full]"
allowed-tools: Read, Bash, Skill
---

利用可能なバックエンド（doc-db / doc-advisor）を自動選択して仕様文書のインデックス再構築 SKILL に転送するラッパー。

> ❌ 自己再帰禁止: `Skill` ツールで自分自身や他の `/forge:*-db-*` 抽象 SKILL を呼ばないこと（無限再帰）

## Procedure

### Step 1: バックエンド選択

available-skills から `doc-db:build-index` / `doc-advisor:create-specs-toc` の有無を判定し、利用可能なバックエンドをカンマ区切りで `--available` に渡す（両方なら `doc-db,doc-advisor`、なければ空文字列）。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backend_selection/select_backend.py" \
  --available "<doc-db,doc-advisor 等>" \
  --category specs \
  --operation update
```

stdout に `{ "backend": ..., "skill": ..., "error": ... }` の JSON が返る。

### Step 2: 転送

- `error` が null でない場合 → `error` 文字列をそのまま親に返して終了
- `error` が null の場合 → `skill` フィールドの SKILL を `Skill` ツールで 1 回呼ぶ:
  - `/doc-db:build-index` → `/doc-db:build-index --category specs`（`$ARGUMENTS` に `--full` が含まれる場合は付ける）
  - `/doc-advisor:create-specs-toc` → `/doc-advisor:create-specs-toc`（`$ARGUMENTS` に `--full` が含まれる場合は付ける）

### Step 3: 応答の転送

バックエンドの応答をそのまま親に返す。構造変換は行わない。

## Notes

- `/forge:update-db-specs` は明示的なインデックス再構築用。doc-db バックエンドでは `/forge:query-db-specs` 呼出時に自動再生成されるため、明示呼出は「ドキュメント編集直後に確実に最新化したい」場合に使う
- 分岐ロジックの Single Source of Truth は `select_backend.py`。本 SKILL.md に分岐テーブルを複製しない
