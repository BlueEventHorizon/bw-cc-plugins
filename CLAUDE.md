# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claude Code プラグインのマーケットプレイスリポジトリ。1つのプラグイン（kaizen）を格納・配布する。

- **kaizen** (v0.0.4) — AI を活用したコード・文書レビュー。段階的提示と自動修正に対応。`.doc_structure.yaml` によるプロジェクト文書構成の管理機能を統合

## Development

ビルドシステム・パッケージマネージャーは使用していない。Python スクリプトは標準ライブラリのみで動作する（PyYAML 等の外部依存なし）。

### プラグインのローカルテスト

```bash
# セッション限定でプラグインをロード
claude --plugin-dir ./plugins/kaizen

# マーケットプレイス経由
/plugin marketplace add BlueEventHorizon/bw-cc-plugins
/plugin install kaizen@bw-cc-plugins
```

### スクリプト動作確認

```bash
# レビュー対象の自動検出
python3 plugins/kaizen/skills/review/scripts/resolve_review_context.py [対象パス]

# ディレクトリスキャン（メタデータ JSON 出力）
python3 plugins/kaizen/scripts/classify_dirs.py [プロジェクトルート]
```

## Architecture

### マーケットプレイス構造

`.claude-plugin/marketplace.json` がルートに配置され、`plugins/` 配下の各プラグインを参照する。各プラグインは独自の `.claude-plugin/plugin.json` マニフェストを持つ。

### kaizen プラグインのスキル連鎖

`review` → `present-findings` → `fix-findings` の3スキルがパイプラインを構成する。

1. **`/kaizen:review`** (user-invocable) — レビュー実行のエントリーポイント。種別判定・参考文書収集・エンジン選択を行い、レビューを実行
2. **`present-findings`** (AI専用, `user-invocable: false`) — レビュー結果を1件ずつ段階的に提示し、ユーザーの修正判断を仰ぐ
3. **`fix-findings`** (AI専用, `user-invocable: false`) — 指摘事項に基づく修正を subagent で実行

### init-kaizen スキル

`/kaizen:init-kaizen` (user-invocable) — プロジェクトのディレクトリをスキャンし、AI が分類判定を行い `.doc_structure.yaml` を対話的に生成する。`classify_dirs.py` がディレクトリのメタデータ（ファイル数、frontmatter 等）を JSON で出力し、分類判定は AI が SKILL.md 内のルールに従って行う。

### レビュー観点の3階層フォールバック

review スキルがレビュー観点を探索する優先順位：
1. **DocAdvisor** — `/query-rules` Skill が動的にプロジェクト固有の観点を特定（`.claude/skills/query-rules/SKILL.md` で利用可否判断）
2. **プロジェクト設定** — `.claude/review-config.yaml`
3. **プラグインデフォルト** — `plugins/kaizen/defaults/review_criteria.md`

### レビュー種別

`code` / `requirement` / `design` / `plan` / `generic` の5種別。`generic` の場合は `/query-rules` / `/query-specs` を使用せず最小限のレビュー観点のみ適用する。

### 参考文書の収集

kaizen は `.doc_structure.yaml` を直接読み込んでパスを解決し、参考文書を収集する。DocAdvisor（`/query-rules`, `/query-specs`）が利用可能な場合はそちらを優先する。

## Conventions

- SKILL.md 内のコメント・説明は日本語で記述する
- Python スクリプトは標準ライブラリのみ使用（外部依存禁止）
- AI専用スキルには `user-invocable: false` を frontmatter で指定
- スクリプトのパス参照には `${CLAUDE_PLUGIN_ROOT}` を使用
- `[MANDATORY]` マーカーが付いたセクションは省略・変更不可の必須仕様
