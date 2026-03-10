---
name: commit
description: |
  変更内容を要約したコミットメッセージを生成し、commit & push する。
  ブランチ名から issue 番号またはラベルを自動抽出して末尾に付与。
  prepare-commit-msg フックがある場合は付与をスキップ（フック優先）。
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

| 引数 | 内容 |
|-----|------|
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

## Phase 1.5: コミットメッセージ言語の確認

`.git_information.yaml` に `commit_language` が設定済みであれば、それを使用してこの Phase をスキップする。

未設定の場合:

```bash
git log --oneline -10
```

- **日本語コミットが明確に多い** → `commit_language: ja` として `.git_information.yaml` に追記して確定
- **英語コミットが明確に多い** → `commit_language: en` として `.git_information.yaml` に追記して確定
- **コミットなし / `initial commit` のみ / 混在・判定困難** → AskUserQuestion を使用してユーザーに確認する:
  - 日本語（例: `feat: ログイン機能を追加`）
  - English（例: `feat: add login feature`）

確定した値を `.git_information.yaml` の `commit_language` フィールドに書き込む（ファイルが存在しない場合は作成）。

---

## Phase 2: prepare-commit-msg フックの動的確認

```bash
[ -x ".git/hooks/prepare-commit-msg" ] && echo "hook_exists"
```

- **フックあり** → issue 参照の付与をスキルでは行わない（Phase 3 をスキップ）。フックが `[ISSUE_REF]` 形式で自動付与する
- **フックなし** → Phase 3 へ

---

## Phase 3: issue 参照の抽出（フックなし時のみ）

ブランチ名から以下の優先順位で抽出する:

```bash
BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null) || BRANCH=""
ISSUE_REF=$(echo "$BRANCH" | grep -oE '[0-9]+' | head -1)
if [ -z "$ISSUE_REF" ]; then
  IFS='/' read -ra PARTS <<< "$BRANCH"
  if [ ${#PARTS[@]} -gt 1 ]; then
    ISSUE_REF="${PARTS[1]}"   # feature/{ここ}/xxx
  else
    ISSUE_REF="${PARTS[0]}"   # セグメント1つ → branch名そのまま
  fi
fi
```

**抽出ルール**:

| ブランチ名 | 抽出結果 | 理由 |
|-----------|---------|------|
| `feature/456/fix-login` | `456` | 最初の数字列 |
| `feature/762` | `762` | 最初の数字列 |
| `issue981` | `981` | 最初の数字列 |
| `feature/fix-login/detail` | `fix-login` | 数字なし → ARRAY[1] |
| `feature/no-slash` | `no-slash` | 数字なし → ARRAY[1] |
| `main` | `main` | 数字なし・セグメント1つ → ARRAY[0] |

detached HEAD（`git symbolic-ref` 失敗）の場合は `ISSUE_REF` を空にして続行する。

---

## Phase 4: コミットメッセージ生成

### 引数あり

指定されたメッセージをそのまま使用する。

### 引数なし

`git diff HEAD` の変更内容を解析して要約を自動生成する。変更の性質に応じて以下のプレフィックスを使用:

| 変更の性質 | プレフィックス |
|-----------|--------------|
| 新機能追加 | `feat:` |
| バグ修正 | `fix:` |
| リファクタリング | `refactor:` |
| 文書変更 | `docs:` |
| その他 | `chore:` |

### issue 参照の付与（フックなし時のみ）

`ISSUE_REF` が取得できた場合、メッセージ末尾に付与:

```
{message} #{ISSUE_REF}
```

例:
- `fix: ログインバリデーションを修正 #456`
- `feat: ダッシュボード画面を追加 #fix-login`
- `docs: README を更新 #main`

---

## Phase 5: ステージング確認

```bash
git status
```

未ステージのファイルがある場合、AskUserQuestion を使用してステージング対象を確認する:

- はい（追跡済みファイルを全てステージング）→ `git add -u`
- いいえ（現在のステージング状態のまま進む）

未追跡ファイルがある場合は AskUserQuestion を使用して個別に確認する。

---

## Phase 6: コミット確認 [MANDATORY]

以下の内容を表示した上で、AskUserQuestion を使用してコミットの承認を得る:

```
ブランチ: <current-branch>
メッセージ: <生成したコミットメッセージ>
対象ファイル: <ステージング済みファイル一覧>
```

- **コミットする** → `git commit -m "<生成されたメッセージ>"` を実行
- **キャンセル** → 終了（push は行わない）

フックがある場合、`prepare-commit-msg` が `[ISSUE_REF]` を自動付与する。

コミット失敗（pre-commit hook によるエラー等）の場合は、AskUserQuestion を使用してエラー内容を提示し対応を確認する。

---

## Phase 7: プッシュ確認 [MANDATORY]

コミット成功後、AskUserQuestion を使用してプッシュの承認を得る:

- **push しない（デフォルト）** → push せずに終了
- **push する** → リモートへの追跡設定を確認してから push:
  - 追跡設定あり → `git push`
  - 追跡設定なし → `git push -u origin <current-branch>`

push 失敗の場合は AskUserQuestion を使用してエラー内容を提示し対応を確認する。

---

## エラーハンドリング

| エラー | 対応 |
|--------|------|
| 変更なし | エラー終了・変更を促す |
| detached HEAD | `git symbolic-ref` 失敗 → issue 参照なしで続行 |
| コミット失敗 | AskUserQuestion でエラー内容を提示し対応を確認 |
| push 失敗 | AskUserQuestion でエラー内容を提示し対応を確認 |
