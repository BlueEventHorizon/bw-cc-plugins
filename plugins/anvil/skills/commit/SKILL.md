---
name: commit
description: |
  コミットメッセージを自動生成し、手間なく commit & push できる。
  トリガー: "コミットして", "commit して", "push して", "commit & push"
user-invocable: true
argument-hint: "[message]"
---

# /anvil:commit

変更内容を要約したコミットメッセージを生成し、GitHub へ commit & push する。

## コマンド構文

```
/anvil:commit [message]
```

| 引数    | 内容                                               |
| ------- | -------------------------------------------------- |
| message | コミットメッセージ（省略時は変更内容から自動生成） |

---

## Phase 0: フォーマット適用 [MANDATORY]

commit 前に format 乱れを必ず解消する。format ずれたまま commit すると、後で誰かが fmt を走らせたときに無関係なファイルが diff に混入し、PR レビューや git blame が混乱する。

共有スクリプトで実行する（存在チェック + 実行、条件判定ロジックのインライン重複を避けるため）:

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/run_dprint_fmt.sh"
```

`dprint fmt` が新たにファイルを書き換えた場合、それも本 commit に含める (関連: ユーザー方針「dprint fmt がスコープ外ファイルを整形しても revert 不要」)。

`dprint` 以外の formatter (prettier / black / rustfmt 等) が project で使われている場合は、CLAUDE.md か README.md の指示に従って手動適用したうえで本 commit に含める。

---

## Phase 1: 変更確認 [MANDATORY]

```bash
git status --porcelain
```

変更なし → エラー終了:

```
Error: コミットする変更がありません。
変更をファイルに保存してから再試行してください。
```

---

## Phase 2: コミットメッセージ生成

### 引数あり

指定されたメッセージをそのまま使用する。

### 引数なし

`git diff HEAD` の変更内容を解析して要約を自動生成する。変更の性質に応じて以下のプレフィックスを使用:

| 変更の性質       | プレフィックス |
| ---------------- | -------------- |
| 新機能追加       | `feat:`        |
| バグ修正         | `fix:`         |
| リファクタリング | `refactor:`    |
| 文書変更         | `docs:`        |
| その他           | `chore:`       |

---

## Phase 3: ステージング確認 [MANDATORY]

```bash
git status
```

**原則: ステージ済みファイルのみをコミット対象とする。自動で `git add` しない。**

ステージ済みファイルがある場合 → そのまま Phase 4 へ進む。

ステージ済みファイルがなく、未ステージの変更がある場合 → AskUserQuestion を使用して確認する:

- **追跡済みファイルを全てステージする** → `git add -u` を実行
- **ステージせずに終了する** → 終了

未追跡ファイルがある場合は AskUserQuestion を使用して個別にステージするか確認する。

---

## Phase 3.5: 保護ブランチチェック [MANDATORY]

保護ブランチへの直接 commit を未然に防ぐ。

### 3.5.1 現在のブランチと保護ブランチの解決

```bash
git branch --show-current
```

保護ブランチの解決優先順位（`create-pr` skill と同一の優先順位に揃える）:

1. `.git_information.yaml` の `default_base_branch`
2. 上記が無い場合 `develop` → `main` → `master` の順で、リポジトリに存在するものを採用

### 3.5.2 現在のブランチが保護ブランチと一致する場合

`AskUserQuestion` で警告し、対応を確認する:

```
現在のブランチ (<current-branch>) は保護ブランチです。直接 commit せず feature ブランチを作成することを推奨します。

提案する feature ブランチ名: feature/<Phase 2 で生成したコミットメッセージから推定したスラッグ>
```

- **feature ブランチを作成して続行**（デフォルト）→ 提案したブランチ名を `AskUserQuestion` で承認・修正させた上で `git checkout -b <branch>` を実行し、Phase 4 へ進む
- **このまま保護ブランチに commit する（非推奨）** → 警告を出したまま Phase 4 へ進む
- **キャンセル** → 終了（commit しない）

ブランチ名の推定は AI が Phase 2 で生成したコミットメッセージ（`fix(anvil): ...` 等）の要約部分を英語スラッグ化して `feature/` を前置する（例: `fix(anvil): triage-issue Phase 7 条件3の測定単位を客観的な閾値に修正` → `feature/anvil-clarify-blast-radius-threshold`）。

### 3.5.3 現在のブランチが保護ブランチと一致しない場合

そのまま Phase 4 へ進む（確認不要）。

---

## Phase 4: コミット確認 [MANDATORY]

以下の内容を表示した上で、AskUserQuestion を使用してコミットの承認を得る:

```
ブランチ: <current-branch>
メッセージ: <生成したコミットメッセージ>
対象ファイル: <ステージング済みファイル一覧>
```

- **コミットする** → `git commit -m "<生成されたメッセージ>"` を実行
- **キャンセル** → 終了（push は行わない）

コミット失敗（pre-commit hook によるエラー等）の場合は、AskUserQuestion を使用してエラー内容を提示し対応を確認する。

---

## Phase 5: プッシュ確認 [MANDATORY]

コミット成功後、AskUserQuestion を使用してプッシュの承認を得る:

- **push しない（デフォルト）** → push せずに終了
- **push する** → リモートへの追跡設定を確認してから push:
  - 追跡設定あり → `git push`
  - 追跡設定なし → `git push -u origin <current-branch>`

push 失敗の場合は AskUserQuestion を使用してエラー内容を提示し対応を確認する。

---

## エラーハンドリング

| エラー        | 対応                                           |
| ------------- | ---------------------------------------------- |
| 変更なし      | エラー終了・変更を促す                         |
| detached HEAD | `git symbolic-ref` 失敗 → ブランチ名なしで続行 |
| コミット失敗  | AskUserQuestion でエラー内容を提示し対応を確認 |
| push 失敗     | AskUserQuestion でエラー内容を提示し対応を確認 |
