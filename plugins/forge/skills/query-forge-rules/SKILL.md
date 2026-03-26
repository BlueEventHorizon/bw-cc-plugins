---
name: query-forge-rules
description: |
  forge 内蔵ドキュメントの ToC を検索し、タスクに関連する forge docs のパスを返す。
  query-rules と同じパターンだが、対象は forge プラグイン内蔵の知識ベース。
context: fork
agent: general-purpose
model: haiku
user-invocable: false
---

## Role

タスク内容を分析し、関連する forge 内蔵ドキュメントのパスリストを返す。

## Procedure

1. `${CLAUDE_PLUGIN_ROOT}/toc/rules_toc.yaml` を Read で全文読み込む
   - **見つからない場合**: 「forge ToC が見つかりません」とエラー報告して終了
2. 全エントリを理解し、タスク内容と各エントリの `applicable_tasks` / `keywords` を照合する
3. 関連の可能性があればファイル実体を Read して確認する（false negative 禁止）
4. 確認済みパスリストを返す

## Critical Rule

**ToC は必ず全文を Read で読み込んでから判断する。**

- ❌ 禁止: Grep/検索ツールで ToC を部分検索
- ❌ 禁止: ToC の部分読み込み・斜め読み
- ✅ 必須: Read ツールで ToC 全文を読む
- ✅ 必須: 全エントリを理解してから関連文書を特定する

## Output Format

```
Required documents:
- plugins/forge/docs/xxx.md
- plugins/forge/skills/review/docs/xxx.md
```

## Notes

- false negative は厳禁。迷ったら含める
- パスは bw-cc-plugins リポジトリルートからの相対パス
