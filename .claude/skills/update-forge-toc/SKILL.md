---
name: update-forge-toc
description: |
  forge 内蔵ドキュメントの rules_toc.yaml を doc-advisor パイプラインで自動生成する。
  .doc_structure.yaml を一時的に forge 用設定に差し替え、create-rules-toc を実行し、復元する。
  トリガー: "forge ToC 更新", "update forge toc", "forge 内蔵ドキュメントの ToC を再生成"
allowed-tools: Bash, Read, Write, Glob
user-invocable: true
argument-hint: ""
---

# update-forge-toc

doc-advisor の `/doc-advisor:create-rules-toc --full` パイプラインを借用して、`plugins/forge/toc/rules_toc.yaml` を AI 品質で自動生成する。

## 前提条件

- `/doc-advisor:create-rules-toc` スキルが利用可能であること

## 実行フロー

> **重要**: Step 2 がエラーになっても **必ず** Step 4 (restore) を実行すること。

### Step 1: 設定の退避と差し替え

```bash
python3 .claude/skills/update-forge-toc/scripts/swap_doc_config.py --store
```

JSON 出力の `status` を確認:
- `ok` → Step 2 へ
- `error` → 中断（restore 不要）

### Step 2: ToC 生成

`/doc-advisor:create-rules-toc --full` を実行する。

**エラー時**: Step 2 の結果に関わらず **必ず** Step 3 以降を実行する。

### Step 3: 生成結果のコピーとヘッダ更新

1. `.toc_work/` が残っていれば削除する:

```bash
rm -rf .claude/doc-advisor/toc/rules/.toc_work
```

2. 生成された ToC をコピーする:

```bash
cp .claude/doc-advisor/toc/rules/rules_toc.yaml plugins/forge/toc/rules_toc.yaml
```

3. `plugins/forge/toc/rules_toc.yaml` のヘッダコメントを更新する:

先頭 3 行を以下に置換:
```
# plugins/forge/toc/rules_toc.yaml
# forge 内蔵ドキュメントの検索インデックス（query-forge-rules 用）
# /update-forge-toc で自動生成 — 手動編集しない
```

### Step 4: 設定の復元

```bash
python3 .claude/skills/update-forge-toc/scripts/swap_doc_config.py --restore
```

JSON 出力の `status` を確認:
- `ok` → Step 5 へ
- `error` → ユーザーに手動復元を案内: `.claude/skills/update-forge-toc/.backup/` にバックアップがある

### Step 5: 完了報告

```
✅ forge rules_toc.yaml を更新しました

- 生成元: plugins/forge/docs/, plugins/forge/skills/*/docs/
- 出力先: plugins/forge/toc/rules_toc.yaml
- .doc_structure.yaml: 復元済み
```
