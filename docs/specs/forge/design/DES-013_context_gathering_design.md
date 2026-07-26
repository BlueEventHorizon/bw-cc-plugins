# DES-013 コンテキスト収集タスク仕様

## メタデータ

| 項目     | 値                                                              |
| -------- | --------------------------------------------------------------- |
| 設計ID   | DES-013                                                         |
| 関連設計 | DES-010 (DES-010_create_skills_orchestrator_design.md), DES-022 |
| 作成日   | 2026-03-14                                                      |
| 対象     | start-requirements, start-design, start-plan, start-implement   |

---

## 1. 概要

forge の create-\* スキルおよび start-implement スキルが使用するコンテキスト収集タスクの仕様を定義する。

コンテキスト収集は、各 SKILL.md（またはモード別ワークフロー文書）にインラインで定義した prompt で汎用 agent を **Agent ツールで並列起動**し、各 agent の **return value**（markdown bullet list）を main AI コンテキストに直接保持する方式で行う（DES-022 並列 agent 出力契約）。

- 文書検索は agent 内から `/forge:query-db-specs` / `/forge:query-db-rules` スキルに委譲する（検索ロジックを収集 agent に持たせない）
- セッションディレクトリ・中間ファイルは使わない（セッション機構は廃止済み）
- agent がエラー終了した場合は該当カテゴリなしで後続工程に進む（fail-open）

---

## 2. タスク一覧

コンテキスト収集 agent が実行するタスクは以下の 3 種類:

| タスク名       | 出力（return value）               | 検索手段                 | 説明                                     |
| -------------- | ---------------------------------- | ------------------------ | ---------------------------------------- |
| 仕様書調査     | `## 仕様書 (N 件)` + bullet list   | `/forge:query-db-specs`  | 要件定義書・設計書・計画書を特定         |
| 実装ルール調査 | `## ルール (N 件)` + bullet list   | `/forge:query-db-rules`  | プロジェクト固有の開発ルール・規約を特定 |
| 既存コード調査 | `## 既存実装 (N 件)` + bullet list | `Grep` / `Glob` 直接探索 | 関連ソースコード・テスト・類似実装を特定 |

bullet list の各行は `` `path` — 関連理由を 1 行 `` の形式とする。見出しの文言・件数上限は各 SKILL.md の prompt テンプレートが確定する。

---

## 3. スキル別タスク適用マトリクス

各スキルが各タスクをどの条件で実行するかを定義する。

| スキル             | 仕様書調査           | 実装ルール調査 | 既存コード調査                     |
| ------------------ | -------------------- | -------------- | ---------------------------------- |
| start-requirements | `--add` モード時のみ | 常時           | `reverse-engineering` モード時のみ |
| start-design       | 常時                 | 常時           | 常時                               |
| start-plan         | 常時                 | 常時           | 不要                               |
| start-implement    | 不要（直接特定）     | 常時           | 常時                               |

> **start-requirements の設計判断**: interactive モード（新規）ではコンテキスト収集は最小限（rules のみ）。
> 要件定義は「何を実現するか」を定義する工程であり、既存実装への過度な依存は避ける。
>
> **start-plan の設計判断**: 計画書は実装ファイルを参照しないため、既存コード調査は不要。
>
> **start-implement の設計判断**: 仕様書（設計書・要件定義書）は計画書のトレーサビリティマトリクスと
> タスクの `required_reading` から直接特定する。Issue/Task 確認も計画書から既に把握済みのため agent に委ねない。

---

## 4. スキル別 agent 構成

| スキル             | 並列起動する agent                               | 定義位置                                 |
| ------------------ | ------------------------------------------------ | ---------------------------------------- |
| start-requirements | モードに応じて rules / specs / code              | モード別ワークフロー文書（`docs/` 配下） |
| start-design       | specs agent + rules agent + code agent（3 並列） | SKILL.md Phase 1                         |
| start-plan         | specs agent + rules agent（2 並列）              | SKILL.md Phase 1                         |
| start-implement    | rules agent + code agent（2 並列）               | SKILL.md Phase 3.1                       |

---

## 5. agent への指示

各 agent への指示は、SKILL.md にインラインで記述した prompt テンプレートで渡す。テンプレートには以下を含める:

1. **検索目的**: Feature 名・作業種別（設計 / 計画 / 実装等）を埋め込んだ 1 行の目的文
2. **検索手段**: 呼び出す query スキル（`/forge:query-db-specs` / `/forge:query-db-rules`）または `Grep` / `Glob` の探索手順
3. **出力契約**: return value の markdown 形式（見出し + bullet list、件数上限）

セッションディレクトリや外部仕様書パスは渡さない。agent は prompt だけで自己完結して動作する（REQ-001 FNC-003）。
