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
