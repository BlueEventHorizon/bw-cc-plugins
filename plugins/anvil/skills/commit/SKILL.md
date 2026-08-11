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

**ただし「ステージ済みがあるから」を理由に、確認せず Phase 4 へ進んではならない [MANDATORY]。**
先に 3.1 の状態検査を実行し、`stale_staged_paths`（index の内容が作業ツリーと食い違うパス）を確認する。

- `stale_staged_paths` が**空** かつ 未ステージ・未追跡の変更が無い → そのまま Phase 4 へ進む
- `stale_staged_paths` が**空でない** → 3.2 の確認へ進む。**そのまま commit すると、作業ツリーの
  最新ではなく古い内容が入る**（ステージ後にさらに編集したファイルで起きる）。差分は commit した
  後にしか現れないため、気付くのは常に手遅れになる
- ステージ済みと未ステージが混在する → 3.2 の確認へ進む（同じ変更の一部が落ちる可能性がある）

**ステージ対象は、いずれの場合も利用者に確認してから確定する。** AI が「必要と思われるファイル」を
自分の判断だけでステージしない。

#### 3.1 変更の状態を調べる [MANDATORY]

**ステージの確認より前に実行する。**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/commit/scripts/inspect_stage_state.py"
```

出力 JSON の `tracked_paths` / `untracked_paths` / `stale_staged_paths` を使う。

**`stale_staged_paths` が空でない場合、そのパスを利用者へ明示する [MANDATORY]**。「ステージ済みだが、その後さらに編集されている」ことは `git status` の 2 文字表記（`MM` / `AM`）にしか現れず、見落とすと古い内容が commit される。ステージし直せば解消するため、3.2 の選択肢は現在の内容で `git add` し直す形にする。

#### 3.2 ステージ対象を確認する [MANDATORY]

`AskUserQuestion` で次を提示する。

- **追跡済みファイルを全てステージする**（既定）→ `git add -u` を実行
- **ステージせずに終了する** → 終了

`stale_staged_paths` が空でない場合、選択肢の説明に「ステージし直して最新の内容にする」ことを明記する（`git add -u` は現在の内容で index を更新するため、これで解消する）。

未追跡ファイル（`untracked_paths`）がある場合は AskUserQuestion を使用して個別にステージするか確認する（`git add -u` の対象外であるため上記の選択とは別に問う）。

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
