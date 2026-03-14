# forge レビューパイプライン セッションディレクトリ設計

> **⚠️ 廃止**: 本設計書の内容は `plugins/forge/docs/session_format.md` に統合されました。
> 正規の仕様は統合先を参照してください。本ファイルは設計判断の経緯として保持しています。

## Context

### 問題

現在のアーキテクチャでは、`reference_docs` / `related_code` / `target_files` / レビュー結果を
すべてプロンプトテキストとして各スキルに渡している。これにより:

1. **コンテキスト圧縮で消失**: 長時間セッションでリスト・Codex出力が消える
2. **状態の非永続性**: セッション中断後に「どこまで処理したか」が失われる
3. **複数フロー同時実行の衝突**: 単一の `review-result-{timestamp}.md` は複数フローで衝突しうる
4. **`.claude/.temp/` が gitignore されていない**: レビュー結果がリポジトリに混入するリスク

### 解決策

`/forge:review` 実行ごとに**セッションワーキングディレクトリ**を作成し、
すべての中間ファイルをそこに集約する。各スキルはプロンプト経由でなくファイル経由でデータを受け取る。

---

## セッションディレクトリ設計

### パス

```
.claude/.temp/{skill_name}-{random6}/
```

例: `.claude/.temp/review-a3f7b2/`

- スキル名: どのスキルのセッションか一目でわかる
- 6文字ランダム hex: 同一スキルの複数起動でも衝突しない
- `.gitignore` に `.claude/.temp/` を追加（要変更）

### ライフサイクル

| タイミング | 操作 |
|------------|------|
| Phase 2 開始 | `review` がディレクトリ作成 + `session.yaml` 初期化 |
| Phase 5 正常完了 | `review` がディレクトリを削除 |
| セッション中断 | ディレクトリが残存（次回起動時に検出・再開提案） |

---

## ファイル一覧

### `session.yaml` — セッションメタデータ

```yaml
review_type: code
engine: codex
auto_count: 0       # 0 = 対話モード、N = --auto N
current_cycle: 0
started_at: "2026-03-09T18:30:00Z"
last_updated: "2026-03-09T18:30:00Z"
status: in_progress # in_progress / completed
```

**書き込み**: `review` (Phase 2 開始時・Phase 5 完了時)

---

### `refs.yaml` — 参照ファイルリスト（最重要）

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
    reason: 同種AIスキルのfrontmatter参考
    lines: "1-30"   # 関連する行範囲（Phase 1.5 の探索サブエージェントが特定）
  - path: plugins/forge/skills/evaluator/SKILL.md
    reason: 同種AIスキルのfrontmatter参考
    lines: "1-10"
```

**書き込み**: `review` (Phase 1.5)
**読み込み**: `reviewer` / `evaluator` / `fixer` / `present-findings` がすべてここから取得（プロンプト経由不要）

**lines フィールドについて**:
- Phase 1.5 の関連コード探索サブエージェントがファイルを Read しながら関連行を特定する
- 任意項目（特定できない場合は省略）

---

### `review.md` — レビュー結果（生出力）

現行の `review-result-{timestamp}.md` に相当するが、セッションディレクトリ内に配置。
フォーマットは現行の frontmatter + Markdown 形式を**廃止**し、Markdown のみとする
（メタデータは `session.yaml` + `refs.yaml` に分離済みのため）。

**Codex の場合:**
```bash
codex exec --full-auto --sandbox read-only --cd <dir> "<prompt>" \
  > {session_dir}/review.md
```
shell リダイレクトで直接ファイルに書き込む。コンテキストに乗せない。

**Claude サブエージェントの場合:**
サブエージェントが `Write` ツールで `{session_dir}/review.md` に書き込む。

**書き込み**: `reviewer` サブエージェント
**読み込み**: `evaluator` / `present-findings` / `generate_report.py`

複数サイクル（`--auto N`）では上書きする（最新サイクルのみ保持）。

---

### `evaluation.yaml` — evaluator の判定結果

```yaml
cycle: 1
items:
  - id: 1
    severity: critical
    title: "help と review のコマンド仕様不一致"
    recommendation: fix       # fix / skip / needs_review
    auto_fixable: false
    reason: "明確な仕様不一致、副作用なし。複数の修正案があるため auto_fixable: false"
  - id: 3
    severity: major
    title: "レビュー手順の自己矛盾"
    recommendation: needs_review
    reason: "設計意図の確認が必要"
```

**書き込み**: `evaluator` サブエージェント（全モード共通）
**読み込み**: `fixer` / `present-findings`（AI推奨・auto_fixable の参照）

> 全モードで evaluator が `evaluation.yaml` に推奨（recommendation + auto_fixable）を記録する。
> `present-findings` は auto_fixable を ✅ マークとして提示し、最終判断は人間が行う。
> これにより「AIの却下判断」が対話モードでも活かせる。

---

### `plan.yaml` — 修正プランと進捗状態

```yaml
items:
  - id: 1
    severity: critical
    title: "help と review のコマンド仕様不一致"
    status: fixed          # pending / in_progress / fixed / skipped / needs_review
    fixed_at: "2026-03-09T18:35:00Z"
    files_modified:
      - plugins/forge/skills/help/SKILL.md
  - id: 4
    severity: major
    title: "レビュー手順の自己矛盾"
    status: pending
    skip_reason: ""        # skipped の場合のみ記載
```

**書き込み**:
- `reviewer`: 初期作成（全件 `pending`）
- `evaluator`: 全モード共通で `recommendation` に基づき `status` 初期更新
- `present-findings`: 対話モードでユーザー判断後に更新
- `fixer`: 修正完了後に `fixed` に更新

これが**セッション再開の鍵**。`⬜ pending` の項目のみ処理すれば続きから再開できる。

---

### `report.html` — ビジュアルレポート

- `plan.yaml` + `review.md` + `evaluation.yaml` から生成する静的 HTML
- `<meta http-equiv="refresh" content="10">` で自動リロード（10秒ごと）
- セッション開始時に `open {session_dir}/report.html` で自動表示

**生成**: `/forge:show-report` Skill（後述）が担当
**タイミング**: `plan.yaml` が更新されるたびに呼び出す

---

## `/forge:show-report` Skill（新規追加）

### 概要

セッションディレクトリのファイルを読み込み、HTML レポートを生成してブラウザで表示する。
ユーザーも直接呼び出せる（`user-invocable: true`）。

### 入力

```
/forge:show-report [session_dir]
```

- `session_dir` 省略時: `.claude/.temp/` の最新セッションディレクトリを自動検出

### ワークフロー

1. session_dir の確定（引数 or 自動検出）
2. general-purpose subagent を起動して HTML 生成を委譲:
   - `session.yaml` / `plan.yaml` / `review.md` / `evaluation.yaml` を Read
   - HTML を生成して `{session_dir}/report.html` に Write
3. `open {session_dir}/report.html` でブラウザ表示

### HTML 表示内容

| セクション | 内容 |
|------------|------|
| ヘッダー | レビュー種別・エンジン・開始日時 |
| 進捗バー | fixed/skipped/needs_review/pending の件数と割合 |
| 項目一覧 | 🔴🟡🟢 色分け + ステータスバッジ + evaluator 推奨 |
| 自動リロード | `<meta http-equiv="refresh" content="10">` |

### 呼び出し元

| 呼び出し元 | タイミング |
|------------|-----------|
| `review` | セッション開始時（report.html 初期生成 + ブラウザ表示） |
| `present-findings` | 各項目の plan.yaml 更新後（サイレント再生成、ブラウザ表示なし） |
| `fixer` | 修正完了後（サイレント再生成） |
| ユーザー | オンデマンド（`/forge:show-report` で最新レポートを表示） |

> サイレント再生成: `open` を呼ばず HTML のみ更新（ブラウザの自動リロードに委ねる）

---

## 変更スコープ

| ファイル | 変更内容 | 規模 |
|----------|----------|------|
| `.gitignore` | `.claude/.temp/` を追加 | 小 |
| `plugins/forge/skills/show-report/SKILL.md` | **新規作成** | 中 |
| `plugins/forge/skills/review/SKILL.md` | Phase 2: session_dir 作成 / session.yaml + refs.yaml 書き込み / Codex リダイレクト変更 / Phase 5: 削除 | 大 |
| `plugins/forge/skills/reviewer/SKILL.md` | refs.yaml から読み込み / review.md に書き込み / plan.yaml 初期作成 | 中 |
| `plugins/forge/skills/evaluator/SKILL.md` | refs.yaml から読み込み / evaluation.yaml 書き込み / plan.yaml 更新 | 中 |
| `plugins/forge/skills/fixer/SKILL.md` | refs.yaml から読み込み / plan.yaml 更新 | 小 |
| `plugins/forge/skills/present-findings/SKILL.md` | session_dir から読み込み / plan.yaml から状態復元・更新 / 再開フロー追加 | 大 |

---

## スキル間インターフェース変更のポイント

### 現在（プロンプト経由）
```
review → reviewer: "reference_docs は A, B, C。related_code は X, Y..."
review → evaluator: "レビュー結果はこちら: [長いテキスト]..."
```
コンテキスト圧縮で消える。

### 変更後（ファイル経由）
```
review → 全スキル: session_dir のパスのみ渡す
各スキル: session_dir/{refs.yaml, review.md, plan.yaml} を Read して動作
```
ファイルは永続。コンテキスト圧縮の影響を受けない。

---

## 検討した代替案と却下理由

| 案 | 却下理由 |
|----|---------|
| フロントマター方式を継続 | 根本解決にならない（コンテキスト圧縮問題が残る） |
| UUID をディレクトリ名に使用 | 人間可読性・ソート可能性を優先してタイムスタンプ+random に |
| HTML 生成を各スキルが担当 | 共通スクリプト (`generate_report.py`) に集約した方が変更コスト低 |
| evaluator は --auto のみ | 対話モードでも AI 推奨を活かすため常時実行に変更 |

---

## 確定事項（ユーザー確認済み）

| 項目 | 決定 |
|------|------|
| evaluator の実行タイミング | 対話モード・auto モード両方で常時実行 |
| 完了後のディレクトリ | Phase 4 で削除 |
| 実装方針 | 体系的に全部一気に実装 |

## 注意事項

- **plan.yaml の競合書き込み**: `--auto` サイクル内は evaluator → fixer の順で直列実行のため競合なし
- **show-report は `user-invocable: true`**: ユーザーがオンデマンドでレポートを確認できる唯一のエントリーポイント
- **サイレント再生成**: present-findings / fixer からは `open` なしで HTML のみ更新する（ブラウザが開いていれば自動リロードで反映）

---

## 検証方法

1. `/forge:review code` を実行し、`.claude/.temp/{timestamp}-{random}/` が作成されることを確認
2. 各ファイル（session.yaml, refs.yaml, review.md, plan.yaml）が正しく生成されることを確認
3. report.html がブラウザで開くことを確認
4. セッション中断後に再度 `/forge:review` を実行し、再開を提案されることを確認
5. Phase 4 完了後にセッションディレクトリが削除されることを確認
6. `.claude/.temp/` が git に追跡されないことを確認
