---
name: show-report
user-invocable: true
description: |
  レビューセッションの進捗をHTML形式でブラウザに表示する。
  session_dir のファイル（session.yaml/plan.yaml/review.md/evaluation.yaml）を読み込み
  HTMLレポートを生成してブラウザで開く。
argument-hint: "[session_dir] [--silent]"
---

# /forge:show-report Skill

レビューセッションの進捗を可視化する HTML レポートを生成し、ブラウザで表示する Skill。
セッションディレクトリ内の YAML / Markdown ファイルを読み込み、自己完結した HTML を生成する。

## 設計原則

| 原則 | 説明 |
|------|------|
| HTML生成はsubagent | general-purpose subagent がファイルを読んで HTML を生成・書き込む |
| ユーザー呼び出し可能 | `/forge:show-report` でオンデマンドに最新レポートを確認できる |
| サイレント再生成モード | `--silent` フラグで `open` をスキップ（他スキルから呼ばれる場合） |

---

## 入力仕様

| 項目 | 必須 | 説明 |
|------|------|------|
| session_dir | 任意 | セッションディレクトリのパス。省略時は `.claude/.temp/` の最新を自動検出 |
| --silent | 任意 | HTML 生成のみ実行。`open` コマンドによるブラウザ表示をスキップ |

---

## ワークフロー

### Step 1: session_dir の確定

引数を解析し、`session_dir` パスと `--silent` フラグを取り出す。

**session_dir が省略された場合:**
1. `.claude/.temp/` を Glob で検索し、サブディレクトリ一覧を取得
2. タイムスタンプ（ディレクトリ名プレフィックス `YYYYMMDD-HHmmss`）が最大のものを選択
3. `.claude/.temp/` が空または存在しない場合: 「アクティブなセッションがありません」と表示して終了

**session_dir が指定された場合:**
- 指定パスが存在しない場合: 「セッションディレクトリが見つかりません: {path}」と表示して終了

**plan.yaml の確認:**
- `{session_dir}/plan.yaml` が存在しない場合: 「plan.yaml が見つかりません」と表示して終了

### Step 2: subagent を起動して HTML を生成

general-purpose subagent に以下を委譲する:

**読み込むファイル:**
- `{session_dir}/session.yaml`（必須）
- `{session_dir}/plan.yaml`（必須）
- `{session_dir}/review.md`（存在する場合のみ）
- `{session_dir}/evaluation.yaml`（存在する場合のみ）

**HTML の要件:**
- 自己完結した単一 HTML ファイル（外部 CSS / JS 不要）
- `<meta http-equiv="refresh" content="10">` を `<head>` 内に配置（自動リロード）
- 文字コード UTF-8
- ダークモード対応（`prefers-color-scheme: dark` メディアクエリを使用）

**HTML の構成:**

1. **ヘッダー**: レビュー種別・エンジン・開始日時（`session.yaml` の値を使用）
2. **進捗バー**: fixed / skipped / needs_review / pending の件数と割合をビジュアル表示（`plan.yaml` の `items` を集計）
3. **項目一覧テーブル**: 以下の列を含む
   - 重大度アイコン: `🔴`（critical）/ `🟡`（major）/ `🟢`（minor）
   - タイトル
   - ステータスバッジ（色付き）: pending=グレー / in_progress=青 / fixed=緑 / skipped=オレンジ / needs_review=赤
   - AI推奨（`evaluation.yaml` が存在する場合、対応する `id` の `decision` を表示）
   - 修正ファイル（`status: fixed` の場合、`files_modified` を表示）
4. **フッター**: 最終更新日時

**書き込み先:** `{session_dir}/report.html` に Write

### Step 3: ブラウザ表示（`--silent` でない場合のみ）

```bash
open {session_dir}/report.html
```

---

## 呼び出し元

| 呼び出し元 | タイミング | フラグ |
|------------|-----------|--------|
| review | セッション開始時（初期生成＋表示） | なし |
| present-findings | plan.yaml 更新後 | --silent |
| fixer | 修正完了後 | --silent |
| ユーザー | オンデマンド | なし |

---

## エラーハンドリング

| エラー | 対応 |
|--------|------|
| session_dir が存在しない | 「セッションディレクトリが見つかりません: {path}」と表示して終了 |
| plan.yaml が存在しない | 「plan.yaml が見つかりません」と表示して終了 |
| .claude/.temp/ が空 | 「アクティブなセッションがありません」と表示して終了 |
