# bw-cc-plugins

AI によるドキュメントライフサイクル管理のための Claude Code プラグインマーケットプレイス。

[English README (README.md)](README.md)

## プラグイン一覧

| プラグイン | バージョン | 説明                                                                                                                    |
| ---------- | ---------- | ----------------------------------------------------------------------------------------------------------------------- |
| **forge**  | 0.0.26     | AI によるドキュメントライフサイクルツール。要件定義・設計・計画書の作成、コード・文書レビュー、自動修正、品質確定に対応 |
| **anvil**  | 0.0.4      | GitHub 操作ツールキット。PR 作成、Issue 管理、GitHub ワークフロー自動化に対応                                           |
| **xcode**  | 0.0.1      | Xcode ビルド・テストツールキット。iOS/macOS プロジェクトのビルドとテストをプラットフォーム自動判定で実行                |

## インストール

### 方法 A: マーケットプレイス経由（永続）

Claude Code セッション内で:

```
/plugin marketplace add BlueEventHorizon/bw-cc-plugins
/plugin install forge@bw-cc-plugins
```

すでにinstall済みの場合は、ターミナルから:

```bash
claude plugin enable forge@bw-cc-plugins
```

`marketplace add` は GitHub リポジトリをプラグイン取得元として登録します（ユーザーごとに1回）。一度インストールすれば、常に利用可能です。

### 方法 B: ローカルディレクトリ（セッション限定）

```bash
git clone https://github.com/BlueEventHorizon/bw-cc-plugins.git
claude --plugin-dir ./bw-cc-plugins/plugins/forge
```

> **注意**: `--plugin-dir` はセッション限定です。Claude Code を起動するたびに指定が必要です。解除するには、フラグなしで起動するだけです。

### 更新

ターミナルから:

```bash
claude plugin update forge@bw-cc-plugins --scope local
```

## forge

AI によるドキュメントライフサイクルツール。要件定義・設計・計画書の作成から、コード・文書レビュー、自動修正、品質確定まで対応。`.doc_structure.yaml` によるプロジェクト文書構成の管理機能を統合。

### Feature（フィーチャー）

forge は **Feature（フィーチャー）** 単位で文書を管理する。Feature とは、関連する仕様をグループ化した開発単位。

| 開発パターン | Feature の使い方 |
|-------------|-----------------|
| 追加開発 | 既存のメイン仕様に後から追加する機能群を Feature として分割する |
| アジャイル開発 | イテレーションごとに Feature 単位で開発・デリバリーする |
| 小規模プロジェクト | プロジェクト全体を1つの Feature として扱ってもよい |

`start-requirements` / `start-design` / `start-plan` / `start-implement` は Feature 単位で処理を実行する。各 Feature は共通のディレクトリ構造で要件定義書・設計書・計画書を管理する:

```
specs/
  {feature}/
    requirements/   # 要件定義書
    design/         # 設計書
    plan/           # 計画書
```

### 使い方

```
/forge:review <種別> [対象] [--エンジン] [--auto [N]]
```

| 引数     | 値                                                                                        |
| -------- | ----------------------------------------------------------------------------------------- |
| 種別     | `code` \| `requirement` \| `design` \| `plan` \| `generic`                                |
| 対象     | ファイルパス（複数可）、ディレクトリ、Feature 名、省略で対話的に決定                      |
| エンジン | `--codex`（デフォルト）\| `--claude`                                                      |
| モード   | `--auto [N]`（レビュー+修正を N サイクル実行。省略時 N=1）\| `--auto-critical`（🔴のみ修正） |

### 使用例

```bash
# ディレクトリ内のソースコードをレビュー
/forge:review code src/

# 特定ファイルをレビュー
/forge:review code src/services/auth.swift

# Feature 名で要件定義書をレビュー
/forge:review requirement login

# 設計書をレビュー
/forge:review design specs/login/design/login_design.md

# 計画書をレビュー（1サイクル修正、デフォルト）
/forge:review plan specs/login/plan/login_plan.yaml --auto

# 3サイクル繰り返してレビュー+修正
/forge:review code src/ --auto 3

# レビューのみ（修正なし）
/forge:review code src/ --auto 0

# 任意の文書をレビュー
/forge:review generic README.md

# ブランチ差分をレビュー（対象省略 = 現在のブランチの変更）
/forge:review code

# Claude エンジンを使用（Codex の代わりに）
/forge:review code src/ --claude

# .doc_structure.yaml を対話的に作成・更新
/forge:setup-doc-structure

# 要件定義書を対話的に作成
/forge:start-requirements

# 既存アプリからリバースエンジニアリングで要件定義書を作成
/forge:start-requirements myfeature --mode reverse-engineering

```

### スキル構成

| スキル                | ユーザー呼び出し | 説明                                                                                                                    |
| --------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `review`              | 可能             | メインのレビュースキル。種別判定、参考文書収集、レビュー実行                                                            |
| `setup-doc-structure` | 可能             | プロジェクトのディレクトリをスキャン・分類し、`.doc_structure.yaml` を生成                                              |
| `start-requirements` | 可能             | 対話・リバースエンジニアリング・Figmaの3モードで要件定義書を作成                                                        |
| `start-design`       | 可能             | 要件定義書から設計書を作成。/query-rules でプロジェクト固有ワークフローを自動取得、なければ組み込みワークフローを使用   |
| `start-plan`         | 可能             | 設計書から計画書を作成・更新。/query-rules でプロジェクト固有ワークフローを自動取得、なければ組み込みワークフローを使用 |
| `start-implement`     | 可能             | 計画書からタスクを選択し、コンテキスト収集・実装・レビュー・計画書更新を一連で実行するオーケストレーター               |
| `setup-version-config`| 可能             | プロジェクトをスキャンして `.version-config.yaml` を生成・更新する。プロジェクト構造変更時に再実行                     |
| `update-version`      | 可能             | `.version-config.yaml` の設定に従いバージョンを一括更新。patch/minor/major/直接指定対応。CHANGELOG 自動生成オプション付き |
| `clean-rules`         | 可能             | プロジェクトの rules/ を開発文書の分類学で分析し、forge 内蔵知識との重複を除去して体系的に再構築する                      |
| `help`                | 可能             | インタラクティブヘルプウィザード。スキルを選択し、引数を1つずつ入力してそのまま実行できる                               |
| `present-findings`    | AI 専用          | レビュー結果を段階的・対話的に提示                                                                                      |
| `reviewer`            | AI 専用          | レビュー実行エンジン。参考文書を収集し指摘事項を作成                                                                    |
| `evaluator`           | AI 専用          | 指摘事項を5つの基準で吟味し、修正・スキップ・確認の判定を行う                                                           |
| `fixer`               | AI 専用          | レビュー指摘に基づく修正を実行。参考文書パスを受け取り再収集を回避                                                      |

### レビュー種別

| 種別          | 対象                                        |
| ------------- | ------------------------------------------- |
| `code`        | ソースコードファイル・ディレクトリ          |
| `requirement` | 要件定義書                                  |
| `design`      | 設計書                                      |
| `plan`        | 開発計画書                                  |
| `generic`     | 任意の文書（ルール、スキル定義、README 等） |

### 重大度レベル

| レベル | 意味                                                           |
| ------ | -------------------------------------------------------------- |
| 致命的 | 修正必須。バグ、セキュリティ問題、データ損失リスク、仕様違反   |
| 品質   | 修正推奨。コーディング規約、エラーハンドリング、パフォーマンス |
| 改善   | あると良い。可読性向上、リファクタリング提案                   |

### レビュー観点

プラグインにはレビュー種別ごとの観点ファイルが `skills/review/docs/` に同梱されています:

- `review_criteria_requirement.md` — 要件定義書レビュー観点
- `review_criteria_design.md` — 設計書レビュー観点
- `review_criteria_plan.md` — 計画書レビュー観点
- `review_criteria_code.md` — コードレビュー観点
- `review_criteria_generic.md` — 汎用文書レビュー観点

レビュー観点は以下のソースから累積的に構成されます:

- **プラグインデフォルト**（常に含む）: 上記の同梱観点ファイルの perspectives を使用
- **DocAdvisor**（追加 perspective）: プロジェクトに DocAdvisor Skill（`/query-rules`）がある場合、プロジェクト固有のルール文書を追加の perspective として適用

### 文書構造管理 (.doc_structure.yaml)

`setup-doc-structure` スキルがプロジェクトのディレクトリをスキャンして Markdown ファイルを検出し、対話的に分類して `.doc_structure.yaml` を生成します。forge はこのファイルを直接読み込んで、レビュー・修正時の参考文書を収集します。

完全なスキーマ仕様は [docs/specs/forge/design/doc_structure_format.md](docs/specs/forge/design/doc_structure_format.md) を参照してください。

```yaml
# doc_structure_version: 3.0

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule

specs:
  root_dirs:
    - "docs/specs/*/design/"
    - "docs/specs/*/requirement/"
  doc_types_map:
    "docs/specs/*/design/": design
    "docs/specs/*/requirement/": requirement
```

## xcode

Xcode ビルド・テストツールキット。スキームとプラットフォームを自動判定して iOS/macOS プロジェクトをビルド・テストします。

### 使い方

```
/xcode:build [scheme-name]
/xcode:test [scheme-name] [test-target]
```

### 使用例

```bash
# プロジェクトをビルド（スキーム・プラットフォーム自動検出）
/xcode:build

# スキームを指定してビルド
/xcode:build MyApp

# 全テストを実行
/xcode:test

# 特定のテストターゲットを実行
/xcode:test MyApp LibraryTests/FooTests
```

### スキル構成

| スキル  | ユーザー呼び出し | 説明                                                                     |
| ------- | ---------------- | ------------------------------------------------------------------------ |
| `build` | 可能             | クリーンビルドを実行しエラーを報告。iOS/macOS プラットフォームを自動判定 |
| `test`  | 可能             | テストを実行。iOS はシミュレーターを自動検出。失敗を詳細報告             |

### 動作要件

- Xcode（`xcodebuild` が PATH に存在）
- iOS テスト: Xcode Simulator

---

## anvil

GitHub 操作ツールキット。コミット差分から自動生成されたタイトル・本文で PR をドラフト作成します。

### 使い方

```
/anvil:create-pr [ベースブランチ]
```

### 使用例

```bash
# 現在のブランチからドラフト PR を作成
/anvil:create-pr

# ベースブランチを明示的に指定
/anvil:create-pr develop
```

### スキル構成

| スキル      | ユーザー呼び出し | 説明                                                                                      |
| ----------- | ---------------- | ----------------------------------------------------------------------------------------- |
| `create-pr` | 可能             | コミット差分からタイトル・本文を生成し GitHub ドラフト PR を作成。`gh` CLI 必須           |
| `commit`    | 可能             | 変更内容からコミットメッセージを生成し commit & push。ブランチ名から issue 参照を自動付与 |

### 動作要件

- [gh CLI](https://cli.github.com/)（認証済み）

### Git 情報キャッシュ (.git_information.yaml)

初回実行時、`create-pr` は `git remote` から GitHub の owner/repo を検出し、`.git_information.yaml` への保存を提案します（git コマンドの繰り返しを省略するため）:

```yaml
version: "1.0"
github:
  owner: "<org-or-user>"
  repo: "<repo-name>"
  remote_url: "<url>"
  default_base_branch: main
  pr_template: .github/PULL_REQUEST_TEMPLATE.md
```

## 動作要件

- [Claude Code](https://claude.ai/code) CLI
- Python 3（setup スキャン用）
- [Codex CLI](https://github.com/openai/codex)（任意。Codex エンジン使用時に必要。未インストールの場合は Claude にフォールバック）

## ライセンス

[MIT](LICENSE)
