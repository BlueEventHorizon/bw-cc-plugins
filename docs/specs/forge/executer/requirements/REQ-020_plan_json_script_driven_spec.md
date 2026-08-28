---
feature_type: temporary-feature
feature_note:
  - この文書が正。旧仕様（ソースコード・設計書・計画書）と矛盾する場合はこの文書を優先して判断・実装すること。
  - 旧仕様ファイルは本 feature 実装完了まで書き換えない。新規ファイル / 新規ディレクトリとして切り出すこと。
  - 本 feature 実装完了後、旧仕様との齟齬を解消する（merge）。merge は意味の統合であり、文書の物理的な結合ではない。
  - 旧仕様と同一スコープの内容は旧仕様側へ移す。スコープが異なる内容は分離したまま維持し、この文書を残す。
---

# REQ-020 計画書の JSON 化・script 駆動アーキテクチャ 要件定義書

## 1. 背景

計画書（`plan.yaml`）の生成・読取・状態更新は、現状すべて AI が計画書ファイルを直接 Read/Write/Edit することで行われている。この方式には以下の課題がある。

- AI が計画書ファイルのフォーマット（[DES-074_plan_format_design.md](../design/DES-074_plan_format_design.md) のスキーマ）を毎回意識しながら手作業で YAML テキストを組み立てる必要があり、書き崩れ・二重管理のリスクがある
- 計画書の一部（実行対象タスク）を抽出して executor へ渡す既存の仕組み（`task_context_contract.py`）が PyYAML に依存しており、CI 環境へのインストール漏れが検知されずに残っていた

計画書を JSON 化し、生成・読取・タスク選択・依存関係判定・状態更新をすべて script が担う構成へ移行することで、AI がファイル形式そのものを意識する必要をなくし、外部依存（PyYAML）を排除する。

## 2. 前提条件

- 本要件は Issue #25（plan.yaml → plan.json 全面 script 化）のトリアージにより、要件は確定・設計判断は残余ありと判定され、差分 feature `executer` として起票された
- 既存要件 REQ-001 FNC-005 は「計画書には YAML を使う」と明記しており、本要件はこの記述と矛盾する。実装完了後、REQ-001 との齟齬を merge で解消する
- 対象システムの性質: forge プラグイン内部の計画書操作アーキテクチャであり、本番運用・外部公開・個人情報等のデータ保護のいずれにも該当しない内部 CLI ツール相当のスコープである

## 3. 要件一覧

### FNC-001: 計画書の JSON 形式化

計画書は JSON 形式で記録される。実装完了後にユーザーの選択により削除されうる一時的（ephemeral）な作業ファイルであり、恒久保存を目的としない（削除するか残すかは `start-implement` の完了処理でユーザーに確認する。自動削除はしない）。フィールド構造（`requirements_traceability` / `design_traceability` / `tasks` / `revision_history`）は現行 [DES-074_plan_format_design.md](../design/DES-074_plan_format_design.md) のスキーマを踏襲する。ファイル名は現行の `{feature}_plan.yaml` 命名パターンを踏襲し、拡張子のみ `.json` に変更する（`{feature}_plan.json`）。

### FNC-002: 計画書生成の script 経由化

AI はタスクの意味内容（title・description・acceptance_criteria 等）を決定するが、計画書ファイルへの書き込みは script が行う。

### FNC-003: タスク選択・依存関係判定の script 経由化

実行可能タスクの選定（`status: pending` かつ `depends_on` 全件が `completed`）は script が判定し、AI は判定結果を受け取るだけになる。

### FNC-004: タスクステータス更新の script 経由化

タスク完了後の `status` 更新・トレーサビリティ更新は script が行う。

### FNC-005: タスクコンテキストファイルの JSON 化

executor へ渡すタスクコンテキストファイルは JSON 形式（`tasks/{task_id}.json`）で生成され、PyYAML に依存しない。

### FNC-006: 計画書は追加 feature の frontmatter を持たない

計画書には追加 feature 用の frontmatter・予約キーを一切付与しない。追加 feature に属する計画書かどうかは、`requirements_traceability` が参照する要件定義書の `feature_type: temporary-feature` frontmatter を辿って判定する（[frontmatter_format.md](../../../../../plugins/forge/docs/frontmatter_format.md) §1.3）。計画書自体に重複してマーカーを持たせないため、[DES-074_plan_format_design.md](../design/DES-074_plan_format_design.md) のトップレベルキー制限（`requirements_traceability` / `design_traceability` / `tasks` / `revision_history` の 4 つのみ）に例外を設けない。

### FNC-007: AI のスキーマ非依存性（範囲限定）

AI は計画書操作 script との入出力契約（script へ渡す候補データのフィールド名）を知る必要があるが、計画書ファイルの形式そのもの（JSON 構造・キー配置・シリアライズ方式）を知る必要はない。

## 4. 未確定事項

該当なし。
