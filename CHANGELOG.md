# Changelog

All notable changes to this project will be documented in this file.

## [0.1.2] - 2026-03-29

### doc-advisor

- **refactor**: `check_doc_structure.sh` を廃止し、Python エラーハンドリングに統合
  - `ConfigNotReadyError` を `init_common_config()` に追加。設定未完了時に `{"status": "config_required"}` JSON を出力し、SKILL.md の Error Handling で AskUserQuestion による設定案内に対応
  - 4 SKILL.md の Pre-check セクションを削除し Error Handling を更新

### doc-advisor / forge 共通

- **fix**: `find_project_root()` / `get_project_root()` の親方向探索を削除。`~/.claude/` 誤検出によるホームディレクトリスキャンを防止

### forge

- **docs**: present-findings サマリーテーブルの5列目ヘッダを `AF` に修正
- **docs**: review SKILL.md の reviewer/evaluator/fixer 起動方法を明確化（general-purpose を明示）

## [0.1.1] - 2026-03-28

### doc-advisor

- **fix**: `determine_doc_type()` が `doc_types_map` の glob パターンキーとマッチしないバグを修正。`expand_doc_types_map()` を追加し `init_common_config()` で事前展開する根本対応
- **fix**: `load_checksums()` が空行でパースを中止する問題を修正
- **fix**: `load_config()` / `load_checksums()` の例外捕捉に OSError を追加
- **fix**: `has_substantive_content()` に UnicodeDecodeError 捕捉を追加
- **refactor**: DEPRECATED 関数 `extract_id_from_filename()` を削除
- **refactor**: checksums YAML 書き込みを `write_checksums_yaml()` に共通化
- **refactor**: 未使用 `import re` 削除、`import hashlib` をトップレベルに移動
- **refactor**: `validate_toc.py` の形骸化した重複パス検査を削除
- **docs**: SKILL.md の Error Handling に AskUserQuestion を明示
- **test**: `has_substantive_content()`, `determine_doc_type()`, `expand_doc_types_map()`, `expand_root_dir_globs()` のテスト追加

## [0.1.0] - 2026-03-28

### doc-advisor

- **feat**: .claude/ 配下のローカルスキルから独立プラグインに移行（TASK-001〜013）
  - スキル・agent・docs・scripts を `plugins/doc-advisor/` に移行
  - toc_utils.py をプラグイン環境に適応（`CLAUDE_PROJECT_DIR` / CWD 探索）
  - 全テストを Python unittest に移行（統合テスト含む）
  - forge プラグインからの namespace 参照を更新
- **refactor**: 重複関数の統一とコード一貫性の改善

## [0.0.26] - 2026-03-22

### forge

- **refactor**: バグ隠蔽フォールバックを除去し YAML ユーティリティを統合
  - session_manager.py の `except Exception` バグ隠蔽ハンドラを削除
  - session_manager.py の YAML ユーティリティを yaml_utils.py に統合（約60行削除）
  - skill_monitor.py の YamlReader 自前パーサーを yaml_utils.parse_yaml に統合（約300行削除）
  - エラー握りつぶし箇所（4箇所）に stderr 警告を追加
  - 到達不能コード（IndexError キャッチ、デッドコード、不要ラッパー）を削除

## [0.0.25] - 2026-03-22

### forge

- **refactor**: バグ起因でしか発生しない例外に対する無用なフォールバックを全スクリプトから除去
  - `except Exception` を具体的な例外型（IOError, OSError, UnicodeDecodeError）に限定（migrate_doc_structure / resolve_doc_references / resolve_review_context / read_session）
  - skill_monitor.py の二重ファイル読み込みを排除し、content ベースの parse_yaml に変更
  - scan_version_targets.py から不要な ValueError catch を除去
- **refactor**: review SKILL.md の Codex 存在チェック二重化を解消（Phase 3 の exit code ハンドリングに一本化）
- **refactor**: fixer SKILL.md から到達不能なフォールバック手順を削除し session_dir を必須化
- **fix**: セッション削除保護機能を追加（in_progress セッションの誤削除防止）
- **fix**: バージョン管理スクリプトのコードレビュー指摘事項を修正
- **docs**: subagent diff review ステップを review Phase 5 に追加
- **docs**: parallel agent output contract 設計書を追加

## [0.0.24] - 2026-03-22

### forge

- **feat**: perspectives ベースのレビューアーキテクチャを実装（reviewer/evaluator を perspective ごとに並列起動）
  - review_criteria を5種別（requirement/design/plan/code/generic）に分割し `## Perspective:` セクションで観点を定義
  - reviewer を 1 perspective 単位処理に変更（並列起動はオーケストレーターが制御）
  - evaluator を perspective 並列起動対応。出力契約パターン導入（eval_*.json → orchestrator が一括マージ）
  - extract_review_findings.py を multi-file merge 対応（glob 収集・通し番号 ID・perspective タグ・重複除去）
  - write_refs.py を perspectives 必須フィールド対応（name/criteria_path/section/output_path バリデーション付き）
- **feat**: バージョン管理ワークフロー設計書を作成（setup-version-config / update-version の設計を文書化）
  - scan_version_ref_files 追加（ルート全テキストファイルからバージョン参照を自動検出）
  - filter ルールを設計書に明記（README/CLAUDE.md 等の複数 target ファイルで誤置換を防止）
  - .version-config.yaml に CLAUDE.md を sync_files として追加
- **feat**: clean-rules スキルを追加
- **refactor**: evaluation.yaml を廃止し plan.yaml に統合（recommendation/auto_fixable/reason フィールド追加）
  - write_evaluation.py とテストを削除
  - present-findings から evaluation.yaml 依存を除去
  - session_format.md から evaluation.yaml セクションを削除
- **refactor**: evaluator SKILL.md を強化（対象ファイル検証必須化、判定バイアス是正）
- **fix**: 設計書のパイプライン順序を実装と統一（reviewers → extract → evaluators）
- **fix**: 廃止済み evaluation.yaml / review_criteria_spec.md への参照を全設計書・スクリプト・テストから削除
- **fix**: UnicodeDecodeError ハンドリングを extract_review_findings.py / scan_version_targets.py / list_forge_docs.py に追加
- **fix**: update_plan.py に recommendation/auto_fixable/reason フィールド処理と --recommendation バリデーションを追加
- **fix**: review/SKILL.md にブランチ確認ステップを追加（ブランチ関連の対象指定時）

## [0.0.23] - 2026-03-16

### forge

- **refactor**: セッション YAML 操作を scripts/session/ パッケージに委譲（write_refs, write_evaluation, update_plan, read_session, yaml_utils）
- **refactor**: 単一 SKILL 専用スクリプトをスキルディレクトリへ移動（extract_review_findings → reviewer, calculate/update_version → bump, scan_version_targets → setup-version-config）
- **refactor**: doc_structure 関連スクリプトを scripts/doc_structure/ に整理（classify_dirs, resolve_doc_references, migrate_doc_structure）
- **fix**: extract_review_findings.py が見出し形式（`### 1. **問題名**`）の指摘をパースできない問題を修正
- **feat**: reviewer テンプレート（templates/review.md）を追加し、SKILL.md のプロンプトをテンプレート参照に変更
- **refactor**: start-requirements ワークフローをモード別ファイルに分離（interactive, reverse-engineering, from-figma）

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
