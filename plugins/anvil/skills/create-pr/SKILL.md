---
name: create-pr
description: |
  コミット差分からタイトル・本文を生成し、PR を素早く作成できる。
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

| 引数        | 内容                                                                                    |
| ----------- | --------------------------------------------------------------------------------------- |
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
  owner: "<org-or-user>" # git remote URL から抽出
  repo: "<repo-name>" # git remote URL から抽出
  remote_url: "<url>" # git remote get-url origin の出力
  default_base_branch: main # 初回確認済みのデフォルトベースブランチ
  pr_template: .github/PULL_REQUEST_TEMPLATE.md # 存在すれば記録
```

### 1.4 現在ブランチの確認

```bash
git branch --show-current
```

- main / master / develop ブランチの場合 → AskUserQuestion を使用して警告し確認する（続行 or 中止）

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

| ブランチ名パターン | PR タイトル              |
| ------------------ | ------------------------ |
| `feature/xxx-yyy`  | `[Feature] Xxx yyy`      |
| `fix/xxx`          | `[Fix] Xxx`              |
| `chore/xxx`        | `[Chore] Xxx`            |
| `docs/xxx`         | `[Docs] Xxx`             |
| `refactor/xxx`     | `[Refactor] Xxx`         |
| その他             | ブランチ名をそのまま使用 |

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

### 3.4 Issue クローズキーワードの付与

コミットメッセージ（`git log <base>..HEAD`）や会話コンテキストから、この PR が解決する Issue 参照（`Fixes #N` / `Closes #N` / `Resolves #N` 等）を検出する。検出した Issue ごとに、参照先リポジトリに応じて PR 本文（概要セクション付近）に以下を追記する:

| 参照先 Issue       | 追記する記法                                                                                                                                                |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **同一リポジトリ** | `Closes #<N>`（GitHub の自動クローズキーワードとして機能する）                                                                                              |
| **別リポジトリ**   | `Closes https://github.com/<owner>/<repo>/issues/<N>`（フル URL。自動クローズキーワードは同一リポジトリ限定のため機能しないが、追跡用リンクとして明記する） |

該当 Issue が見つからない場合はこの節をスキップする（無理に追記しない）。

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
  - 失敗した場合は AskUserQuestion を使用してエラー内容を提示し対応を確認する（中止 or 別対応）
- **存在する** → ローカル HEAD が origin の同名ブランチと一致するか確認する（remote-tracking ref はローカルキャッシュのため fetch なしでは古い可能性があるため、`git ls-remote` でリモートを直接問い合わせる）:
  ```bash
  git rev-parse HEAD
  git ls-remote --heads origin <current-branch>  # 出力の先頭列（sha）と HEAD を比較
  ```
  - **一致** → 追加 push 不要のまま 4.2 へ
  - **不一致（ローカルに未 push commit がある stale 状態）** → プッシュ:
    ```bash
    git push origin <current-branch>
    ```
    - 失敗した場合は AskUserQuestion を使用してエラー内容を提示し対応を確認する（中止 or 別対応）

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

## Phase 6: CI 結果確認 [MANDATORY]

### 6.1 CI 設定の有無を確認

```bash
git rev-parse --show-toplevel
```

で取得したリポジトリルート配下に `.github/workflows/*.yml` または `.github/workflows/*.yaml` が存在するか確認する。

- **存在しない**（CI 未設定）→ 本 Phase をスキップして終了
- **存在する** → 6.2 へ

### 6.2 CI 結果の確認（完了まで待機）

Phase 4.2 で作成した PR の番号に対し、`gh pr checks` の `--watch` オプションで CI 完了までブロッキング待機する（自前のポーリングループは実装しない。gh CLI 標準機能に委譲する）:

```bash
gh pr checks <PR番号> --repo <owner>/<repo> --watch
```

- **終了コード 0（全件成功）** → 6.3 へ
- **終了コード非 0（1 件以上失敗）** → 6.4 へ

### 6.3 CI 全件成功時

完了報告に CI 結果を追記する:

```
CI: ✅ すべてのチェックが成功しました
```

### 6.4 CI 失敗時

```bash
gh pr checks <PR番号> --repo <owner>/<repo>
```

の出力から失敗したチェック名・詳細 URL を要約し、ユーザーに提示したうえで `AskUserQuestion` で対応を確認する:

```
CI が失敗しました:
<失敗したチェックの要約>

対応を選択してください:
- 修正する: 失敗原因を調査し、修正してから再度 push する
- このまま報告して終了: 現状の PR URL と CI 失敗内容を報告して終了する
```

---

## エラーハンドリング

| エラー                                          | 対応                                                                                      |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------- |
| gh CLI 未インストール                           | `https://cli.github.com/` のインストール手順を案内して終了                                |
| gh CLI 未認証                                   | `gh auth login` を案内して終了                                                            |
| main/master/develop ブランチから実行            | AskUserQuestion で警告し確認（続行 or 中止）                                              |
| コミット差分なし                                | エラー終了・コミットを促す                                                                |
| push 失敗                                       | AskUserQuestion でエラー内容を提示し対応を確認                                            |
| リモートブランチが stale（未 push commit あり） | ローカル HEAD を origin へ push してから続行。失敗時は AskUserQuestion で対応を確認       |
| PR 作成失敗                                     | エラー内容を表示して終了                                                                  |
| CI 失敗                                         | 失敗内容を要約して提示し、AskUserQuestion で対応（修正する / このまま報告して終了）を確認 |
