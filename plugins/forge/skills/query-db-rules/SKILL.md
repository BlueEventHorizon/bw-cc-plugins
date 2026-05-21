---
name: query-db-rules
description: |
  プロジェクトのコーディング規約・命名規則・設計原則・レビュー基準を検索する。
  設計・実装・コーディング・レビュー等、開発作業のあらゆる場面でルールを参照したいときに使う。
  自然文でタスクを記述すると関連ルール文書のパスを返す。
  トリガー: "ルールを検索", "コーディング規約", "プロジェクトルール", "命名規則"
user-invocable: false
argument-hint: "task description"
allowed-tools: Read, Grep, Glob, Bash, Skill
---

利用可能なバックエンド（doc-db / doc-advisor）を自動選択して該当検索 SKILL に転送する read-only ラッパー。

> ❌ 自己再帰禁止: `Skill` ツールで自分自身や他の `/forge:*-db-*` 抽象 SKILL を呼ばないこと（無限再帰）

## Procedure

### Step 1: バックエンド選択

available-skills から `doc-db:query` / `doc-advisor:query-rules` の有無を判定し、利用可能なバックエンドをカンマ区切りで `--available` に渡す（両方なら `doc-db,doc-advisor`、なければ空文字列）。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backend_selection/select_backend.py" \
  --available "<doc-db,doc-advisor 等>" \
  --category rules \
  --operation query
```

stdout に `{ "backend": ..., "skill": ..., "error": ... }` の JSON が返る。

### Step 2: 転送

- `error` が null でない場合 → `error` 文字列をそのまま親に返して終了
- `error` が null の場合 → `skill` フィールドの SKILL を `Skill` ツールで 1 回呼ぶ:
  - `/doc-db:query` → `/doc-db:query --category rules --query "$ARGUMENTS" --mode rerank`
  - `/doc-advisor:query-rules` → `/doc-advisor:query-rules "$ARGUMENTS"`

バックエンドの応答はそのまま親に返す。構造変換は行わない。

## Output Format

応答の先頭は `Required documents:` 形式（DES-001 §3.1 / §9）:

```
Required documents:

- docs/rules/xxx.md
- docs/rules/yyy.md
```

doc-db バックエンド採用時は後段に `## Hybrid scores / grep hits` セクションが付加されることがある（任意）。

## Notes

- バックエンド間のフォールバックなし（DES-001 §5.4）。最初に選択したバックエンドが失敗したらエラー終了
- 分岐ロジックの Single Source of Truth は `select_backend.py`。本 SKILL.md に分岐テーブルを複製しない
