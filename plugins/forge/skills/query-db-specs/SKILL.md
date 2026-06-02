---
name: query-db-specs
description: |
  プロジェクトの様々な仕様書を、キーワード・機能名・自然文で、高速・高品位に、優先度をつけて検索する。
  設計・実装・コーディング・レビュー等、開発作業のあらゆる場面で仕様を参照したいときに使う。
user-invocable: false
argument-hint: "task description"
allowed-tools: Skill, Read, Grep, Glob, Bash
---

仕様文書（key `specs`）を検索する read-only ラッパー。`doc-advisor:query-docs` へ転送する。
doc-advisor が未インストールの場合は grep による簡易検索へフォールバックする。

> ❌ 自己再帰禁止: `Skill` ツールで自分自身や他の `/forge:*-db-*` 抽象 SKILL を呼ばないこと（無限再帰）

## Procedure

### A. doc-advisor が利用可能な場合（推奨パス）

`doc-advisor:query-docs` が available-skills に存在する場合、`Skill` ツールでこれを **1 回だけ** 呼ぶ:

```
/doc-advisor:query-docs --key specs <$ARGUMENTS>
```

`$ARGUMENTS`（検索タスク記述）をそのまま末尾に渡す。バックエンドの応答はそのまま親に返す（構造変換しない）。

ToC（key `specs`）が未生成（`TOC_NOT_FOUND`）の場合は、`/forge:update-db-specs` で索引を生成するよう案内する。

### B. doc-advisor が未インストールの場合（grep フォールバック）

`doc-advisor:query-docs` が available-skills に **存在しない** 場合は、A を呼ばずに以下を実行する。

**Step B-1: ユーザーへ通知 [MANDATORY]**

応答の冒頭に必ず以下の警告を出す（grep フォールバックは優先度付けの品質が doc-advisor に劣るため）:

```
⚠️ doc-advisor（外部 marketplace BlueEventHorizon/DocAdvisor）が未インストールのため、grep による簡易検索にフォールバックしました。
高品位な優先度付き検索を行うにはインストールを推奨します:
  /plugin marketplace add BlueEventHorizon/DocAdvisor
  /plugin install doc-advisor@DocAdvisor
```

**Step B-2: 対象パスの解決**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py" --type specs
```

stdout の JSON から `specs` 配列（project-root-relative パス）を読む。`status` が `error` の場合は
`message` を報告して終了する。`specs` が空の場合は「検索対象の仕様文書がありません」と報告して終了する。

**Step B-3: 検索語の類義語展開 [MANDATORY]**

grep は表記が一致しないとヒットしない（doc-advisor のような意味検索ができない）ため、`$ARGUMENTS` から
抽出した検索語ごとに **類義語・関連語を展開** してから検索する。展開の観点:

- 日英対訳（例: 「バージョン」↔ `version`、「レビュー」↔ `review`、「権限」↔ `permission`）
- 略語・正式名称（例: `req` ↔ `requirements`、`spec` ↔ `specification`、`CI` ↔ continuous integration）
- 表記ゆれ・活用（例: `index` / `indexing` / 索引、`config` / configuration / 設定）
- 同義・上位下位概念（例: 「コミット」→ commit / git、「文書」→ doc / document / ドキュメント）

元の語と展開語をまとめて検索対象とする。

**Step B-4: grep 検索**

展開した語を `Grep` ツール（`-i` 相当の大文字小文字無視、語を `|` で連結した正規表現も可）で
Step B-2 の対象ファイル群に横断適用する。いずれかの語にマッチしたファイルを候補とし、
マッチした語の種類数・出現数が多い順に並べる。判断に迷う候補は実体を `Read` で確認し、
false negative を避ける。

## Output Format

応答の先頭は `Required documents:` 形式（フォールバック時は Step B-1 の警告を先に出してから続ける）:

```
Required documents:

- docs/specs/xxx/requirements/yyy.md
- docs/specs/xxx/design/zzz.md
```

## Notes

- doc-advisor 自体には他バックエンドへのフォールバックは存在しない（doc-advisor 単一）。本スキルの grep
  フォールバックは「doc-advisor 不在時の縮退動作」であり、優先度付けの品質は doc-advisor に劣る。
- key の意味（specs）は forge が決定し、doc-advisor へ opaque key として渡す。
