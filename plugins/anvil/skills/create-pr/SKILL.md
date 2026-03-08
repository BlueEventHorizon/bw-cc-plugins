---
name: create-pr
description: |
  現在のブランチから GitHub PR をドラフト作成する。AI専用ではなくユーザー起動。
  PR テンプレート自動適用・コミット差分からタイトル/本文生成。gh CLI 必須。
  トリガー: "PR を作成", "プルリクエスト作成", "create-pr", "PR 出して"
user-invocable: true
argument-hint: "[base-branch]"
---

# /anvil:create-pr

現在のブランチのコミット差分を解析し、GitHub PR をドラフト作成する。

## コマンド構文

```
/anvil:create-pr [base-branch]
```

| 引数 | 内容 |
|-----|------|
| base-branch | ベースブランチ（省略時は `.git_information.yaml` > develop > main > master の順で決定） |

---

## Phase 1: 環境確認 [MANDATORY]

### 1.1 gh CLI の確認

```bash
gh --version
```

- **失敗** → エラー終了:
  ```
  Error: gh CLI が必要です。
  インストール: https://cli.github.com/
  ```

### 1.2 gh CLI 認証確認

```bash
gh auth status
```

- **未認証** → エラー終了:
  ```
  Error: gh CLI が認証されていません。
  実行してください: gh auth login
  ```

### 1.3 .git_information.yaml の確認

`.git_information.yaml` がプロジェクトルートに存在するか確認する。

- **存在する** → 読み込んで `owner` / `repo` / `default_base_branch` / `pr_template` を取得
- **存在しない** → git コマンドで自動検出:
  ```bash
  git remote get-url origin
  ```
  → URL から owner・repo 名を正規表現で抽出
  → `.git_information.yaml` の生成をユーザーに提案（任意。拒否してもスキップして続行）

#### .git_information.yaml のスキーマ

```yaml
version: "1.0"
github:
  owner: "<org-or-user>"          # git remote URL から抽出
  repo: "<repo-name>"             # git remote URL から抽出
  remote_url: "<url>"             # git remote get-url origin の出力
  default_base_branch: main       # 初回確認済みのデフォルトベースブランチ
  pr_template: .github/PULL_REQUEST_TEMPLATE.md  # 存在すれば記録
```

### 1.4 現在ブランチの確認

```bash
git branch --show-current
```

- main / master / develop ブランチの場合 → 警告してユーザーに確認（続行 or 中止）

### 1.5 ベースブランチの決定

優先順位: 引数 > `.git_information.yaml` の `default_base_branch` > develop > main > master

```bash
git branch -a | grep -E "(develop|main|master)"
```

で存在確認してから決定する。

---

## Phase 2: コミット差分確認 [MANDATORY]

```bash
git log <base>..HEAD --oneline
```

- **コミット 0 件** → エラー終了:
  ```
  Error: <base> からのコミットがありません。
  変更をコミットしてから再試行してください。
  ```
- **1 件以上** → Phase 3 へ

> **注意**: `git status` の状態（ステージングされた変更等）は PR 作成可否の判断に使用しない。

---

## Phase 3: PR 情報生成

### 3.1 差分情報の収集

```bash
git log <base>..HEAD                 # コミット詳細（本文生成に使用）
git diff <base>...HEAD --stat        # 変更ファイル統計（概要に使用）
```

### 3.2 PR タイトルの生成

ブランチ名から変換:

| ブランチ名パターン | PR タイトル |
|-----------------|------------|
| `feature/xxx-yyy` | `[Feature] Xxx yyy` |
| `fix/xxx` | `[Fix] Xxx` |
| `chore/xxx` | `[Chore] Xxx` |
| `docs/xxx` | `[Docs] Xxx` |
| `refactor/xxx` | `[Refactor] Xxx` |
| その他 | ブランチ名をそのまま使用 |

コミット内容からタイトルを補正する（コミットメッセージが明確な場合はそちらを優先）。

### 3.3 PR 本文の生成

PR テンプレートの適用:
1. `.git_information.yaml` の `pr_template` パスを確認
2. なければ `.github/PULL_REQUEST_TEMPLATE.md` を確認
3. どちらも存在しない場合は下記デフォルト構造を使用:

```markdown
## 概要
{コミットメッセージ・差分から自動生成}

## 変更内容
{git diff --stat の結果を整形}

## テスト
- [ ] 動作確認済み
```

テンプレートが存在する場合は Read して骨格に使用し、コミット差分から内容を補完する。

---

## Phase 4: リモートプッシュ & PR 作成

### 4.1 リモートへのプッシュ

現在ブランチがリモートに存在するか確認:

```bash
git ls-remote --heads origin <current-branch>
```

- **存在しない（未プッシュ）** → プッシュ:
  ```bash
  git push -u origin <current-branch>
  ```
  - 失敗した場合はエラー内容を表示してユーザーに確認（中止 or 別対応）

### 4.2 PR 作成

```bash
/bin/bash -c 'gh pr create --draft --base <base> --title "<title>" --body "$(cat <<'\''EOF'\''
<body>
EOF
)"'
```

**PR 本文に含めないもの**:
- `🤖 Generated with [Claude Code](https://claude.com/claude-code)`
- `Co-Authored-By: Claude <noreply@anthropic.com>`

---

## Phase 5: 完了

PR URL を表示する。

```
PR を作成しました:
  <PR URL>
```

ブラウザで開くか確認（AskUserQuestion）:
```
ブラウザで PR を開きますか？
```

- **はい** → `gh pr view --web`
- **いいえ** → 終了

---

## エラーハンドリング

| エラー | 対応 |
|--------|------|
| gh CLI 未インストール | `https://cli.github.com/` のインストール手順を案内して終了 |
| gh CLI 未認証 | `gh auth login` を案内して終了 |
| main/master/develop ブランチから実行 | 警告してユーザーに確認（続行 or 中止） |
| コミット差分なし | エラー終了・コミットを促す |
| push 失敗 | エラー内容を表示してユーザーに確認 |
| PR 作成失敗 | エラー内容を表示して終了 |
