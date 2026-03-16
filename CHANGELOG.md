# Changelog

All notable changes to this project will be documented in this file.

## [0.0.22] - 2026-03-16

### forge

- **refactor**: 全オーケストレーター（start-requirements/design/plan/implement）の完了処理を統一（review --auto → ToC → commit）
- **refactor**: finalize スキルを廃止。完了処理は各オーケストレーターが直接実行
- **refactor**: review Phase 1 の引数解析を Python スクリプトから AI 解釈に移行
- **remove**: `parse_review_args.py` とテスト削除（AI 解析に移行のため）
- **fix**: README の `--refactor` オプション名を `--auto` に統一（SKILL.md と整合）
- **refactor**: CLAUDE.md のルールを `docs/rules/implementation_guidelines.md` に移動（DocAdvisor 管理）
- **docs**: `orchestrator_pattern.md` に FNC-006（共通完了処理フロー）、FNC-007（AI 引数解釈）追加

## [0.0.21] - 2026-03-16

### forge

-

## [0.0.20] - 2026-03-15

### forge

- **refactor**: .doc_structure.yaml v3.0 対応（Doc Advisor v5.0 内部フィールド除去）
- **feat**: `migrate_doc_structure.py` 新規作成（COMMON-REQ-001 準拠の段階的マイグレーション）
  - v1→v2→v3 のチェーン実行、--check / --dry-run モード、テスト45件
- **feat**: `version_migration_spec.md` 新規作成（バージョンマイグレーション実装仕様）
- **fix**: review ワークフロー実装を設計書に整合
  - 残存セッション検出フロー追加、session_manager.py cleanup 使用、--diff-only パラメータ明示
  - 一括修正後の再レビューループ追加、auto 次サイクルで reviewer 再呼び出し
- **refactor**: 計画書フォーマットを Markdown → YAML に移行（FNC-005）
- **docs**: 設計書・要件定義書の齟齬修正（COMMON-REQ-001 と version_management_design の整合）

## [0.0.19] - 2026-03-15

### forge

- **refactor**: ドキュメント構造の大規模リファクタリング
  - `defaults/` を `docs/` に統合（8ファイル移動、ディレクトリ削除）
  - 設計書ファイル名を `_design` 接尾辞で統一（4ファイルリネーム）
  - ランタイム docs を `_format` / `_spec` 接尾辞で統一（5ファイルリネーム）
  - `doc_structure_format.md` を設計書 → ランタイム docs に移動
  - パイプライン → ワークフロー用語統一
- **refactor**: スキルリネーム `create-design/plan/requirements` → `start-design/plan/requirements`
- **refactor**: `start-implement` の `--parallel` を廃止、`--task` を複数ID対応（カンマ区切り）に変更
- **feat**: `review_workflow_design.md` 新規作成（3設計書を統合）
- **fix**: review ワークフロー実装を設計書に整合
  - fixer 後の単独修正レビュー（`--diff-only`）ループ追加
  - 対話モードで evaluator が plan.yaml を更新するよう修正
  - show-report を review Phase 4 から除去

## [0.0.18] - 2026-03-13

### forge

-

## [0.0.17] - 2026-03-13

### forge

-

## [anvil 0.0.4] - 2026-03-13

### anvil

-

## [0.0.16] - 2026-03-13

### forge

- **fix**: evaluator の plan.yaml 更新責務を全モード共通に統一（session_format.md, review_session_design.md）
- **fix**: present-findings の `in_progress` 更新を fixer 呼び出し前に移動し、`fixed` 上書きリスクを解消
- **fix**: forge_review_pipeline.md の evaluator インタフェーステーブルに3モード（--auto / --auto-critical / --interactive）を記載
- **fix**: review_session_design.md の進捗バー定義に `needs_review` を追加
- **fix**: `doc_structure_format.md` への参照パスを `docs/specs/forge/design/` に修正（README, README_ja, setup/SKILL.md, テスト）

## [0.0.15] - 2026-03-12

### forge

- **feat**: evaluator に `auto_fixable` フラグを追加（✅ 自明マーク判定を evaluator に一元化）
- **refactor**: evaluation.yaml の `decision` フィールドを `recommendation` にリネーム
- **refactor**: evaluator の plan.yaml 更新を全モード共通化（`--interactive` でも初期更新）
- **feat**: create-design / create-plan スキルのフルワークフロー実装
- **feat**: オーケストレータパターン要件定義書・セッションプロトコル設計書・コンテキスト収集ガイドを追加
- **docs**: create-* スキルから競合する優先度指示を削除
- **feat**: doc-advisor の SKILL / query ドキュメント改善

### anvil

- **refactor**: commit スキルの hook/issue-ref 検出をスクリプト化
- **fix**: Phase 7 で「push しない」をデフォルト選択肢に設定

## [0.0.14] - 2026-03-11

### forge

- **fix**: review パイプラインの Phase 番号を整数化（1.5 → 2 等）

## [0.0.13] - 2026-03-10

### forge

- **feat**: 全 SKILL.md でユーザー確認に AskUserQuestion ツールを必須化
- **fix**: AskUserQuestion の呼び出し修正

## [0.0.12] - 2026-03-09

### forge

- **feat**: `update-version` スキルを追加（plugin.json / marketplace.json / README.md の一括更新）

## [0.0.11] - 2026-03-08

### forge

- **feat**: セッションディレクトリ設計の実装と `session_format.md` 追加
- **refactor**: review パイプラインをオーケストレータパターンに再設計し設計書を追加
- **feat**: review パイプラインに Phase 別 progress reporting を追加

## [0.0.10] - 2026-03-07

### forge

- **feat**: review --refactor サイクルに evaluation phase（吟味フェーズ）を追加
- **refactor**: Phase 番号を 1.5 → 2, 2 → 3, 3 → 4 に整理
- **fix**: commit & push のユーザー確認フロー修正
- **fix**: コードレビュー指摘の修正（3サイクル）

## [0.0.9] - 2026-03-06

### forge

- **feat**: `create-design`, `create-plan`, `help` スキルを追加

### xcode

- **fix**: xcode スクリプトの修正

## [0.0.8] - 2026-03-05

### xcode

- **feat**: xcode プラグインを追加（`build`, `test` スキル）

## [0.0.7] - 2026-03-04

### anvil

- **feat**: anvil プラグインを追加（`create-pr`, `commit` スキル）

### forge

- **fix**: forge スキルの修正

## [0.0.6] - 2026-03-03

### forge

- **feat**: doc-advisor 更新
- **refactor**: スキル名のリネーム

## [0.0.5] - Initial Release

### forge

- **feat**: 初回リリース — review, setup, create-requirements, present-findings, fix-findings スキル
- **feat**: doc-advisor 統合（/query-rules, /query-specs）
- **feat**: .doc_structure.yaml によるプロジェクト文書構造管理
