# Phase 10: Issue 更新ルール

**書き込む内容**: 解決内容（対策・実装計画・TODO）のみを追記する。
背景/現象・原因は `/anvil:create-issue` が記載済みのため上書きしない。

> ⚠️ **暫定運用の警告**
>
> 本来は `/anvil:update-issue` Skill が Issue 本文の特定領域のみを差し替える方式で書き戻す予定だが、**現時点では未実装**である。
>
> したがって暫定的に `gh issue edit --body-file` で本文全体を更新するが、以下を**必ず**遵守すること（ユーザー記述セクションは一字一句保持する）:
>
> 1. 既存本文のうち `/anvil:create-issue` が書いたユーザー記述セクション（`## 背景 / 現象`、`## 原因` 等）は**一字一句保持**する
> 2. 解決内容（対策・実装計画・TODO）は既存本文の**末尾に追記**する形に限定する
> 3. 既存セクションの**並び順・本文・空行**を改変しない
> 4. `/anvil:update-issue` 実装後はこの手順を廃止する

## Issue 参照ルール

Issue に記載する参照は **GitHub / Figma でブラウザから開けるものだけ** にする：

- commit & push 済みで GitHub 上に存在するファイルは GitHub blob URL で記載する
- ローカルにしか存在しないファイル（未 push の `specs/design/...` など）は関連ドキュメント欄には載せない
- 上記ルールは関連ドキュメント欄だけでなく、実装スコープ表・TODO 内の参照表記にも適用する
- Figma URL はそのまま記載する

## Issue 更新手順

1. ユーザーに計画内容を提示し確認する
2. 本文を一時ファイルに書き出してから `--body-file` で渡す：

```bash
# 本文を一時ファイルに書き出す（特殊文字・バッククォート・ドル記号が含まれても安全）
tee /tmp/issue_body.md <<'BODY'
<本文>
BODY

# --body-file で渡す（<owner>/<repo> は Phase 0 で取得した値を使用）
gh issue edit <issue番号> --repo <owner>/<repo> --body-file /tmp/issue_body.md
```

3. 更新後、内容を確認する：

```bash
gh issue view <issue番号> --repo <owner>/<repo>
```

## Issue 更新テンプレート

[assets/TEMPLATE.md](../assets/TEMPLATE.md) を参照。
