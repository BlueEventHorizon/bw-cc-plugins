# オーケストレータ セッション通信プロトコル設計

> 対象: forge プラグイン全オーケストレータスキル
> 要件: `docs/specs/forge/requirement/orchestrator_pattern.md`

---

## 1. 概要

forge のオーケストレータスキルが subagent / agent と通信する際の
共通プロトコルを定義する。セッションディレクトリをデータバスとして使用し、
ファイル経由でデータを受け渡す。

### 設計の背景

`twinkling-popping-kahan.md` で review パイプライン固有のセッションディレクトリを設計した。
本設計書はその**共通部分を抽出・汎用化**し、全オーケストレータで使える構造にする。

review 固有の設計（review.md, plan.yaml, evaluation.yaml 等）は
`twinkling-popping-kahan.md` に残し、本設計書を参照する形とする。

---

## 2. セッションディレクトリ構造

### パス

```
.claude/.temp/{YYYYMMDD-HHmmss}-{random6}/
```

例: `.claude/.temp/20260312-183000-a3f7b2/`

- タイムスタンプ: 人間可読・ソート可能
- 6文字ランダム hex: 同一秒に複数起動しても衝突しない
- `.gitignore` に `.claude/.temp/` を追加

### 共通ディレクトリレイアウト

```
.claude/.temp/{session}/
├── session.yaml           # セッションメタデータ（共通・必須）
├── refs/                  # 参照ファイル（コンテキスト収集 agent の出力）
│   ├── specs.yaml         # 仕様書検索 agent の結果
│   ├── rules.yaml         # ルール検索 agent の結果
│   ├── prs.yaml           # PR検索 agent の結果（任意）
│   └── code.yaml          # コード探索 agent の結果
└── [スキル固有ファイル]   # 各スキルが自由に追加
```

### スキル固有ファイルの例

| スキル | 追加ファイル |
|--------|-------------|
| review | `review.md`, `plan.yaml`, `evaluation.yaml`, `report.html` |
| create-design | `design_draft.md` |
| create-plan | `plan_draft.md` |
| create-requirements | `requirements_draft.md` |

スキル固有ファイルのスキーマは各スキルの設計書で定義する。

---

## 3. session.yaml — 共通メタデータ

```yaml
# === 共通フィールド（全オーケストレータ必須）===
skill: review                      # 起動スキル名
started_at: "2026-03-12T18:30:00Z"
last_updated: "2026-03-12T18:35:00Z"
status: in_progress                # in_progress | completed

# === スキル固有フィールド（各スキルが自由に追加）===
# 例: review の場合
review_type: code
engine: codex
auto_count: 0
current_cycle: 0
```

### 共通フィールド定義

| フィールド | 型 | 必須 | 説明 |
|-----------|------|------|------|
| skill | string | ○ | 起動スキル名（review, create-design 等）|
| started_at | datetime | ○ | セッション開始時刻（ISO 8601）|
| last_updated | datetime | ○ | 最終更新時刻（ISO 8601）|
| status | enum | ○ | `in_progress` / `completed` |

### ライフサイクル

| タイミング | 操作 |
|------------|------|
| スキル開始時 | オーケストレータがディレクトリ作成 + `session.yaml` 初期化 |
| 正常完了時 | オーケストレータがディレクトリを削除 |
| セッション中断 | ディレクトリが残存（次回起動時に検出・再開提案）|

---

## 4. refs/ — 参照ファイルディレクトリ

### 設計原則

- 各コンテキスト収集 agent が**独立して** refs/{category}.yaml を書き込む
- ファイルが分かれているため**並列実行でファイル競合が起きない**
- オーケストレータが refs/ 内の全ファイルを読み込んで次の agent に渡す

### 共通スキーマ

全ての refs/{category}.yaml は同一スキーマに従う:

```yaml
source: query-specs               # 取得手段の識別子
query: "login feature design"     # 検索に使用したクエリ（デバッグ用）
documents:
  - path: specs/requirements/app_overview.md
    reason: "アプリ全体の要件定義"
  - path: specs/design/login_screen_design.md
    reason: "ログイン画面の設計仕様"
    lines: "10-50"                 # 関連する行範囲（任意）
```

### フィールド定義

| フィールド | 型 | 必須 | 説明 |
|-----------|------|------|------|
| source | string | ○ | 取得手段（`query-specs`, `query-rules`, `gh-pr-search`, `code-exploration`, `doc_structure_fallback`）|
| query | string | - | 検索クエリ（デバッグ・再現用）|
| documents | array | ○ | 発見した参照文書のリスト |
| documents[].path | string | ○ | プロジェクトルートからの相対パス |
| documents[].reason | string | ○ | なぜこの文書が関連するか |
| documents[].lines | string | - | 関連する行範囲（例: "10-50"）|

### カテゴリ別ファイル

| ファイル | 収集対象 | 主な取得手段 |
|----------|---------|-------------|
| `refs/specs.yaml` | 仕様書（要件・設計・計画）| `/query-specs` or `.doc_structure.yaml` |
| `refs/rules.yaml` | 開発ルール・規約 | `/query-rules` or `.doc_structure.yaml` |
| `refs/prs.yaml` | 類似PR | `gh pr list --search` |
| `refs/code.yaml` | 関連ソースコード・テスト | Glob / Grep 探索 |

### refs/ がない場合の扱い

refs/ ディレクトリ自体が存在しない、または中身が空の場合:
- コンテキスト収集フェーズがスキップされたことを意味する
- 後続の agent は参照文書なしで動作する（最低限の品質でも実行可能）

---

## 5. 通信フロー

### 典型的なフロー

```
オーケストレータ（例: review）
│
├─ 1. session_dir 作成 + session.yaml 初期化
│
├─ 2. コンテキスト収集（並列）
│     ├── Agent A → refs/specs.yaml
│     ├── Agent B → refs/rules.yaml
│     ├── Agent C → refs/prs.yaml     ← gh CLI 利用可能時のみ
│     └── Agent D → refs/code.yaml
│
├─ 3. 本作業（直列）
│     └── Agent E（レビュー / 設計書作成 等）
│         入力: session_dir（session.yaml + refs/ を読み込み）
│         出力: session_dir にスキル固有ファイルを書き込み
│
├─ 4. 後処理（オーケストレータ自身 or agent）
│     └── ユーザー確認・ToC更新・commit 等
│
└─ 5. session_dir 削除
```

### agent への指示テンプレート

```
session_dir: .claude/.temp/20260312-183000-a3f7b2
guide: plugins/forge/docs/context_gathering_guide.md
steps: [1, 2, 3, 5]    # 実行する Step 番号
```

- `session_dir`: 結果を書き込む先
- `guide`: 参照するガイド文書のパス
- `steps`: 実行する Step のリスト（適用マトリクスに基づく）

---

## 6. twinkling-popping-kahan.md との関係

| 項目 | 本設計書 | twinkling-popping-kahan.md |
|------|---------|---------------------------|
| session.yaml | 共通フィールド定義 | review 固有フィールド定義 |
| refs/ | 共通スキーマ定義 | — |
| review.md | — | フォーマット定義 |
| plan.yaml | — | スキーマ定義 |
| evaluation.yaml | — | スキーマ定義 |
| report.html | — | 生成仕様 |
| ライフサイクル | 共通パターン | review 固有のタイミング |

twinkling-popping-kahan.md は本設計書の共通部分を参照し、
review 固有の拡張のみを記述する形に将来的に更新する。
