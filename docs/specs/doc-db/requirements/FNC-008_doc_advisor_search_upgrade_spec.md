# FNC-008: doc-advisor 検索エンジン昇格 要件定義書

## 概要

doc-advisor の `/doc-advisor:query-specs` および `/doc-advisor:query-rules` のデフォルト検索（auto モード）を、現行の doc-advisor Embedding 方式から **doc-db の Hybrid 検索**（Embedding + Lexical + LLM Rerank）に切り替える。ToC キーワード検索は `--toc` フラグ指定時、および doc-db 未インストール時に使用する。

本要件のスコープは以下:

1. mode=auto のデフォルト検索を doc-db Hybrid 検索へ切り替える（OP-01 / IDX-01〜02 / SRC-01〜02）
2. `--toc` モード（OP-02）は現行動作を維持
3. `--index` モード（doc-advisor Embedding 検索）も現行動作を維持（OP-03）
4. doc-advisor の Embedding スクリプト群の **API KEY 参照を doc-db と統一**（`OPENAI_API_DOCDB_KEY` 優先、未設定時 `OPENAI_API_KEY` へフォールバック / KEY-01）

## 前提条件

- OpenAI API key が利用可能であること（doc-db の Hybrid 検索および doc-advisor の Embedding 検索に必要）
- API KEY の参照規約は doc-db と統一する: **`OPENAI_API_DOCDB_KEY` を優先参照し、未設定時のみ `OPENAI_API_KEY` をフォールバックとして使用する**（doc-advisor / doc-db 双方の Embedding 利用箇所で同一仕様）

## 要件一覧

### 操作モード

| ID    | 要件                                                                                                                                          |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| OP-01 | フラグなし（auto モード）で呼び出した場合、doc-db がインストール済みであれば Hybrid 検索を実行する。未インストールの場合は ToC 検索を使用する |
| OP-02 | `--toc` フラグで ToC キーワード検索のみを実行できる（現行動作を維持）                                                                         |
| OP-03 | `--index` フラグは **現行動作のまま維持**する（doc-advisor Embedding 検索による semantic 検索）。mode=index のロジックには手を加えない        |

### API KEY 参照

| ID     | 要件                                                                                                                                                                                                                                                   |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| KEY-01 | doc-advisor の Embedding 関連スクリプト（`embedding_api.py` / `search_docs.py` / `embed_docs.py`）の API KEY 参照仕様を doc-db と同一に統一する: **`OPENAI_API_DOCDB_KEY` を優先参照し、未設定時のみ `OPENAI_API_KEY` をフォールバックとして使用する** |
| KEY-02 | doc-advisor の SKILL.md（`query-specs` / `query-rules` / `create-specs-toc` / `create-rules-toc`）の API KEY 関連エラーメッセージおよび案内文言を `OPENAI_API_DOCDB_KEY`（フォールバック: `OPENAI_API_KEY`）に合わせて更新する                         |

### Index 管理

| ID     | 要件                                                                                                                                                                                                            |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| IDX-01 | auto モード実行時、doc-db Index が未構築の場合は `build-index` を自動実行する（完了待機 / 非同期の選択は DES-028 §1.1 TBD-001 / §5.1 参照）。build-index が失敗した場合はエラー内容をユーザーに通知して停止する |
| IDX-02 | `build-index` 実行中はユーザーに進行状況を通知する                                                                                                                                                              |

### 検索本体

| ID     | 要件                                                                                                                                                                                              |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SRC-01 | auto モードでは doc-db の Hybrid 検索（Embedding + Lexical + LLM Rerank）を使用する（FNC-006 OP-03 の hybrid + rerank モードに相当）                                                              |
| SRC-02 | doc-db 検索が失敗した場合（API エラー等）、ToC へ自動フォールバックせず、エラー内容をユーザーに通知して停止する。Index が古い場合は FNC-006 継承の差分自動再生成に委譲する（SRC-02 のスコープ外） |

### 現行維持対象

本要件では doc-db Hybrid 検索を auto モードに**新規追加**するのみで、既存の Embedding 関連資産は維持する。各対象の取り扱いと完了判定条件を以下に定義する。

| 対象                                       | 取り扱い                                                                                                                                                                                                                                                       | 完了判定条件                                                                                                                                              |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| doc-advisor Embedding スクリプト           | `search_docs.py` / `embed_docs.py` / `embedding_api.py` を **保持**。`--index` モード用・互換維持のため動作させ続ける。API KEY 仕様のみ KEY-01 で更新                                                                                                          | 対象ファイルがリポジトリに存在し、`OPENAI_API_DOCDB_KEY` → `OPENAI_API_KEY` のフォールバック仕様で動作すること                                            |
| `query_index_workflow.md`                  | `--index` モードのワークフロー文書として **保持**。mode=auto の doc-db 検索ワークフローのみ `query-rules/SKILL.md` および `query-specs/SKILL.md` にインライン記述する（独立した `query_db_workflow.md` 等の新ワークフロー文書は作成しない。理由 DES-028 §5.5） | `query_index_workflow.md` が存在し続け、かつ `query-rules/SKILL.md` および `query-specs/SKILL.md` に mode=auto ワークフローがインライン記述されていること |
| `--index` モード                           | `query-specs` / `query-rules` の `--index` オプションは **現行動作のまま維持**                                                                                                                                                                                 | `--index` 指定時に従来通り Embedding 検索が実行されること（OP-03）                                                                                        |
| 対応テスト（`tests/doc_advisor/scripts/`） | Embedding スクリプト保持に伴い、対応テスト（`test_embed_docs.py` / `test_search_docs.py` / `test_embedding_api.py`）も **保持**。KEY-01 の変更に追従するテスト修正は §テスト要件 を参照                                                                        | 対象テストが存在し、KEY-01 の API KEY 仕様に整合していること                                                                                              |
| `forge:clean-rules` SKILL                  | `embedding_api.py` が保持されるため、本要件では touch しない（SKILL.md → SKILL.md.disabled へのリネームは行わない）。install 環境（`~/.claude/plugins/cache/...`）における既存の cross-plugin import バグは本要件とは独立した issue として扱う                 | `plugins/forge/skills/clean-rules/SKILL.md` が存続し、`SKILL.md.disabled` を作らないこと                                                                  |

> **注記**: 上記の Embedding 関連ファイル（`embed_docs.py` / `embedding_api.py` / `search_docs.py`）は FNC-005「参照実装」および FNC-006「参照実装」として参照されている。本要件では維持するため、FNC-005 / FNC-006 の `参照実装` 記述は変更不要。
>
> **`create_checksums.py` も保持**: `/doc-advisor:create-specs-toc` / `create-rules-toc` SKILL（`toc_orchestrator.md` workflow）の incremental mode 用 checksum 生成・promote-pending・clean-work-dir を担う **ToC 系スクリプト**。Embedding Index 系（`embed_docs.py` / `search_docs.py` / `embedding_api.py`）とは独立に従来通り動作する。

### テスト要件

| ID     | 要件                                                                                                                                                                                                                                                                                                     |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TST-01 | KEY-01 の変更（`OPENAI_API_DOCDB_KEY` 優先 / `OPENAI_API_KEY` フォールバック）を、`tests/doc_advisor/scripts/test_embedding_api.py`（または相当箇所）でユニットテスト化する。`OPENAI_API_DOCDB_KEY` のみ設定 / `OPENAI_API_KEY` のみ設定 / 両方設定 / 両方未設定 の 4 ケースで正しいキーが返ることを検証 |
| TST-02 | 既存の `test_embed_docs.py` / `test_search_docs.py` を KEY-01 後の挙動と整合するように更新（環境変数モックの差し替えのみ。スクリプト本体の振る舞いは変えない）                                                                                                                                           |

## 非機能要件

| ID     | 要件                                                           |
| ------ | -------------------------------------------------------------- |
| NFR-01 | 本要件適用後も FNC-002「見落としゼロ」要件を引き続き満たすこと |
| NFR-02 | REQ-006 NFR-004（recall 同等基準）を本要件適用後も継続適用する |

## 関連要件

- 依存先: FNC-005（Index 生成）、FNC-006（Hybrid 検索）
- 参照: REQ-006（doc-db 概要）、FNC-001〜003（doc-advisor 既存要件）、DES-028（本要件の設計）
