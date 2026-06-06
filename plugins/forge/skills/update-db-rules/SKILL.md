---
name: update-db-rules
description: |
  ルール文書の追加・改訂後に検索インデックスを最新化する。
  新しいルール文書を /forge:query-db-rules で検索可能にしたいときに実行する。
  トリガー: "ルール検索インデックス更新", "ルールインデックス再構築"
user-invocable: true
argument-hint: ""
allowed-tools: Read, Bash, Skill
---

ルール文書（key `rules`）の検索インデックス（ToC）を再構築するラッパー。`.doc_structure.yaml` から
rules の対象パスを解決して `doc-advisor:index-docs` へ転送する。

> ❌ 自己再帰禁止: `Skill` ツールで自分自身や他の `/forge:*-db-*` 抽象 SKILL を呼ばないこと（無限再帰）

## Procedure

### Step 1: 対象パスの解決

`.doc_structure.yaml` の `rules.root_dirs` / `doc_types_map` / `patterns.exclude` から、index 対象の
project-root-relative パス一覧を取得する（doc-advisor は `.doc_structure.yaml` を読まないため、forge 側で解決して渡す）:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py" --type rules
```

stdout の JSON から `rules` 配列（project-root-relative パスのリスト）を読む。
`status` が `error` の場合は `message` を報告して終了する。

### Step 2: index-docs へ転送

取得した `rules` 配列を **そのまま** `--paths-json` の値（JSON 配列文字列）として、`Skill` ツールで
`doc-advisor:index-docs` を **1 回だけ** 呼ぶ:

```
/doc-advisor:index-docs --key rules --paths-json '<rules 配列の JSON>'
```

`doc-advisor` プラグイン（外部 marketplace `BlueEventHorizon/DocAdvisor`）が未インストールで
`doc-advisor:index-docs` が available-skills に存在しない場合は、その旨を報告して終了する。

### Step 3: 応答の転送

`doc-advisor:index-docs` の完了レポート（added / updated / deleted / toc_path 等）をそのまま親に返す。

## Notes

- **desired-state**: `--paths-json` は key `rules` の完全な desired state。Step 1 で解決した一覧に
  含まれないパスは ToC から削除される（`.doc_structure.yaml` が正）。
- 索引の出力先は `.claude/doc-advisor/toc/rules-<hash>/toc.yaml`（doc-advisor が管理）。
