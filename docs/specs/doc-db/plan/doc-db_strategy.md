# doc-db 実装戦略

## 前提の共有（読み取った現状）

- 対象は forge プラグインのみ。現行 4 SKILL（`plugins/forge/skills/{query,update}-db-{rules,specs}/SKILL.md`）は **script を 1 つも持たず**、`doc-advisor:query-docs` / `index-docs` へ `Skill` ツールで転送するだけの薄い SKILL である（query 系は grep フォールバックを内包、`allowed-tools: Skill, Read, Grep, Glob, Bash`）。
- したがって本 feature は「既存 script の改修」ではなく **共有低レベル層（新規 6 モジュール）+ SKILL 固有 wrapper（新規 10 ファイル）+ SKILL.md 4 本の書き換え** の新規追加が主体である。既存資産で再利用するのは `resolve_doc_structure.py`（`--type rules|specs` が既に project-root 相対のファイル一覧を JSON で返す）と `run_dprint_fmt.sh` の 2 つ。
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
  - `tests/forge/scripts/doc_backend/` に応答注入用の fixture（JSON 応答・SSE 応答・tool error・HTTP error の canned response）。時計・HTTP 送信・process・filesystem を差し替え可能な境界として設ける（§9.1 末尾）。**socket を開く fake server は作らない**（§9.3）。
- **検証ポイント**:
  - `python3 -m unittest discover -s tests -p 'test_*.py'` 全通過（既存テストの回帰なし）。
  - §9.1 の該当行（`docdb_client.py` / `docdb_runtime.py` / `project_documents.py`）の単体テストが緑。特に「秘密値非出力」「実行ファイル不在」「早期終了」「再接続不能」の 4 異常系。
  - 注入した JSON 応答・SSE 応答の両経路が同一の parse 結果を返すこと。
  - **中間検証（`docdb_client.py` 完成時点で先に実施し、後続に持ち越さない）**: 実際に `doc-db` を起動した状態で `initialize` → `tools/call query` が通ること。手元に doc-db 実体があるため、ここで実測して §4.5 スナップショットとのズレを早期に検出する。

### フェーズ 2: operation 層と exit code 契約

- **目標**: 3 つの低レベル CLI が単体で叩けて、exit code 0 / 10 / 20 / 30 が §4.4 の表どおりに出る。SKILL からはまだ呼ばれないため、既存経路は無傷のまま。
- **スコープ**:
  - `plugins/forge/scripts/doc_backend/query_docdb.py` — `mode=all` / `top_n=20` / `series=現在の branch`、`results[].path` の順位維持抽出、**出力前のパス実在確認と除外件数**（§4.2）、`Required documents:` 文字列の決定論的構築（`origin_signals` は出さない／`warnings` は path リストの後に別掲）、対象文書 0 件の先行判定 → 索引状態確認、未整備の exit 30、KEY 不在／ゴミ箱状態／その他障害の error 判別（§4.5）。
  - `plugins/forge/scripts/doc_backend/sync_docdb.py` — `--start`（desired state 投入 → `job_id` 即返し）と `--status <job_id>`（`get_sync_status` 1 回・**未完了でも exit 0**）の 2 操作のみ。**プロセス内ポーリングループを持たない**（§4.3）。0 件時は同期せず明示エラー。
  - `plugins/forge/scripts/doc_backend/prepare_advisor_index.py` — `run_dprint_fmt.sh` 実行 + `.doc_structure.yaml` からの `root_dirs` / `patterns.exclude` 解決。成功 exit 0 / `status=success`、失敗 exit 20 / `status=operation_error`（§5.2 末尾）。
  - 3 CLI 共通の JSON 契約（`status` / `backend` / `operation` / `startup` / `reason_code`）をここで 1 箇所に固定する。SKILL は exit code だけで分岐し JSON から状態を再構成しないため（§4.4）、**JSON field の組合せに意味を持たせない**ことをレビュー観点にする。
- **検証ポイント**:
  - §9.1 の `query_docdb.py` / `sync_docdb.py` / `prepare_advisor_index.py` 単体テストが緑。
  - §9.3 の統合経路のうち script 単体で閉じるものが緑: 初回接続成功 → query 完了 / 初回接続失敗 → 起動後成功 / 0 件で索引に触れない（索引状態確認より前に判定される）/ 未整備 exit 30 / 未整備・0 件のいずれでも series を外した横断検索へ切り替えない / 障害 exit 20 で fallback しない / 実在しない path の除外と件数 / `--start` の job_id / `--status` の未完了 exit 0。
  - **中間検証（`query_docdb.py` 完成時点。`sync_docdb.py` を待たない）**: 実 doc-db に対して `query_docdb.py` を手で叩き、既存 doc-advisor 出力と `Required documents:` の形が一致すること（NFR-002 の出力互換）。
  - **実 doc-db に対する error 文言の実測**（確認事項 3 の解消）: 存在しない KEY への query と、`trash_index` 済み KEY への query が返す error を実際に採取し、判別根拠を DES-057 §4.5 へ追記する。判別できない error は障害扱いのままにする（fail-safe を崩さない）。

### フェーズ 3: wrapper と SKILL.md の切替（update → query の順）

- **目標**: 4 SKILL が doc-db 優先で動き、doc-db 不在時に doc-advisor へ落ち、両方不在なら失敗する。grep フォールバックが消える。
- **スコープ**: SKILL 固有 wrapper 計 10 ファイル（DES-024 §2.1 単一ラッパー・category を hardcode・位置引数のみ・透過）:
  - `query-db-{rules,specs}/scripts/`: `query_documents.py`、`sync_documents.py`、`prepare_advisor_index.py`（各 3 本 = 6）
  - `update-db-{rules,specs}/scripts/`: `sync_documents.py`、`prepare_advisor_index.py`（各 2 本 = 4）
  - DES-024 §3.2 に従い共有 wrapper 層は作らない。同名 wrapper を SKILL ごとに置き、固定値（`rules` / `specs`）だけが異なる。
- **切替の順序（これが本フェーズの要点）**:
  - **3a. `update-db-rules` / `update-db-specs` を先に切り替える。** 理由は 2 つ。(1) update 経路は `check-toc` を呼ばず（§5.3）、分岐が「doc-db sync + ポーリング」か「prepare → index-docs」の 2 本だけで最も単純。(2) query 経路の未整備リカバリ（exit 30 → `--start` → `--status` ポーリング → query 再実行）は sync 経路そのものに依存するため、sync 経路を先に実運用で検証済みにしておくと、query 側の失敗原因を sync と query に切り分けられる。
  - **3b. `query-db-rules` / `query-db-specs` を切り替える。** ここで初めて grep フォールバック手順の削除と `allowed-tools` からの `Grep` 削除（`Skill, Read, Bash` へ）、`check-toc` の 3 分岐（§5.1.3）、`advisor_absent` / `advisor_outdated` の区別（§2.4）、§7.1 の母集団相違通知を入れる。
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

### フェーズ 4: 契約テストと周辺文書の整合

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

| リスク                                                                                                                                          | 影響度 | 対策（どのフェーズで潰すか）                                                                                                                                     |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| KEY 不在とゴミ箱状態を error 文言から判別する設計（§4.5）が、doc-db のメッセージ文言に依存して脆い。誤判別するとゴミ箱 KEY へ同期を試みる       | 高     | フェーズ 2 で実 doc-db から両 error を実測し、判別根拠を §4.5 に追記。判別不能な error は障害（exit 20）扱いのまま維持し、未整備側に倒さない                     |
| series 未同期の検出手段が §4.5 の tool 表に無い（参考実装は `list_indexes` を使うが、表は `query` / `sync_documents` / `get_sync_status` のみ） | 高     | フェーズ 2 着手前に方式を確定（確認事項 4）。`list_indexes` を使うなら §4.5 スナップショットへ追記してから実装する                                               |
| MCP Streamable HTTP + SSE を標準ライブラリのみで実装する部分が未検証                                                                            | 高     | フェーズ 1 に前倒し。注入応答で JSON / SSE 双方の解析を通し、さらに実 doc-db で中間検証する                                                                      |
| on-demand 起動（`Popen` 新規セッション・切り離し）が環境依存で失敗する / 別 wrapper と競合起動する                                              | 中     | フェーズ 1。§2.3 のとおり「MCP 接続に成功すれば利用可能」と判定し、プロセスの生死ではなく接続で判定する。probe 上限（1s / 10s / 0.25s）で長時間ブロックしない    |
| SKILL 側ポーリングの実装が SKILL.md 記述に依存し、AI が進捗報告を省略する（NFR-001 違反）                                                       | 中     | フェーズ 3。`--status` 1 回 = 1 報告の対応を SKILL.md に `[MANDATORY]` で固定。フェーズ 3a の実行検証で進捗がチャットに出ることを目視確認する                    |
| SKILL.md 書き換え中に既存 doc-advisor 経路が壊れ、リポジトリ自身の `/forge:query-db-*` が使えなくなる（本リポジトリは SoT のため実害が大きい）  | 中     | フェーズ 3 を 3a（update）→ 3b（query）に分割。共有層・operation 層（フェーズ 1・2）は SKILL から参照されないため、フェーズ 2 完了時点までは既存経路が完全に無傷 |
| doc-advisor の `check-toc` 応答が既知値以外だったときに fresh へ縮退して stale ToC で検索してしまう                                             | 中     | フェーズ 3b + 4。§5.1.4 の「縮退せず明示エラー」を実装し、契約テストで固定                                                                                       |
| forge のテストが doc-advisor / doc-db の内部判定に依存し、外部変更で壊れる                                                                      | 中     | フェーズ 4。`fresh` / `stale` は応答値として与え判定を再現しない。境界値・skew・`generated_at` 解析に依存するテストを書かない                                    |
| 4 SKILL × 同名 wrapper の量産で、固定値だけ違う 10 ファイルの取り違え                                                                           | 低     | フェーズ 3。wrapper テストで category 固定値を各ファイルについて明示的に assert する（DES-024 §8）                                                               |
| 実在確認の除外が同期直後の正常結果まで削ってしまう（0 件化）                                                                                    | 低     | フェーズ 2。除外はパス存在判定のみ（内容読み取り・checksum なし）。全件除外でも operation は成功・空の `Required documents:` を返す仕様をテストで固定            |

## 確認事項の決着（DES-057 へ反映済み）

戦略策定時に挙げた 4 件は、いずれも DES-057 側を修正して決着した。実装前に残る判断はない。

### 1. 「共有低レベル script どうしの依存も持たない」（§3.1）の解釈 → 案 A

禁止対象は **CLI エントリ script 相互の呼び出し**（`query_docdb.py` ↔ `sync_docdb.py` ↔ `prepare_advisor_index.py`）であり、helper モジュールの import は同一層内でも許容する、と §3.1 を書き換えた。CLI 相互の呼び出しを禁じることで、複数 operation の進行と進捗報告の位置が SKILL 側に固定される。

### 2. 対象文書 0 件判定を誰が行うか → 案 A

`query_docdb.py` が `project_documents.py` を使って件数を得る。§3.2 の依存列に `project documents` を追記した（記載漏れの修正）。

### 3. KEY ゴミ箱状態の判別根拠 → 実測してから確定

§4.5 に「判別に用いる signal は実装時に確定する。実 doc-db に対して『存在しない KEY への query』と『ゴミ箱状態の KEY への query』を実測し、得られた error の識別可能な要素を本項に追記してから実装へ進む」と明記した。実測前に文言を推測して固定しない。判別できない場合は障害扱いに倒す既定を保つ。**フェーズ 2 の作業に含まれる。**

### 4. series 未同期の検出方式 → 案 (a)

`list_indexes` を §4.5 の tool 表に追加し、当該 series の登録確認に使うことと、`series[]` が「未同期」と「同期済みだが 0 件」を区別できないため対象文書数 0 の判定を先に行うことを明記した。参考実装と同じ手段になる。

### 5. 統合テストの方式（本戦略書のレビューで判明）→ 送信境界への応答注入

§9.3 の「fake HTTP server を使い」を「HTTP 送信境界に応答を注入して」へ変更した。移植元が送信を 1 関数に閉じているため socket は不要で、fake server は実 doc-db 検証の劣化版にしかならない。実際に HTTP を話せることの確認は実 doc-db への実行で 1 度行い、テストには含めない。
