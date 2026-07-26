# Phase 4: 類似PR調査ルール

今回の実装と**同じスコープ**（同様の機能・同様のレイヤー変更）のマージ済み PR を 3 件以上探して特定する。

特定した PR 番号は判定材料（Blast Radius の実測等）に使い、調査結果として実装工程へ引き継ぐ。PR の内容を使った実装パターンの学習・適用は実装工程の責務（`impl-issue` Phase 4）。

## コマンド例

`<owner>/<repo>` は Phase 0 で解決した値を使用する。

```bash
# キーワードで検索
gh pr list --repo <owner>/<repo> --state merged --search "<キーワード>" --limit 20

# PR の詳細確認
gh pr view <pr番号> --repo <owner>/<repo>

# 変更ファイル一覧確認
gh pr diff <pr番号> --repo <owner>/<repo> --name-only
```
