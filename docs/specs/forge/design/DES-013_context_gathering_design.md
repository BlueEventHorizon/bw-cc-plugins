# DES-013 コンテキスト収集タスク仕様

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

start-design / start-plan / start-requirements の適用マトリクス・agent 構成は [DES-010](DES-010_create_skills_orchestrator_design.md) §3〜§4 を正本とする。`start-implement` は DES-010 の対象外（同 §1 に明記）であるため、本文書ではこのスキルの分のみを扱う。

### 3.1 start-implement のタスク適用

| スキル          | 仕様書調査       | 実装ルール調査 | 既存コード調査 |
| --------------- | ---------------- | -------------- | -------------- |
| start-implement | 不要（直接特定） | 常時           | 常時           |

> **設計判断**: 仕様書（設計書・要件定義書）は計画書のトレーサビリティマトリクスとタスクの `required_reading` から直接特定する。Issue/Task 確認も計画書から既に把握済みのため agent に委ねない。

---

### 3.2 start-implement の agent 構成

| スキル          | 並列起動する agent                 | 定義位置           |
| --------------- | ---------------------------------- | ------------------ |
| start-implement | rules agent + code agent（2 並列） | SKILL.md Phase 3.1 |

---

## 4. agent への指示

各 agent への指示は「検索目的・検索手段・出力契約」の3要素で構成する prompt テンプレートで渡す。テンプレートの形式は [DES-010](DES-010_create_skills_orchestrator_design.md) §3.3 を正本とする。

セッションディレクトリや外部仕様書パスは渡さない。agent は prompt だけで自己完結して動作する（REQ-001 FNC-003）。
