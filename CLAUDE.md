# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claude Code プラグインのマーケットプレイスリポジトリ。1つのプラグイン（forge）を格納・配布する。

- **forge** (v0.0.5) — AI を活用したドキュメントライフサイクルツール。要件定義・設計・計画書の作成、コード・文書レビュー、自動修正、品質確定に対応

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
python3 plugins/forge/scripts/classify_dirs.py [プロジェクトルート]
```

## Architecture

### マーケットプレイス構造

`.claude-plugin/marketplace.json` がルートに配置され、`plugins/` 配下の各プラグインを参照する。各プラグインは独自の `.claude-plugin/plugin.json` マニフェストを持つ。

### forge プラグインのスキル連鎖

`review` → `present-findings` → `fix-findings` の3スキルがレビューパイプラインを構成する。

1. **`/forge:review`** (user-invocable) — レビュー実行のエントリーポイント。種別判定・参考文書収集・エンジン選択を行い、レビューを実行。`--refactor N` で N サイクルのレビュー+修正を繰り返す（🔴+🟡対象）
2. **`present-findings`** (AI専用, `user-invocable: false`) — レビュー結果を1件ずつ段階的に提示し、ユーザーの修正判断を仰ぐ
3. **`fix-findings`** (AI専用, `user-invocable: false`) — 指摘事項に基づく修正を subagent で実行

### setup-doc-structure スキル

`/forge:setup-doc-structure` (user-invocable) — プロジェクトのディレクトリをスキャンし、AI が分類判定を行い `.doc_structure.yaml` を対話的に生成する。`classify_dirs.py` がディレクトリのメタデータ（ファイル数、frontmatter 等）を JSON で出力し、分類判定は AI が SKILL.md 内のルールに従って行う。

### create-requirements スキル

`/forge:create-requirements` (user-invocable) — 要件定義書を作成する。3つのモードに対応:

- **interactive**: 対話形式でゼロから要件を固める
- **reverse-engineering**: 既存アプリのソースコードを解析して要件を抽出
- **from-figma**: Figma MCP を使いデザインファイルから要件とデザイントークンを作成（Figma MCP 必須）

文書作成のみに専念し、後処理は行わない。完了後に `/forge:finalize` の実行を案内する。

### finalize スキル（post-creation オーケストレーター）

`/forge:finalize` (user-invocable) — 文書作成後の品質確定を担うオーケストレーター。
`create-requirements` / `start-design`（予定）/ `start-plan`（予定）の後続処理として使用:

1. `/forge:review {type} {target} --refactor N` を呼び出す
2. `/create-specs-toc` が利用可能なら実行

ユーザーが明示的に呼び出す設計（start-X からの自動呼び出しは行わない）。

### start-implement スキル（タスク実行オーケストレーター）

`/forge:start-implement` (user-invocable) — 計画書からタスクを選択し、コンテキスト収集→実装→レビュー→計画書更新を一連で実行する。

1. 計画書の読み込みとタスク選択（優先度順 or `--task` 指定）
2. コンテキスト収集（rules/code agent 並列起動）
3. task-executor agent に実装を委譲（`task_execution_guide.md` を参照）
4. `/forge:review code` でレビュー
5. 計画書のチェックマーク更新（☐ → ☑）

### setup-version-config / bump スキル（バージョン管理）

`/forge:setup-version-config` (user-invocable) — プロジェクトをスキャンし `.version-config.yaml` を対話的に生成・更新する。
`scan_version_targets.py` がバージョンファイル（plugin.json / package.json / Cargo.toml 等）・README・CHANGELOG を検出し、AI が設定草案を生成してユーザーが確認する。
プロジェクト構造変更時（プラグイン追加・README フォーマット変更など）に再実行して設定を更新する。

`/forge:bump` (user-invocable) — `.version-config.yaml` の設定に基づきバージョンを一括更新する。
`patch` / `minor` / `major` または直接バージョン指定に対応。CHANGELOG への git log 自動反映・git commit/tag 作成オプション付き。
`.version-config.yaml` が存在しない場合は `/forge:setup-version-config` の実行を案内する。

### レビュー観点の3階層フォールバック

review スキルがレビュー観点を探索する優先順位：

1. **DocAdvisor** — `/query-rules` Skill が動的にプロジェクト固有の観点を特定（`.claude/skills/query-rules/SKILL.md` で利用可否判断）
2. **プロジェクト設定** — `.claude/review-config.yaml`
3. **プラグインデフォルト** — `plugins/forge/defaults/review_criteria.md`

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
│   ├── scripts/
│   └── show_report/
└── {plugin}/               # 新プラグイン追加時も同構造
```

### テスト実行

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Conventions

- **タスク開始時に `/query-rules` を実行する**: 新しいタスクに取り掛かる前に `/query-rules` でプロジェクトルールを確認すること
- SKILL.md 内のコメント・説明は日本語で記述する
- Python スクリプトは標準ライブラリのみ使用（外部依存禁止）
- AI専用スキルには `user-invocable: false` を frontmatter で指定
- スクリプトのパス参照には `${CLAUDE_PLUGIN_ROOT}` を使用
- `[MANDATORY]` マーカーが付いたセクションは省略・変更不可の必須仕様
- **SKILL.md にインラインスクリプトを書かない** [MANDATORY]: AI がスクリプトを勝手に解釈して失敗するリスクがある。処理ロジックは独立した Python スクリプトファイルとして実装し、SKILL.md からはそのスクリプトを呼び出す形式にすること
