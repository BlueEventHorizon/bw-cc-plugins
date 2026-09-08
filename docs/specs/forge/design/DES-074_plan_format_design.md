# 計画書 デフォルトフォーマット

プロジェクト固有の `plan_format.md` が見つからない場合に使用する汎用フォーマット。

作成原則: [plan_principles_spec.md](../../../../plugins/forge/docs/plan_principles_spec.md)

本文書は script（`write_plan.py` / `select_tasks.py` / `update_plan_status.py` / `build_task_context.py`）の実装契約を定義する開発文書である（配布物ではない）。AI はランタイムでこの文書を読まない。

要件: [REQ-024 実装計画書 要件定義書](../requirements/REQ-024_implementation_plan_spec.md)

## フォーマット選定理由

計画書は JSON を使用する。理由:

- タスクID・優先度・依存関係・ステータス等、全てが構造化データ
- `start-implement` が機械的にパース・更新する必要がある（タスク選択・依存チェック・完了更新）
- Markdown テーブルは AI によるパースが不確実（列幅崩れ・`<br>` 改行等）
- 生成・読取・検証を script（標準ライブラリ `json`）に一元化することで、AI がファイル形式を意識する必要をなくす

要件定義書・設計書は mermaid や自由記述を含むため Markdown を維持する。

---

## 追加 feature の計画書（frontmatter を付与しない）

計画書には frontmatter を付与しない。追加 feature に属する計画書かどうかは、`requirements_traceability` が参照する要件定義書の `feature_type: temporary-feature` frontmatter で辿って判定する。計画書自体に重複してマーカーを持たせる必要はない。

トップレベルキーは `requirements_traceability` / `design_traceability` / `tasks` / `revision_history` のみ許容する（それ以外の追加は 🟡 major 違反）。

frontmatter 定義: [frontmatter_format.md](../../../../plugins/forge/docs/frontmatter_format.md) §1.3
判定基準・現在の仕様の所在・merge 手順: [additive_development_spec.md](../../../../plugins/forge/docs/additive_development_spec.md) §1 適用条件

---

## JSON スキーマ

ファイル名: `{feature}_plan.json`

```json
{
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

---

## build_task_context.py の並行状態文書の分類契約

要件: [REQ-025 差分開発の仕組み 要件定義書](../requirements/REQ-025_additive_development_spec.md) FNC-003（実装者への伝達）・FNC-005（識別できない場合の扱い）

### 対象文書

候補 JSON（`task_context_input.json` テンプレート）の `required_reading.requirement_docs` と `required_reading.design_docs` に列挙された各文書を対象とする。実装者が読む文書がそのまま対象であり、この一覧の外にある文書を分類しない。

**設計書を対象に含めるのは、設計書も並行状態の識別子を持つためである**（[frontmatter_format.md](../../../../plugins/forge/docs/frontmatter_format.md) §1.2）。実装者は設計書をタスクの直接根拠として最優先で読む（[task_execution_spec.md](../../../../plugins/forge/skills/start-implement/docs/task_execution_spec.md) Step 2.1）。要件定義書だけを分類すると、旧設計書が現在の設計として読まれる経路が残る。

`required_reading` の他のフィールド（`strategy_doc` / `rule_docs` / `reference_code` / `additional`）は対象にしない。並行状態は要件定義書・設計書に付与される識別子であり（REQ-025 FNC-001）、他の種別の文書は識別子を持たない。

対象文書を読めない場合は解析失敗として扱う（後述）。読めないことを「並行状態にない」と同一視しない（REQ-025 FNC-005）。

### frontmatter の解析

文書先頭の YAML frontmatter（`---` で囲まれたブロック）から `feature_type` の値を取り出す。標準ライブラリのみで実装する（PyYAML 禁止）。

判定は次の 3 値のいずれかになる。

| 判定           | 条件                                                                           |
| -------------- | ------------------------------------------------------------------------------ |
| 並行状態にある | frontmatter に `feature_type` が 1 回だけ現れ、値が `temporary-feature` である |
| 並行状態にない | frontmatter を持たない、または frontmatter に `feature_type` が現れない        |
| 解析失敗       | 上記のいずれにも当てはまらない（下記の列挙）                                   |

解析失敗として扱うもの:

- 対象文書を読めない
- 先頭の `---` に対応する終端の `---` が無い
- `feature_type` が複数回現れ、値を一意に決められない
- `feature_type` の値が `temporary-feature` 以外である（[frontmatter_format.md](../../../../plugins/forge/docs/frontmatter_format.md) §1 は他の値を定義していない）

**キーの順序で判定結果が変わってはならない [MANDATORY]**。`frontmatter_format.md` §2.3 は `feature_type` と `doc_status` の併記を許可し、キーの順序を制約していない。`feature_note` はリスト値を持つため後続行がインデントされるが、これも `feature_type` の抽出に影響してはならない。規約が許可している書式のいずれかで解析が失敗する実装は、この契約に違反する。

解析失敗は「並行状態にない」と区別する（REQ-025 FNC-005）。失敗した場合はタスクコンテキストの生成を失敗させ、対象パスと理由を `errors` に載せる。並行状態にあるかを判定できないまま実装へ進むと、実装者は旧仕様に従って実装しうる。

### 分類結果の伝達形式

`implementation_instructions` への文字列連結ではなく、専用の構造化フィールド `spec_authority` を `tasks/{task_id}.json` のトップレベルに追加する。値は並行状態にある文書のパスの配列とする:

```json
{
  "spec_authority": [
    "docs/specs/{feature}/requirements/REQ-xxx_{name}.md",
    "docs/specs/{feature}/design/DES-xxx_{name}.md"
  ]
}
```

該当なしの場合は `spec_authority: []` とする（`null` にしない。`required_reading` 等の既存フィールドの空値表現と統一する）。

**行動の指示を値に含めない**（REQ-025 FNC-002）。実装者が取るべき行動は executor guide が定義する。ここで運ぶのは「どの文書が並行状態にあるか」という分類結果のみである。

`scope_in` / `scope_out` は拡張しない（並行状態は別軸の情報であり、タスクのスコープ定義とは独立する）。

### executor による受領

[task_execution_spec.md](../../../../plugins/forge/skills/start-implement/docs/task_execution_spec.md)（executor guide）が次を持つ:

- Step 1「タスク情報の受領」の受領フィールド一覧に `spec_authority` を含める
- Step 3「実装」に、`spec_authority` に挙がった文書が対象範囲の現在の仕様であり、当該範囲について旧仕様の記述を実装の根拠にしないことを定める（REQ-025 FNC-004）
