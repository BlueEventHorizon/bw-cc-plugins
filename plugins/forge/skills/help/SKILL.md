---
name: help
description: |
  forge スキルのインタラクティブヘルプ。スキルを選択し、引数を対話的に入力してそのまま実行できる。
  トリガー: "forge help", "使い方", "ヘルプ", "/forge:help"
user-invocable: true
argument-hint: ""
allowed-tools: AskUserQuestion
---

# /forge:help

forge スキルの使い方をガイドし、そのまま実行できる。

---

## Step 1: スキル選択

AskUserQuestion でスキルを選択する:

```
どの forge スキルのヘルプを表示しますか？

選択肢:
- review             : コード・文書のレビュー（オーケストレーター）
- create-requirements: 要件定義書の作成
- create-design      : 設計書の作成
- create-plan        : 計画書の作成
- setup              : .doc_structure.yaml の作成・更新
```

---

## Step 2: 引数ウィザード

選択されたスキルに応じて、以下の引数ウィザードを実行する。

### review

#### 2-1. 種別

```
レビュー種別を選択してください:
- code        : ソースコード
- requirement : 要件定義書
- design      : 設計書
- plan        : 計画書
- generic     : 任意の文書（README等）
```

#### 2-2. 対象

```
レビュー対象を選択してください:
- ブランチ差分（対象を省略）
- ファイル・ディレクトリを指定する
```

「ファイル・ディレクトリを指定する」を選んだ場合:

```
パスを入力してください（スペース区切りで複数指定可）:
例: src/  または  src/services/auth.swift
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
- 自動修正 1サイクル（🔴致命的 + 🟡品質問題を修正）
- 自動修正 Nサイクル（サイクル数を指定）
- --auto [N]（N サイクル自動修正。省略時 N=1）
```

「自動修正 Nサイクル」を選んだ場合:

```
サイクル数を入力してください（例: 3）:
```

---

### create-requirements

#### 2-1. Feature 名

```
対象の Feature 名を入力してください（省略時はインタラクティブに決定）:
```

#### 2-2. モード

```
作成モードを選択してください:
- interactive          : 対話形式でゼロから要件を固める
- reverse-engineering  : 既存ソースコードから要件を抽出
- from-figma           : Figma デザインから要件を作成（Figma MCP 必須）
```

---

### create-design

#### 2-1. Feature 名

```
対象の Feature 名を入力してください（省略時は specs/ 一覧から選択）:
```

---

### create-plan

#### 2-1. Feature 名

```
対象の Feature 名を入力してください（省略時は specs/ 一覧から選択）:
```

---

### setup

引数なし。そのまま Step 3 へ進む。

---

---

## Step 3: コマンド確認と実行

収集した引数からコマンドを組み立てて表示し、AskUserQuestion を使用して実行確認する:

```
以下のコマンドを実行します:

  /forge:review code src/ --claude --auto 3

実行しますか？
- 実行する
- キャンセル
```

「実行する」を選択した場合、対応するスキルを呼び出す。
