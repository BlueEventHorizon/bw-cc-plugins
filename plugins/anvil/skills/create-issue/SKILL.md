---
name: create-issue
description: |
  問題・背景・原因を整理し、GitHub Issue として記録する。
  解決内容（対策・実装計画）は /anvil:impl-issue が担当する。
  トリガー: "issue を作りたい", "問題を記録したい", "バグを issue にして", "課題を起票"
user-invocable: true
argument-hint: "[issue-title]"
allowed-tools: Bash, AskUserQuestion
---

# /anvil:create-issue

問題・背景・原因を整理し、GitHub Issue として記録するスキル。
解決内容の分析・実装計画・ブランチ作成・PR 作成は `/anvil:impl-issue` が担当する。

## コマンド構文

```
/anvil:create-issue [issue-title]
```

| 引数        | 内容                                                |
| ----------- | --------------------------------------------------- |
| issue-title | Issue タイトル（省略時は対話で入力 / 問題から生成） |

---

## 前提条件 [MANDATORY]

### gh CLI 確認

```bash
gh --version
gh auth status
```

- 未インストール → `https://cli.github.com/` を案内して終了
- 未認証 → `gh auth login` を案内して終了

### リポジトリ確認

```bash
git rev-parse --is-inside-work-tree
git remote get-url origin
```

- git リポジトリでない → エラー終了
- リモート未設定 → エラー終了

---

## Phase 1: 問題・背景・原因の整理 [MANDATORY]

ユーザーとの対話、または現在のコンテキストから以下を整理する:

| 項目       | 内容                                   |
| ---------- | -------------------------------------- |
| タイトル   | 簡潔な問題の要約（50 文字以内目安）    |
| 背景・現象 | 何が起きているか・再現手順             |
| 原因       | 判明している原因（不明なら「調査中」） |

**整理が不十分な場合**: AskUserQuestion で不足項目を補う。

### Issue 本文テンプレート

```markdown
## 背景 / 現象

<現象・再現手順>

## 原因

<判明している原因。不明なら「調査中」>
```

> 対策・実装計画・受け入れ条件は `/anvil:impl-issue` が追記する。ここでは書かない。

---

## Phase 2: Issue 作成 [MANDATORY]

### 2.1 内容確認

以下を表示し AskUserQuestion で承認を得る:

```
タイトル: <title>
ラベル: <labels (任意)>

本文:
<body>
```

- **作成する** → 次へ
- **修正する** → Phase 1 に戻り再整理
- **キャンセル** → 終了

### 2.2 Issue 作成

```bash
gh issue create --title "<title>" --body "$(cat <<'EOF'
<body>
EOF
)"
```

作成された Issue 番号（`#N`）を記録する。

---

## 完了後の次ステップ

```
/anvil:impl-issue #<issue-number>
```

`/anvil:impl-issue` が以下を担当します:

- ブランチ作成（ベースブランチはプロジェクト設定から決定）
- 仕様書・ルール文書の調査
- 類似 PR のパターン学習
- 解決内容（対策・実装計画）を Issue に記録
- 実装・PR 作成

---

## エラーハンドリング

| エラー                         | 対応                                  |
| ------------------------------ | ------------------------------------- |
| gh CLI 未インストール / 未認証 | インストール / 認証手順を案内して終了 |
| `gh issue create` 失敗         | エラー内容を表示して終了              |
