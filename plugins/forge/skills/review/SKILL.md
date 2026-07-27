---
name: review
description: |
  msg-sys 通信基盤（常駐 Codex セッションとの Stop フック経由の非同期往復）の上で、
  Codex とのレビュー依頼・所見受領・修正・完了判定を駆動する。3モード（依頼/受信/再開）を持つ。
  依頼モードのトリガー句: "レビューして", "review", "確認して", "Codexとレビュー往復したい",
  "常駐Codexにレビューを依頼", "Codexセッションにコードレビューを頼みたい"。
  受信モードの起動契機（トリガー句ではなくメッセージ本文の形式で成立）: Stop フックが差し戻した
  メッセージ本文の先頭が `[msg-review] <種別> review_id=<review_id> round=<n>` である。
  再開モードのトリガー句: "レビューを再開したい", "レビューの往復上限到達通知が来た、状況を確認して",
  "review_idの未解決所見を要約して", "レビューの続きを確認したい"。
user-invocable: true
argument-hint: "[code|design|requirement|plan|uxui] [--diff|--branch|--files a.md,b.py,...] [--focus \"重点観点\"]"
allowed-tools: Skill, Read, Write, Bash, Monitor, AskUserQuestion
---

このスキルは、常駐 Codex セッションとの msg-sys 経由レビュー往復（依頼の組み立てと送信・受領した所見の評価と修正と再依頼・完了判定と再開時の要約報告）のみを行う。親が依頼している他の作業（実装等）を引き継いではならない。

> このスキル自身を `Skill ツール`で再起動しない（自己再帰禁止）。`/forge:query-db-rules` / `/forge:query-db-specs` は Skill ツールで起動する別スキルであり、依頼モードから呼んでよい。

> **ワイヤプロトコルの識別子 `[msg-review]` は改称しない [MANDATORY]**: 本スキルは旧称 `msg-review` から `review` へ改称されたが、メッセージ本文先頭のプロトコルヘッダは `[msg-review]` のまま据え置く。このトークンはスキル名ではなく **msg-sys の DB に永続化された通信路上の識別子**であり、`build_review_request.py` の生成・`parse_findings.py` の `HEADER_RE`・`filter_review_history.py` のスレッド連鎖判定・後述 Step 6.6 の `--header-regex` が同一値を前提に噛み合っている。改称すると、既に DB に存在する未解決スレッドがどの経路からも辿れなくなる（スレッド判定の起点を失う）。

## 概要

`/forge:review` は msg-sys（通信路のみを提供）の上に成り立つレビューオーケストレーションである。単一ターンで完結せず、3つの動作モードを持つ。

| モード         | 起動契機                                                                                        | このセクションへ |
| -------------- | ----------------------------------------------------------------------------------------------- | ---------------- |
| **依頼モード** | 利用者による `/forge:review <種別> ...` の明示起動                                              | 「依頼モード」   |
| **受信モード** | 差し戻されたメッセージ本文の先頭に `[msg-review] <種別> review_id=<review_id> round=<n>` がある | 「受信モード」   |
| **再開モード** | 往復上限到達の OS 通知を受けた利用者が状況確認・再開を明示指示したターン                        | 「再開モード」   |

**受信モードの成立根拠**: 依頼・返信メッセージ本文には常にこのプロトコルヘッダを含める。文脈が失われたターン（セッション再開・compaction 後等）でも、`description` に記載したヘッダ文字列をトリガーにこの SKILL.md を再読すれば受信モード手順へ復帰できる。
**再開モードの成立根拠**: msg-sys は往復上限到達時に対象メッセージを配信しない（受信モードの起動契機を持たない）。代わりに、上限到達を告げる OS 通知を受けた利用者が状況確認・再開を明示指示すること自体を起動契機とする。

## コマンド構文

```
/forge:review <種別> [--diff | --branch | --files a.md,b.py,...] [--interactive | --auto-critical | --auto] [--focus "<重点観点>"]
```

| 軸               | 値                                                  | 既定値                   | 意味                                                                                         |
| ---------------- | --------------------------------------------------- | ------------------------ | -------------------------------------------------------------------------------------------- |
| 種別（位置引数） | `code` / `design` / `requirement` / `plan` / `uxui` | （`--files` 時のみ必須） | 依頼テンプレートの選択に使う（Step 3）。`--diff` / `--branch` では無視する                   |
| 対象軸           | `--diff` / `--branch` / `--files`                   | `--diff`                 | 未 commit 差分 / base ブランチ分岐以降の全変更 / 明示指定ファイル群                          |
| 介入軸           | `--interactive` / `--auto-critical` / `--auto`      | `--interactive`          | 🔴🟡 を自動修正・🟢 は対象外（暫定的に `--auto` と同じ） / 🔴 のみ自動修正 / 🔴🟡 を自動修正 |
| 重点観点         | `--focus "<自然文>"`                                | 指定なし                 | 今回の依頼で特に注意を払う対象。テンプレートが名指しする観点文書に**加えて**適用する         |

**`--secrets`（独立起動）**: 上表の軸とは別に、機密情報の混入だけを対象とする独立したレビューを持つ。

```
/forge:review --secrets [--focus "<自然文>"]
```

- **種別・対象軸と相互排他**（`--secrets --branch` 等はエラー終了する）。対象は常にリポジトリ全体であり、利用者が範囲を選ばない
- 対象を差分に絞らない理由: 過去のコミットで混入した秘密は今回の差分に現れないが、リポジトリには残っており漏洩の対象である。差分に絞った時点でこのレビューの目的を達成できない
- 介入軸は受け付けるが、**自動修正の対象にしない**（後述 Step 2a の分岐）。混入の修正は削除だけでは完了せず、該当する秘密の失効・再発行を伴うため、人間の判断が要る
- `--focus` は併用できる

引数解釈は AI が自然言語混在を許容して直接行う（リジッドなパーサーは使わない。`docs/rules/implementation_guidelines.md`）。種別・対象が不足・曖昧な場合は AskUserQuestion で補完する。

**対象軸の二重指定はエラー終了する**（`--diff` と `--files` を同時指定等）。既定動作を推定できないため、依頼を送信せず利用者へ再入力を促して終了する。

**介入軸**: `--auto-critical`/`--auto` は所見の重大度に応じた自動修正範囲を実際に区別する（受信モード Step 2a 参照）。**`--interactive`（既定・介入軸未指定時も同じ）は暫定的に `--auto` と同じ振り分けを適用する**（ユーザー指示・ユーザー責任 [2026-07-19]。この仕組みを早期に多くのプロジェクトで実運用し問題を洗い出すための暫定措置）。本来の「所見を1件ずつ提示して人間の判断を仰ぐ」段階的提示は未実装であり、次回以降に**本スキル内で完結する形で**実装する（後述「対象外」節）。

**重点観点（`--focus`）**: 利用者が口頭で「特に〜を中心にレビューして」と述べた場合も、フラグを明示していないとして無視せず、その意図を重点観点として解釈する（引数解釈は AI が自然言語混在を許容して行うため。上記参照）。以下の性質を持つ:

- **内蔵の観点文書を置き換えない**。テンプレートが名指しする criteria・規範文書によるレビューはそのまま行われ、重点観点はそこに追加される。「これだけを見る」という絞り込みではない
- **P1〜P3 の優先度体系を変えない**。重点観点は P1 ルール合致の照合において特に注意を払う対象を伝えるものであり、新しい観点軸を追加するものではない（`${CLAUDE_PLUGIN_ROOT}/docs/review_priorities_spec.md` §3.3「固有 perspective の追加禁止」と衝突しない）
- **severity を指定できない**。重点観点由来の所見であっても、severity は委譲先 principles の重大度カタログから決まる（同 §2.2）。「重点だから critical」という扱いはしない
- **単一行に要約して渡す**。複数行の自由文はプロトコル注入（見出し行・完了宣言行の偽装）の経路になるため `build_review_request.py` が拒否する。利用者の指示が長い場合は AI が 1 行へ要約してから渡す

**非対応軸の警告付き続行**: `--codex` / `--claude`、および将来 DROP されたフラグを検出した場合、「本スキルはエンジン軸を持たない（当該フラグは無視して続行する）」旨を警告したうえで、当該フラグを無視し既定動作で続行する。黙殺しない。エラー終了にしない理由: `/forge:review` を発行する既存の呼び出し元（`/forge:start-implement` の Phase 5・`/forge:start-design`・`/forge:start-plan`・`/anvil:impl-issue` 等）が `--auto` や `--codex` 付きで起動するため、エラー終了にすると旧パイプラインからの差し替えが成立しない。

### 引数解釈結果の定型出力 [MANDATORY]

依頼モードは送信前に必ず以下の定型表を出力する。「無視したフラグ」欄は無視したフラグが無い場合も省略せず「なし」と明示する（自由記述の注意書きに置き換えない）。

```
### 引数解釈結果

| 項目           | 値                               |
| -------------- | -------------------------------- |
| パターン       | <diff|branch|code|design|secrets|...> |
| 対象軸         | <diff|branch|files|なし（リポジトリ全体）> |
| 対象ファイル   | <一覧、または「範囲指定のため渡さない」> |
| base / target  | <branch パターン時のみ>          |
| 介入軸         | <interactive|auto-critical|auto> |
| 重点観点       | <渡す1行、または「指定なし」>    |
| 無視したフラグ | <一覧、または「なし」>            |
```

「重点観点」欄には、実際に `--focus` へ渡す 1 行をそのまま出力する（利用者の指示を要約した場合、要約後の文言が渡る内容であることを送信前に見えるようにするため）。

## 依頼モード

利用者が前節のコマンド構文で `/forge:review <種別> ...` を明示起動したターン、または他スキル（`/forge:start-design` 等）が Skill ツールで `/forge:review` を起動したターンで実行する。

### Step 1: 引数解釈

種別・対象軸・介入軸・重点観点を解釈し、対象軸二重指定なら Step を進めずエラー終了する。重点観点は `--focus` の明示指定に限らず、口頭指示（「特に〜を中心に」等）からも抽出し、単一行へ要約して保持する（受信モード Step 2a の所見評価まで保持する）。介入軸未指定時は `--interactive` を既定値とする。非対応フラグ（エンジン軸等）があれば無視して続行する（上記「非対応軸の警告付き続行」）。確定した介入軸の値は受信モード Step 2a まで保持する。**`--interactive`・介入軸未指定時は、受信モード Step 2a では暫定的に `--auto` として扱う**（ユーザー指示・ユーザー責任）。

### Step 1.5: Codex 側フックの自己修復 [MANDATORY]

Codex は Claude Code のプラグイン hooks 自動登録機構を持たず、`.codex/hooks.json`（Codex CLI 自身が固定のプロジェクトルート直下でのみ読む設定）の登録コマンドが指すスクリプトパスは常に静的な文字列である。このパスが実在しないまま Codex の Stop フックが発火すると、コマンド自体が実行に失敗し、Codex はそれを解消されるまでブロックし続ける無限ループに陥る。これを避けるため、依頼を送信する**前に毎回**次を実行し、symlink・登録内容を自己修復する:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/msg-sys/ensure_codex_hook.py" \
  --project-root "$(git rev-parse --show-toplevel)" \
  --plugin-msg-sys-dir "${CLAUDE_PLUGIN_ROOT}/scripts/msg-sys"
```

> `ensure_codex_hook.py`・`wait_for_reply.py` は本スキル固有ではなく、msg-sys を使う任意のスキル（`talk-to-codex` 等）が共有するプロトコル非依存の部品のため `${CLAUDE_PLUGIN_ROOT}/scripts/msg-sys/` に置かれている（`docs/rules/implementation_guidelines.md`「スクリプトの配置」）。`wake_codex.sh`・`find_codex_pane.py` はさらに cmux 端末多重化ツール前提の機能であり（msg-sys 本体は cmux 非依存で単独動作する）、`${CLAUDE_PLUGIN_ROOT}/scripts/msg-sys/cmux/` に分離して置かれている。

このスクリプトは `<project_root>/.codex/msg-sys/scripts` を、現在ロードされている forge プラグイン自身の `scripts/msg-sys/` への symlink にする（コピーではない。プラグインが更新されても再インストール作業なしで常に最新版を参照する）。あわせて `<project_root>/.codex/hooks.json` の Stop フックに、この symlink 経由の git-root-relative パス（`$(git rev-parse --show-toplevel)/.codex/msg-sys/scripts/hooks/check_inbox.py`）を指すエントリが無い・古ければ追加・修復する（既存の無関係な Stop フックは変更しない）。

`symlink.status` が `"conflict"` の場合（symlink であるべき場所に人間由来の実ファイル・ディレクトリが存在する）は書き換えを行わないため、その旨を利用者に報告し、手動での確認を促す（自動修復を諦めるのみで、依頼の送信自体は Step 2 の前提検査結果に従う）。`hooks_json.status` が `"error"` の場合（既存 `.codex/hooks.json` が壊れた JSON 等）も同様に書き換えず報告する。

### Step 2: 前提検査

msg-sys 側の自己診断 CLI を Bash subprocess として呼ぶ:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/msg-sys/check_setup.py" [--project-root <path>]
```

出力 JSON の `status` が `error` の場合、依頼を送信せず終了する（fail closed）。`checks` の中で `ok: false` の項目を利用者に提示し、対処を具体的に案内する。`claude_plugin_hook_registration`（forge プラグイン同梱の `hooks/hooks.json`。Claude Code のプラグイン hooks 自動登録機構により、forge プラグイン導入だけで有効化される。手動での `.claude/settings.json` 編集は不要）が失敗している場合は forge プラグイン自体の破損・古いバージョンを疑い、再インストールを案内する。`codex_hooks_registration`（`.codex/hooks.json`。Codex CLI 自体の設定でありプラグイン機構の対象外。実在確認込み——登録コマンドの参照先スクリプトが実際に存在するファイルへ解決できない場合は `ok: false` になる）が Step 1.5 の自己修復後もなお失敗している場合は、Step 1.5 の `symlink`/`hooks_json` の `conflict`/`error` 報告を参照し、手動での確認を案内する。`warnings`（Codex 常駐・trust 登録は機械検査不能）は送信前の予告として提示するが、これのみでは送信を止めない（fail-open）。

### Step 3: パターンの確定

Step 1 で解釈した種別・対象軸から**レビューのパターン**を確定する。パターンは依頼本文のテンプレートと 1 対 1 に対応する。

| 起動                             | パターン      |
| -------------------------------- | ------------- |
| `--diff`（対象軸未指定時も同じ） | `diff`        |
| `--branch`                       | `branch`      |
| `--files` かつ種別 `code`        | `code`        |
| `--files` かつ種別 `requirement` | `requirement` |
| `--files` かつ種別 `design`      | `design`      |
| `--files` かつ種別 `plan`        | `plan`        |
| `--files` かつ種別 `uxui`        | `uxui`        |
| `--secrets`                      | `secrets`     |

**`secrets` は対象軸を持たない**。`--secrets` に種別・対象軸が併記されていた場合はエラー終了する（どちらを優先すべきか推定できないため。既定動作での続行はしない）。Step 3.1・3.2 は実行せず、代わりに Step 3.3 を実行する。

**`--branch` は種別指定を無視する**（ブランチ差分にはコード・文書・設定が混在するため種別軸に載らない）。上表に無い組み合わせは AskUserQuestion でどのパターンとして扱うかを確認する。

**範囲指定（`diff` / `branch`）をファイル一覧へ展開しない [MANDATORY]**: 対象の確定はレビュアー自身が差分から行う。forge が列挙して渡すと、列挙漏れがそのままレビュー範囲の欠落になり、欠落した事実がレビュアーにも利用者にも見えない。特に削除されたファイルはワークツリーに存在せず Read できないため列挙から落ち、削除が変更の大半を占める場合はレビュー範囲が変更集合の半分以下になる。

#### 3.1 `--branch` の base ブランチ確定

```
python3 "${CLAUDE_SKILL_DIR}/scripts/analyze_branch_point.py" [--project-root <path>]
```

出力 JSON の `candidates` は分岐点が新しい順に並ぶ。**先頭を既定値として提示し、AskUserQuestion で利用者に確認して base を確定する**（既知ブランチ名の優先順位だけで黙って採用しない。feature から派生したブランチを誤って `develop` 起点と判定するため）。`target_branch` をそのまま target として使う。

`candidates` が空、または `target_branch` が `null`（detached HEAD）の場合は、依頼を送信せず理由を報告して終了する。

#### 3.2 対象の検証と allowlist の取得

```
python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_targets.py" --mode <diff|branch|files> [--files a,b,...] [--project-root <path>]
```

`--files` の場合は指定ファイルの実在検証に使う。`status` が `error` なら依頼を送信せず理由を報告して終了する。

いずれのパターンでも、返る `files` は**修正フェーズの allowlist（target_files）として保持する**。受信モード Step 2a の安全検証で使うものであり、**依頼本文には入れない**（レビュアーへ渡すものではないため粒度保存の対象外）。

#### 3.3 `--secrets` の機械スキャン

**スキャンを SKILL 側で実行しない [MANDATORY]**。`build_review_request.py` が Step 5 で `scan_secrets.py` を import して自分で実行する。SKILL がスキャンを実行して結果をファイル経由で渡す形は廃止した。

理由: 依頼本文へ載る検出値が必ず `mask()` を通ったものであることを、**構造的に**保証するため。外部ファイルを受け取る形では、渡された値がマスクを経たかどうかを形式検証でしか確認できず、形式は生成元の証明にならない（実値がたまたまマスク形式に一致すれば通る。`${CLAUDE_PLUGIN_ROOT}/docs/sensitive_information_spec.md` §5.3 / 実 Codex レビューでの指摘）。

したがってこの Step で実行するコマンドは無い。**スキャン結果を会話へ貼り付けたり、内容を要約して依頼本文へ書き写したりもしない**（経由地点を増やすことが露出経路を増やすことになる）。

スキャンが失敗した場合は Step 5 の `build_review_request.py` が非ゼロ終了する。その場合は依頼を送信せず理由を報告して終了する（fail closed）。スキャンできなかったまま「AI が目を通したから大丈夫」とするのは、二段構えの片方を黙って落とすことになる。

検出 0 件でも依頼は送信する。機械検出が拾えない混入の捜索（同 §5.1 の (b)）はレビュアーの担当であり、0 件はレビュー不要を意味しない。

`--secrets` では修正フェーズの allowlist（target_files）を持たない。混入箇所は検出結果が指すファイルであり、事前に確定できないため。受信モード Step 2a の安全検証は、この事情に合わせて後述のとおり扱う。

### Step 4: 関連ルール・仕様の収集

対象・種別に関連するプロジェクトルール・仕様を以下の別スキル呼び出しで収集し、返却されたパス一覧（プロジェクトルート相対）をそれぞれまとめる:

- `/forge:query-db-rules` → `--project-rules-json`
- `/forge:query-db-specs` → `--project-specs-json`

forge 内蔵の観点文書（criteria / principles / format）はクエリしない。**どの観点文書を渡すかはテンプレートに静的に書かれている**ため、SKILL 側で組み立てる必要がない。

### Step 5: 依頼本文の組み立て

```
python3 "${CLAUDE_SKILL_DIR}/scripts/build_review_request.py" \
  --pattern <diff|branch|code|requirement|design|plan|uxui> \
  --project-root "$(git rev-parse --show-toplevel)" \
  [--base-branch <base> --target-branch <target>] \
  [--files-json '["path1","path2",...]'] \
  [--project-rules-json '[...]'] [--project-specs-json '[...]'] \
  [--focus '<重点観点の1行>']
```

`templates/<パターン>_review_request_template.md` を読み、動的データを埋めた依頼本文を標準出力へ書く。**依頼本文の文言・レビュー観点の名指しはテンプレート側にあり、このスクリプトは散文を持たない。** 依頼内容を変えたいときはテンプレートを編集する（スクリプトには手を入れない）。

`--base-branch` / `--target-branch` は `branch` パターンのみ、`--files-json` はファイル指定パターンのみ。範囲指定パターンにファイル一覧を渡すとエラー終了する。`--focus` は全パターン共通の任意引数であり、未指定なら依頼本文の重点観点欄が「（指定なし）」になる。改行を含む値はエラー終了する（Step 1 で単一行へ要約しておく）。

`secrets` パターンでは、このスクリプトが `--project-root` を起点にスキャンを実行してから本文を組み立てる（Step 3.3 参照）。スキャン結果を渡す引数は無い。スキャンが失敗した場合は本文を出力せず非ゼロ終了する。

本文は `review_id`（このスクリプトが新規生成する不透明トークン）を含むプロトコルヘッダで始まる。この `review_id` を以後のやり取り（受信モード・再開モード）で参照するためコンテキストに保持する。

### Step 6: 送信

Write ツールで依頼本文を一時ファイルへ書き出し、msg-sys の `send.py` を Bash subprocess として呼ぶ（シェル経由の本文書き出しは行わない。既存 msg-sys の返信ヒント手順と同じ安全原則）:

```
FORGE_MSG_PROJECT_ROOT="$(git rev-parse --show-toplevel)" \
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/msg-sys/send.py" claude codex - < "一時ファイルパス"
```

送信後、一時ファイルを削除する。`send.py` が非ゼロ終了した場合は送信失敗として報告し終了する（部分送信は起こらない。send は単一 INSERT）。

### Step 6.5: push型起床 [MANDATORY]

**本 Step の実行（`wake_codex.sh` の呼び出し自体）は必須であり、省略してはならない**（結果が `skipped`/`failed` であっても構わないが、呼び出さないことは許されない）。常駐 Codex の Stop hook は Codex 自身のターン終了時にしか発火しない（pull型）。人間が対話しない専用の常駐 Codex セッションでは、送信側からこの Step を呼ばない限り Codex のターンが自然に終わる契機自体が存在せず、Step 6.6 の受動ポーリングは無期限に応答を得られない。したがって本 Step は「ポーリングを高速化するだけの最適化」ではなく、専用常駐運用における配信の唯一の起点であり、呼び出し自体を必須の手順として扱う。

**この必須性は Claude 側のあらゆる送信に適用する（依頼・返信を問わない）[MANDATORY]**。受信モードで修正報告・再送を送る場合も、送信直後に本 Step を実行する（受信モード側にはこの手順を再掲せず、ここを参照する）。理由は上と同一である——「Codex のターンが自然に終わる契機が無い」という条件は、こちらが依頼を送ったか返信を送ったかに一切依存しない。

かつて本 Step は依頼モードにしか置かれておらず、受信モードには「送信済み報告を出力してターンを終える（次の受信は次ターンの Stop フック起点）」とだけ書かれていた。その結果、**往復 2 ラウンド目以降が必ず止まった**（1 ラウンド目は依頼モードで起床するため動き、2 ラウンド目で Codex が起きないまま未読で滞留する）。実運用の 1 レビューで 4 回の手動起床を要したため、必須性を全送信へ拡張した。

```
"${CLAUDE_PLUGIN_ROOT}/scripts/msg-sys/cmux/wake_codex.sh" "$(git rev-parse --show-toplevel)"
```

`wake_codex.sh` は対象ペイン（project_root の cwd と一致する Codex セッションの cmux pane）を、独立スクリプト `find_codex_pane.py`（read-only・副作用無し）で**毎回その場で発見**し、結果をファイルへキャッシュしない（cmux は同じ pane を維持したまま workspace ID だけを再発行することがあり、キャッシュした ID は stale 化して push 起床が恒久的に機能しなくなる。発見自体は数回の cmux subprocess 呼び出しで軽量であり、依頼往復ごとに高々1回しか呼ばれないため、毎回発見し直す方が単純かつ頑健である）。発見ロジックを `wake_codex.sh` の inline Python に閉じ込めず独立スクリプトへ切り出したのは、将来の別の呼び出し元（送信前に Codex の稼働を確認する事前ゲート等、いずれも未実装）が同じ発見ロジックを重複実装せずに再利用できるようにするため。

`{"status": "sent"|"skipped"|"failed"}` を返すが、いずれの結果であっても本 Step の**呼び出し自体**は必須である（結果内容は依頼モードの完了判定に影響しない。終了コードは常に0）。cmux環境でない、対象ペインが見つからない、複数候補で曖昧、のいずれの場合も `skipped` として次へ進むが、これは「起床が不要だった」ことを意味しない——専用常駐運用では Step 6.6 の受動ポーリングが Codex 側の契機を得られないまま無期限に待つ可能性がある（上記 [MANDATORY] 参照）。

**`skipped` と `failed` の区別**: `skipped` は cmux 非導入、対象なし・候補の曖昧さ、作業中など、確認できた安全条件による意図的な見送りであり、リトライしても同じ理由で再度見送られるだけなので許容する（入力欄の下書き有無は送信前チェックの対象外。履歴巻き戻り等の残留テキストが定常状態であり、これを見送り条件にすると push起床が恒久的に機能しなくなる）。一方 `failed` は、`cmux workspace list` / `list-panels` の問い合わせ失敗・不正 JSON のように対象の有無を判断できない探索エラー、または安全ゲートを全て通過した後の `cmux send`/`send-key` のエラー終了である。後者は `wake_codex.sh` 内部で3回までリトライする。この `failed` は依頼モードの完了判定には引き続き影響させないが（cmux 側の一時的な不調である可能性があり、review の正しさとは無関係なため）、この結果を保持しておき、Step 7 で `timeout` に至った場合の報告に含める（cmux 環境が整っているのに push 起床が機能していないという診断情報を利用者に伝えるため）。

### Step 6.6: 応答のブロッキング待機

本スキルが `/forge:review` として旧パイプラインを差し替えた後も、呼び出し元（`/forge:start-implement` Phase 5 等）の「結果を受け取ってから次工程に進む」という前提が崩れないよう、送信直後にその場で Codex の返信を待つ。

`wait_for_reply.py`（msg-sys 共有・プロトコル非依存）を `run_in_background: true` で**1回だけ**起動する。`wait_for_reply.py` も `send.py` 等と同じ `mailbox.resolve_db_path()`（fail-closed）で DB パスを解決するため、`--db-path` を渡さない場合は Step 6 と同じ `FORGE_MSG_PROJECT_ROOT` の前置が必須である（この前置を省略すると `RuntimeError: DB path could not be resolved` で即エラー終了する）。本スキルのスレッド識別には review_id ヘッダの正規表現を `--header-regex` として渡す（ヘッダの識別子は改称せず `[msg-review]` のまま。冒頭の [MANDATORY] 参照）:

```
FORGE_MSG_PROJECT_ROOT="$(git rev-parse --show-toplevel)" \
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/msg-sys/wait_for_reply.py" claude codex \
    --header-regex '^\[msg-review\]\s+\S+\s+review_id=(\S+)\s+round=\d+\s*$' --thread-id <review_id> \
    --max-seconds 600 --progress-interval 10 [--db-path <path>]
```

`Monitor` ツールでこのジョブを監視し、10秒おきの進捗行（「経過N秒、まだ返信なし」）と最終結果を受け取る。

**`nohup`・末尾 `&` での二重バックグラウンド化は禁止 [MANDATORY]**: `wait_for_reply.py` は Bash ツールの `run_in_background: true` パラメータで起動する。これに加えて `nohup ... &` でシェル自身もバックグラウンド化すると、実際のポーリングプロセスがハーネスの追跡から外れ（ハーネスが完了を検知できるのは自身が起動したプロセスの終了のみ）、`replied`/`timeout` の完了通知が二度と届かなくなる（Bash ツールは `echo "started pid $!"` 等の直後に即座に完了扱いになり、その通知は本当の待機結果ではない）。`run_in_background: true` を指定した時点で既にバックグラウンド実行されるため、二重の `nohup`/`&` は不要かつ有害である。

**通知が来ない場合の復旧手順 [MANDATORY]**: 上記の誤りに限らず、何らかの理由で `wait_for_reply.py` の完了通知を受け取れなくなった場合、新たな一時ポーリング処理を手書きしない（DB へのアドホックな SQL 直接発行を含む）。既存の `filter_review_history.py` を次の形で呼び、`resolved` および `messages` の最新の送信者・`in_reply_to` から返信の有無を確認する（このスクリプトは review_id のスレッド判定を `in_reply_to` の連鎖で正しく行う。手書きの SQL は本連鎖判定を再実装することになり、後述の `--in-reply-to` 必須化の意図を再度壊しかねない）:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/filter_review_history.py" claude codex <review_id> \
  --project-root "$(git rev-parse --show-toplevel)"
```

- 最終結果が `{"status": "replied", "messages": [...], "delivered_ids": [...]}` → ターンを終えず、**`delivered_ids` に含まれる id のメッセージ本文**を使って**同一ターン内で「受信モード Step 1」へ合流**する。この場合その Codex 発メッセージの `id` を、後続の返信（受信モード Step 2a 手順5・Step 1 完了宣言行なし時の再送）で使う `--in-reply-to` の値として保持する（下記参照）。**`messages`（スレッド全体、文脈用）の中で単純に `sent_at` が最大のメッセージを「直近の Codex 発メッセージ」として選んではならない**——同一 poll 内で ack の成否がメッセージごとに異なりうるため（例: 古い返信の ack は成功し、より新しい返信の ack は Stop フック等の別プロセスに先を越されて失敗する）、`sent_at` 最大値だけで選ぶと、他プロセスが既に配信を受けているメッセージを誤って処理し二重処理になる。`delivered_ids` はこの呼び出しが実際に配信権を得た（＝安全に処理してよい）返信のみを表す
- 最終結果が `{"status": "timeout", ...}` → Step 7 のタイムアウト報告へ

**`--in-reply-to` を全ての送信で必須にする**: `filter_review_history.py` は review_id のスレッド判定を `in_reply_to` の連鎖で行う（body 先頭行のヘッダパースは連鎖の起点特定にのみ使う）。ヘッダ行は自由記述本文の一部として手で書く自己申告値であり、書き忘れ・省略に対して無防備である（ヘッダ行が欠落した返信は `wait_for_reply.py` がスレッドの一部として検知できず、待機時間を浪費する）。したがって、Claude 側のあらゆる送信（Step 6 の初回依頼を除く。初回はスレッドの起点でありヘッダで足りる）は、直前に受信した Codex メッセージの `id` を `--in-reply-to <id>` として `send.py` に必ず渡す。Stop フック経由（`check_inbox.py` の返信ヒント）で受信した場合はヒントの中に既に `--in-reply-to` が組み込まれているためそのまま使えばよいが、`wait_for_reply.py` 経由（本 Step の `messages` から直接合流する場合）は返信ヒントが存在しないため、上記で保持した `id` を使い Claude 自身が `--in-reply-to` を明示的に組み立てる。

### Step 7: 完了報告・タイムアウト報告

**Step 6.6 が `status: "replied"` の場合**、本 Step は使わない（受信モードの完了処理・要約報告がそのまま完了報告を兼ねる）。

**Step 6.6 が `status: "timeout"` の場合**、フォールバックしない（`docs/rules/implementation_guidelines.md`「フォールバックを反射的に書かない」）。種別・対象・`review_id`・経過時間を含め、「Codex からの返信が{経過時間}間ありませんでした。Codex 側セッションの稼働状況を確認してください」という**確定した失敗**を報告してターンを終える。非同期往復（受信モード・再開モード）への切り替えを装って処理を先に進めることはしない。`last_observed_request_read_by_agent_b`（タイムアウト宣言の瞬間の状態ではなく、最後に完了したポーリング時点の観測値であることに注意。最終 sleep 中に ack された場合、最大1ポーリング間隔分古い値になりうる）が `false` の場合は「Codex は最後の確認時点では依頼をまだ読んでいませんでした（常駐していない・停止している可能性があります）」を、`true` の場合は「Codex は最後の確認時点では依頼を読んでいましたが応答していませんでした（処理中の可能性があります）」を追記する（診断情報。`null` の場合は追記しない）。

**push起床が `failed` だった場合の追記**: Step 6.5 で保持した `wake_codex.sh` の結果が `{"status": "failed", ...}` だった場合、上記の報告に「なお、push起床（wake_codex.sh）も失敗していました（reason: {reason}）。cmux 側の状態を確認してください」を追記する。安全ゲートを全て通過したにもかかわらず送信自体が失敗していたという事実は、「たまたま長い待機になっただけ」なのか「push 起床が構造的に壊れている」のかを利用者が切り分けるための診断情報になる（`skipped` の場合はこの追記を行わない。安全ゲートによる意図的な見送りであり、push 起床が壊れている signal ではないため）。

## 受信モード

差し戻されたメッセージ本文の先頭が `[msg-review] <種別> review_id=<review_id> round=<n>` であるターンで実行する。文脈が失われている場合は、まずこの review_id を使って「再開モード」の `filter_review_history.py` を呼び、当該レビューの往復のみを復元してから以下に進む。

### Step 1: 完了宣言行の照合

受信本文には Stop フックが付与する返信ヒント（複数行のコマンド案内）が末尾に連結されており、完了宣言行が本文の最終行になるとは限らない。受信本文を 1 行ずつ走査し、前後の空白を除去した上で**行全体が正確に** `REVIEW_RESULT: approved` または `REVIEW_RESULT: findings` に一致する行のみを完了宣言行の候補とする（行の一部として出現する場合は対象外）。候補が複数見つかった場合は、本文中で**最後に出現した行**を完了宣言行として採用する（返信の末尾に近いほど最終判断を反映するため）:

- 採用された行が `REVIEW_RESULT: approved` → 「UC-3 承認による完了」へ
- 採用された行が `REVIEW_RESULT: findings` → 「UC-2 所見の受領・修正・再依頼」へ
- 候補が 1 つも無い（形式違反） → 修正は行わず、完了宣言行を含めて再送するよう返信する（プロトコル契約の再掲を含める）。返信は依頼モード Step 6 と同じ手順（Write で一時ファイル→送信→削除）に従い、受信メッセージ本文に含まれる返信ヒントのコマンドをそのまま使う。**送信後に依頼モード Step 6.5（push型起床）を実行する [MANDATORY]**（この経路も Claude 側の送信であり、起床の必要性は依頼と変わらない）

### Step 2a: UC-2 所見の受領・修正・再依頼

1. **所見評価 [MANDATORY]**: 依頼時に Codex へ渡したものと同じ観点文書（Step 3 で確定したパターンのテンプレートが名指ししている criteria / principles / format。以後の往復でも同一ファイルを Read する）**と、依頼時に渡した重点観点**を基準に、**所見ごとに**以下の評価を行う。重点観点を渡した場合、それに直接応答する所見を「criteria に明文の規定が無い」ことのみを理由にドロップしてはならない（利用者が明示的に依頼した観点であるため）。ただし重点観点は severity を引き上げない（重大度は委譲先 principles の重大度カタログに従う）。**Step 2 の severity による振り分け（`auto_fix`/`excluded`）は自動修正の「対象範囲」を決めるだけであり、この評価を代替・省略しない**（`auto_fix` に含まれる所見であっても、この評価を経ていない機械的な適用をしてはならない）:
   - **不要な指摘**: criteria・対象コードの実態に照らして妥当でないと判断した場合 → ドロップする。対応表には「対応しない（理由: 検証の結果、該当しないと判断）」と記載する
   - **Codex の勘違いに基づく指摘**: 対象・前提の理解に誤りがあると判断した場合 → ドロップするか、修正報告の中で Codex に確認・訂正を求める（次ラウンドで Codex の再考を促す。理由欄に具体的な確認事項を書く）
   - **妥当な指摘**: 鵜呑みにせず、**影響範囲・代替案・よりよい修正方法を検討したうえで**実施内容を決定する（本セッション中の実 Codex レビュー往復で、提案をそのまま採用した後に別の観点から反証を受け撤回した事例があり、この教訓を反映する）
     依頼側と受信側で判断基準を揃え、Codex の指摘を別基準で恣意的に棄却することも、逆に無条件に採用することも防ぐ。**実施する修正は当該所見が指摘した内容に限定し、関連する体裁修正・リファクタリングを合わせて行わない**（所見が指摘していない箇所まで直すと、Codex の再レビューで「何が今回の修正か」が判別できなくなり、往復が収束しない）
     **`secrets` パターンの例外 [MANDATORY]**: 混入の所見は自動修正しない。介入軸が `--auto` / `--auto-critical` であっても、`confirmed_fix` を空として扱い（手順3〜5を実行せず）「Step 2c: 未対応所見を残した完了」へ進む。理由は 2 つある:
   - **削除だけでは修正が完了しない**。commit 済みの秘密は履歴・fork・CI ログに残るため、該当する秘密の失効・再発行を伴う（`${CLAUDE_PLUGIN_ROOT}/docs/sensitive_information_spec.md` §1）。失効は AI が実施できず、実施したかを検証もできない
   - **修正を急ぐと痕跡が消える**。該当行を機械的に消すと、人間が影響範囲（いつから・どこに露出していたか）を調査する起点を失う

   要約報告には、所見ごとに「該当箇所」「必要な失効対象」「人間が実施すべきこと」を列挙する。**検出値そのものは報告に書かない**（同 §5.3）。

2. **介入軸による振り分け**: 以下を常に実行する。`--interactive`・未指定時は暫定的に `mode = auto` として扱う（ユーザー指示・ユーザー責任 [2026-07-19]）:
   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/parse_findings.py" --body-file <受信本文の一時ファイルパス>
   ```
   出力の `findings` 配列をそのまま次に渡す（`--interactive`・未指定時は `--mode auto` を渡す）:
   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/gate_findings.py" --findings-json '<findings 配列>' --mode <auto-critical|auto>
   ```
   `auto_fix` は severity に基づく**候補**であり、確定した「修正する所見」ではない。`auto_fix` の各所見に対して Step 1 の評価を適用し、その結果に応じて以下の3群に分ける:
   - **`confirmed_fix`**: Step 1 で妥当と判断され、実施内容（影響範囲・代替案検討済み）が決まった所見 → Step 3 で実施する
   - **Step 1 でドロップした所見**（不要な指摘・Codex の勘違い）: `severity` に関わらず修正しない。対応表には「対応しない（理由: 検証の結果、該当しないと判断）」または「対応しない（理由: <具体的な確認事項。Codex に再考を依頼>）」と記載する
   - **`excluded`**（`gate_findings.py` の出力）: `severity` が `critical`/`major`/`minor` のものは「対応しない（理由: 重大度が現在のモード `<mode>` の自動修正範囲外）」、`unclassified`（`parse_findings.py` が severity マーカーを検出できなかった所見。フォーマット逸脱への対応）のものは「対応しない（理由: 重大度を判定できませんでした。人間の確認が必要です）」として記載する

   **終了判定 [MANDATORY]**: `confirmed_fix` が空の場合（＝ Step 1 の評価を経てもなお今回実施すべき新規の修正が無い。severity 除外のみ・Step 1 でのドロップのみ・所見自体が0件のいずれか）、Step 3〜5 を実行せず「Step 2c: 未対応所見を残した完了（承認以外）」へ進む。これは、対応しなかった所見を残したまま再レビューを依頼すると、Codex が同じ所見を指摘し続け `REVIEW_RESULT: findings` から抜け出せず往復上限まで往復し続けることを避けるための必須の分岐であり、`confirmed_fix` が空でない限り再レビューを要求してはならない。**この完了は Codex の承認とは異なる状態であり、「Step 2b: UC-3 承認による完了」とは別の Step として明確に区別する**（承認と同一視すると、Codex がなお指摘ありと判定している事実が要約報告で埋もれ、人間が見落とす）
3. **修正の実施（Claude 直接修正 + 安全検証）**: Claude 自身が直接、`confirmed_fix` の所見の修正を実施する（専用の evaluator/fixer Agent は起動しない）。

   > **専用 Agent を持たない理由**: 所見の妥当性評価・要修正判断・修正の実施という**機能**は無くなっておらず、オーケストレーターが直接担う。省いているのは、隔離コンテキストで動く別 Agent に課していた**機械的な強制**（1 起動 1 所見の限定・修正可能ファイルの allowlist・修正後の構文検証）である。修正がメイン会話上で利用者の目に見える構成では前提が異なるため、まず強制なしで運用し、逸脱がどの程度生じるかを評価してから再導入を判断する。なお allowlist 検証・構文検証は、その後**検出専用スクリプト**として下記 3 に導入済みである（ロールバックの判断は Claude が行う）。

   ただし全件をまとめて修正してから検証するのではなく、finding 単位で「適用 → 検証 → 判断 → 次へ」を逐次繰り返す:

   1. **baseline 取得（ループ開始前に1回）**: 依頼モード Step 3 で保持した target_files に対して構文検証の baseline を取得する:
      ```bash
      python3 "${CLAUDE_SKILL_DIR}/scripts/capture_syntax_baseline.py" --files-json '<target_files の JSON 配列>'
      ```
   2. `confirmed_fix` の finding を1件ずつ、以下を繰り返す:
      1. その finding の修正のみを実施する（他の `confirmed_fix` 所見の編集は同時に行わない）
      2. この finding のために実際に Edit したファイルパスを自己申告する（Claude は自分が何を編集したか常に把握しているため、git diff 等の外部推測は不要）
      3. 検出専用の安全検証を実行する（**ファイルは一切書き換えない**）:
         ```bash
         python3 "${CLAUDE_SKILL_DIR}/scripts/verify_fix_safety.py" \
           --allowed-files-json '<target_files>' \
           --modified-files-json '<この finding で自己申告したファイル群>' \
           --baseline-json '<Step i で取得した baseline>'
         ```
      4. 結果を Claude 自身が判断する（スクリプトは自動でロールバックしない）:
         - `allowlist_violations` / `syntax_errors` が事故的な逸脱・意図しない構文破壊と判断した場合 → Claude 自身が Edit で元の内容に戻し、この finding を「対応しない（理由: 修正後の安全検証で問題を検出したため取り消し）」として記録する
         - `allowlist_violations`（target_files 外の関連ファイル修正）をレビュー基準に照らして正当な波及修正と判断した場合 → 変更を維持し、その理由を修正報告に明記する（沈黙したスコープ拡大を許さない）
         - 検証結果が `status: "ok"` の場合 → この finding を「対応した」として記録し、次の finding へ進む
   3. **ラウンド終了時の独立検証 [MANDATORY]（自己申告への依存を補完）**: 上記ループの `--modified-files-json` は finding ごとの自己申告に基づく。申告漏れ（Claude が編集を忘れて申告しない等）が起きると、そのファイルは allowlist・構文検証のいずれも通過しないまま見過ごされうる。すべての `confirmed_fix` 処理後、自己申告に依存しない形でこのラウンド全体の変更集合を独立に確認する。ファイルパスの抽出は行/矢印単位の手動パースでは行わない（`git status --porcelain` は空白・改行・非 ASCII を含むパスを quote し、rename/copy は `->` を含む1行で表現するため、手動パースでは実パスを取り違える）。代わりに NUL 区切り・quote 無しの `-z` 出力を決定論的に解析する専用スクリプトを使う:
      ```bash
      python3 "${CLAUDE_SKILL_DIR}/scripts/collect_modified_files.py"
      ```
      出力の `files` 配列を `target_files ∪ (このラウンドで正当な波及修正として維持したファイル)` を allowlist として `verify_fix_safety.py` に渡す:
      ```bash
      python3 "${CLAUDE_SKILL_DIR}/scripts/verify_fix_safety.py" \
        --allowed-files-json '<target_files ∪ 波及修正で維持したファイル>' \
        --modified-files-json '<collect_modified_files.py の files 配列>' \
        --baseline-json '<Step i で取得した baseline>'
      ```
      `allowlist_violations` が検出された場合、それはどの finding の自己申告にも含まれていなかった変更である。Claude 自身がその変更内容を確認し、意図した変更であれば理由を修正報告に明記し、意図しない変更であれば元に戻す。この独立検証は「今回のラウンドで新たに変更されたファイル集合」を追跡するものではなく（`--diff` モードでは target_files 自体が既にラウンド開始前から未 commit 差分として存在するため、finding 単位の変更を厳密に切り分ける独立検出は行わない）、「ラウンド終了時点で allowlist 外の変更が実際に存在するか」の粗い最終確認である
4. 修正報告メッセージを組み立てる: プロトコルヘッダ（同一 `review_id`、`round` は表示上の通し番号としてインクリメント）に続けて、所見ごとの対応表（対応した / 対応しない（理由））と再レビュー依頼を記述する。`excluded` が空でない場合は、再レビュー依頼に「対応しなかった所見は今回のモードでは意図的に対象外としています。今回対応した所見が正しく解消されているかのみご確認ください」を明記し、Codex に対象外所見の再指摘を求めない（Step 2「終了判定」が実際の歯止めであり、本文言は往復回数を減らすための補助に過ぎない）
5. 既存 msg-sys の返信ヒント手順（受信メッセージ本文に含まれる、一時ファイル + 標準入力リダイレクトのコマンド案内）にそのまま従って送信する。返信ヒントが存在しない場合（Step 6.6 の `wait_for_reply.py` 経由で合流した場合）は、保持しておいた直近の Codex メッセージ `id` を使い `--in-reply-to <id>` を明示的に付けて送信する（**必須。省略しない**。Step 6.6 の説明参照）。返信本文はシェルコマンド（heredoc・echo・printf 等）ではなく Write ツールで一時ファイルへ書き出す
6. **送信直後に依頼モード Step 6.5（push型起床）を実行する [MANDATORY]**。手順・結果の解釈はすべて Step 6.5 に従う（ここには再掲しない）。これを省くと専用常駐運用では Codex が起きず、返信が未読のまま滞留して往復が止まる
7. 送信済み報告を出力してターンを終える（次の受信は Codex が返信した後の Stop フック起点）

### Step 2b: UC-3 承認による完了

`REVIEW_RESULT: approved` を受けた場合に実行する。要約報告を出力して終了する。要約報告には以下を含める（FNC-005）:

- 指摘の件数
- 対応した修正の概要
- 不採用とした所見とその理由

### Step 2c: 未対応所見を残した完了（承認以外）

Step 2a の「終了判定」（`confirmed_fix` が空。`--interactive`・未指定時も暫定的に `--auto` として判定するため対象になりうる）により到達する。**Codex は `REVIEW_RESULT: findings`（指摘あり）と判定し続けている**ため、Step 2b（承認による完了）とは異なる完了状態として扱う。要約報告には Step 2b の内容に加え、以下を明記し、承認された場合と混同しない形で人間の判断を仰ぐ [MANDATORY]:

- **Codex はなお指摘ありと判定していること**（承認ではない旨を冒頭で明示する）
- **修正しなかった所見全ての一覧と理由**（`excluded` のみでは不十分。以下すべてを含める）:
  - severity によるモード範囲外（`excluded`。重大度が既知の場合）
  - 重大度を判定できなかった `unclassified`（`excluded`）
  - Step 1 の評価でドロップした所見（不要な指摘・Codex の勘違い）とその具体的根拠
  - Step 3 の安全検証で問題を検出し取り消した所見とその内容（allowlist 逸脱・構文エラーの別）
- 現在のモード（`<mode>`。`--interactive`・未指定時も暫定的に `auto` として扱っている旨）と、対応するには現時点では人間が直接内容を確認するしかない旨（本来の `--interactive` 段階的提示は未実装。暫定運用である）

## 再開モード

往復上限到達の OS 通知を受けた利用者が状況確認・再開を明示指示したターンで実行する。msg-sys は上限到達時に対象メッセージを配信しないため、受信モードは自動発火しない（人間介在契機）。

### Step 1: 対象 review_id の往復履歴を取得

対象の `review_id`（コンテキストに保持しているもの。失われていれば利用者に確認する）を使い、往復履歴の絞り込み CLI を呼ぶ:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/filter_review_history.py" claude codex <review_id> \
  --project-root "$(git rev-parse --show-toplevel)" [--db-path <path>]
```

**`--project-root` を省略しない**: DB パスは `--project-root`（または `--db-path`）から解決され、どちらも無ければ fail closed で `RuntimeError: DB path could not be resolved` になる。review スキルの他スクリプトと同じ `--project-root` で統一されているため、`FORGE_MSG_PROJECT_ROOT` をシェルで前置する必要はない（前置に頼る形は実運用で繰り返し忘れられた）。

出力 JSON（`review_id` / `messages` / `round` / `resolved`）は、`history.py` の全履歴から対象 `review_id` のメッセージのみを送信順に抽出済みである（決定論的処理としてスクリプトに切り出し済み。SKILL.md 側で手動パースしない）。

### Step 2: 未解決所見の集計・要約報告

`resolved` が `false` の場合、`messages` の中の直近の Codex 所見（`REVIEW_RESULT: findings` を含む最新メッセージ）から未解決所見を抽出し、以下を含む要約報告を出力して人間の判断を仰ぐ:

- 往復回数（`round`）
- 未解決所見の一覧
- これまでの対応・不採用理由（Claude 側の返信メッセージから）

`resolved` が `true` の場合は、既に承認済みであることを報告する（上限到達通知と承認が競合した場合の整合性確認）。

## エラーフロー一覧

| 異常系                                                 | 挙動                                                                                                               |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| 前提検査 error（UC-5）                                 | 依頼を送信せず、不足項目と対処を報告して終了                                                                       |
| 対象 0 件 / 指定ファイル不在                           | 依頼を送信せず報告して終了                                                                                         |
| `send.py` 非ゼロ終了                                   | 送信失敗を報告して終了                                                                                             |
| `--secrets` に種別・対象軸を併記                       | 依頼を送信せずエラー終了（どちらを優先すべきか推定できない。既定動作で続行しない）                                 |
| スキャン失敗（`build_review_request.py` が非ゼロ終了） | 依頼を送信せず報告して終了（fail closed）。二段構えの片方を落としたまま進めない                                    |
| Codex から返信が来ない（待機予算内）                   | `wait_for_reply.py` が指数バックオフでポーリングを継続する（Step 6.6）                                             |
| Codex から返信が来ない（待機予算超過）                 | フォールバックせず、確定したタイムアウト失敗として報告して終了（Step 7）。利用者に Codex 側の状態確認を促す        |
| 受信メッセージに完了宣言行がない                       | 受信モード Step 1 のとおり、修正せず完了宣言行の再送を依頼する                                                     |
| 返信後に Codex が読まないまま滞留する                  | push型起床（Step 6.5）の呼び忘れを疑う。Claude 側の**あらゆる**送信の直後に必要（依頼・返信・再送を問わない）      |
| 往復上限到達（UC-4）                                   | msg-sys が人間通知へ降格。SKILL は往復回数管理を持たない。人間介在で再開モードへ                                   |
| 受信モードで文脈が失われている                         | プロトコルヘッダをトリガーに本 SKILL.md を再読し、`filter_review_history.py` で当該 review_id の文脈のみを復元する |

## 対象外（v1 スコープ外）

- **session ディレクトリを持たない**: 本スキルは所見の状態をファイルに永続化せず、1 ターン内で受領・評価・修正・返信まで完結させる。所見の評価・修正は専用 Agent へ委譲せず Claude が直接行う（FNC-004）。ただし allowlist 検証・構文検証（検出のみ、ロールバックは Claude 自身が判断）は受信モード Step 2a に導入済み（決定論的スクリプトとして独立）
- Codex セッションの自動起動・管理（人間が手動起動して常駐させる前提）
- msg-sys 既存実装の変更（`send.py` / `inbox.py` 等を利用者として呼ぶのみ）
- **段階的提示（所見を1件ずつ提示して人間の判断を仰ぐ）の実装**。`--interactive`・介入軸未指定時は、ユーザー指示・ユーザー責任で暫定的に `--auto` と同じ振り分けを適用する。実装する際は**本スキル内で完結させる**（受信本文から `parse_findings.py` で得た所見配列をそのまま AskUserQuestion で提示する）。外部スキルへ委譲する形は採らない——所見の状態をファイルに永続化する必要が生じ、上記「session ディレクトリを持たない」と衝突するため
