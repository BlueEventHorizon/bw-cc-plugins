# セッションディレクトリ ファイルフォーマット仕様

forge レビューパイプラインが使用するセッションワーキングディレクトリ（`.claude/.temp/{YYYYMMDD-HHmmss}-{random6}/`）内の全ファイルのスキーマ定義。

各 SKILL.md ではインラインでスキーマを定義せず、このドキュメントを参照すること。

---

## セッションディレクトリ構造

```
.claude/.temp/{YYYYMMDD-HHmmss}-{random6}/
├── session.yaml       # セッションメタデータ（review が作成）
├── refs.yaml          # 参照ファイルリスト（review が作成）
├── review.md          # レビュー結果（reviewer が書き出し）
├── plan.yaml          # 修正プランと進捗状態（reviewer が初期作成）
├── evaluation.yaml    # evaluator の判定結果（evaluator が作成）
└── report.html        # 可視化レポート（show-report が生成）
```

**ライフサイクル:**
- Phase 1.5 開始: `review` がディレクトリ作成 + `session.yaml` / `refs.yaml` を書き出す
- Phase 4 完了: `review` が `rm -rf {session_dir}` で削除する
- セッション中断: ディレクトリが残存する（次回の `present-findings` 呼び出し時に再開を提案）

---

## session.yaml

セッションのメタデータ。`review` が Phase 1.5 で作成し、フロー全体を通じて更新する。

### スキーマ

| フィールド | 型 | 必須 | 説明 |
|------------|----|------|------|
| `review_type` | string | 必須 | レビュー種別（後述の許容値参照） |
| `engine` | string | 必須 | レビューエンジン（後述の許容値参照） |
| `auto_count` | integer | 必須 | 自動修正サイクル数。`0` = 対話モード |
| `current_cycle` | integer | 必須 | 現在のサイクル番号。初期値 `0` |
| `started_at` | string | 必須 | 開始日時（ISO 8601 形式） |
| `last_updated` | string | 必須 | 最終更新日時（ISO 8601 形式） |
| `status` | string | 必須 | セッション状態（後述の許容値参照） |

### 許容値

**`review_type`:** `code` / `requirement` / `design` / `plan` / `generic`

**`engine`:** `codex` / `claude`

**`status`:** `in_progress` / `completed`

### 例

```yaml
review_type: code
engine: codex
auto_count: 0
current_cycle: 0
started_at: "2026-03-09T18:30:00Z"
last_updated: "2026-03-09T18:30:00Z"
status: in_progress
```

### 読み書き

| スキル | 操作 | タイミング |
|--------|------|-----------|
| `review` | Write（作成） | Phase 1.5 Step 7 |
| `review` | Write（`status: completed` に更新） | Phase 4 完了時 |
| `show-report` | Read | HTML 生成時 |

---

## refs.yaml

レビューパイプライン全体で共有する参照ファイルリスト。`review` が Phase 1.5 で作成し、以降の全スキルはここからファイルパスを取得する（プロンプト経由の受け渡しは行わない）。

### スキーマ

| フィールド | 型 | 必須 | 説明 |
|------------|----|------|------|
| `target_files` | string[] | 必須 | レビュー対象ファイルパス一覧 |
| `reference_docs` | object[] | 必須 | 参考文書リスト（`path` フィールドを持つオブジェクト） |
| `review_criteria_path` | string | 必須 | レビュー観点ファイルのパス |
| `related_code` | object[] | 任意 | 関連コードリスト（後述のフィールド参照） |

**`reference_docs` オブジェクト:**

| フィールド | 型 | 必須 | 説明 |
|------------|----|------|------|
| `path` | string | 必須 | ファイルパス |

**`related_code` オブジェクト:**

| フィールド | 型 | 必須 | 説明 |
|------------|----|------|------|
| `path` | string | 必須 | ファイルパス |
| `reason` | string | 必須 | 関連性の説明（1行） |
| `lines` | string | 任意 | 関連する行範囲（例: `"1-30"`）。探索時に特定できた場合のみ記載 |

### 例

```yaml
target_files:
  - plugins/forge/skills/review/SKILL.md
  - plugins/forge/skills/reviewer/SKILL.md

reference_docs:
  - path: docs/rules/skill_authoring_notes.md
  - path: plugins/forge/defaults/review_criteria.md

review_criteria_path: plugins/forge/defaults/review_criteria.md

related_code:
  - path: plugins/forge/skills/reviewer/SKILL.md
    reason: 同種 AI 専用スキルの frontmatter 参考
    lines: "1-30"
  - path: plugins/forge/skills/evaluator/SKILL.md
    reason: 同種 AI 専用スキルの frontmatter 参考
```

### 読み書き

| スキル | 操作 | タイミング |
|--------|------|-----------|
| `review` | Write（作成） | Phase 1.5 Step 7 |
| `reviewer` | Read | Phase 1（参考文書取得） |
| `evaluator` | Read | Step 1（データ読み込み） |
| `fixer` | Read | Step 2（参考文書準備）`session_dir` が渡された場合 |

---

## review.md

`reviewer` が書き出すレビュー結果ファイル。Markdown 形式（YAML フロントマターなし）。

複数サイクル（`--auto N`）では上書きする（最新サイクルのみ保持）。

### フォーマット

```markdown
### 🔴致命的問題
1. **[問題名]**: [具体的な説明]
   - 箇所: [ファイル名:行番号 / セクション名]
   - 参照: [関連ルール/要件定義書]（任意）
   - 修正案: [具体的な修正提案]

### 🟡品質問題
1. **[問題名]**: [具体的な説明]
   - 箇所: [ファイル名:行番号 / セクション名]

### 🟢改善提案
1. **[提案名]**: [具体的な説明]

### サマリー
- 🔴致命的: X件
- 🟡品質: X件
- 🟢改善: X件
```

### 読み書き

| スキル | 操作 | タイミング |
|--------|------|-----------|
| `reviewer` | Write（作成 / 上書き） | Phase 2 レビュー完了後 |
| `evaluator` | Read | Step 1（指摘事項取得） |
| `present-findings` | Read | Step 0（セッション復元） |
| `show-report` | Read | HTML 生成時（オプション） |

---

## evaluation.yaml

`evaluator` が各指摘事項を吟味した結果。`--auto` / `--auto-critical` モードでは AI が修正判定を行い、`--interactive` モードでは AI 推奨として記録する（最終判断は人間）。

### スキーマ

| フィールド | 型 | 必須 | 説明 |
|------------|----|------|------|
| `cycle` | integer | 必須 | サイクル番号（1 始まり） |
| `items` | object[] | 必須 | 指摘事項ごとの判定結果リスト |

**`items` オブジェクト:**

| フィールド | 型 | 必須 | 説明 |
|------------|----|------|------|
| `id` | integer | 必須 | plan.yaml の `id` と対応する連番 |
| `severity` | string | 必須 | 重大度（後述の許容値参照） |
| `title` | string | 必須 | 指摘事項のタイトル |
| `decision` | string | 必須 | 判定結果（後述の許容値参照） |
| `reason` | string | 必須 | 判定理由 |

### 許容値

**`severity`:** `critical` / `major` / `minor`

**`decision`:** `fix` / `skip` / `needs_review`

### 例

```yaml
cycle: 1
items:
  - id: 1
    severity: critical
    title: "help と review のコマンド仕様不一致"
    decision: fix
    reason: "明確な仕様不一致、副作用なし"
  - id: 2
    severity: major
    title: "frontmatter 必須項目不足"
    decision: fix
    reason: "規約違反。修正が一意で副作用なし"
  - id: 3
    severity: major
    title: "設計意図が不明瞭な処理"
    decision: needs_review
    reason: "意図的な設計の可能性があり、確認が必要"
  - id: 4
    severity: minor
    title: "コメントの表記揺れ"
    decision: skip
    reason: "既存コードとの一貫性を保つため変更不要"
```

### 読み書き

| スキル | 操作 | タイミング |
|--------|------|-----------|
| `evaluator` | Write（作成） | Step 3 |
| `fixer` | Read | 修正対象の確認（`--batch` モード） |
| `present-findings` | Read | Step 0（AI 推奨列の表示） |
| `show-report` | Read | HTML 生成時（オプション） |

---

## plan.yaml

修正プランと各指摘事項の進捗状態。`reviewer` が初期作成し、`evaluator` / `present-findings` / `fixer` が更新していく。セッション再開の際はここの `status: pending` 項目から処理を再開する。

### スキーマ

| フィールド | 型 | 必須 | 説明 |
|------------|----|------|------|
| `items` | object[] | 必須 | 指摘事項ごとの修正状態リスト |

**`items` オブジェクト:**

| フィールド | 型 | 必須 | 説明 |
|------------|----|------|------|
| `id` | integer | 必須 | 1 始まりの連番。evaluation.yaml の `id` と対応 |
| `severity` | string | 必須 | 重大度（後述の許容値参照） |
| `title` | string | 必須 | 指摘事項のタイトル |
| `status` | string | 必須 | 進捗状態（後述の許容値参照） |
| `fixed_at` | string | 任意 | 修正完了日時（ISO 8601 形式）。`status: fixed` の場合に記録 |
| `files_modified` | string[] | 任意 | 修正したファイルパスリスト。`status: fixed` の場合に記録 |
| `skip_reason` | string | 任意 | スキップ理由。`status: skipped` の場合に記録 |

### 許容値

**`severity`:** `critical` / `major` / `minor`

**`status`:**

| 値 | 意味 | 設定者 |
|----|------|--------|
| `pending` | 未処理（初期値） | `reviewer` |
| `in_progress` | 処理中 | `present-findings`（ユーザーが修正を選択した瞬間） |
| `fixed` | 修正完了 | `fixer` |
| `skipped` | スキップ（false positive / 設計意図等） | `evaluator`（--auto時）/ `present-findings`（対話時） |
| `needs_review` | 要確認（判断困難） | `evaluator`（--auto時）/ `present-findings`（対話時） |

### 例

```yaml
items:
  - id: 1
    severity: critical
    title: "help と review のコマンド仕様不一致"
    status: fixed
    fixed_at: "2026-03-09T18:35:00Z"
    files_modified:
      - plugins/forge/skills/help/SKILL.md
    skip_reason: ""
  - id: 2
    severity: major
    title: "frontmatter 必須項目不足"
    status: pending
    fixed_at: ""
    files_modified: []
    skip_reason: ""
  - id: 3
    severity: major
    title: "設計意図が不明瞭な処理"
    status: needs_review
    fixed_at: ""
    files_modified: []
    skip_reason: ""
  - id: 4
    severity: minor
    title: "コメントの表記揺れ"
    status: skipped
    fixed_at: ""
    files_modified: []
    skip_reason: "既存コードとの一貫性を保つため変更不要"
```

### 読み書き

| スキル | 操作 | タイミング |
|--------|------|-----------|
| `reviewer` | Write（初期作成 — 全件 `pending`） | Phase 2 完了後 |
| `evaluator` | Write（`--auto` / `--auto-critical` モードで `status` 更新） | Step 4 |
| `present-findings` | Read / Write（ユーザー判断後に `status` 更新） | Step 3.5 |
| `fixer` | Write（`status: fixed` + `fixed_at` + `files_modified` を更新） | 修正完了後 |
| `show-report` | Read | HTML 生成時 |

---

## 付記: `id` の整合性

`review.md` の指摘事項 → `plan.yaml` の `id` → `evaluation.yaml` の `id` は同一の連番で対応している。`reviewer` が `plan.yaml` を初期作成する際に採番し、`evaluator` はその `id` を参照して `evaluation.yaml` を作成する。
