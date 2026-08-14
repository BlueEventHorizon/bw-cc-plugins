# DES-001 文書検索ラッパー（forge → 文書検索 backend）設計書

## メタデータ

| 項目         | 値                                                                                              |
| ------------ | ----------------------------------------------------------------------------------------------- |
| 設計 ID      | DES-001                                                                                         |
| 対象スコープ | forge の文書検索ラッパー 4 SKILL                                                                |
| 関連設計     | COMMON-DES-001_skill_base_design、DES-057（backend 選択・doc-db 経路）、DES-061（設定ファイル） |

---

## 1. 概要

forge は文書検索（ルール・仕様の発見）と索引更新を外部の文書検索 backend に委譲する。
backend は 2 つある: 外部プラグイン doc-advisor
（[BlueEventHorizon/DocAdvisor](https://github.com/BlueEventHorizon/DocAdvisor)、`index-docs` / `query-docs`）と、
ローカルで稼働する文書検索サーバ doc-db である。
forge 自身は検索・索引生成を実装せず、`plugins/forge/skills/` 配下の 4 つのラッパー SKILL が
**順序リストに基づいて backend を選択**し、選択した側の経路を実行する。

選択順序は `.claude/.forge.yaml` の `doc_backend.prefer` から決まり、既定は doc-advisor 先位である。
可用性判定は各 backend が所有し、選択の仕組み・doc-db 経路・順序リスト解決 CLI
（`resolve_backend_order.py`）の設計は **DES-057 が所有する**。設定ファイルの入れ物の規約は DES-061。
本設計が所有するのは、4 SKILL の抽象（key マッピング・出力契約・SKILL 契約）と doc-advisor 経路の転送契約である。

doc-advisor は文書集合を opaque な `key` 単位で管理する。forge は category（rules / specs）を key にマッピングして渡す。

---

## 2. スキル一覧

| Skill 名                 | 役割                                     | key   | doc-advisor 経路の転送先 | user-invocable |
| ------------------------ | ---------------------------------------- | ----- | ------------------------ | -------------- |
| `/forge:query-db-rules`  | ルール文書を検索しパスリストを返す       | rules | `doc-advisor:query-docs` | true           |
| `/forge:query-db-specs`  | 仕様文書を検索しパスリストを返す         | specs | `doc-advisor:query-docs` | true           |
| `/forge:update-db-rules` | ルール文書の検索インデックスを最新化する | rules | `doc-advisor:index-docs` | true           |
| `/forge:update-db-specs` | 仕様文書の検索インデックスを最新化する   | specs | `doc-advisor:index-docs` | true           |

4 SKILL とも `user-invocable: true`。ユーザーが直接 `/forge:query-db-rules` 等を起動する運用も許容しつつ、forge の他 SKILL（review / start-* /
create-feature-from-markdown-plan 等）から `Skill` ツール経由で呼ばれる。

doc-db 経路では、各 SKILL の `scripts/` 配下の SKILL 固有 wrapper を経由して共有低レベル CLI を呼ぶ。
wrapper は category を固定し、当該 SKILL が必要とする操作だけを公開する（wrapper と CLI の設計は DES-057 §3.2）。

---

## 3. query 系（query-db-rules / query-db-specs）

### 引数

| 引数     | 必須 | 説明                             |
| -------- | ---- | -------------------------------- |
| `{task}` | 必須 | 検索クエリ（タスク記述・自然文） |

### 実行フロー

1. `resolve_backend_order.py` で backend の順序リストを解決する（設定不正は既定値へ落ちず明示エラー。DES-057 §2.5）。
2. 順序リストの先位から可用性を判定し、最初に利用可能な backend の経路を実行する。
   - **doc-advisor 経路**: `doc-advisor:query-docs --key {rules|specs} {task}` を 1 回呼び、応答をそのまま親に返す。
   - **doc-db 経路**: query wrapper 経由で低レベル CLI を呼ぶ（DES-057 §4.2）。

   **query は索引を書き換えない**（REQ-014 FNC-002）。索引の維持は update 系（§4）の責務である。
   索引が未整備で検索が成立しない場合のみ、承認を得たうえで、**確定済みの backend を指定して
   update 系 SKILL へ整備を委譲する**（整備の手順を query 側に持たない。DES-057 §5.3）。
3. いずれの backend も利用できなければ、両者の理由を並べて明示エラーとする。grep 等による代替検索は行わない。

### 出力契約

応答の先頭は `Required documents:` 形式のパスリスト（プロジェクトルート相対）。構造変換は行わない。
この出力契約は backend によらず共通である（NFR-002 の互換性は REQ-014 が規定する）。

### SKILL 契約 [MANDATORY]

`/forge:query-db-rules` / `/forge:query-db-specs` は **継承型検索 SKILL**
（COMMON-DES-001 §3.1 デフォルト方針 / §6 規定リスト外、`context: fork` を指定しない）。
doc-advisor 経路の転送先 `doc-advisor:query-docs` も継承型 dispatcher であり、実検索は read-only なカスタム Agent（`doc-advisor:query-worker`）へ隔離される。隔離境界は Agent ツール起動が担うため、forge 側・doc-advisor 側のいずれも `context: fork` を使わない。
`allowed-tools: Skill, Read, Bash, AskUserQuestion`（Bash は wrapper / 順序リスト解決 CLI の実行に使い、
`AskUserQuestion` はセッション内変更の確認と索引整備の承認に使う。`Grep` は許可しない —
grep フォールバックは廃止済みであり、検索の代替にしない）。書き込み・コミット・自己再帰は行わない。

呼び出し側は `args` を **検索キーワード + 短い自然文タスク記述のみ**に限定する。Issue 本文・実装指示・差分等の
親 context を貼り付けてはならない（COMMON-DES-001 §4）。

---

## 4. update 系（update-db-rules / update-db-specs）

### 実行フロー

0. **`--backend` の指定がある場合は選択を行わず、指定された backend で更新する**（利用できなければ他方へ
   切り替えず明示エラー。REQ-014 BL-006 / FNC-003）。指定は query 系が索引整備を委譲するときに渡す。
1. 指定が無い場合、`resolve_backend_order.py` で順序リストを解決し、先位から可用性を判定する（query 系と同じ）。
2. **doc-advisor 経路**: 索引入力準備 wrapper（`prepare_advisor_index.py`。dprint 適用と `.doc_structure.yaml` からの
   `dirs`（`root_dirs`）/ `exclude`（`patterns.exclude`）解決を行う）を実行し、その結果を `Skill` ツールで
   `doc-advisor:index-docs --key {rules|specs} --dirs-json '[...]' --exclude-json '[...]'`（常に dirs モード）として渡す。
   ディレクトリからファイル一覧への展開は doc-advisor 側（`expand_dirs.py`）が行う。
   完了レポート（added / updated / deleted / toc_path）をそのまま親に返す。
3. **doc-db 経路**: sync wrapper で desired-state 同期を投入し、SKILL が状態取得を反復して進捗を毎回報告する
   （DES-057 §4.3）。

`allowed-tools: Read, Bash, Skill`。

> `resolve_doc_structure.py --type` はファイルパス単位の解決が必要な他 consumer（`review` の
> `resolve_review_context.py` 等）で引き続き使われるが、update 系の doc-advisor 経路はディレクトリ単位の
> `dirs`/`exclude` 転送に移行済み（doc-advisor 側でのディレクトリ展開に統一するため）。

### desired-state

いずれの経路でも対象集合の正は `.doc_structure.yaml` である。doc-advisor 経路の `--dirs-json`/`--exclude-json` は
当該 key の、doc-db 経路の対象文書一覧は当該 series の、それぞれ完全な desired state であり、
含まれないパスは索引から削除・切り離しされる。

---

## 5. 前提

- いずれかの文書検索 backend が利用可能であること。可用性はバージョンではなく、必要な機能が利用できるかで判定する（DES-057 §2.4）
  （REQ-014 前提条件）。片方が利用できない場合は残る backend を試し、両方利用できないときに限り失敗する。
- key `rules` / `specs` は doc-advisor の予約語 `all` と衝突しない。
- doc-advisor は `.doc_structure.yaml` を読まない。対象ディレクトリ（`dirs`/`exclude`）は forge が解決して
  `--dirs-json`/`--exclude-json` で渡し、ディレクトリからファイル一覧への展開は doc-advisor 側が行う。

---

## 6. テスト

- `tests/forge/doc_structure/test_resolve_doc_structure.py` — `.doc_structure.yaml` のパス解決を検証する。
- `tests/common/test_query_skill_isolation.py` — 継承型 read-only 検索 SKILL（`query-forge-rules`）の
  Role 制約・引数解釈ガード・`Required documents:` 出力契約を機械検証する。
- `tests/forge/doc_backend/` — backend 選択（順序リスト・settings_invalid）、doc-db 経路の低レベル CLI、
  doc-advisor 契約（`test_advisor_contract.py`）を検証する。
- `tests/forge/{query,update}-db-{rules,specs}/` — SKILL 固有 wrapper の透過性を検証する。
