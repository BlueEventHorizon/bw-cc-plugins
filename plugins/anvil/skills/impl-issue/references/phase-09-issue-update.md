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

### `gh issue edit --body-file` は本文の完全置換である [MANDATORY]

`gh issue edit --body-file` に diff/追記の概念はない。渡したファイルの内容が Issue 本文を**丸ごと置き換える**。
「解決内容（対策・実装計画・TODO）のみを追記する」という本 Phase の原則を守るには、**既存本文を取得してから
末尾に実装計画を結合した「全文」を組み立てて渡す**必要がある。既存本文を持たないファイル（実装計画セクションのみ）を
そのまま `--body-file` に渡すと、背景・現象・原因（`/anvil:create-issue` が作成した課題の内容）を消してしまう。

0. **実行ごとに一意な作業ディレクトリを作る [MANDATORY]**: `/tmp/issue_body*.md` のような固定パスは、並行実行
   （複数セッション・複数 Issue の同時作業）や前回異常終了時の残骸ファイルと衝突し、**別 Issue の本文を誤って
   結合・上書きするリスク**がある。`mktemp -d` で実行ごとに一意なディレクトリを作り、`trap` でスクリプト終了時に
   確実に削除する：

   ```bash
   workdir=$(mktemp -d)
   trap 'rm -rf "$workdir"' EXIT
   ```

   以降の Step ではこの `$workdir` 配下のパスのみを使用する（固定パスを直接書かない）。

1. 計画内容を提示したうえで、`AskUserQuestion` を使用して Issue 更新を実行するか確認する。承認後のみ Step 2 へ進む
2. **既存本文を取得し、成否を検証する**（更新前に必ず実行。取得を飛ばして新規ファイルだけを渡さない）：

   **取得結果を検証する [MANDATORY]**: `gh` コマンドの失敗（認証切れ・レート制限・ネットワーク断）や本文が
   null の場合でも、シェルのリダイレクトは空（または `null` という文字列）のファイルをそのまま作成してしまう。
   取得コマンドの exit code と出力ファイルの非空を、**取得コマンドと同じシェル実行内で**確認し、失敗または空の
   場合は Step 3 へ進まず中断してユーザーに報告する（別のコマンド実行に分けると `$?` が別コマンドの結果に
   上書きされ検証が機能しなくなるため、1 ブロックで実行する）：

   ```bash
   gh issue view <issue番号> --repo <owner>/<repo> --json body --jq '.body' > "$workdir/issue_body_original.md"
   rc=$?
   if [ $rc -ne 0 ] || [ ! -s "$workdir/issue_body_original.md" ] || [ "$(cat "$workdir/issue_body_original.md")" = "null" ]; then
     echo "既存本文の取得に失敗しました。Issue 番号・権限・ネットワークを確認してください。" >&2
     exit 1
   fi
   ```

3. 既存本文 + 実装計画（テンプレート）を**1 つのファイルに結合**する。既存本文の内容は変更・削除・要約しない、そのまま末尾に追記する：

   ```bash
   cat "$workdir/issue_body_original.md" > "$workdir/issue_body.md"
   echo "" >> "$workdir/issue_body.md"
   tee -a "$workdir/issue_body.md" <<'BODY'
   <実装計画テンプレートの内容>
   BODY
   ```

4. 結合後のファイルを `--body-file` で渡す：

   ```bash
   gh issue edit <issue番号> --repo <owner>/<repo> --body-file "$workdir/issue_body.md"
   ```

5. **更新後、本文全体を確認し、既存の背景・現象・原因セクションが残っていることを検証する**（実装計画セクションの追加だけでなく、削れていないかを見る）：

   ```bash
   gh issue view <issue番号> --repo <owner>/<repo>
   ```

   既存セクションが失われていた場合は、直前の Issue 内容（本 Phase 開始前に取得したコメント・本文）から手作業で復元し、再度 `--body-file` で修正する。

## Issue 更新テンプレート

[assets/TEMPLATE.md](../assets/TEMPLATE.md) を参照。
