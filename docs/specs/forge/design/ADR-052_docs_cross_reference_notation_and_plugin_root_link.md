# ADR-052 docs/ 内部相互参照の記法統一と `${CLAUDE_PLUGIN_ROOT}` 実体アクセスの改善

## メタデータ

| 項目     | 値                                                               |
| -------- | ---------------------------------------------------------------- |
| ADR ID   | ADR-052                                                          |
| Status   | accepted                                                         |
| 決定日   | 2026-07-23                                                       |
| 関連設計 | N/A（既存 DES に対応しない、forge プラグイン基盤インフラの改善） |

## 1. コンテキスト

`plugins/forge/docs/` 配下の全 20 文書を精査し、文書間の相互参照リンクを「参照先を読まないと本文の主張・規定が検証できないか」を基準に棚卸しした過程で、以下 3 点の関連する問題が判明した。

### 問題 1: `${CLAUDE_PLUGIN_ROOT}` は経路によって解決性質が異なる

`${CLAUDE_PLUGIN_ROOT}` はプラグインのランタイム変数だが、その解決タイミング・解決有無は AI がその文字列に遭遇する経路によって異なることを実測で確認した。

- **`hooks.json` の `command` フィールド**: Claude Code が spawn 前に実パスへ文字列置換する。実プロセスの環境変数としても渡る（`SessionStart` hook を実際に仕込み、stdin JSON・環境変数ダンプで実測確認）。
- **`SKILL.md` 本文が実際にスキルとして起動されコンテキストへ注入される経路**: 同様に実パスへ置換される（`forge:query-forge-rules` を実起動し、注入内容が生ファイルと異なり実パスに解決されていることを実測確認）。
- **`Read` ツールで `SKILL.md` / `docs/*.md` を生ファイルとして直接読む経路**: 置換は一切行われず、リテラル文字列 `${CLAUDE_PLUGIN_ROOT}` のまま残る。プラグイン開発・レビュー・監査作業（本リポジトリでの通常の作業）はこの経路を常用する。

### 問題 2: `docs/` 内部の相互参照が `${CLAUDE_PLUGIN_ROOT}` 形式で書かれていた

`docs/` はフラット構成（サブディレクトリを持たない）で、文書同士の相互参照は本質的に同一ディレクトリの兄弟ファイル参照である。しかし既存の `docs/*.md` は `document_style_guide.md` §5.1（旧版）の「フルパス必須」規約に従い、`docs/` 内部の参照にも `${CLAUDE_PLUGIN_ROOT}/docs/xxx.md` 形式を用いていた。この形式は「問題 1」の直接 Read 経路では解決されない生の文字列として残り、AI が実体パスへ変換する手間を都度発生させていた。一方、`docs/` の外側にある `SKILL.md` / `agents/*.md` / `commands/*.md` から `docs/` 内の文書を参照する場合は、相対パスでは `docs/` を起点にできず誤った場所を指すため、`${CLAUDE_PLUGIN_ROOT}/docs/xxx.md` 形式が引き続き必須である。

### 問題 3: ダウンストリーム環境での実体パス確認コスト

marketplace 経由でインストールされた環境では `${CLAUDE_PLUGIN_ROOT}` の実体が `~/.claude/plugins/cache/.../forge/...` のような非決定的なキャッシュパスになる。「問題 1」の直接 Read 経路でこの実体にアクセスする際、AI は `ps -axo args | grep plugin-dir` 等のプロセス起動引数の逆引きで都度実パスを推測する必要があり、`CLAUDE.md`「外部プラグインの実体確認」節が明示的に手順化しているほどのコストがかかる。

## 2. 決定

### 2.1 `docs/` 内部の相互参照は相対パス（Markdown リンク構文）に統一する

`docs/` 内の文書が `docs/` 内の他文書を参照する場合、`docs/` を起点とした相対パスを Markdown リンク構文で記述する（例: `[design_format.md](design_format.md)`）。地の文でのファイル名のみの言及（リンク構文なし）は用いない。

**採用理由**: 直接 Read 経路（問題 1）では、参照元ファイルと参照先ファイルが同一ディレクトリの兄弟である限り、相対パスは `${CLAUDE_PLUGIN_ROOT}` の解決有無に依存せず常に正しく解決される。Markdown リンク構文は人間が読んだ場合にもクリック可能で、地の文言及より曖昧性が低い。

### 2.2 `SKILL.md` / `agents/*.md` / `commands/*.md` からの `docs/` 参照は `${CLAUDE_PLUGIN_ROOT}/docs/` 形式を維持する

これらは `docs/` の外側に位置するため、相対パスでは解決できない。引き続きフルパス表記 `${CLAUDE_PLUGIN_ROOT}/docs/xxx.md` を用いる。この経路は実際のスキル起動時（問題 1 で確認済み）には自動解決されるため、記法自体に問題はない。

### 2.3 `document_style_guide.md` §5.1 を改訂する

旧 §5.1 は参照元の位置（`docs/` 内部か外部か）を区別せず一律フルパスを規定していた。2.1 / 2.2 の使い分けを明文化し、SoT の矛盾を解消した。

### 2.4 `SessionStart` hook による symlink 自己修復を導入する（問題 3 への対処）

`plugins/forge/hooks/hooks.json` の `SessionStart` に `ensure_plugin_root_link.py` を登録し、セッション開始のたびに `<project_root>/.claude/forge-docs` を現在の `${CLAUDE_PLUGIN_ROOT}/docs` 実体への symlink として作成・修復する。プラグイン全体ではなく `docs/` サブパスのみに限定する（比例性、`scope_proportionality_spec.md` §2）。symlink はマシン固有の絶対パスを含むため `.gitignore` で非追跡とする。

この symlink は AI（および人間）が直接 Read 経路でダウンストリーム環境の実体へ素早くアクセスするための利便性機構であり、`docs/`・SKILL.md 等の配布物本文に記述する正式な参照記法ではない（2.1 / 2.2 を置き換えない）。

## 3. 検討した代替案

| 代替案                                                                                      | 棄却理由                                                                                                                                                                                      |
| ------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| symlink をプラグインルート全体（`plugins/forge/` 全体）に対して作成する                     | 今回の動機（`docs/` 相互参照解決）に対して開示範囲が過大。`scope_proportionality_spec.md` の比例性原則に反する                                                                                |
| `docs/` 内部の参照も含め、全参照記法を `${CLAUDE_PLUGIN_ROOT}/docs/` に統一する（現状維持） | 直接 Read 経路で解決されない生文字列が残り続け、AI の実体パス推測コストを毎回発生させる。docs/ がフラット構成である事実を活用できない                                                         |
| symlink を導入せず、都度 `ps`/`PATH` 逆引きで実体パスを解決する運用を継続する               | ダウンストリーム環境での調査コストが恒久的に残る。`SessionStart` hook での自動化が技術的に実現可能であることを実測で確認済みのため、採用しない理由がない                                      |
| symlink を人間の手動運用ルール（都度貼り直す）に委ねる                                      | 貼り忘れ・タイミングのズレが「サイレントに古い実体を指す」失敗モードを生む（`document_style_guide.md` §8 の「関連リンクは腐敗しがち」と同根の問題）。自動化（hook）でのみ「必ず」を保証できる |

## 4. 影響

`plugins/forge/docs/*.md` のうち約 15 ファイルの docs 内部相互参照（計 20 箇所超）を相対パス形式に書き換えた。`document_style_guide.md` §5.1 を改訂した。`plugins/forge/scripts/ensure_plugin_root_link.py`（新規、テスト12件）と `plugins/forge/hooks/hooks.json` の `SessionStart` 登録を追加した。`.gitignore` に `.claude/forge-docs` を追加した。

得られるもの: docs 内部参照の解決が `${CLAUDE_PLUGIN_ROOT}` の解決性質に依存しなくなり恒久的に安全になる。ダウンストリーム環境での実体アクセスコストが `SessionStart` hook による自動化で削減される。

失うもの・新たに生じる制約: 今後 `docs/` に新規文書を追加する際、内部参照と外部参照（SKILL.md 等からの参照）で記法を使い分ける必要があり、執筆者が §5.1 の区別を把握している前提が生まれる。symlink 機構自体の保守（`ensure_plugin_root_link.py` のテスト維持）が必要になる。

### 4.1 既知の未解決事項（本 ADR のスコープ外）

`hooks/hooks.json` を調査する過程で、`DES-031_resume_status_presenter_design.md`（会話再開時の未完了作業提示、SessionStart hook + `resume_status.py` を設計）が**未実装のまま**であることを発見した。`plugins/forge/scripts/resume_status.py` / `plugins/forge/skills/resume-status/SKILL.md` / 対応テストのいずれも全ブランチの git 履歴に存在しない。

本 ADR が追加した `ensure_plugin_root_link.py` の `SessionStart` 登録とは無関係（`SessionStart` は配列で複数エントリを共存できるため、両者は構造的に衝突しない）。DES-031 の実装自体は本 ADR のスコープ外とし、現状把握のみをここに記録する。

## 5. ステータス履歴

| 日付       | Status   | 備考                                                                           |
| ---------- | -------- | ------------------------------------------------------------------------------ |
| 2026-07-23 | accepted | `docs/` 相互参照棚卸し作業から派生した調査・実験・実装をまとめて決定として作成 |
