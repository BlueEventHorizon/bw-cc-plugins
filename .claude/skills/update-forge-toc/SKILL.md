---
name: update-forge-toc
description: |
  forge 内蔵ドキュメントの rules_toc.yaml を doc-advisor パイプラインで自動生成する。
  swap-doc-config SKILL に依頼して .doc_structure.yaml を forge 用設定に差し替え、create-rules-toc を実行し、復元する。
  トリガー: "forge ToC 更新", "update forge toc", "forge 内蔵ドキュメントの ToC を再生成"
allowed-tools: Bash, Read, Write, Glob, Skill
user-invocable: true
argument-hint: ""
---

# update-forge-toc

doc-advisor の `/doc-advisor:create-rules-toc` パイプラインを借用して、`plugins/forge/toc/rules_toc.yaml` を AI 品質で自動生成する。

## 前提条件

- `/doc-advisor:create-rules-toc` SKILL が利用可能であること
- `/swap-doc-config` SKILL が利用可能であること

## forge 固有の引数

| 値                                               | 内容                                          |
| ------------------------------------------------ | --------------------------------------------- |
| `${CLAUDE_PLUGIN_ROOT}/forge_doc_structure.yaml` | swap-doc-config の `--target` に渡す YAML     |
| `${CLAUDE_PLUGIN_ROOT}/.backup`                  | swap-doc-config の `--backup-dir` に渡す path |

> **注**: `${CLAUDE_PLUGIN_ROOT}` は本 SKILL のディレクトリを指す。

## 実行フロー

> **重要**: Step 2 がエラーになっても **必ず** Step 3 (restore) を実行すること。

### Step 1: 設定の退避と差し替え

Skill ツールで `swap-doc-config` を以下の引数で実行する:

```
--store --target ${CLAUDE_PLUGIN_ROOT}/forge_doc_structure.yaml --backup-dir ${CLAUDE_PLUGIN_ROOT}/.backup
```

JSON 出力の `status` を確認:

- `ok` → Step 2 へ
- `error` → 中断（restore 不要）。`message` に `Backup already exists` が含まれる場合は前回 `--restore` し忘れの状態。`${CLAUDE_PLUGIN_ROOT}/.backup/` の中身を確認した上で `--restore` を実行して復旧してから再試行する

### Step 2: ToC 生成

`/doc-advisor:create-rules-toc` を実行する（incremental モード）。初回や checksums がない場合は自動で full にフォールバックする。

forge_doc_structure.yaml の `output_dir` 設定により、ToC は `plugins/forge/toc/rules/rules_toc.yaml` に直接出力される。コピー不要。

**エラー時**: Step 2 の結果に関わらず **必ず** Step 3 以降を実行する。

### Step 3: 設定の復元

Skill ツールで `swap-doc-config` を以下の引数で実行する:

```
--restore --backup-dir ${CLAUDE_PLUGIN_ROOT}/.backup
```

JSON 出力の `status` を確認:

- `ok` → Step 4 へ
- `error` → ユーザーに手動復元を案内: `${CLAUDE_PLUGIN_ROOT}/.backup/` にバックアップがある

### Step 4: 完了報告

```
forge rules_toc.yaml を更新しました

- 生成元: plugins/forge/docs/, plugins/forge/skills/*/docs/
- 出力先: plugins/forge/toc/rules/rules_toc.yaml (output_dir convention)
- .doc_structure.yaml: 復元済み
```
