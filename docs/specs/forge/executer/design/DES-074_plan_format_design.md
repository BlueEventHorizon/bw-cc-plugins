# 計画書 デフォルトフォーマット

プロジェクト固有の `plan_format.md` が見つからない場合に使用する汎用フォーマット。

作成原則: [plan_principles_spec.md](plan_principles_spec.md)

本文書は script（`write_plan.py` / `select_tasks.py` / `update_plan_status.py` / `build_task_context.py`）の実装契約を定義する開発文書である（配布物ではない）。AI はランタイムでこの文書を読まない（REQ-020 FNC-007）。

## フォーマット選定理由（FNC-005 改訂）

計画書は JSON を使用する。理由:

- タスクID・優先度・依存関係・ステータス等、全てが構造化データ
- `start-implement` が機械的にパース・更新する必要がある（タスク選択・依存チェック・完了更新）
- Markdown テーブルは AI によるパースが不確実（列幅崩れ・`<br>` 改行等）
- 生成・読取・検証を script（標準ライブラリ `json`）に一元化することで、AI がファイル形式を意識する必要をなくす（REQ-020）

要件定義書・設計書は mermaid や自由記述を含むため Markdown を維持する。

---

## 追加 feature 用 frontmatter

**追加 feature に属する計画書（判定は [additive_development_spec.md](additive_development_spec.md) §1）を作成するときに限り**、`_feature_meta` 予約キーを付与すること。判定は変更の実質（分離管理価値・旧仕様との衝突リスク）で行い、文書操作の形式（新規作成か追記か）では判定しない。分離して管理する価値のない軽微な追記・修正、および main の初期立ち上げ時は含めない。

トップレベルキーは `requirements_traceability` / `design_traceability` / `tasks` / `revision_history` / `_feature_meta` のみ許容する（`_feature_meta` 以外の追加は 🟡 major 違反）。

`_feature_meta` には `type: "temporary-feature-plan"` と、①正本は対応する追加 feature 要件定義書（REQ-xxx）であること②実装済みのため実装完了後に破棄される予定であること、の2点を notes として記載する。正式な文言は [additive_development_spec.md](additive_development_spec.md) §6-3 を参照。

正式定義（全文書種別の集約 SoT）・判定基準・矛盾時の優先度・merge 手順: [additive_development_spec.md](additive_development_spec.md)（§6 frontmatter 定義一覧 / §1 適用条件）

---

## JSON スキーマ

ファイル名: `{feature}_plan.json`

```json
{
  "_feature_meta": {
    "type": "temporary-feature-plan",
    "notes": ["追加 feature の場合のみ、この予約キーを含める"]
  },
  "requirements_traceability": [
    {
      "requirement_id": "REQ-001",
      "title": "要件のタイトル",
      "design_id": "DES-001",
      "status": "pending"
    }
  ],
  "design_traceability": [
    {
      "design_id": "DES-001",
      "title": "設計書のタイトル",
      "requirement_ids": ["REQ-001"],
      "task_ids": ["TASK-001", "TASK-002"]
    }
  ],
  "tasks": [
    {
      "task_id": "TASK-001",
      "title": "タスクのタイトル",
      "priority": 90,
      "status": "pending",
      "design_id": "DES-001",
      "depends_on": [],
      "group_id": null,
      "build_check": "per_task",
      "description": ["やるべきこと 1", "やるべきこと 2", "やるべきこと 3"],
      "acceptance_criteria": "受け入れ基準の記述",
      "required_reading": ["path/to/design.md", "path/to/rule.md"]
    }
  ],
  "revision_history": [{ "date": "2026-03-15", "content": "初版作成" }]
}
```

---

## フィールド定義

### requirements_traceability

| フィールド     | 型     | 必須 | 説明                    |
| -------------- | ------ | ---- | ----------------------- |
| requirement_id | string | Yes  | 要件ID                  |
| title          | string | Yes  | 要件のタイトル          |
| design_id      | string | Yes  | 対応する設計ID          |
| status         | enum   | Yes  | `pending` / `completed` |

### design_traceability

| フィールド      | 型       | 必須 | 説明                    |
| --------------- | -------- | ---- | ----------------------- |
| design_id       | string   | Yes  | 設計ID                  |
| title           | string   | Yes  | 設計書のタイトル        |
| requirement_ids | string[] | Yes  | 対応する要件ID の配列   |
| task_ids        | string[] | Yes  | 対応するタスクID の配列 |

### tasks

| フィールド          | 型          | 必須 | 説明                                      |
| ------------------- | ----------- | ---- | ----------------------------------------- |
| task_id             | string      | Yes  | タスクID（`TASK-001` 形式）               |
| title               | string      | Yes  | タスクのタイトル                          |
| priority            | integer     | Yes  | 優先度 1-99                               |
| status              | enum        | Yes  | `pending` / `in_progress` / `completed`   |
| design_id           | string/null | Yes  | 対応する設計ID。なければ `null`           |
| depends_on          | string[]    | Yes  | 依存するタスクID の配列。なければ `[]`    |
| group_id            | string/null | Yes  | グループID。独立タスクは `null`           |
| build_check         | enum        | Yes  | `per_task` / `skip` / `on_group_complete` |
| description         | string[]    | Yes  | やるべき内容の配列（1項目 = 1行）         |
| acceptance_criteria | string/null | Yes  | 受け入れ基準。なければ `null`             |
| required_reading    | string[]    | Yes  | 必読文書パスの配列。なければ `[]`         |

### revision_history

| フィールド | 型     | 必須 | 説明               |
| ---------- | ------ | ---- | ------------------ |
| date       | string | Yes  | 日付（YYYY-MM-DD） |
| content    | string | Yes  | 改定内容           |

---

## status の遷移

```
pending → in_progress → completed
```

- `pending`: 未着手
- `in_progress`: `start-implement` が実行中
- `completed`: タスク完了（`start-implement` が更新）

---

## 優先度の目安

| 範囲  | 意味                                               |
| ----- | -------------------------------------------------- |
| 70-99 | 高: コアビジネスロジック・共通基盤・ブロッカー解消 |
| 40-69 | 中: 主要機能                                       |
| 1-39  | 低: UI・補助機能                                   |
