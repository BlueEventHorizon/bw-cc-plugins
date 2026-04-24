# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claude Code プラグインのマーケットプレイスリポジトリ。4プラグインを格納・配布する。

- **forge** (v0.0.39) — ドキュメントライフサイクルツール。要件定義・設計・計画書の作成、コード・文書レビュー、自動修正に対応
- **doc-advisor** (v0.2.1) — AI 検索可能なドキュメントインデックス。ToC キーワード検索と Embedding セマンティック検索の2層構造
- **anvil** — commit / PR 作成支援（`/anvil:commit`, `/anvil:create-pr`）
- **xcode** — Xcode ビルド / テスト実行（`/xcode:build`, `/xcode:test`）

全体像・スキル一覧・ワークフロー図は [README.md](README.md) を参照。

## Repository Layout

| Path | 役割 |
|---|---|
| `.claude-plugin/marketplace.json` | マーケットプレイスマニフェスト |
| `plugins/{plugin}/.claude-plugin/plugin.json` | 各プラグインマニフェスト |
| `plugins/{plugin}/skills/{skill}/SKILL.md` | スキル定義（frontmatter + 本文） |
| `plugins/{plugin}/scripts/` | スキルから呼ばれる Python / Bash |
| `plugins/{plugin}/docs/` | プラグイン内部仕様（forge は `/forge:query-forge-rules` 対象） |
| `plugins/forge/toc/rules/rules_toc.yaml` | forge 内蔵知識ベースの ToC |
| `docs/rules/` | プロジェクトルール（`/query-rules` 対象） |
| `docs/specs/{plugin}/{requirements,design,plan}/` | プラグインごとの仕様文書（`/query-specs` 対象） |
| `docs/readme/` | ユーザー向けガイド（日英併記、`guide_*_ja.md`） |
| `docs/references/` | 外部参考資料 |
| `tests/{common,forge,doc_advisor}/` | プラグイン別テスト |
| `meta/` | 研究・評価・ゴールデンセット（git 管理外） |
| `.claude/settings.json` | 権限・hooks 設定（プロジェクトレベル） |
| `.claude/skills/` | ローカル限定 skill（配布対象外、`update-forge-toc` 等） |
| `.agents/skills/` | agent 向け skill |
| `.doc_structure.yaml` | rules/specs のパス解決設定 |
| `.version-config.yaml` | バージョン一括更新の対象設定 |
| `dprint.jsonc` | フォーマッタ設定（JSON/TOML/Markdown/YAML） |
| `AGENTS.md` | `CLAUDE.md` へのシンボリックリンク（Codex 向け、内容は CLAUDE.md と同一） |

## Information Sources

タスクに応じて以下の入口を使う:

| 対象 | 入口 |
|---|---|
| プロジェクト全体の鳥瞰 | `README.md`（ワークフロー図 + 全スキル一覧 + トリガー句） |
| 仕様駆動開発の思想・What/How 境界 | `docs/readme/guide_sdd_ja.md` |
| 各スキルの挙動・引数・使用例 | `docs/readme/forge/guide_{create_docs,implement,review,setup,uxui_design}_ja.md` / `docs/readme/guide_{anvil,xcode,doc-advisor}_ja.md` |
| プロジェクトルール（実装・文書・CLI・SKILL 作成） | `/query-rules` → `docs/rules/` |
| プロジェクト仕様（要件/設計/計画） | `/query-specs` → `docs/specs/` |
| forge 内部仕様（ID体系・フォーマット・原則・レビュー基準） | `/forge:query-forge-rules` → `plugins/forge/docs/` |
| Claude Code / SDK / API 仕様 | `claude-code-guide` agent |
| 最新の変更意図 | `git log main..HEAD` / `CHANGELOG.md` |

### docs/rules/ の代表ファイル

`/query-rules` で取得されるが、存在を把握しておくべき主要ルール:

- `implementation_guidelines.md` — Python / Bash / SKILL.md 実装ルール（**スクリプト実装時必読**）
- `skill_authoring_notes.md` — SKILL.md 作成注意点（**スキル追加・修正時必読**）
- `document_writing_rules.md` — 全文書の一貫性ルール
- `cli_output_formatting.md` — CLI 色コード指針
- `version_migration_design.md` — バージョンマイグレーション設計

## Development

ビルドシステム・パッケージマネージャーは使用していない。Python スクリプトは標準ライブラリのみで動作する（外部依存なし）。

### フォーマット

JSON / TOML / Markdown / YAML は [dprint](https://dprint.dev/) でフォーマット。設定は `dprint.jsonc`。

```bash
dprint fmt          # フォーマット適用
dprint check        # チェックのみ
```

### プラグインのローカルテスト

```bash
# セッション限定でプラグインをロード
claude --plugin-dir ./plugins/forge

# マーケットプレイス経由
/plugin marketplace add BlueEventHorizon/bw-cc-plugins
/plugin install forge@bw-cc-plugins
```

### スクリプト動作確認

```bash
# レビュー対象の自動検出
python3 plugins/forge/skills/review/scripts/resolve_review_context.py [対象パス]

# ディレクトリスキャン（メタデータ JSON 出力）
python3 plugins/forge/scripts/doc_structure/classify_dirs.py [プロジェクトルート]
```

## Testing [MANDATORY]

`plugins/` 配下の Python スクリプトにはテストが必須。SKILL.md はテスト困難なため例外。
`.claude/` 配下のローカルスキル・スクリプトはテスト対象外。

### テストの配置

`tests/` にプラグイン名・スキル名で分類:

```
tests/
├── common/                 # プラグイン横断（マニフェスト整合性等）
├── forge/
│   ├── review/
│   └── scripts/
└── {plugin}/               # 新プラグイン追加時も同構造
```

### テスト実行

```bash
# 一括実行
python3 -m unittest discover -s tests -p 'test_*.py' -v

# 特定モジュールのみ
python3 -m unittest tests.forge.review.test_xxx -v
```

### doc-advisor 品質テスト

ユニットテストはバグがないことを保証する。**検索品質**（精度・再現率）は `meta/test_docs/` で測定する（git 管理外、ローカルのみ）。

- Embedding / ToC / Index の3方式を同一ゴールデンセットで比較評価
- 詳細・実行手順は `meta/test_docs/README.md`

## Architecture

個別スキルの詳細は [README.md](README.md) と `docs/readme/forge/guide_*_ja.md` を参照。ここでは **スキル連鎖とプラグイン統合点** のみ記載する。

### マーケットプレイス構造

`.claude-plugin/marketplace.json`（ルート）が `plugins/` 配下の各プラグインを参照する。各プラグインは独自の `.claude-plugin/plugin.json` マニフェストを持つ。

### forge レビューパイプライン

1. **`/forge:review`** (user-invocable) — オーケストレーター。種別判定・参考文書収集・エンジン選択。`--auto N` で N サイクルのレビュー+自動修正を繰り返す（🔴+🟡対象）
2. **`reviewer`** (AI専用) — レビュー実行（指摘作成）
3. **`evaluator`** (AI専用) — 指摘の吟味・修正判定
4. **`present-findings`** (AI専用) — 対話モードで指摘を1件ずつ提示
5. **`fixer`** (AI専用) — subagent で修正を実行

### 共通完了処理フロー

文書生成系オーケストレーター（start-requirements, start-design, start-plan）は成果物作成後に以下を実行する:

1. `/forge:review {type} {差分ファイル} --auto` — AI レビュー+自動修正（差分のみ対象）
2. `/doc-advisor:create-specs-toc` — ToC 更新（利用可能な場合）
3. `/anvil:commit` — commit/push 確認

start-implement は ToC 更新を含まず、review → commit の2ステップで完了する。

### レビュー種別と perspectives

- **種別**: `code` / `requirement` / `design` / `plan` / `generic` の5種別
- **perspectives**（観点）の累積構造:
  - プラグインデフォルト（常に含む） — `plugins/forge/skills/review/docs/review_criteria_{type}.md` の `## Perspective:` セクション
  - DocAdvisor 追加（`/query-rules` 利用可能時） — プロジェクト固有ルールを perspective として追加
- `generic` は `/query-rules` / `/query-specs` を使わず最小限の観点のみ適用

### 参考文書の収集

forge は `.doc_structure.yaml` を直接読み込んでパスを解決し、参考文書を収集する。DocAdvisor（`/query-rules`, `/query-specs`）が利用可能な場合はそちらを優先する。

### forge 内蔵知識ベース

`plugins/forge/toc/rules/rules_toc.yaml` — forge 自身の仕様文書（ID体系・フォーマット・原則・レビュー基準等）の ToC。`/forge:query-forge-rules` が検索する。ToC は `/update-forge-toc`（ローカル skill）で再生成する。

## Conventions

- **タスク開始時に `/query-rules` を実行**: 新しいタスクに取り掛かる前に `/query-rules` でプロジェクトルールを確認する
- **ルールは `docs/rules/` で管理**: CLAUDE.md にルールを直接書かない（コンテキスト肥大化防止）
- **設計文書の保存**: plan モードで作成した重要な設計文書は `docs/specs/forge/design/` に保存する
