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

| 原則                   | 説明                                                              |
| ---------------------- | ----------------------------------------------------------------- |
| HTML生成はスクリプト   | Python スクリプト + HTML テンプレートで安定的にレポートを生成する |
| ユーザー呼び出し可能   | `/forge:show-report` でオンデマンドに最新レポートを確認できる     |
| サイレント再生成モード | `--silent` フラグで `open` をスキップ（他スキルから呼ばれる場合） |

---

## 入力仕様

| 項目        | 必須 | 説明                                                                     |
| ----------- | ---- | ------------------------------------------------------------------------ |
| session_dir | 任意 | セッションディレクトリのパス。省略時は `.claude/.temp/` の最新を自動検出 |
| --silent    | 任意 | HTML 生成のみ実行。`open` コマンドによるブラウザ表示をスキップ           |

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

### Step 2: generate_report.py を実行して HTML を生成

Python スクリプトがセッションファイルを読み込み、HTML テンプレートにデータを注入して `report.html` を生成する。

```bash
PYTHON=$(/usr/bin/which python3 2>/dev/null || echo "python3")
"$PYTHON" "${CLAUDE_SKILL_DIR}/generate_report.py" {session_dir}
```

- exit 0: `{session_dir}/report.html` が生成された
- exit 1: stderr のエラーメッセージをユーザーに表示して終了

**読み込むファイル（スクリプトが自動で読み込む）:**

- `{session_dir}/session.yaml`（必須）
- `{session_dir}/plan.yaml`（必須）
- `{session_dir}/review.md`（存在する場合のみ）
- `{session_dir}/evaluation.yaml`（存在する場合のみ）
- `{session_dir}/refs.yaml`（存在する場合のみ）

**HTML の特徴:**

- 自己完結した単一 HTML ファイル（外部 CSS / JS 不要）
- 10秒間隔の自動リロード（スクロール位置を保持）
- ダークモード対応（`prefers-color-scheme: dark`）
- `vscode://file/` リンクでエディタ直接オープン

**HTML の構成:**

1. **ヘッダー**: レビュー種別・エンジン・開始日時
2. **参照ファイル一覧**: refs.yaml の target_files / reference_docs / related_code を `vscode://file/` リンクで表示
3. **進捗バー**: fixed / skipped / needs_review / in_progress / pending の件数と割合
4. **項目一覧テーブル**: 重大度アイコン・タイトル・ステータスバッジ・AI推奨・対象箇所リンク・修正ファイルリンク
5. **フッター**: 最終更新日時

### ファイルリンクの生成 [MANDATORY]

`generate_report.py` と `report_template.html` に実装済み。ルール:

- プロジェクトルート（`git rev-parse --show-toplevel`）を基準に絶対パスを構築
- リンク形式: `vscode://file/{absolute_path}:{line}`（行番号がある場合）
- リンク形式: `vscode://file/{absolute_path}`（行番号がない場合）
- リンクテキスト: 相対パス（例: `docs/specs/forge/plan/forge_plan.md:20`）
- ファイルパスの表示はモノスペースフォント

**書き込み先:** `{session_dir}/report.html`

### Step 3: ブラウザ表示（`--silent` でない場合のみ）

```bash
open {session_dir}/report.html
```

---

## 呼び出し元

| 呼び出し元       | タイミング                         | フラグ   |
| ---------------- | ---------------------------------- | -------- |
| review           | セッション開始時（初期生成＋表示） | なし     |
| present-findings | plan.yaml 更新後                   | --silent |
| fixer            | 修正完了後                         | --silent |
| ユーザー         | オンデマンド                       | なし     |

---

## エラーハンドリング

| エラー                   | 対応                                                             |
| ------------------------ | ---------------------------------------------------------------- |
| session_dir が存在しない | 「セッションディレクトリが見つかりません: {path}」と表示して終了 |
| plan.yaml が存在しない   | 「plan.yaml が見つかりません」と表示して終了                     |
| .claude/.temp/ が空      | 「アクティブなセッションがありません」と表示して終了             |
