# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claude Code プラグインのマーケットプレイスリポジトリ。forge / anvil / xcode の3プラグインを格納・配布する。

- **forge** (v0.0.27) — AI を活用したドキュメントライフサイクルツール。要件定義・設計・計画書の作成、コード・文書レビュー、自動修正、品質確定に対応

## Development

ビルドシステム・パッケージマネージャーは使用していない。Python スクリプトは標準ライブラリのみで動作する（PyYAML 等の外部依存なし）。

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

## Architecture

### マーケットプレイス構造

`.claude-plugin/marketplace.json` がルートに配置され、`plugins/` 配下の各プラグインを参照する。各プラグインは独自の `.claude-plugin/plugin.json` マニフェストを持つ。

### forge プラグインのスキル連鎖

#### レビューパイプライン

以下のスキルがレビューパイプラインを構成する。

1. **`/forge:review`** (user-invocable) — レビュー実行のオーケストレーター。種別判定・参考文書収集・エンジン選択を行い、レビューを実行。`--auto N` で N サイクルのレビュー+自動修正を繰り返す（🔴+🟡対象）
2. **`reviewer`** (AI専用) — レビュー実行（指摘事項の作成）
3. **`evaluator`** (AI専用) — 指摘事項の吟味・修正判定
4. **`present-findings`** (AI専用) — 対話モードで指摘を1件ずつ段階的に提示
5. **`fixer`** (AI専用) — 指摘事項に基づく修正を subagent で実行

#### 共通完了処理フロー

文書生成系オーケストレーター（start-requirements, start-design, start-plan）は成果物作成後に以下を実行する:

1. `/forge:review {type} {差分ファイル} --auto` — AIレビュー+自動修正（差分のみ対象）
2. `/create-specs-toc` — ToC 更新（利用可能な場合）
3. `/anvil:commit` — commit/push 確認

start-implement は ToC 更新を含まず、review → commit の2ステップで完了する。

### setup-doc-structure スキル

`/forge:setup-doc-structure` (user-invocable) — プロジェクトのディレクトリをスキャンし、AI が分類判定を行い `.doc_structure.yaml` を対話的に生成する。`classify_dirs.py` がディレクトリのメタデータ（ファイル数、frontmatter 等）を JSON で出力し、分類判定は AI が SKILL.md 内のルールに従って行う。

### start-requirements スキル

`/forge:start-requirements` (user-invocable) — 要件定義書を作成する。3つのモードに対応:

- **interactive**: 対話形式でゼロから要件を固める
- **reverse-engineering**: 既存アプリのソースコードを解析して要件を抽出
- **from-figma**: Figma MCP を使いデザインファイルから要件とデザイントークンを作成（Figma MCP 必須）

完了後は共通完了処理フロー（review → ToC → commit）を実行する。

### start-implement スキル（タスク実行オーケストレーター）

`/forge:start-implement` (user-invocable) — 計画書からタスクを選択し、コンテキスト収集→実装→レビュー→計画書更新を一連で実行する。

1. 計画書の読み込みとタスク選択（優先度順 or `--task` 指定）
2. コンテキスト収集（rules/code agent 並列起動）
3. task-executor agent に実装を委譲（`task_execution_spec.md` を参照）
4. `/forge:review code {差分} --auto` でレビュー+自動修正
5. 計画書のステータス更新（`status: pending` → `status: completed`）
6. `/anvil:commit` で commit/push 確認

### setup-version-config / update-version スキル（バージョン管理）

`/forge:setup-version-config` (user-invocable) — プロジェクトをスキャンし `.version-config.yaml` を対話的に生成・更新する。
`scan_version_targets.py` がバージョンファイル（plugin.json / package.json / Cargo.toml 等）・README・CHANGELOG を検出し、AI が設定草案を生成してユーザーが確認する。
プロジェクト構造変更時（プラグイン追加・README フォーマット変更など）に再実行して設定を更新する。

`/forge:update-version` (user-invocable) — `.version-config.yaml` の設定に基づきバージョンを一括更新する。
`patch` / `minor` / `major` または直接バージョン指定に対応。CHANGELOG への git log 自動反映・git commit/tag 作成オプション付き。
`.version-config.yaml` が存在しない場合は `/forge:setup-version-config` の実行を案内する。

### perspectives ベースのレビュー観点

review スキルは perspectives（観点）の累積構造でレビュー観点を構成する:

- **プラグインデフォルト**（常に含む） — `plugins/forge/skills/review/docs/review_criteria_{type}.md` の `## Perspective:` セクションから perspectives を構成
- **DocAdvisor**（追加 perspective） — `/query-rules` Skill が利用可能な場合、プロジェクト固有のルール文書を追加の perspective として渡す

### レビュー種別

`code` / `requirement` / `design` / `plan` / `generic` の5種別。`generic` の場合は `/query-rules` / `/query-specs` を使用せず最小限のレビュー観点のみ適用する。

### 参考文書の収集

forge は `.doc_structure.yaml` を直接読み込んでパスを解決し、参考文書を収集する。DocAdvisor（`/query-rules`, `/query-specs`）が利用可能な場合はそちらを優先する。

## Testing [MANDATORY]

`plugins/` 配下の Python スクリプトにはテストが必須。SKILL.md はテスト困難なため例外とする。
`.claude/` 配下のローカルスキル・スクリプトはテスト対象外。

### テストの配置

`tests/` にプラグイン名・スキル名で分類して配置する:

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
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Conventions

- **タスク開始時に `/query-rules` を実行する**: 新しいタスクに取り掛かる前に `/query-rules` でプロジェクトルールを確認すること
- 詳細なルールは `docs/rules/` に配置し、DocAdvisor（`/query-rules`）経由で参照する
- CLAUDE.md にルールを直接書かない。コンテキスト肥大化を防ぐため `docs/rules/` で管理する
- **設計文書の保存**: plan モードで作成した重要な設計文書は `docs/specs/forge/design/` に保存すること
