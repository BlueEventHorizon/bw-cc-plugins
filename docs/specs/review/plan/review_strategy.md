# review 実装戦略

対象は REQ-029・REQ-027・REQ-026 と DES-084・DES-083 である。これらは差分開発型（`feature_type: temporary-feature`）の文書で、旧仕様は REQ-013・DES-066・DES-055・REQ-016・DES-072 などが持つ。

## 調査の範囲

- 本文を通読した: 上記の要件定義書 3 件・設計書 2 件、REQ-013、REQ-016、DES-072、DES-066（§1〜§3.1.1。以降は未読）
- 実体を通読した: `agents/reviewer.md`、`agents/evaluator.md`、`skills/review/SKILL.md`、`skills/agent-review/SKILL.md`、`code_review_request_template.md`、`diff_review_request_template.md`、`resolve_review_backend.py` の冒頭 120 行、`scripts/plan/strategy_exchange.py` の冒頭 60 行（受け渡し script の既存の型として参照した）
- 存在と参照関係だけを確認した（本文は読んでいない）: `build_review_request.py`、`parse_findings.py`、`parse_evaluation.py`、`combine_findings_and_evaluations.py`、`split_by_location.py`、`resolve_targets.py`、`scan_secrets.py`、`verify_fix_safety.py`、`capture_syntax_baseline.py`、`collect_modified_files.py`、`resolve_doc_structure.py`、`consult/SKILL.md`（agenda 呼び出しの箇所だけ）、`group_review_batch.py`
- 検索で拾えたが読んでいない: DES-055、DES-047、REQ-017、DES-078、agenda の要件定義書・設計書。以下の判断のうち、これらに依存するものは、タスク化のときに各タスクの必読へ加える
- 既存テストのうち、横断系（`tests/common/test_plugin_integrity.py`・`test_test_discovery.py`、`tests/forge/agents/test_agent_frontmatter.py`、`tests/forge/subagent/` の 5 本、`tests/forge/doc_structure/test_forge_toc_freshness.py`）と、`tests/forge/agent-review/test_agent_review_contract.py`、`tests/forge/agenda/test_agenda_integration.py` は本文を読んだ。その制約を下の「既存テストが課す制約」にまとめた。`tests/forge/review/` の各 script のテストは、削除・修正する script と 1 対 1 で、名前の突き合わせだけを行った

## 既存実装との不一致

| 既存実装                                                                                                                                                 | 新仕様との食い違い                                                                                                                                                                                                                              | 処置                                                                                                       |
| -------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `agents/reviewer.md`                                                                                                                                     | 応答の最終行に `REVIEW_RESULT:` 宣言と重大度マーカー付き自由記述を返す形。新仕様は script 経由の JSON 書き出しと終了の値で、severity は持たない（DM-302）。read-only 宣言が「ファイルを作成しない」であり、所見を書く script を呼ぶ余地が無い   | 削除して新規作成（パスは変えない。参照元が名前で指している）                                               |
| `agents/evaluator.md`                                                                                                                                    | 所見配列を依頼に載せ、最終応答に JSON 1 つを返す形。`index` で所見を指す。新仕様は `finding_id`・複数所見を引く評価・新規指摘・script による書き出しと封緘                                                                                      | 削除して新規作成（パスは変えない。参照元が名前で指している）                                               |
| `skills/review/SKILL.md`                                                                                                                                 | バックエンドへ「ラウンド実行」を委譲し、`approved/findings/failure` を受ける。依頼本文を組み立てて運ぶ。終了判定は `confirmed_fix` が空かどうか。新仕様は ID だけを運び、終端は評価の件数と利用者の決定で決まり、本体は最終決定者として吟味する | 修正（Step 4〜8 を全面書き直し。Step 1・2・3・7 手順 3 の修正フェーズは大半を残す）                        |
| `skills/review/templates/*_review_request_template.md`（7 本。secrets 用を除く）                                                                         | 依頼本文を散文で組み立てる。新仕様の依頼は JSON で種別を持たない（FNC-317）。散文に載っていた指示が消える（下記「移し替え」）                                                                                                                   | 削除（内容は reviewer.md・evaluator.md・`criteria/review_target_types.md` へ移す）                         |
| `skills/review/scripts/build_review_request.py`                                                                                                          | `review_id` の生成と本文の組み立て。新仕様は `publish_request.py` が依頼 JSON を書く。`secrets` パターンの組み立て（スキャンの実行を含む）も担っている                                                                                          | 削除（`secrets` の扱いは決定事項 1）                                                                       |
| `scripts/review/parse_findings.py`                                                                                                                       | 自由記述の応答を所見配列へ変換する。新仕様は JSON を script が直接書くので、解釈する対象が無い                                                                                                                                                  | 削除                                                                                                       |
| `skills/review/scripts/parse_evaluation.py`                                                                                                              | evaluator の応答 JSON の検証。新仕様は `append_result.py` が書く時点で保証する（FNC-203）                                                                                                                                                       | 削除                                                                                                       |
| `skills/review/scripts/combine_findings_and_evaluations.py`                                                                                              | `index` で所見と評価を 1 対 1 に結合する。新仕様の評価は 1 対 1 ではなく、`finding_ids` が既に対応を持つ（DM-201）                                                                                                                              | 削除                                                                                                       |
| `skills/review/scripts/split_by_location.py`                                                                                                             | 結合済み配列を located / unlocated に分ける。新仕様の位置は文字列配列で、`位置未確定` だけを要素とする形になる                                                                                                                                  | 修正（新しい位置の形に合わせて残す。決定事項 3）                                                           |
| `skills/agent-review/SKILL.md`                                                                                                                           | 可用性検査・ラウンド実行・終了通知の 3 つを持つ。ラウンド実行は `parse_findings.py` に依存する。新仕様では本体が reviewer を直接起動する（DES-084 §2 S5）。可用性検査の条件 4 は `REVIEW_RESULT` 宣言を要求しており、新 reviewer と矛盾する     | 修正（ラウンド実行・終了通知を外し、可用性検査を新 reviewer に合わせる。可用性検査だけを残す。決定事項 2） |
| `skills/review/scripts/resolve_review_backend.py`                                                                                                        | 候補名と順序だけを返す。`retains_context` を返さない（REQ-029 FNC-316）。値の宣言が無い名前を拒む `backend_undeclared` が無い                                                                                                                   | 修正（出力と終了コード 20 の理由を加える。既存の契約は変えない）                                           |
| `scripts/doc_structure/resolve_doc_structure.py`                                                                                                         | パスから種別を返す口が無い。`match_path_to_doc_type` は関数としてあるが CLI から呼べない                                                                                                                                                        | 修正（`--match-path` を加える。DES-084 §6.8）                                                              |
| 受け渡しの script 群                                                                                                                                     | `publish_request.py`・`append_result.py`・`seal_result.py`・`resolve_review_path.py`・`count_actionable.py`・`advance_round.py`・`delete_review.py`、reviewer / evaluator / body のラッパー 9 本が存在しない                                    | 新規作成（`plugins/forge/scripts/review/`）                                                                |
| `docs/criteria/review_target_types.md`                                                                                                                   | 存在しない。種別判定の手順と、種別ごとに上乗せする観点文書の対応は、今は 8 本のテンプレートに分散している                                                                                                                                       | 新規作成                                                                                                   |
| `skills/consult/SKILL.md`                                                                                                                                | 提示の状態を agenda に記録する。DES-083 §4.3 は暫定措置として、記録せずコンテキストに状態を持つ形に変える                                                                                                                                       | 修正（暫定。実装完了後に見直す）                                                                           |
| `tests/forge/review/` の旧 script のテスト、`tests/forge/scripts/test_parse_findings.py`、`tests/forge/agent-review/test_agent_review_contract.py`       | 削除する script のテスト、および新 reviewer に反する契約（`REVIEW_RESULT` 宣言・重大度マーカーを要求する検査）を含む                                                                                                                            | 削除する script のテストは削除。契約テストは修正                                                           |
| `tests/forge/agenda/test_agenda_integration.py`                                                                                                          | 結合 script（`combine_findings_and_evaluations.py`）を import して agenda の入力を作る。結合 script を削除すると読み込めず、全体テストが落ちる                                                                                                  | 修正（結合 script を使わず、固定の入力データで同じ検証を行う。agenda の機構は変えない）                    |
| `skills/start-implement/scripts/group_review_batch.py`                                                                                                   | `--scope` の注入検証を `build_review_request.py` の構造行拒否に合わせている（コメントと検証）。新仕様の `scope` は JSON の値なので、見出し行などを拒む理由が無くなる                                                                            | 変更しない（無害。決定事項 4）                                                                             |
| `skills/review/scripts/resolve_targets.py`・`verify_fix_safety.py`・`capture_syntax_baseline.py`・`collect_modified_files.py`・`analyze_branch_point.py` | 修正フェーズの allowlist と安全検証、`--branch` の base 確定。要件・設計はこれらに触れていない                                                                                                                                                  | 変更しない（本体の Step 2.1・2.2・7 手順 3 の呼び出しは残す）                                              |

### 移し替え（テンプレートを削除する前に済ませること）

既存の実装と新仕様の食い違いのうち、気づきにくいのは、テンプレートの散文に載っていた指示が新仕様の文書のどこにも書かれていないことである。削除すると、黙って挙動が変わる。次を `reviewer.md`・`evaluator.md`・`review_target_types.md` のいずれかへ移すか、不要と判断して理由を残す。

- 到達目標（`scope`）の読み方: 指定が無ければ最終形とみなす。宣言された未実装が設計書・仕様書との乖離を生むなら所見にする（REQ-013 FNC-1319）
- 重点観点（`focus`）の読み方: 通常のレビューへの加算であり、他の観点を免除しない。severity を上げる根拠にしない
- 所見の自己検証（REQ-013 FNC-1321）: 質問へ分解して独立に検証し、成立するものだけを書き出す。FNC-310（確定してから書き出す）と整合させる
- code と uxui で、対応する規約が見当たらなければその事実を所見にする（REQ-013 FNC-1320）
- 削除とリネームの確認項目（`diff` テンプレートの 3 項目。REQ-027 FNC-306 は「変更の一部」とだけ定める）
- 現 `reviewer.md` / `evaluator.md` にある ADR の棄却理由の確認（文言は写さず、現行の `review_priorities_spec.md` §3.8 に従って書く。§3.8 は ADR を根拠にした場合に `ADR-NNN §N` の記録を求め、失効マーカーの規定を持たない。現 `reviewer.md` の「ADR ID を明記」はこれより古い）、比例性チェックの適用条件、`advisor` ツールの禁止、重大度カタログの特定手順（severity は evaluator だけが付けるので evaluator 側へ寄る）

**方針**: 新仕様の実体は「ID だけを運び、JSON は script が書き、agent は script が返したパスを直接読む」という別の構造であり、既存の「本文を組み立てて運び、自由記述を解釈する」構造とは両立しない。そのため agent 定義・受け渡し・解釈系の script は、既存を直すのではなく置き換える。直して使うのは、設計が既存の契約を変えないと明示している `resolve_review_backend.py`、`resolve_doc_structure.py`、本体の引数解釈・修正フェーズ・consult である。実装は隔離した作業コピー（本 worktree）で行うので、新旧を共存させる互換層は作らない（additive_development_spec §3.2）。

**依存により残す旧実装**: 確定したものは無い。`secrets` パターン（`build_review_request.py` の `secrets` 経路、`secrets_review_request_template.md`、`scan_secrets.py`、`review_criteria_secrets.md`）だけが、本 feature の外（Issue #62 が別の検査工程に分離する）に依存先を持つ可能性がある。扱いは決定事項 1 に従う。

## 既存テストが課す制約

本文を読んで確認した事実である。計画の各タスクの受け入れ基準に反映した。

| テスト                                                                                                  | 課す制約                                                                                                                                                                    | 影響するタスク               |
| ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| `tests/common/test_plugin_integrity.py`                                                                 | `plugins/forge/` 配下の `.py` の、docstring とコメント以外の文字列に `/forge:xxx` 形式を書かない。SKILL.md の `/plugin:skill` 参照は、存在する skill を指す                 | 001〜003・008〜011・013〜015 |
| `tests/common/test_test_discovery.py`                                                                   | テストを置くディレクトリすべてに `__init__.py` が要る                                                                                                                       | 001〜003・008〜011           |
| `tests/forge/agents/test_agent_frontmatter.py`                                                          | reviewer / evaluator の `tools`（Read, Grep, Glob, Bash）、`model: inherit`、`permissionMode: plan` を固定で検査する                                                        | 005・006・010                |
| `tests/forge/subagent/test_agent_allowedtools_consistency.py`・`test_skill_allowedtools_consistency.py` | SKILL.md の本文に Agent ツール・`/forge:xxx` の呼び出しがあれば、`allowed-tools` に `Agent`・`Skill` が要る                                                                 | 013〜015                     |
| `tests/forge/subagent/test_slash_command_launch_context.py`・`test_subagent_term_usage.py`              | 起動経路の語を伴わない `/forge:xxx` 表記の件数は baseline 43 件以下。`subagent` の単独使用は 0 件                                                                           | 013〜015                     |
| `tests/forge/subagent/test_changed_lines_policy.py`                                                     | `main` との差分の追加行だけを検査する。旧 `/forge:review <種別> <対象>` 構文を追加しない。`/forge:xxx` の行は近傍に起動経路の語かユーザー入力例の語を置く                   | 013〜015                     |
| `tests/forge/doc_structure/test_forge_toc_freshness.py`                                                 | `plugins/forge/docs/`・`skills/*/docs/` を編集したら、内蔵文書の索引（`update-forge-toc`）を更新する                                                                        | 005・015・016                |
| `tests/forge/agent-review/test_agent_review_contract.py`                                                | 旧 reviewer の `REVIEW_RESULT` 宣言・重大度マーカー、旧 agent-review のラウンド実行、`parse_findings.py` を検査する。新仕様と両立しない部分は削除し、残る禁止条文は維持する | 005・010・014・016           |
| `tests/forge/agenda/test_agenda_integration.py`                                                         | 削除する結合 script を import する                                                                                                                                          | 016                          |
| `tests/forge/adr/test_adr_writer_contract.py`                                                           | `write-adr` の SKILL.md に文字列 `/forge:review design` があることを検査する（69 行目）。位置引数を除くと落ちるので、新しい起動形を検査する文面に同じタスクで直す           | 015                          |

## アプローチ

**選択**: スケルトン先行（reviewer の縦 1 本を先に通し、共有部分の形を固めてから evaluator と本体を足す）。

**根拠**:

- 受け渡しの script 群は reviewer と evaluator で `append_result.py`・`seal_result.py`・`resolve_review_path.py` を共有する（`--kind` で分ける）。まず reviewer 側の縦 1 本を通し、共有部分の形を固めてから evaluator 側を足す。逆順にすると、共有部分を 2 回作り直す
- 本体 SKILL の書き直しと旧実装の削除は、新しい agent と script が揃ってから行う。本体は両方に依存し、先に壊すと検証の足場を失う

## フェーズ

### フェーズ 1: 受け渡しの基盤と reviewer の縦 1 本

- **目標**: reviewer をカスタム Agent として実際に起動し、`targets` の 3 形（`paths` / `base_branch` / `diff`）で依頼を読み、所見を script 経由で書き出して封緘するところまで動く。失敗（`target_unreadable`・書き出さずに終了）が `resolve_review_path.py` の失敗として現れる
- **スコープ**:
  - `publish_request.py`・`append_result.py --kind findings`・`seal_result.py --kind findings`・`resolve_review_path.py --kind request|findings`、`reviewer_*` のラッパー 4 本（DES-084 §6）
  - `resolve_doc_structure.py --match-path`（§6.8）、`resolve_review_backend.py` の `retains_context`（§6.7）
  - `criteria/review_target_types.md`（§4.2）と、forge 内蔵文書の索引の更新
  - `agents/reviewer.md` の新規作成（旧版は削除。FNC-301・「移し替え」の項目を含む）
- **検証ポイント**:
  - DES-084 §7 の単体・契約・統合テストが通る
  - `python3 -m unittest discover -s tests -p 'test_*.py'` と `dprint check`

### フェーズ 2: evaluator と本体専用 script

- **目標**: reviewer が書いた所見を evaluator が評価し、全所見が引かれるまで封緘できず、本体専用の script でラウンドを進めて保持物を削除できる
- **スコープ**:
  - `append_result.py` / `seal_result.py` / `resolve_review_path.py` の `evaluations`・`inputs` 対応（DES-083 §5・§6.2〜§6.4）
  - `evaluator_*` ラッパー 3 本、`body_resolve_*` ラッパー 2 本、`count_actionable.py`・`advance_round.py`・`delete_review.py`
  - `agents/evaluator.md` の新規作成（旧版は削除。メタ観点・`reason` の書き方・severity と確信度の付け方・新規指摘）
- **検証ポイント**:
  - DES-083 §7 の単体・契約テストが通る
  - 統合テストの全ケース（束ねる・分ける・新規指摘のみ・新規指摘と所見を束ねる・所見 0 件で新規指摘あり・評価 0 件、および引き残しで `evaluator_finish` が失敗して足せること）が通る
  - 本物の reviewer → evaluator を 1 ラウンド手動で通し、第 2 ラウンドの `finding_id` が連番になることを確かめる
  - 全体のテストと `dprint check` が通る

### フェーズ 3: 本体の書き直しと旧実装の撤去

- **目標**: `/forge:review` が新しい仕組みで終端まで動き、旧実装と旧テストが残っていない。呼び出し元（`start-*`・`impl-issue`）が引数を変えずに動く
- **スコープ**:
  - `skills/review/SKILL.md`（Step 1.5〜8 の書き直し。DES-084 §4.1・DES-083 §4.2）
  - `agent-review/SKILL.md` の縮小（決定事項 2）
  - `consult/SKILL.md` の暫定措置（DES-083 §4.3）
  - 削除: テンプレート 7 本（secrets 用を除く）、`build_review_request.py`（決定事項 1）、`parse_findings.py`、`parse_evaluation.py`、`combine_findings_and_evaluations.py`、`split_by_location.py`（決定事項 3 により削除せず、新しい位置の形に直す）、およびそれらのテスト
  - 配布物の文書で古くなる記述の洗い出しと更新（`help`・`start-*`・`impl-issue` の SKILL、`sensitive_information_spec.md`、`review_priorities_spec.md`、`forge_anti_patterns.md`、`additive_development_spec.md` の `/forge:review` やこれらの script を指す記述。内蔵文書の索引も更新）
- **検証ポイント**:
  - `--diff`・`--files`・`--dirs`・`--branch` の各対象軸と、`--interactive` / `--auto` で、小さな対象に対して `/forge:review` を実際に通す。終端の 3 経路（対応を要するものが尽きる・利用者が終える・agent 失敗で止まる）で `delete_review.py` が走り保持物が消える
  - 削除した script の名前・別名・形式の呼び名を、`plugins/`・`tests/`・`docs/` で検索して残りが無いことを確かめる（検索語と範囲を残す）
  - 全テスト・`dprint check`

## 決定事項

要件定義書・設計書・Issue から導けた判断である。

1. **`--secrets`**。機密情報の確認は、Issue #62（担当者が別ブランチ `feature/62-feature-secret-linter` で実装中）が、レビュー型の検査ごと廃止して `forge:secret-linter` へ置き換える。REQ-027 も本 feature の対象外とする。したがって本 feature は新しい仕組みへ移植しない。`--secrets` はシステムから完全に排除される機能なので、案内の記述（`SKILL.md` の `--secrets` 節、`README.md`・`README_en.md`、`docs/readme/forge/guide_review(_ja).md`）は削除し、廃止の案内も書かない（呼ぶ経路が無くなるため、エラー終了の説明は要らない）。資産（`scan_secrets.py`、`review_criteria_secrets.md`、`secrets_review_request_template.md`、`sensitive_information_spec.md` のマスク規定）は、#62 の置き換えに任せて触れない。#62 と同じファイルを触る箇所は、実装時に `git diff` で洗い出して担当者へ共有する
2. **`agent-review` SKILL**。可用性検査だけを残す。可用性検査は、バックエンドが依頼を送る前に自身で判定して返す（`forge:REQ-013` FNC-1318）。ラウンド実行と終了通知は、本体が reviewer を直接起動する新仕様では要らないので削除する。`resolve_review_backend.py` の候補名と SKILL 名（`forge:<name>`）の 1 対 1 の対応は保つ
3. **`split_by_location.py`**。位置が確定していない所見を黙って破棄しない（`forge:REQ-013`・REQ-029 DM-304）ので、仕分けは新仕様でも要る。新しい位置の形（文字列配列、`位置未確定` だけを要素とする形）に合わせて残す
4. **位置引数の種別（`code|design|...`）**。廃止する。依頼は種別を持たず（FNC-317）、reviewer が対象ごとに判定するので、引数としての意味が無い。受け付けて無視する互換も、廃止を案内するエラー終了も `SKILL.md` に書かない（構文に無い語として、AI が利用者に案内する）。`/forge:review <種別>` を渡している呼び出し元は、同じ変更の中で直す。対象は `plugins/anvil/skills/impl-issue/SKILL.md`、`plugins/forge/skills/{help,start-design,start-implement,start-plan,start-uxui-design,write-adr}/SKILL.md`、`plugins/forge/skills/start-requirements/docs/` の 3 文書、`plugins/forge/skills/start-uxui-design/docs/uxui_analysis_workflow.md`、および `README.md`・`docs/readme/` の利用例である。`/forge:review` の引数解釈は `SKILL.md` に書く。`README_en.md` の利用例も対象に含める。洗い出しの検索語は、`/forge:review` の直後に `--` で始まらない語が続く記述すべてとする（種別名の `code` 等、`{type}`・`<type>`・`<種別>` のプレースホルダ、接頭辞を欠く `review plan --auto` を含む）。種別名だけを検索語にすると、プレースホルダ形と接頭辞なしの形を落とす。位置引数を書いた旧仕様（`REQ-001`・`REQ-013`・`DES-010`・`DES-017`・`DES-018`・`DES-019`・`DES-025`・`DES-055`・`DES-066`）は、実装期間中に書き換えない（additive_development_spec §3）。実装完了後の merge で、新しい仕様に合わせて改訂する（同 §4.3 手順 3）。例外は `docs/specs/adr-writer/design/DES-085_adr_writer_design.md` である。別 feature の差分文書で旧仕様ではなく、`write-adr` の完了処理（250 行目）に起動形を書いているので、`write-adr` の `SKILL.md` と同じ変更の中で直す。`group_review_batch.py` の `--scope` 検証は `build_review_request.py` の構造行拒否に合わせたものだが、無害なので触らない
5. **TBD-001（メタ観点が実際に働くか）**。REQ-026 と DES-083 が実装後の検証とする。フェーズ 3 の統合確認の後の別の作業とし、実装の完了条件に含めない
6. **script 間の共通部品**。JSON の出力・失敗の返し方・一時ファイルを経由した公開・絶対パスの検査は、`plugins/forge/scripts/review/review_common.py` に 1 つだけ置き、review の script が import する（DES-084 §6.1）。利用者が決めた（TASK-001 の完了後。先例の受け渡し script が各ファイルへコピーしている形は、review の script には採らない）。置くのは使い手が確定した部品だけで、後続のタスクが必要としたときに足す。先例の `strategy_exchange.py`・`adr_exchange.py` は別 feature の実装であり、書き換えない

## リスクと対策

| リスク                                                                                                                                 | 影響度 | 対策（どのフェーズで潰すか）                                                                                                                                                                                    |
| -------------------------------------------------------------------------------------------------------------------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| テンプレートの指示が移し替えられずに消え、reviewer の挙動が黙って変わる                                                                | 中     | フェーズ 1 の reviewer.md の新規作成の時点で「移し替え」の一覧を消化する。フェーズ 3 の削除前に再確認する                                                                                                       |
| 実装の途中で `/reload-plugins` を実行すると、読み込まれる `/forge:review` が新旧の混在した状態になり、実装そのもののレビューが行えない | 中     | プラグインは再読み込みするまで更新されないので、実装の途中は再読み込みしない。実装のレビューは、フェーズ 3 の完了後に再読み込みしてから行う。再読み込みが要る場合は、公開済みの版を読み込んだ別セッションを使う |
| 書き出し先 `<project_root>/.temp/review/` が `.gitignore` に無く、作業中の JSON が untracked として混ざる                              | 低     | フェーズ 1 で `.gitignore` の有無を確かめ、無ければ利用者に案内する（`.toc_work` と同じ方針の例外になるので、利用者の判断を得る）                                                                               |
| `agent-review` の契約テストを新 reviewer に合わせ損ね、可用性検査が常に不可になる                                                      | 中     | フェーズ 3 で、`resolve_review_backend.py` → 可用性検査 → ラウンドの通しを実際に動かして確かめる                                                                                                                |
| 呼び出し元（`start-implement` の Phase 5 など）が `/forge:review` の引数・出力に依存している                                           | 中     | フェーズ 3 の削除の前に、`plugins/` 全体で呼び出し元の引数を列挙して突き合わせる。引数は変えない                                                                                                                |
| 削除した script の名前が、読まれていない文書・テスト・索引に残る                                                                       | 低     | フェーズ 3 の検索（名前・別名・形式の呼び名）で潰す                                                                                                                                                             |
