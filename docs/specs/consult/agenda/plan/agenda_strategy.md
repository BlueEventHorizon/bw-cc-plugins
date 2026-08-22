# agenda 機構 実装戦略

`/forge:start-plan` の実装戦略フェーズ（[DES-027](../../../forge/design/DES-027_plan_strategy_phase_adr.md)）に基づく、agenda 機構への移行戦略。実装完了後に削除する ephemeral 文書であり、恒久文書ではない。

## メタデータ

| 項目     | 値                                                                                                                                                                    |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| feature  | consult/agenda                                                                                                                                                        |
| 関連設計 | [DES-075](../design/DES-075_agenda_mechanism_design.md), [DES-077](../design/DES-077_agenda_display_design.md), [ADR-076](../design/ADR-076_agenda_storage_format.md) |

## アプローチ選択

**フィーチャースライス**（新機構を先に単体で成立させ、その後に既存呼び出し元を1つずつ縦断的に繋ぎ替える）を採用する。

理由: `agenda_store.py` / `agenda_render.py` は `consult` の既存実装から独立して動作を確認できる（CLI 単体で init→update→render の一連が完結する）。先に新機構だけを動作確認してから呼び出し元（`consult` SKILL.md）を繋ぎ替える方が、繋ぎ替え作業中に新機構自体のバグを疑う必要がなくなり、切り分けが容易になる。

## フェーズ順序の判断 [IMPORTANT]

`discussion_file_template.md` のリライトは、独立フェーズではなく**フェーズ1の末尾タスク**として実装群に統合する。

根拠: `agenda_render.py` はテンプレートファイルを実行時に読み込まない設計であり（DES-075 §3.1 の依存は標準ライブラリ `html` のみ）、コード上の依存関係を持たない。一方、DES-077 §3.1a・§3.2 は「重大度の具体的な配色は本設計書で確定せず、実装後に生成された `agenda.html` を見ながら利用者と調整する」と明記しており、テンプレートリライトは実際に動く `agenda_render.py` が生成した実物の `agenda.html` を見て書くのが最も正確である。設計書の記述だけを転記して先に書くと、実装後の調整で書き直す二度手間になる。したがってテンプレートリライトはフェーズ1の実装（T2・T3）完成後に着手する。

## フェーズ分割

| フェーズ | 内容                                                                                                                                                | 対応する設計書の節                        |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| 1        | `agenda_schema.py` → `agenda_render.py` → `agenda_store.py` の実装（CLI 単体で動作確認可能な状態にする）＋ `discussion_file_template.md` のリライト | DES-075 §3, §4, §5, §6, §8 / DES-077 全節 |
| 2        | `consult` SKILL.md の書き換え（下記「置き換え対応表」）                                                                                             | consult:REQ-017 §1.2 準拠                 |
| 3        | 既存記録の破棄（FNC-010）                                                                                                                           | agenda:REQ-019 FNC-010                    |

### フェーズ1: タスク分解の材料

DES-075 §3.1 の依存列から導かれる実装順序は **schema → render → store** である。`agenda_schema.py` と `agenda_render.py` の間にコード依存は無く、並列実行候補になる。

| タスク候補 | ファイル / 対象                                                                                             | 内容                                                                                                                                                                                                                                                                                                                              | 依存           |
| ---------- | ----------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| T1         | `plugins/forge/scripts/agenda/__init__.py`（新規）、`plugins/forge/scripts/agenda/agenda_schema.py`（新規） | DES-075 §5.1 の `TransitionRule`（`required_fields_for` / `validate` → `TransitionResult(ok, missing_fields)`）と `verification.action` の固定語彙を実装する。`plan_contract.py` と同型（関数＋契約でよい。UML クラスをそのまま class 化する必要はない）                                                                          | なし（並列可） |
| T2         | `plugins/forge/scripts/agenda/agenda_render.py`（新規）                                                     | 手作りの fixture（`agenda.json` 相当）から `agenda.html` / `agenda_state.js` を生成する。`html.escape()` パターンは `plugins/anvil/skills/prepare-figma/scripts/json_to_html.py` に倣う。DES-077 §3〜§4.3 の各要素（アジェンダ表、ガタードット、severity バッジ、`<script src>` 差し替え、スクロール保持）を実装する              | なし（並列可） |
| T3         | `plugins/forge/scripts/agenda/agenda_store.py`（新規）                                                      | `init` / `update`（差分パッチ。§6.1） / `next` / `pending` / `record-structural-judgment` / `set-current` の CLI（`argparse`）＋ CRUD・`content_version` インクリメント規則（§3.2）・書き込み成功後の `agenda_render.py` 自動呼び出し（§8.1）を実装する。CLI 設計は `plugins/forge/scripts/review/parse_findings.py` を参考にする | T1, T2         |
| T4         | 統合テスト（`tests/forge/agenda/` 配下）                                                                    | DES-075 §9 の統合テスト（`init → record-structural-judgment → update×N → next/pending`）。各書き込み直後に表示が再生成され、内容が最新の `agenda.json` と一致することも検証する（テストタスクそのもの）                                                                                                                           | T3             |
| T5         | `plugins/forge/skills/consult/assets/discussion_file_template.md`（既存・改修）                             | 保存フォーマットとしての記述を破棄し、T2・T3 完成後に実際に生成した `agenda.html` の構造を材料に、表示専用のリファレンス文書へリライトする。「書くときの約束」節（ID 不変・状態行を消さない等）は §5.1 の `TransitionRule` が機械的に強制するため、散文としての記述は縮小・削除する                                               | T2, T3         |

T1・T2 はそれぞれ単体で（互いを待たずに）テスト可能であり、フェーズ1着手直後に検証点を持てる。T3 は両者の統合点であり、フェーズ1の中核検証（DES-075 §9 の一連の CLI 呼び出し）はここで初めて成立する。

**物理的な HTML テンプレートファイル（`templates/agenda_display_template.html` 等）は新設しない。** 参考実装 `json_to_html.py` は Python の f-string によるインライン HTML 構築であり、外部テンプレートファイルを読み込む構成を取っていない。`agenda_render.py` も同じパターン（インライン構築 + `html.escape()`）を採る。テンプレート構造の文書としての記述は T5 の `discussion_file_template.md` が担う（コードが読み込む実体ではなく、人間が読む構造リファレンス）。

### 新規ファイル一覧

```
plugins/forge/scripts/agenda/
├── __init__.py            # パッケージマーカー（plan/__init__.py と同型）
├── agenda_schema.py        # T1: TransitionRule・verification.action 語彙
├── agenda_render.py        # T2: agenda.html / agenda_state.js 生成
└── agenda_store.py         # T3: CRUD・CLI・自動 render 呼び出し
```

### フェーズ2: consult SKILL.md の置き換え対応表

現行の Phase 2（討議ファイルの用意）・Phase 4（進行における討議ファイル更新）・Phase 5（終了時のファイル参照）を、`agenda_store.py` / `agenda_render.py` の CLI 呼び出しに置換する。

| 現行（Markdown 自前実装）                                         | 変更後（agenda 機構）                                                                                                                                                                                |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.claude/.temp/consult/<日付>-<主題>.md` を Write で新規作成      | `agenda_store.py init` を呼ぶ。直後に Bash で `open {path}/agenda.html` を実行する（初回表示。DES-077 §2.2）                                                                                         |
| 討議ファイルへの Edit（決着・状態更新）                           | `agenda_store.py update --item-file <item.json>` を呼ぶ（差分パッチ。§6.1）                                                                                                                          |
| 討議ファイルを Read して既存ファイル・再開候補を確認（Phase 2.1） | `agenda_store.py pending` / `next` を呼ぶ                                                                                                                                                            |
| 対話中の項目をコンソールへ明示                                    | `agenda_store.py set-current --item-id <id>` を呼ぶ（`content_version` は増えない。DES-077 §4.2）                                                                                                    |
| コンソールへのアジェンダ表再掲（Phase 4 手順 6）                  | `agenda_render.py` を明示的に呼ばない（`update` 完了時に自動生成済み。[DES-075](../design/DES-075_agenda_mechanism_design.md) §8.1）。2 回目以降は `open` を呼ばない（DES-077 §2.2「重複タブ」注記） |
| Phase 0〜1・Phase 3（アジェンダ提示）・Phase 5 の未判断件数明示   | 変更なし（agenda 機構が置き換えるのは記録の保存・表示だけであり、対話進行の手順・作法は consult 側の責務のまま。consult:REQ-017 §1.2）                                                               |

T6（フェーズ2 のタスク）は `plugins/forge/skills/consult/SKILL.md` の Phase 2・Phase 4・Phase 5 の該当箇所をこの対応表に沿って書き換える 1 タスクとする。depends_on: T3（`agenda_store.py` が動作すること）, T5（テンプレートリライト後の表示構造と SKILL.md の説明文を整合させるため）。SKILL.md はテキスト規約であり自動テスト困難なため、テストタスクは `implementation_guidelines.md` の例外に従い省略する。受け入れ基準は Yes/No で判定できる形にする（例:「Phase 2/4/5 の本文に `.claude/.temp/consult/` への Write/Edit の記述が残っていない」）。

### フェーズ3: 既存記録の破棄（FNC-010）

T7（1 タスク）: `.claude/.temp/review/triage.md`（存在する場合）・`.claude/.temp/consult/*.md`（存在する場合）を対象に、削除前に未決着項目の有無を一覧して利用者へ提示し、確認を得てから削除する。depends_on: T6（consult がこれらのファイルを新規作成しなくなった後に実施する一度限りの移行作業のため）。

コード実装ではなく一度限りの移行作業（レガシーデータの後始末）であり、独立したテストタスクは設けない。受け入れ基準は Yes/No で判定できる形にする（例:「実行後、`.claude/.temp/review/` `.claude/.temp/consult/` に対象ファイルが残存しない、または元から対象が存在しなかった旨が明示される」）。

## 検証ポイント

| フェーズ | 完了時の検証事項                                                                                                                                                                                                                                                           |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1        | T1・T2 が単体テストで個別に合格する（T3 完了を待たずに検証可能）。`agenda_store.py init → record-structural-judgment → update → next/pending` が意図通り動作する（T4）。リライトした `discussion_file_template.md` が、生成された `agenda.html` の構造を過不足なく説明する |
| 2        | 既存 `consult` の Phase 0〜5 の対話フローが、置き換え後も同じ利用者体験を提供する。SKILL.md 本文に `.claude/.temp/consult/` への直接 Write/Edit の記述が残っていない                                                                                                       |
| 3        | 既存記録の破棄後、`.claude/.temp/review/` `.claude/.temp/consult/` に放置ファイルが残っていない。破棄前に未決着項目の一覧提示が行われている                                                                                                                                |

## リスクと対策

| リスク                                                                                       | 対策                                                                                                                                                       |
| -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| フェーズ3の既存記録破棄で、未決着の議題を利用者に気づかせずに失う                            | フェーズ3実行前に、破棄対象ファイルの内容（未決着項目の有無）を一覧して利用者に確認を取ってから破棄する（FNC-010 が要求する事前把握）                      |
| フェーズ2の書き換え中、consult の対話フロー自体を壊す                                        | フェーズ1で新機構を単体動作確認（T1〜T4）してから着手することで、フェーズ2で問題が起きた場合に「新機構のバグか、置き換え作業のミスか」を切り分けやすくする |
| T5（テンプレートリライト）を T2・T3 完成前に着手すると、実装後に調整する値を先取りしてしまう | T5 の depends_on を T2・T3 とし、実際に生成された `agenda.html` を見てから書く順序を固定する                                                               |

## 既存資産の活用

| コンポーネント                          | ファイルパス                                                      | 用途                                                                           |
| --------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| 単一責務モジュール構成                  | `plugins/forge/scripts/plan/plan_contract.py`                     | `agenda_schema.py`（T1）のモジュール構成の参考。クラスではなく関数＋契約でよい |
| 状態機械 + CLI パターン                 | `plugins/forge/scripts/review/parse_findings.py`                  | `agenda_store.py`（T3）の CLI 設計・JSON 出力設計の参考                        |
| HTML エスケープ・インライン構築パターン | `plugins/anvil/skills/prepare-figma/scripts/json_to_html.py`      | `agenda_render.py`（T2）の `html.escape()` 使用・f-string インライン構築の参考 |
| 討議ファイルテンプレート                | `plugins/forge/skills/consult/assets/discussion_file_template.md` | T5 でリライトして転用（保存フォーマット→表示構造リファレンス）                 |

再利用しない判断: `update_triage.py` 相当の永続化スクリプトは本リポジトリに実在しない（review 側の仕分けは会話内で完結していたため）。置き換え対象は `consult` の自前 Markdown 実装のみである。
