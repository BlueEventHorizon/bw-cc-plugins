# doc-db 実装戦略

## 前提の共有（読み取った現状）

- 対象は forge プラグインのみ。現行 4 SKILL（`plugins/forge/skills/{query,update}-db-{rules,specs}/SKILL.md`）は **script を 1 つも持たず**、`doc-advisor:query-docs` / `index-docs` へ `Skill` ツールで転送するだけの薄い SKILL である（query 系は grep フォールバックを内包、`allowed-tools: Skill, Read, Grep, Glob, Bash`）。
- したがって本 feature は「既存 script の改修」ではなく **共有低レベル層（新規 7 モジュール。`.claude/.forge.yaml` を読む forge_settings.py を含む）+ SKILL 固有 wrapper（新規 10 ファイル）+ SKILL.md 4 本の書き換え** の新規追加が主体である。既存資産で再利用するのは `resolve_doc_structure.py`（`--type rules|specs` が既に project-root 相対のファイル一覧を JSON で返す）と `run_dprint_fmt.sh` の 2 つ。
- 移植元は doc-db-mcp-server 同梱の `docdb_client.py`（589 行・JSON-RPC/SSE/session/`sync-start`/`sync-status`/`--series` 検証を実装済み）、`resolve_docs.py`（`detect_project_name` = `git rev-parse --git-common-dir` の親、`detect_git_branch` = detached は `main`）、`run_sync.py`（`--start-only` の 0 件防御）。DES-057 §4.5 のスナップショットは実装と一致している。
- 移植元 `docdb_client.py` は **HTTP 送信を `_post()` の 1 箇所に閉じ、応答解析を `_parse_response(raw, content_type)` の純関数に分離している**。したがって統合テストに socket を開く fake server は不要で、送信境界への応答注入で JSON / SSE / tool error / HTTP error をすべて決定論的に再現できる（DES-057 §9.3）。
- 移植元に Python テストは存在しない（doc-db 側のテストは Go の `internal/`）。テスト資産は移植できないため、forge 側で新規に書く。
- wrapper テストの共通 helper は `tests/forge/wrapper_helpers.py` に既存（`assert_transparent_subprocess_kwargs` / `assert_exit_code_transparent`）で、DES-024 §2.3 の透過性検証をそのまま流用できる。

## アプローチ

**選択**: ボトムアップ（基盤層 → operation 層 → SKILL）+ リスク駆動（最不確実な要素を第 1 フェーズに前倒し）

**根拠**:

- DES-057 §3.1 の依存方向は `SKILL.md → SKILL 固有 wrapper → 共有低レベル script → 外部 backend` の一方向で、循環がない純粋な階層構造である。上位から作ると下位が stub になり、最大リスク（MCP HTTP 直結・SSE 解析・on-demand 起動）の検証が最後まで先送りされる。よって基盤層優先が自然。
- 一方で本 feature の技術的不確実性は下位層に集中している（`urllib` による MCP Streamable HTTP、SSE 応答、`subprocess.Popen` の新規セッション起動と期限付き再接続、`Mcp-Session-Id` の維持）。基盤層を先に作ることは同時にリスク駆動でもあり、2 つのアプローチは競合しない。
- スケルトン先行は採らない。既存 4 SKILL は**現在 doc-advisor 単一前提で正常動作している**ため、SKILL.md を先に書き換えて stub を呼ばせると、その間ずっと既存経路が壊れる。SKILL.md の書き換えは「呼ぶ先の CLI が exit code 契約どおりに動くと確認できた後」に限る。
- フィーチャースライスも採らない。4 SKILL は同じ共有層を使うため、1 SKILL だけ縦断実装しても共有層の完成度は変わらず、SKILL.md 書き換えのリスクだけが早期に持ち込まれる。ただし **SKILL.md 書き換えの順序**（update → query）はスライス的に分割する（フェーズ 3 参照）。

## フェーズ

### フェーズ 1: 共有低レベル基盤と応答注入テスト

- **目標**: doc-db への MCP 接続・on-demand 起動・project identity 解決が単体で動作し、注入した JSON 応答と SSE 応答の両方を通せる。既存 4 SKILL の挙動は 1 バイトも変わらない。
- **スコープ**（DES-057 §3.2 の下段 3 モジュール）:
  - `plugins/forge/scripts/doc_backend/docdb_client.py` — MCP session / JSON-RPC / JSON・SSE 解析（§2.2）。移植元から `upsert` / `upsert-batch` / `delete-series` / `sync`（プロセス内ポーリング版）を落とし、forge が使う `query` / `sync_documents` / `get_sync_status` に縮小する。通信定数は §2.2 の値（operation timeout 600s / poll 2s / 既定 port 58080 / probe timeout 1s / 起動待ち 10s / 再試行 0.25s）。
  - `plugins/forge/scripts/doc_backend/docdb_runtime.py` — 接続 probe、`shutil.which("doc-db")`、`Popen`（新規セッション・標準入出力切り離し）、期限付き再接続、理由コード生成（§2.3）。ログファイルを作らないこと・認証情報を読まないこと（NFR-005）をここで固定する。
  - `plugins/forge/scripts/doc_backend/project_documents.py` — `{project_name}-{category}` の key、branch series、detached → `main`、対象文書一覧（§4.1）。既存 `resolve_doc_structure.py --type` を subprocess で呼んで再利用し、YAML パーサを二重実装しない。`query_docdb.py` / `sync_docdb.py` の双方が本モジュール経由で件数と一覧を得る（確認事項 2）。
  - `tests/forge/doc_backend/` に応答注入用の fixture（JSON 応答・SSE 応答・tool error・HTTP error の canned response）。時計・HTTP 送信・process・filesystem を差し替え可能な境界として設ける（§9.1 末尾）。**socket を開く fake server は作らない**（§9.3）。
- **検証ポイント**:
  - `python3 -m unittest discover -s tests -p 'test_*.py'` 全通過（既存テストの回帰なし）。
  - §9.1 の該当行（`docdb_client.py` / `docdb_runtime.py` / `project_documents.py`）の単体テストが緑。特に「秘密値非出力」「実行ファイル不在」「早期終了」「再接続不能」の 4 異常系。
  - 注入した JSON 応答・SSE 応答の両経路が同一の parse 結果を返すこと。
  - **中間検証（`docdb_client.py` 完成時点で先に実施し、後続に持ち越さない）**: 実際に `doc-db` を起動した状態で `initialize` → `tools/call query` が通ること。手元に doc-db 実体があるため、ここで実測して §4.5 スナップショットとのズレを早期に検出する。

#### 中間検証の実施記録（doc-db 0.3.2 / 2026-07-31・読み取り専用）

- **手順**: 起動済み doc-db（port 58080）に対し `docdb_client.py` を importlib でロードし、`initialize` → `notifications/initialized` → `tools/call` を実行。`list_indexes` で実在 KEY / series を確認したうえで `query`（`mode=all` / `top_n` 小）を 1 回呼び、transport 層で Content-Type とヘッダを記録した。書き込み系 tool は呼んでいない。
- **結果**: 接続確立・`list_indexes`・`query` すべて成功。session は `initialize` 応答の `Mcp-Session-Id` で確立。**応答は全て SSE（`text/event-stream`）で、JSON 応答は観測されなかった**（client は両対応を維持）。
- **§4.5 とのズレ（実測値へ更新済み）**: (1) `warnings` は正常時に field 自体が存在しない、(2) `list_indexes` は `indexes[]` を包む形で `series` は `null` を取り得る、(3) result は `content[].text` と `structuredContent` の両方に同一内容が載る、(4) KEY 不在は JSON-RPC error ではなく `isError: true` + 文言 `key "<key>" が存在しません`（`code` / `data` なし）、(5) **既存 KEY の未登録 series への query は error にならず 0 件成功**するため、未整備検出は `list_indexes` に依拠するほかない。
- **持ち越し（解消済み・2026-08-01）**: ゴミ箱状態 KEY の error 文言は `trash_index` が必要で読み取り専用検証では採取できず、フェーズ 2 での実測に持ち越していた。その後 doc-db 0.3.3 で機械可読な識別子が公開契約として導入されたため、文言の実測自体が不要になった（ADR-058）。実測 (4) の「`isError: true` + 文言」も 0.3.2 時点の観測であり、0.3.3 では JSON-RPC error + `data.code` に変わっている。

### フェーズ 2: operation 層と exit code 契約

- **目標**: 3 つの低レベル CLI が単体で叩けて、exit code 0 / 10 / 20 / 30 が §4.4 の表どおりに出る。SKILL からはまだ呼ばれないため、既存経路は無傷のまま。
- **スコープ**:
  - `plugins/forge/scripts/forge_settings.py` — `.claude/.forge.yaml` の読み取り（DES-061）。共有低レベル層だがフェーズ 1 完了後の要件追加（REQ-014 優先 backend 指定）で加わったため本フェーズで実装する。load / section の 2 関数のみ・標準ライブラリの行ベースパーサ・不在は空 dict・解析不能は明示エラー。
  - `plugins/forge/scripts/doc_backend/query_docdb.py` — `mode=all` / `top_n=20` / `series=現在の branch`、`results[].path` の順位維持抽出、**出力前のパス実在確認と除外件数**（§4.2）、`Required documents:` 文字列の決定論的構築（`origin_signals` は出さない／`warnings` は path リストの後に別掲）、対象文書 0 件の先行判定 → 索引状態確認、未整備の exit 30、KEY 不在／ゴミ箱状態／その他障害の error 判別（§4.5）。優先 backend の分岐は持たない（責務分離により `resolve_backend_order.py` へ分離。§2.5）。
  - `plugins/forge/scripts/doc_backend/sync_docdb.py` — `--start`（desired state 投入 → `job_id` 即返し）と `--status <job_id>`（`get_sync_status` 1 回・**未完了でも exit 0**）の 2 操作のみ。**プロセス内ポーリングループを持たない**（§4.3）。0 件時は同期せず明示エラー。
  - `plugins/forge/scripts/doc_backend/prepare_advisor_index.py` — `run_dprint_fmt.sh` 実行 + `.doc_structure.yaml` からの `root_dirs` / `patterns.exclude` 解決。成功 exit 0 / `status=success`、失敗 exit 20 / `status=operation_error`（§5.2 末尾）。
  - 3 CLI 共通の JSON 契約（`status` / `backend` / `operation` / `startup` / `reason_code`）をここで 1 箇所に固定する。SKILL は exit code だけで分岐し JSON から状態を再構成しないため（§4.4）、**JSON field の組合せに意味を持たせない**ことをレビュー観点にする。
- **検証ポイント**:
  - §9.1 の `query_docdb.py` / `sync_docdb.py` / `prepare_advisor_index.py` 単体テストが緑。
  - §9.3 の統合経路のうち script 単体で閉じるものが緑: 初回接続成功 → query 完了 / 初回接続失敗 → 起動後成功 / 0 件で索引に触れない（索引状態確認より前に判定される）/ 未整備 exit 30 / 未整備・0 件のいずれでも series を外した横断検索へ切り替えない / 障害 exit 20 で fallback しない / 実在しない path の除外と件数 / `--start` の job_id / `--status` の未完了 exit 0。
  - **中間検証（`query_docdb.py` 完成時点。`sync_docdb.py` を待たない）**: 実 doc-db に対して `query_docdb.py` を手で叩き、既存 doc-advisor 出力と `Required documents:` の形が一致すること（NFR-002 の出力互換）。
  - **識別子契約への適合確認**（確認事項 3 の決着後の残り作業）: 存在しない KEY への query が `error.data.code == "KEY_NOT_FOUND"` を返すことを実 doc-db 0.3.3 で確認し、注入 fixture をその形に合わせる。`KEY_TRASHED` は公開契約の値であるため `trash_index` を実行して確かめることはしない。識別子を読み取れない error は障害扱いのままにする（fail-safe を崩さない）。

#### 識別子契約への適合確認の実施記録（doc-db 0.3.3 / 2026-08-02・読み取り専用）

- **手順**: 未起動の doc-db を `docdb_runtime.ensure_available()` の on-demand 起動（非破壊）で立ち上げ、実在しない KEY（乱数 suffix 付き）へ `query` を 1 回実行した。書き込み系 tool は呼んでいない。
- **結果**: `serverInfo.version` は 0.3.3。KEY 不在は **JSON-RPC error** として届き、`error.data.code == "KEY_NOT_FOUND"`（判別の正本）、`message` は同一の識別子トークン `KEY_NOT_FOUND:` で始まり、数値 code（-31001）は補助として載った。`docdb_client.py` の `ToolError` から `data["code"]` を取り出せることも確認した。応答は SSE（`text/event-stream`）で、フェーズ 1 の観測と変わらない。
- **DES-057 §4.5 とのズレ**: なし（§4.5 の「KEY 状態に関する doc-db の挙動」の契約記述どおり。更新不要）。
- **fixture 整備**: `tests/forge/doc_backend/test_docdb_client.py` の注入 fixture を実応答の形（`KEY_NOT_FOUND`）に合わせ、`KEY_TRASHED` は契約記述（ADR-058 / DES-057 §4.5）から書いた（`trash_index` による採取はしない）。判別テストは `data["code"]` と `message` 先頭トークンのみに依拠し、文言全文・数値 code に依存する記述を持ち込んでいない。

### フェーズ 3: wrapper と SKILL.md の切替（update → query の順）

- **目標**: 4 SKILL が doc-db 優先で動き、doc-db 不在時に doc-advisor へ落ち、両方不在なら失敗する。grep フォールバックが消える。
- **スコープ**: SKILL 固有 wrapper 計 10 ファイル（DES-024 §2.1 単一ラッパー・category を hardcode・位置引数のみ・透過）:
  - `query-db-{rules,specs}/scripts/`: `query_documents.py`、`sync_documents.py`、`prepare_advisor_index.py`（各 3 本 = 6）
  - `update-db-{rules,specs}/scripts/`: `sync_documents.py`、`prepare_advisor_index.py`（各 2 本 = 4）
  - DES-024 §3.2 に従い共有 wrapper 層は作らない。同名 wrapper を SKILL ごとに置き、固定値（`rules` / `specs`）だけが異なる。
- **切替の順序（これが本フェーズの要点）**:
  - **3a. `update-db-rules` / `update-db-specs` を先に切り替える。** 理由は 2 つ。(1) update 経路は `check-toc` を呼ばず（§5.3）、分岐が「doc-db sync + ポーリング」か「prepare → index-docs」の 2 本だけで最も単純。(2) query 経路の未整備リカバリ（exit 30 → `--start` → `--status` ポーリング → query 再実行）は sync 経路そのものに依存するため、sync 経路を先に実運用で検証済みにしておくと、query 側の失敗原因を sync と query に切り分けられる。
  - **3b. `query-db-rules` / `query-db-specs` を切り替える。** ここで初めて grep フォールバック手順の削除と `allowed-tools` からの `Grep` 削除（`Skill, Read, Bash` へ）、`check-toc` の 3 分岐（§5.1.3）、`advisor_absent` / `advisor_outdated` の区別（§2.4）、§7.1 の母集団相違通知を入れる。両段とも、入口で `resolve_backend_order.py` による順序リスト解決（既定 doc-advisor 先位）から始め、先位不能時の切替理由の通知（§2.5・FNC-004）を含む。
  - どちらの段でも、切替済み SKILL は doc-db 不在環境で従来と同じ doc-advisor 経路に落ちる（`check-toc` が入る点だけが差分）。したがって 3a 完了・3b 未着手という中間状態でも 4 SKILL すべてが動作する。
- **SKILL.md 側の注意（ルール文書由来の制約）**:
  - ポーリングループは SKILL 側に置き、`--status` を呼ぶたびに進捗をテキストで報告する（§4.2 / §4.3 / NFR-001）。script の stderr に委ねない。
  - 手続きロジックを SKILL.md にインライン記述しない（`implementation_guidelines.md`「SKILL.md にインラインスクリプトを書かない」）。呼ぶのは wrapper の 1 行。
  - 4 SKILL とも継承型 SKILL のまま（`context: fork` を書かない）。自己再帰禁止の記述は維持する。
  - フォールバック文言は「その異常系に対する正しいリカバリー」であることを SKILL.md 上で説明できる形に限る（同ルール「フォールバックを反射的に書かない」）。接続確立後の operation 失敗を fallback にしない設計はこの規律と一致している。
- **検証ポイント**:
  - §9.2 wrapper テスト: category 固定値、位置引数の透過、stdout/stderr/exit code の透過。`sync_documents.py` は `--start` / `--status <job_id>` の両操作が透過すること。query wrapper は task を 1 つの位置引数として渡し、update wrapper は利用者入力を要求しないこと。`tests/forge/wrapper_helpers.py` の既存 assert を再利用する。
  - **3a 完了時点で実行検証**: `/forge:update-db-rules` を doc-db 起動状態と停止状態の両方で実行し、前者で sync 進捗がチャットに出ること・後者で doc-advisor `index-docs` に落ちることを確認する（**3b を待たない**）。
  - **3b 完了時点で実行検証**: `/forge:query-db-rules` を (a) doc-db 起動・索引あり (b) doc-db 起動・当該 series 未同期（exit 30 → 同期 → 再検索） (c) doc-db 停止・ToC fresh (d) doc-db 停止・ToC stale の 4 条件で実行する。
  - 静的検証: 4 SKILL.md に `Grep` 許可と grep 手順が残っていないこと。

#### 実測記録: query_docdb.py の実 doc-db 中間検証と出力互換確認（doc-db 0.3.3 / 2026-08-02）

フェーズ 2 で規定した `query_docdb.py` の中間検証（実 doc-db への手動実行と NFR-002 出力互換）と、
3a/3b が自動化する経路（未整備 exit 30 → `--start` → `--status` ポーリング → query 再実行）の手動での通し実測。
sync は本リポジトリの project identity（KEY `bw-cc-plugins-rules`）と現在の branch（series `feature/forge-settings`）
のみに対して行い、破壊的操作（`trash_index` / `schedule_delete_series` 等）は実行していない。

- **未整備の exit 30**: KEY `bw-cc-plugins-rules` が未生成の状態で
  `query_docdb.py rules "<task>"` を実行 → exit `30` / `status=index_missing` / `reason_code=key_not_found` を実測
  （検出は `list_indexes` 依拠。対象文書数 7 件の先行判定を通過してからの判定であることも JSON の `document_count` で確認）。
- **同期 → 再検索**: `sync_docdb.py rules --start` が `job_id` を即時返却（count=7）、`--status` 1 回目で
  `done`（processed=7）。query 再実行は exit `0` で `Required documents:` を返した。
- **出力互換（NFR-002）**: JSON の `result` は `Required documents:` ヘッダ + `- <相対パス>` 列挙であり、
  DocAdvisor 0.4.6 `query-worker` の Output Format（形式 A: `Required documents:` + `- docs/...` 列挙・相対パス・
  0 件はヘッダのみ）と一致することを確認。差はヘッダ直後の空行 1 行のみで、これは DES-057 §4.2 が規定する
  forge 側契約どおり。
- **実在しないパスの除外**: 一時文書 `docs/rules/task009_zxqprobe_temp.md`（untracked・一意キーワード入り）を
  作成 → sync（done / processed=1・skipped=7）→ ファイル削除 → 当該キーワードで query。結果は exit `0` の成功で、
  `excluded_count: 1` と notice「実在しないパス 1 件を検索結果から除外しました」を実測（git 追跡ファイルには
  触れていない）。実測後に再 sync し、`deleted_paths_marked: 1` で索引を現状（7 件）へ収束させた。
- **§4.5 とのズレ（同じ変更で §4.5 を更新済み）**:
  1. `get_sync_status` の実応答（done）に `errors` field が存在せず、`sync_docdb.py` の契約検証が exit 20 で
     誤失敗した。`warnings` と同じ省略形と判断し、不在・`null` を空リストへ正規化する形へ `sync_docdb.py` と
     テストを修正（リスト以外の値は従来どおり契約違反）。
  2. `query` の `results[]` は chunk 単位で返り、同一 path が複数回現れる（top_n=20 が 4 文書程度に畳まれる）。
     §4.5 へ実測事実として追記した。§4.2 の現行契約（順位どおりにそのまま返す・重複除去は未規定）は
     変更していない。重複除去の要否は設計判断として未決着（本記録で顕在化した論点）。

- **目標**: doc-advisor 側 I/F への依拠が機械検証され、本変更で古くなる文書が同じ変更内で直っている。
- **スコープ**:
  - §9.3 後半の doc-advisor 契約テスト／静的テスト: `--key` と `--max-age 86400` を渡すこと、`fresh` / `stale` / `status=error` の 3 分岐、`stale` 時だけ prepare → `index-docs` → `query-docs` の順になること、exit code ではなく `status` / `freshness` で分岐すること、`reason` 等の補助 field に依存しないこと、§5.1.4 の防御（解析不能・既知値以外で query を呼ばず失敗）、§7.1 の通知が doc-advisor 経路だけに出ること。**境界値・skew 60 秒・`generated_at` の解析可否に依存するテストを書かない**（§9.3 末尾。書くと DocAdvisor の内部変更で forge のテストが壊れる）。
  - 導入案内への最小対応 DocAdvisor **0.4.6** の記載（REQ-014 前提条件・§2.4）。
  - 本変更で嘘になる記述の修正: `README.md`（「forge の検索系は doc-advisor へ転送する」前提の記述群）、`CLAUDE.md` 冒頭の「文書検索バックエンド（doc-advisor）は外部依存」注記、`docs/readme/` の該当記述。
  - `docs/specs/forge/design/DES-001` および旧設計書群の更新は **本フェーズでは行わない**。REQ-014 / DES-057 の frontmatter が「旧仕様ファイルは本 feature 実装完了まで書き換えない」と定めており、統合は `/forge:merge-specs` の fold で行う。
- **検証ポイント**:
  - 全テストスイート通過 + `dprint check` 通過。
  - CHANGELOG / version 関連ファイルに差分がないこと（feature PR の禁止事項）。
  - REQ-014 FNC-001〜004・NFR-001〜005・BL-001〜005 の各項に対応する実装・テストを 1 対 1 で突き合わせ、欠落がないことを確認する。

## リスクと対策

| リスク                                                                                                                                         | 影響度 | 対策（どのフェーズで潰すか）                                                                                                                                                                                                                                      |
| ---------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ~~KEY 不在とゴミ箱状態を error 文言から判別する設計が脆い~~ **解消**                                                                           | -      | doc-db 0.3.3 で機械可読な識別子（`KEY_NOT_FOUND` / `KEY_TRASHED`）が公開契約として導入され、文言依拠をやめた（ADR-058）。実測による文言確定は不要になり、`trash_index` を伴う破壊的検証も行わない。識別子を読み取れない error は障害（exit 20）扱いのまま維持する |
| `list_indexes` の `series[]` が「未同期」と「同期済みだが 0 件」を区別できない。取り違えると 0 件の正常結果を未整備と誤判定して索引作成へ倒す  | 高     | **検出方式は決着済み**（確認事項 4 / §4.5 の tool 表に `list_indexes` を追加済み）。残るのはこの取り違えであり、フェーズ 2 で「対象文書数 0 の判定を先に行う」順序をテストで固定する                                                                              |
| MCP Streamable HTTP + SSE を標準ライブラリのみで実装する部分が未検証                                                                           | 高     | フェーズ 1 に前倒し。注入応答で JSON / SSE 双方の解析を通し、さらに実 doc-db で中間検証する                                                                                                                                                                       |
| on-demand 起動（`Popen` 新規セッション・切り離し）が環境依存で失敗する / 別 wrapper と競合起動する                                             | 中     | フェーズ 1。§2.3 のとおり「MCP 接続に成功すれば利用可能」と判定し、プロセスの生死ではなく接続で判定する。probe 上限（1s / 10s / 0.25s）で長時間ブロックしない                                                                                                     |
| SKILL 側ポーリングの実装が SKILL.md 記述に依存し、AI が進捗報告を省略する（NFR-001 違反）                                                      | 中     | フェーズ 3。`--status` 1 回 = 1 報告の対応を SKILL.md に `[MANDATORY]` で固定。フェーズ 3a の実行検証で進捗がチャットに出ることを目視確認する                                                                                                                     |
| SKILL.md 書き換え中に既存 doc-advisor 経路が壊れ、リポジトリ自身の `/forge:query-db-*` が使えなくなる（本リポジトリは SoT のため実害が大きい） | 中     | フェーズ 3 を 3a（update）→ 3b（query）に分割。共有層・operation 層（フェーズ 1・2）は SKILL から参照されないため、フェーズ 2 完了時点までは既存経路が完全に無傷                                                                                                  |
| doc-advisor の `check-toc` 応答が既知値以外だったときに fresh へ縮退して stale ToC で検索してしまう                                            | 中     | フェーズ 3b + 4。§5.1.4 の「縮退せず明示エラー」を実装し、契約テストで固定                                                                                                                                                                                        |
| forge のテストが doc-advisor / doc-db の内部判定に依存し、外部変更で壊れる                                                                     | 中     | フェーズ 4。`fresh` / `stale` は応答値として与え判定を再現しない。境界値・skew・`generated_at` 解析に依存するテストを書かない                                                                                                                                     |
| 4 SKILL × 同名 wrapper の量産で、固定値だけ違う 10 ファイルの取り違え                                                                          | 低     | フェーズ 3。wrapper テストで category 固定値を各ファイルについて明示的に assert する（DES-024 §8）                                                                                                                                                                |
| 実在確認の除外が同期直後の正常結果まで削ってしまう（0 件化）                                                                                   | 低     | フェーズ 2。除外はパス存在判定のみ（内容読み取り・checksum なし）。全件除外でも operation は成功・空の `Required documents:` を返す仕様をテストで固定                                                                                                             |

## 確認事項の決着（DES-057 へ反映済み）

戦略策定時に挙げた 4 件と、本戦略書のレビューで追加された 1 件（下記 5）は、いずれも DES-057 側を修正して決着した。実装前に残る判断はない。

### 1. 「共有低レベル script どうしの依存も持たない」（§3.1）の解釈 → 案 A

禁止対象は **CLI エントリ script 相互の呼び出し**（`query_docdb.py` ↔ `sync_docdb.py` ↔ `prepare_advisor_index.py`）であり、helper モジュールの import は同一層内でも許容する、と §3.1 を書き換えた。CLI 相互の呼び出しを禁じることで、複数 operation の進行と進捗報告の位置が SKILL 側に固定される。

### 2. 対象文書 0 件判定を誰が行うか → 案 A

`query_docdb.py` が `project_documents.py` を使って件数を得る。§3.2 の依存列に `project documents` を追記した（記載漏れの修正）。

### 3. KEY ゴミ箱状態の判別根拠 → 識別子契約に依拠（2026-08-01 に決着）

当初は「実測して得た error の識別可能な要素で判別する」としていたが、doc-db 側へ照会した結果、当該文言は公開契約ではなかった。doc-db 0.3.3 で機械可読な識別子（`error.data.code` の `KEY_NOT_FOUND` / `KEY_TRASHED`）が公開契約として導入され、forge はこれにのみ依拠する。文言・数値 code では分岐しない。決定と代替案の棄却理由は **ADR-058** に記録した。判別できない場合は障害扱いに倒す既定を保つ。

### 4. series 未同期の検出方式 → 案 (a)

`list_indexes` を §4.5 の tool 表に追加し、当該 series の登録確認に使うことと、`series[]` が「未同期」と「同期済みだが 0 件」を区別できないため対象文書数 0 の判定を先に行うことを明記した。参考実装と同じ手段になる。

その後 doc-db 側へ照会し、この手順が backend 側の想定と一致していることを確認した（2026-08-01）。あわせて次の 2 点が安定契約として確認できたため、§4.5 に反映済み。(1) 未登録 series への query が 0 件成功で返るのは意図された仕様で、将来もエラー化しない。(2) `list_indexes` の `series: null` は空配列 `[]` と同義であり、同一視してよい。

### 5. 統合テストの方式（本戦略書のレビューで判明）→ 送信境界への応答注入

§9.3 の「fake HTTP server を使い」を「HTTP 送信境界に応答を注入して」へ変更した。移植元が送信を 1 関数に閉じているため socket は不要で、fake server は実 doc-db 検証の劣化版にしかならない。実際に HTTP を話せることの確認は実 doc-db への実行で 1 度行い、テストには含めない。
