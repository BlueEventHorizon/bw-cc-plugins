# Changelog

All notable changes to this project will be documented in this file.

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
