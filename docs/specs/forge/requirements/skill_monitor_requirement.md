# skill_monitor 要件定義書

**作成日**: 2026-03-15
**作成者**: k_terada

## 概要

forge オーケストレータが管理するセッションデータ（YAML 等）をリアルタイムでブラウザに表示する機能。
全オーケストレータ共通の仕組みとして、スキル側のコード追加なしで動作する。

### 背景

旧 show-report スキルは以下の問題があった:

1. **review 専用** — 他のオーケストレータ（start-design, start-plan 等）では使えない
2. **コンテキスト汚染** — オーケストレータが HTML 生成スキルを呼び出すとツール結果がコンテキストに蓄積
3. **SKILL 側の追加コードが必要** — 各スキルに show-report 呼び出し指示を書く必要があった

### 解決策

SKILL は既存の YAML を更新するだけ（追加コード不要）。Claude Code フックが更新を検知し、独立プロセスの SSE サーバーがブラウザに Push する。

---

## 機能要件

### FNC-001: セッションデータのブラウザ表示

| ID | 要件 |
|---|---|
| FNC-001-1 | セッションディレクトリ内の YAML ファイル（session.yaml, plan.yaml 等）をブラウザに表示できる |
| FNC-001-2 | 表示はセッションファイルのスキーマ（`session_format.md`）に従う |
| FNC-001-3 | 中間ファイル（display.json 等）の生成は不要。既存の YAML を SSE サーバーが直接読む |

### FNC-002: リアルタイム更新

| ID | 要件 |
|---|---|
| FNC-002-1 | SKILL がセッションファイルを更新したとき、ブラウザに自動反映される |
| FNC-002-2 | 更新通知は Claude Code の PostToolUse フック経由で行う（イベント駆動） |
| FNC-002-3 | フックはセッションディレクトリ内のファイルへの Write / Edit に反応する |
| FNC-002-4 | ブラウザへの Push は SSE（Server-Sent Events）を使用する |

### FNC-003: コンテキスト非汚染

| ID | 要件 |
|---|---|
| FNC-003-1 | SKILL は既存のセッションファイル更新以外の追加作業を一切行わない |
| FNC-003-2 | フックはシェルスクリプトとして Claude のコンテキスト外で実行される |
| FNC-003-3 | SSE サーバーは独立プロセスとして動作し、SKILL のコンテキストに影響しない |

### FNC-004: 全オーケストレータ共通

| ID | 要件 |
|---|---|
| FNC-004-1 | review / start-design / start-plan / start-requirements / start-implement の全オーケストレータで動作する |
| FNC-004-2 | スキル固有の表示ロジックは不要。セッションファイルのスキーマに基づき汎用的にレンダリングする |
| FNC-004-3 | セッションディレクトリのパスを知るだけで動作を開始できる |

### FNC-005: SSE サーバー

| ID | 要件 |
|---|---|
| FNC-005-1 | `POST /notify` — フックからの更新通知を受け取る |
| FNC-005-2 | `GET /sse` — SSE ストリームをブラウザに提供する |
| FNC-005-3 | `GET /session` — セッションディレクトリ内の全 YAML を読んで JSON で返す |
| FNC-005-4 | `GET /history` — 更新履歴（いつ、どのファイルが更新されたか）を返す |
| FNC-005-5 | Python 標準ライブラリのみで実装する（外部依存禁止） |

### FNC-006: Claude Code フック

| ID | 要件 |
|---|---|
| FNC-006-1 | PostToolUse フックで Write および Edit ツールの実行を検知する |
| FNC-006-2 | 書き込み先がセッションディレクトリ（`.claude/.temp/` 配下）の場合のみ SSE サーバーに通知する |
| FNC-006-3 | フックは `.claude/hooks/` に配置し、`.claude/settings.json` で登録する |
| FNC-006-4 | フックの実行が失敗しても SKILL の動作に影響しない（exit 0 を保証） |

### FNC-007: ブラウザ UI

| ID | 要件 |
|---|---|
| FNC-007-1 | 起動時に `/session` で現在のセッション状態を取得する |
| FNC-007-2 | SSE で「どのファイルが更新されたか」を受信し、`/session` で最新状態を再取得する |
| FNC-007-3 | session_format.md のスキーマに従い、ファイル種別ごとに適切なレイアウトで表示する |
| FNC-007-4 | 静的 HTML + JavaScript で実装する（ビルドツール不要） |

---

## 非機能要件

| ID | 要件 |
|---|---|
| NFR-001 | SSE サーバーは Python 標準ライブラリのみで実装する |
| NFR-002 | フックの実行時間は 100ms 以内に完了する |
| NFR-003 | SSE サーバーはローカルホストのみでリッスンする（セキュリティ） |
| NFR-004 | 同時に1つのセッションのみ表示する（マルチセッション対応は将来課題） |

---

## データフロー

```
SKILL が plan.yaml 等を更新（既存動作、変更なし）
    │
    ▼
PostToolUse フック（.claude/.temp/ 内への Write を検知）
    │
    ▼
display_notify.sh → SSE サーバーに HTTP POST（更新されたファイルパス）
    │
    ▼
skill_monitor.py（SSE サーバー）
├── 通知受信 → history.jsonl に追記
├── SSE クライアントに更新イベントを Push
└── /session リクエスト時にセッションディレクトリの全 YAML を読んで JSON 化
    │
    ▼
ブラウザ
├── SSE で更新通知受信
├── /session で最新状態を再取得
└── session_format.md のスキーマに従いレンダリング
```

---

## 表示対象ファイル

`session_format.md` で定義されたセッションファイル:

| ファイル | 表示内容 |
|---------|---------|
| `session.yaml` | セッションメタデータ（スキル名、種別、開始日時、ステータス） |
| `refs.yaml` | 参照ファイルリスト（target_files, reference_docs, related_code） |
| `review.md` | レビュー結果（🔴🟡🟢 指摘事項） |
| `plan.yaml` | 修正プラン・タスク進捗 + AI 推奨判定（recommendation, auto_fixable）※ evaluation.yaml は plan.yaml に統合済み |
| `refs/*.yaml` | コンテキスト収集結果（specs.yaml, rules.yaml, code.yaml） |

全ファイルが存在するとは限らない。存在するファイルのみ表示する。

---

## 構成要素

| 要素 | 配置場所 | 役割 |
|------|---------|------|
| `skill_monitor.py` | `plugins/forge/scripts/` | SSE サーバー + YAML → JSON 変換 |
| `display_notify.py` | `.claude/hooks/` | PostToolUse フック → SSE サーバー通知（Python） |
| `index.html` | `plugins/forge/static/` | ブラウザ UI |
| フック設定 | `.claude/settings.json` | PostToolUse フック登録 |

---

## 関連文書

| 文書 | 役割 |
|------|------|
| `plugins/forge/docs/session_format.md` | セッションファイルスキーマ（表示対象の SSOT） |
| `docs/specs/forge/requirement/orchestrator_pattern.md` | オーケストレータパターン要件（FNC-002: セッションディレクトリ通信） |
| `meta/skill_monitor_design.md` | 設計メモ（本要件の背景と検討経緯） |
