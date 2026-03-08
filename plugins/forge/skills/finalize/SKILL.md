---
name: finalize
description: |
  文書作成後の品質確定ステップ。レビュー+自動修正と ToC 更新を一括実行する。
  create-requirements / start-design / start-plan の後続処理として使用。
user-invocable: true
argument-hint: "<type> [target] [--refactor [N]]"
---

# /forge:finalize

`create-requirements` / `start-design` / `start-plan` で作成した文書の品質を確定する。
レビュー+自動修正を N サイクル実行し、specs ToC を更新する。

## コマンド構文

```
/forge:finalize <type> [target] [--refactor [N]]

type:     requirement | design | plan
target:   ファイルパス（省略時は直前に作成したファイルを推定）
--refactor [N]: レビュー+修正サイクル数（省略時 N=1）
```

### 使用例

```bash
# 要件定義書を 1 サイクルでレビュー+修正（デフォルト）
/forge:finalize requirement specs/login/requirements/requirements.md

# 設計書を 3 サイクル
/forge:finalize design specs/login/design/design.md --refactor 3

# レビューのみ（修正なし）
/forge:finalize plan specs/login/plan/plan.md --refactor 0
```

---

## ワークフロー

### Step 1: 引数解析

- `type` → レビュー種別（`requirement` / `design` / `plan`）
- `target` → 対象ファイルパス
  - 省略時: 会話コンテキストから直前に作成されたファイルを推定してユーザーに確認
- `--refactor [N]` → サイクル数（省略時 N=1）

### Step 2: レビュー+修正

以下を呼び出す:

```
/forge:review {type} {target} --refactor {N}
```

`/forge:review` が指定サイクル数分のレビュー+修正を実行し、サマリーを返す。

### Step 3: ToC 更新

`/create-specs-toc` Skill が利用可能か確認する（`.claude/skills/create-specs-toc/SKILL.md` の存在で判断）。

- 利用可能 → `/create-specs-toc` を実行
- 利用不可 → スキップ（エラーにしない）

### Step 4: 完了報告

```
✅ finalize 完了

対象: {target}
レビュー: {N} サイクル実施（🔴修正済: X件 / 🟡修正済: Y件）
ToC: {更新済み / スキップ}
```
