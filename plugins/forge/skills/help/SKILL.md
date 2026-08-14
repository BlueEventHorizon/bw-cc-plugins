---
name: help
description: |
  forge スキル一覧を表示し、選択したスキルの引数をガイド付きで構成してそのまま実行できる。
  トリガー: "forge help", "forge の使い方", "ヘルプ", "どのスキルを使えばいい"
user-invocable: true
argument-hint: ""
allowed-tools: AskUserQuestion
---

# /forge:help

forge スキルの使い方をガイドし、そのまま実行できる。

---

## Step 1: スキル選択

以下のリストをテキストで出力してから AskUserQuestion を呼ぶ:

```
利用可能な forge スキル:

  review              : コード・文書をレビュー。重大度 🔴🟡🟢 で分類
  consult             : 議論を進行。論点を立て、討議ファイルに記録しながら 1 件ずつ
  start-requirements  : 要件定義書の作成。3モード対応
  start-design        : 設計書の作成。レビュー+自動修正→commit
  start-plan          : 計画書の作成。レビュー+自動修正→commit
  start-implement     : 計画書から実装・レビュー・計画更新
  start-uxui-design    : デザイントークン・UI 視覚仕様を創造
  create-feature-from-markdown-plan: Markdown plan から要件定義→設計書へ展開
  merge-specs          : 2 つの仕様 DIR（基本 / 追加）の齟齬を内容単位で解消
  setup-doc-structure : .doc_structure.yaml を対話的に生成
  setup-version-config: .version-config.yaml を対話的に生成
  update-version      : バージョンを一括更新。CHANGELOG 自動反映
  query-forge-rules   : forge 内蔵知識ベースを ToC 検索
```

AskUserQuestion:

- question: "スキルを選択してください"
- options: ["review", "start-requirements", "start-design", "start-plan"]
- ※ 他は Other で入力

---

## Step 2: 引数ウィザード

選択されたスキルに応じて、以下の引数ウィザードを実行する。

### review

#### 2-1. 種別

以下のリストをテキストで出力してから AskUserQuestion を呼ぶ:

```
レビュー種別:

  1. code        : ソースコード
  2. requirement : 要件定義書
  3. design      : 設計書
  4. plan        : 計画書
  5. uxui        : UX/UI デザイン（デザイントークン・コンポーネント）
  6. generic     : 任意の文書（README 等）
```

AskUserQuestion:

- question: "種別番号を入力してください（1〜6）"
- options: ["1 (code)", "2 (requirement)", "3 (design)", "4 (plan)"]
- ※ 5〜6 は Other で入力する

#### 2-2. 対象

```
レビュー対象を選択してください:
- ブランチ差分（対象を省略）
- ファイルを指定する
- ディレクトリを指定する（配下すべて）
```

「ファイルを指定する」を選んだ場合は `--files`、「ディレクトリを指定する」を選んだ場合は `--dirs` を組み立てる。**両者は対象軸として排他であり、混在指定はできない**（review 側がエラー終了する）。利用者がファイルとディレクトリを混ぜて入力した場合は、どちらの軸で実行するかを確認してから組み立てる。

```
パスを入力してください（カンマ区切りで複数指定可）:
例（ファイル）: src/services/auth.swift,src/models/user.swift
例（ディレクトリ）: src/services/,docs/specs/my-feature/design/
```

#### 2-3. エンジン

```
使用するエンジンを選択してください:
- codex（デフォルト）
- claude
```

#### 2-4. 修正モード

```
修正モードを選択してください:
- レビューのみ（修正なし）
- 自動修正 1サイクル（確信のあるものだけ確認なしに修正。確信の無いものは提示して採否を聞く）
- 自動修正 Nサイクル（N サイクル）
```

「自動修正 Nサイクル」を選んだ場合:

```
サイクル数を入力してください（例: 3）:
```

---

### start-uxui-design

#### 2-1. Feature 名

```
対象の Feature 名を入力してください（省略時はインタラクティブに決定）:
```

#### 2-2. プラットフォーム

```
対象プラットフォームを選択してください:
- ios     : iPhone / iPad アプリのデザイン
- macos   : Mac アプリのデザイン
```

---

### start-requirements

#### 2-1. Feature 名

```
対象の Feature 名を入力してください（省略時はインタラクティブに決定）:
```

#### 2-2. 開発種別

```
開発種別を選択してください:
- 新規アプリ（--new）
- 既存アプリへの追加（--add）
```

#### 2-3. モード

```
作成モードを選択してください:
- interactive          : 対話形式でゼロから要件を固める
- reverse-engineering  : 既存ソースコードから要件を抽出
- from-figma           : Figma デザインから要件を作成（Figma MCP 必須）
```

---

### start-design

#### 2-1. Feature 名

```
対象の Feature 名を入力してください（省略時は specs/ 一覧から選択）:
```

---

### start-plan

#### 2-1. Feature 名

```
対象の Feature 名を入力してください（省略時は specs/ 一覧から選択）:
```

---

### start-implement

#### 2-1. Feature 名

```
対象の Feature 名を入力してください（省略時は対話で確定）:
```

#### 2-2. タスク指定

```
実行するタスクを選択してください:
- 優先度順で自動選択（省略）
- タスク ID を指定する
```

「タスク ID を指定する」を選んだ場合:

```
タスク ID を入力してください（例: TASK-001,TASK-003）:
```

#### 2-3. サイクル数

```
最大サイクル数を入力してください（例: 3）:
```

---

### create-feature-from-markdown-plan

引数: Markdown plan のファイルパス（省略時は対話で決定）。
入力は Claude Code plan mode が生成した Markdown plan。forge 実装計画書 `{feature}_plan.yaml`（YAML、`/forge:start-plan` が作成）とは別物。

---

### consult

引数: 議論したい対象や問い（省略時は会話の流れから論点を立てる）

---

### merge-specs

引数: `[base] [additional]`（基本 DIR と追加 DIR の 2 つ。短縮名なら `.doc_structure.yaml` の spec ルート配下を自動探索）

---

### setup-doc-structure

引数: なし。実行すると対話的に開始する。

---

### setup-version-config

引数: なし。実行すると対話的に開始する。

---

### update-version

引数: バージョンアップの種別（patch/minor/major/直接指定）。省略時は対話で決定。

---

### query-forge-rules

引数: 検索クエリ。省略時は対話で決定。

---

## Step 3: コマンド確認と実行

収集した引数からコマンドを組み立てて表示し、AskUserQuestion を使用して実行確認する:

```
以下のコマンドを実行します:

  /forge:review code --files src/foo.py,src/bar.py --auto

実行しますか？
- 実行する
- キャンセル
```

「実行する」を選択した場合、対応するスキルを呼び出す。
