---
type: temporary-feature-requirement
name: FNC-008
description: doc-advisor 検索エンジン昇格（doc-db first）要件定義書
notes:
  - この文書が正。旧仕様（ソースコード・設計書・計画書）と矛盾する場合はこの文書を優先して判断・実装すること。
  - 旧仕様ファイルは本 feature 実装完了まで書き換えない。新規ファイル / 新規ディレクトリとして切り出すこと。
  - 本 feature 実装完了後、この文書は旧仕様書へ merge され削除される予定。
---

# FNC-008: doc-advisor 検索エンジン昇格（doc-db first）要件定義書

## 概要

doc-advisor の `/doc-advisor:query-specs` および `/doc-advisor:query-rules` のデフォルト検索を、現行の doc-advisor Embedding 方式から **doc-db の Hybrid 検索**（Embedding + Lexical + LLM Rerank）に切り替える。ToC キーワード検索は `--toc` フラグ指定時、および doc-db 未インストール時に使用する。

> **方針補足 (v1.4)**: 当初検討した「doc-advisor の Embedding 関連スクリプト（`embed_docs.py` / `search_docs.py` / `embedding_api.py`）および `--index` モードの全面廃止」は、影響範囲が大きい（既存利用者・互換性・`forge:clean-rules` 等の cross-plugin 依存）と判断し撤回する。本 feature のスコープは以下に縮小する:
>
> 1. mode=auto のデフォルト検索を doc-db Hybrid 検索へ切り替える（OP-01 / IDX-01〜02 / SRC-01〜02）
> 2. `--toc` モード（OP-02）は現行動作を維持
> 3. `--index` モード（旧 Embedding 検索）は **そのまま維持** する（OP-03 を「廃止」から「維持」へ変更）
> 4. doc-advisor の Embedding スクリプト群の **API KEY 参照を doc-db と統一**（`OPENAI_API_DOCDB_KEY` 優先、未設定時 `OPENAI_API_KEY` へフォールバック）

## 前提条件

- OpenAI API key が利用可能であること（doc-db の Hybrid 検索および doc-advisor の Embedding 検索に必要）
- API KEY の参照規約は doc-db と統一する: **`OPENAI_API_DOCDB_KEY` を優先参照し、未設定時のみ `OPENAI_API_KEY` をフォールバックとして使用する**（doc-advisor / doc-db 双方の Embedding 利用箇所で同一仕様）

## 要件一覧

### 操作モード

| ID    | 要件                                                                                                                                          |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| OP-01 | フラグなし（auto モード）で呼び出した場合、doc-db がインストール済みであれば Hybrid 検索を実行する。未インストールの場合は ToC 検索を使用する |
| OP-02 | `--toc` フラグで ToC キーワード検索のみを実行できる（現行動作を維持）                                                                         |
| OP-03 | `--index` フラグは **現行動作のまま維持**する（doc-advisor Embedding 検索による semantic 検索）。本 feature では mode=index に手を加えない    |

### API KEY 参照

| ID     | 要件                                                                                                                                                                                                                                                   |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| KEY-01 | doc-advisor の Embedding 関連スクリプト（`embedding_api.py` / `search_docs.py` / `embed_docs.py`）の API KEY 参照仕様を doc-db と同一に統一する: **`OPENAI_API_DOCDB_KEY` を優先参照し、未設定時のみ `OPENAI_API_KEY` をフォールバックとして使用する** |
| KEY-02 | doc-advisor の SKILL.md（`query-specs` / `query-rules` / `create-specs-toc` / `create-rules-toc`）の API KEY 関連エラーメッセージおよび案内文言を `OPENAI_API_DOCDB_KEY`（フォールバック: `OPENAI_API_KEY`）に合わせて更新する                         |

### Index 管理

| ID     | 要件                                                                                                                                                                                  |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| IDX-01 | auto モード実行時、doc-db Index が未構築の場合は `build-index` を自動実行する（完了待機 / 非同期は TBD-001 参照）。build-index が失敗した場合はエラー内容をユーザーに通知して停止する |
| IDX-02 | `build-index` 実行中はユーザーに進行状況を通知する                                                                                                                                    |

### 検索本体

| ID     | 要件                                                                                                                                                                                              |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SRC-01 | auto モードでは doc-db の Hybrid 検索（Embedding + Lexical + LLM Rerank）を使用する（FNC-006 OP-03 の hybrid + rerank モードに相当）                                                              |
| SRC-02 | doc-db 検索が失敗した場合（API エラー等）、ToC へ自動フォールバックせず、エラー内容をユーザーに通知して停止する。Index が古い場合は FNC-006 継承の差分自動再生成に委譲する（SRC-02 のスコープ外） |

### 廃止対象（旧方式）

> **v1.4 改訂**: 当初の「Embedding 関連スクリプト・`--index` モード・関連テスト・`query_index_workflow.md`・`forge:clean-rules` SKILL を一括廃止」案は撤回。本 feature では **新規追加（doc-db 連携）のみを行い、既存資産は維持する**。

| 対象                                       | 取り扱い                                                                                                                                                                                                                                                       | 完了判定条件                                                                                                                                              |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| doc-advisor Embedding スクリプト           | `search_docs.py` / `embed_docs.py` / `embedding_api.py` を **保持**。`--index` モード用・互換維持のため動作させ続ける。API KEY 仕様のみ KEY-01 で更新                                                                                                          | 対象ファイルがリポジトリに存在し、`OPENAI_API_DOCDB_KEY` → `OPENAI_API_KEY` のフォールバック仕様で動作すること                                            |
| `query_index_workflow.md`                  | `--index` モードのワークフロー文書として **保持**。mode=auto の doc-db 検索ワークフローのみ `query-rules/SKILL.md` および `query-specs/SKILL.md` にインライン記述する（独立した `query_db_workflow.md` 等の新ワークフロー文書は作成しない。理由 DES-028 §5.5） | `query_index_workflow.md` が存在し続け、かつ `query-rules/SKILL.md` および `query-specs/SKILL.md` に mode=auto ワークフローがインライン記述されていること |
| `--index` モード                           | `query-specs` / `query-rules` の `--index` オプションは **現行動作のまま維持**                                                                                                                                                                                 | `--index` 指定時に従来通り Embedding 検索が実行されること（OP-03）                                                                                        |
| 対応テスト（`tests/doc_advisor/scripts/`） | Embedding スクリプト保持に伴い、対応テスト（`test_embed_docs.py` / `test_search_docs.py` / `test_embedding_api.py`）も **保持**。KEY-01 の変更に追従するテスト修正は §テスト要件 を参照                                                                        | 対象テストが存在し、KEY-01 の API KEY 仕様に整合する形で grow / 修正されていること                                                                        |
| `forge:clean-rules` SKILL                  | `embedding_api.py` が保持されるため、本 feature による無効化は **行わない**（SKILL.md → SKILL.md.disabled へのリネームは撤回）。install 環境（`~/.claude/plugins/cache/...`）における既存の cross-plugin import バグは本 feature とは独立した issue として扱う | `plugins/forge/skills/clean-rules/SKILL.md` が存続し、`SKILL.md.disabled` を作らないこと                                                                  |

> **注記**: 上記の Embedding 関連ファイル（`embed_docs.py` / `embedding_api.py` / `search_docs.py`）は FNC-005「参照実装」および FNC-006「参照実装」として参照されている。本 feature では維持するため、FNC-005 / FNC-006 の `参照実装` 記述は変更不要。
>
> **`create_checksums.py` も保持**: `/doc-advisor:create-specs-toc` / `create-rules-toc` SKILL（`toc_orchestrator.md` workflow）の incremental mode 用 checksum 生成・promote-pending・clean-work-dir を担う **ToC 系スクリプト**。Embedding Index 系（`embed_docs.py` / `search_docs.py` / `embedding_api.py`）とは独立に従来通り動作する。

### テスト要件

| ID     | 要件                                                                                                                                                                                                                                                                                                     |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TST-01 | KEY-01 の変更（`OPENAI_API_DOCDB_KEY` 優先 / `OPENAI_API_KEY` フォールバック）を、`tests/doc_advisor/scripts/test_embedding_api.py`（または相当箇所）でユニットテスト化する。`OPENAI_API_DOCDB_KEY` のみ設定 / `OPENAI_API_KEY` のみ設定 / 両方設定 / 両方未設定 の 4 ケースで正しいキーが返ることを検証 |
| TST-02 | 既存の `test_embed_docs.py` / `test_search_docs.py` を KEY-01 後の挙動と整合するように更新（環境変数モックの差し替えのみ。スクリプト本体の振る舞いは変えない）                                                                                                                                           |

## 非機能要件

| ID     | 要件                                                             |
| ------ | ---------------------------------------------------------------- |
| NFR-01 | FNC-008 変更後も FNC-002「見落としゼロ」要件を引き続き満たすこと |
| NFR-02 | REQ-006 NFR-004（recall 同等基準）を本変更後も適用対象とする     |

## 未確定事項 [MANDATORY]

| ID      | 内容                                                                                  | 期限       |
| ------- | ------------------------------------------------------------------------------------- | ---------- |
| TBD-001 | `build-index` 自動実行の完了を待機するか、非同期で実行するか                          | 設計開始前 |
| TBD-002 | `build-index` 進行状況の通知形式・タイミング・内容（TBD-001 の同期/非同期決定に依存） | 設計開始前 |

## 関連要件

- 依存先: FNC-005（Index 生成）、FNC-006（Hybrid 検索）
- 参照: REQ-006（doc-db 概要）、FNC-001〜003（doc-advisor 既存要件）

## 変更履歴

| 日付       | 変更者  | 内容                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ---------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-05-12 | k2moons | 初版作成                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| 2026-05-12 | k2moons | v1.1: §削除対象表 `query_index_workflow.md` 行の「内容」「完了判定条件」を改訂。新ワークフロー文書（`query_db_workflow.md` 等）の新規作成を取りやめ、mode=auto フローを `query-rules/SKILL.md` および `query-specs/SKILL.md` にインライン記述する方針へ変更（DES-028 §5.5 / §5.5.1 と整合）。完了判定条件は「旧ファイルが存在せず、両 SKILL.md にインライン記述されていること」に更新                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| 2026-05-13 | k2moons | v1.2: §削除対象表「doc-advisor Embedding スクリプト」行および注記から `create_checksums.py` を除外（旧 v1.0 の誤分類修正）。`create_checksums.py` は `/doc-advisor:create-specs-toc` / `create-rules-toc` SKILL の `toc_orchestrator.md` workflow から呼ばれる **ToC 系スクリプト**（incremental mode 用 checksum 生成・promote-pending・clean-work-dir）であり、廃止対象の Embedding Index 系（`embed_docs.py` / `search_docs.py` / `embedding_api.py`）とは依存関係を持たない。注記末尾に保持理由のサブ Note を追加（DES-028 v1.7 / §3.2 末尾 Note と整合）                                                                                                                                                                                                                                                                                                                 |
| 2026-05-13 | k2moons | v1.3: §削除対象表に `forge:clean-rules` SKILL 行を追加。clean-rules の `detect_forge_overlap.py` が `embedding_api.py` を cross-plugin `sys.path` 操作で import しており、本 feature の `embedding_api.py` 削除により完全に動作不能となるため、`plugins/forge/skills/clean-rules/SKILL.md` を `SKILL.md.disabled` にリネームして plugin の SKILL 登録から外す。再設計（`/forge:query-forge-rules` ベースに移行し Embedding 直叩きを排除する案）は GitHub issue で追跡（DES-028 v1.8 / §3.2 末尾 Note と整合）                                                                                                                                                                                                                                                                                                                                                                 |
| 2026-05-13 | k2moons | v1.4: **方針大改訂**。doc-advisor の Embedding 関連スクリプト（`embed_docs.py` / `search_docs.py` / `embedding_api.py`）および `--index` モード・関連テスト・`query_index_workflow.md`・`forge:clean-rules` SKILL の **全面廃止を撤回**（影響範囲が大きいと判断）。本 feature のスコープを次に縮小: (1) mode=auto を doc-db Hybrid 検索へ切替（既存方針継続）、(2) `--toc` モード現行維持、(3) `--index` モード現行維持（OP-03 を「廃止」から「維持」へ変更）、(4) `forge:clean-rules` SKILL は本 feature では touch しない、(5) **KEY-01 / KEY-02 を新規追加**: doc-advisor の Embedding スクリプト群および関連 SKILL.md の API KEY 参照を doc-db と同一仕様（`OPENAI_API_DOCDB_KEY` 優先、`OPENAI_API_KEY` フォールバック）に統一。§削除対象表を「廃止対象（旧方式）」表へ書き換え、全行を「保持」前提に更新。§テスト要件（TST-01 / TST-02）を新規追加。DES-028 v2.0 と整合 |
