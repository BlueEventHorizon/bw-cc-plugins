---
name: update-forge-toc
description: |
  forge 内蔵ドキュメントの検索インデックスを更新する。
  /forge:query-forge-rules の検索結果を最新化したいときに使う。
  トリガー: "forge ToC 更新", "update forge toc", "forge インデックス更新", "forge 内蔵ドキュメントの ToC を再生成"
allowed-tools: Bash, Read, Skill
user-invocable: true
argument-hint: ""
---

# update-forge-toc

forge 内蔵ドキュメント（`plugins/forge/docs/`, `plugins/forge/skills/*/docs/`）から、
新 doc-advisor の `index-docs` で ToC を生成し、forge 同梱の検索インデックス
`plugins/forge/toc/rules/rules_toc.yaml` を更新する。

## 前提条件

- `doc-advisor` プラグイン（外部 marketplace `BlueEventHorizon/DocAdvisor`）がインストールされ、
  `doc-advisor:index-docs` が available-skills に存在すること
- 未インストールの場合はその旨を報告して終了する

## 実行フロー

### Step 1: 対象パスの解決

forge KB の対象 Markdown を、本 SKILL 同梱の `forge_doc_structure.yaml` から解決する
（doc-advisor は `.doc_structure.yaml` を読まないため、forge 側でパスを解決して渡す）:

```bash
python3 plugins/forge/skills/doc-structure/scripts/resolve_doc_structure.py \
  --type rules \
  --doc-structure .claude/skills/update-forge-toc/forge_doc_structure.yaml
```

stdout JSON の `rules` 配列（project-root-relative パス）を取得する。`status` が `error` なら `message` を報告して終了。

### Step 2: ToC 生成（index-docs）

`Skill` ツールで `doc-advisor:index-docs` を **1 回だけ** 呼ぶ。key には予約語と衝突しない `forge-rules` を使う:

```
/doc-advisor:index-docs --key forge-rules --paths-json '<Step 1 の rules 配列の JSON>'
```

完了レポート JSON の `toc_path`（例: `.claude/doc-advisor/toc/forge-rules-<hash>/toc.yaml`）を取得する。

### Step 3: 同梱 ToC へコピー

生成された ToC を forge プラグイン同梱の場所へコピーする（配布されるのはこのファイル）:

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

- forge 同梱 ToC は `.claude/doc-advisor/toc/<slug>/` の doc-advisor 管理 ToC を **コピー** して配布する設計。
  ランタイムの `/forge:query-forge-rules` は同梱ファイルを直接 Read するため doc-advisor インストール不要。
