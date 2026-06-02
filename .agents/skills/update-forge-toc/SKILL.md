---
name: update-forge-toc
description: |
  forge 内蔵ドキュメントの ToC（検索インデックス）を更新する。
  /forge:query-forge-rules の検索結果を最新化したいときに使う。
  トリガー: "forge ToC 更新", "update forge toc", "forge 内蔵ドキュメントの ToC を再生成"
allowed-tools: Bash, Read, Skill
user-invocable: true
argument-hint: ""
---

# update-forge-toc

forge 内蔵ドキュメント（`plugins/forge/docs/`, `plugins/forge/skills/*/docs/`）から、
新 doc-advisor の `index-docs` で ToC を生成し、forge 同梱の検索インデックス
`plugins/forge/toc/rules/rules_toc.yaml` を更新する。

## 前提条件

- `doc-advisor`（外部 marketplace `BlueEventHorizon/DocAdvisor`）の `doc-advisor:index-docs` が利用可能であること
- 未インストールの場合はその旨を報告して終了する

## 実行フロー

### Step 1: 対象パスの解決

forge KB の対象 Markdown を、本 SKILL 同梱の `forge_doc_structure.yaml` から解決する
（doc-advisor は `.doc_structure.yaml` を読まないため、forge 側でパスを解決して渡す）:

```bash
python3 plugins/forge/skills/doc-structure/scripts/resolve_doc_structure.py \
  --type rules \
  --doc-structure .agents/skills/update-forge-toc/forge_doc_structure.yaml
```

stdout JSON の `rules` 配列（project-root-relative パス）を取得する。`status` が `error` なら `message` を報告して終了。

### Step 2: ToC 生成（index-docs）

`doc-advisor:index-docs` を **1 回だけ** 実行する。key には予約語と衝突しない `forge-rules` を使う:

```
/doc-advisor:index-docs --key forge-rules --paths-json '<Step 1 の rules 配列の JSON>'
```

完了レポート JSON の `toc_path`（例: `.claude/doc-advisor/toc/forge-rules-<hash>/toc.yaml`）を取得する。

### Step 3: 同梱 ToC へコピー

```bash
cp "<Step 2 の toc_path>" plugins/forge/toc/rules/rules_toc.yaml
```

### Step 4: 完了報告

```
forge 内蔵 docs の検索インデックスを更新しました

- 生成元: plugins/forge/docs/, plugins/forge/skills/*/docs/
- key: forge-rules
- 出力: plugins/forge/toc/rules/rules_toc.yaml
```

## Notes

- forge 同梱 ToC は doc-advisor 管理 ToC を **コピー** して配布する設計。ランタイムの
  `/forge:query-forge-rules` は同梱ファイルを直接 Read するため doc-advisor インストール不要。
- `.doc_structure.yaml` の退避・復元（旧 swap_doc_config 方式）は不要。
