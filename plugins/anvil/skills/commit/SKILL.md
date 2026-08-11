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
先に 3.1 の分類を実行し、`stale_staged_paths`（index の内容が作業ツリーと食い違うパス）を確認する。

- `stale_staged_paths` が**空** かつ 未ステージ・未追跡の変更が無い → そのまま Phase 4 へ進む
- `stale_staged_paths` が**空でない** → 3.2 の確認へ進む。**そのまま commit すると、作業ツリーの
  最新ではなく古い内容が入る**（ステージ後にさらに編集したファイルで起きる）。差分は commit した
  後にしか現れないため、気付くのは常に手遅れになる
- ステージ済みと未ステージが混在する → 3.2 の確認へ進む（同じ変更の一部が落ちる可能性がある）

**ステージ対象は、いずれの場合も利用者に確認してから確定する。** AI が「必要と思われるファイル」を
自分の判断だけでステージしない。

#### 3.1 変更を分類する [MANDATORY]

**一括ステージの確認より前に実行する。** 順序を逆にすると `git add -u` が先に走り、生成物を巻き込んでからでは選択の余地がなくなる。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/commit/scripts/classify_generated_index.py"
```

出力 JSON の `branch` / `toc_paths` / `other_paths` / `untracked_paths` / `stale_staged_paths` を使う。保護ブランチの解決は Phase 3.5 と同じ優先順位で、**この時点で**行う（`.git_information.yaml` の `default_base_branch`、無ければ `develop` → `main` → `master`）。

**`stale_staged_paths` が空でない場合、そのパスを利用者へ明示する [MANDATORY]**。「ステージ済みだが、その後さらに編集されている」ことは `git status` の 2 文字表記（`MM` / `AM`）にしか現れず、見落とすと古い内容が commit される。ステージし直せば解消するため、3.2 の選択肢は現在の内容で `git add` し直す形にする。

#### 3.2 ステージ対象を確認する [MANDATORY]

`toc_paths` が空、または現在のブランチが保護ブランチの場合 → 従来どおり次を提示する。

- **追跡済みファイルを全てステージする** → `git add -u` を実行
- **ステージせずに終了する** → 終了

`toc_paths` が空でなく、**かつ現在のブランチが保護ブランチ以外**の場合 → **`git add -u` を提示しない**。代わりに次を提示する。

- **ToC 差分を除いてステージする**（既定）→ `other_paths` のパスだけを明示して `git add -- <paths>` を実行
- **ToC 差分も含めてステージする** → `git add -u` を実行
- **ステージせずに終了する** → 終了

**`other_paths` が空の場合（変更が ToC だけの場合）は「ToC 差分を除いてステージする」を提示しない。** 空の pathspec で `git add --` を実行するとエラーになる。この場合は次の 2 つだけを提示する。

- **ステージせずに終了する**（既定）→ 「ToC 以外に commit 対象が無い」旨を報告して終了
- **ToC 差分も含めてステージする** → `git add -u` を実行

ToC だけが書き換わる状態は、feature ブランチで検索を実行した後の通常の状態である（検索前に索引更新が走るため）。**この場合に既定で終了するのは、捨てられる commit を作らないためである。**

未追跡ファイル（`untracked_paths`）がある場合は AskUserQuestion を使用して個別にステージするか確認する（`git add -u` の対象外であるため上記の選択とは別に問う）。

**`git add -u` を既定の選択肢から外す理由**: ToC は git 管理下の生成物であり、保護ブランチ以外で commit すると並行して作業している他のワークツリー・他の作業者の再生成結果と衝突し、merge 時に破棄される。一括ステージを提示すると、選んだ利用者は生成物を含めた自覚を持てないまま、捨てられる作業を積むことになる。

再生成そのものは禁止しない（検索の正確さのために必要であり、対象文書に変更がなければ ToC は書き換わらない）。判断するのは **commit に含めるかどうか**だけである。

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
