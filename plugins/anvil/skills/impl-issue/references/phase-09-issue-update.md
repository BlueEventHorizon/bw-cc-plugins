# Phase 9: Issue 更新ルール

## Issue 参照ルール

Issue に記載する参照は **GitHub / Figma で開けるものだけ** にする：

- ローカル相対パスは Issue に貼らない。すでに commit & push 済みで GitHub 上に存在するファイルは、ローカルパスではなく GitHub blob URL で記載する
- ローカルにしか存在しないファイル（未 push の `specs/design/...` など）は、Issue の関連ドキュメント欄には載せない
- 上記ルールは関連ドキュメント欄だけでなく、実装スコープ表・TODO 内の参照表記にも適用する
- Figma は URL をそのまま記載する
- 外部リポジトリの仕様書を参照する場合は、対象ファイルの GitHub URL（`html_url`）を取得して記載する

## 日本語等の非 ASCII を含む URL のエンコード

ディレクトリ名・ファイル名に **日本語等の非 ASCII 文字を含む** リポジトリを参照する場合、Markdown リンク `[text](url)` で URL 部分に非 ASCII をそのまま書くとレンダラーや Markdown パーサーによってリンクが途中で切れたり認識されない場合がある。**URL 部分はパーセントエンコードした形式で記載すること。**

リンクテキスト（`[]` 内）は元の文字列のまま可読性を優先する。エンコードするのは URL 部分（`()` 内）だけ。

### 注意点

- ディレクトリ構造はリポジトリの最新状態を `gh api` で確認してから書く（過去に存在したパスが移動・改名されているケースがある）
- `+` 等の Markdown / URL で特殊な扱いを受ける文字も適切にエンコードする
- 既にエンコード済みの URL を再度エンコードすると二重エンコードされてリンクが壊れる。**一度デコードしてから再エンコード**する

### 推奨：URL の取得・エンコード手順

1. パスの存在と正規 `html_url` を `gh api` で取得（`html_url` がエンコード済み URL を返す）：

   ```bash
   gh api "repos/<owner>/<repo>/contents/<パス>?ref=<branch>" --jq '.html_url'
   ```

2. 既存リンクをまとめてエンコードしたい場合は `urllib.parse.quote` / `unquote` を使い、二重エンコードを防ぐ（一度 `unquote` してから `quote` する）

このルールは Issue 本文だけでなく、**PR 本文・コミットメッセージ内のリンク**にも同様に適用する（Issue → PR にコピペするケースが多いため、最初から正しい形式で書いておく）。

## Issue 更新手順

`<owner>/<repo>` は Phase 0 で解決した値を使用する。

1. ユーザーに計画内容を提示し確認する
2. 本文を一時ファイルに書き出してから `--body-file` で渡す（特殊文字・バッククォート・`$` が含まれても安全）：

   ```bash
   tee /tmp/issue_body.md <<'BODY'
   <本文>
   BODY

   gh issue edit <issue番号> --repo <owner>/<repo> --body-file /tmp/issue_body.md
   ```

3. 更新後、内容を確認する：

   ```bash
   gh issue view <issue番号> --repo <owner>/<repo>
   ```

## Issue 更新テンプレート

[assets/TEMPLATE.md](../assets/TEMPLATE.md) を参照。
