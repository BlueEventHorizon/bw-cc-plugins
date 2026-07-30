# DES-001 文書検索ラッパー（forge → doc-advisor）設計書

## メタデータ

| 項目         | 値                               |
| ------------ | -------------------------------- |
| 設計 ID      | DES-001                          |
| 対象スコープ | forge の文書検索ラッパー 4 SKILL |
| 関連設計     | COMMON-DES-001_skill_base_design |

---

## 1. 概要

forge は文書検索（ルール・仕様の発見）を外部プラグイン doc-advisor
（[BlueEventHorizon/DocAdvisor](https://github.com/BlueEventHorizon/DocAdvisor)、`index-docs` / `query-docs`）に委譲する。
forge 自身は検索・索引生成を実装せず、`plugins/forge/skills/` 配下の 4 つの薄いラッパー SKILL から
doc-advisor の SKILL を `Skill` ツールで起動する。

doc-advisor は文書集合を opaque な `key` 単位で管理する。forge は category（rules / specs）を key にマッピングして渡す。

---

## 2. スキル一覧

| Skill 名                 | 役割                                            | key   | 転送先                   | user-invocable |
| ------------------------ | ----------------------------------------------- | ----- | ------------------------ | -------------- |
| `/forge:query-db-rules`  | ルール文書を検索しパスリストを返す              | rules | `doc-advisor:query-docs` | true           |
| `/forge:query-db-specs`  | 仕様文書を検索しパスリストを返す                | specs | `doc-advisor:query-docs` | true           |
| `/forge:update-db-rules` | ルール文書の検索インデックス（ToC）を再構築する | rules | `doc-advisor:index-docs` | true           |
| `/forge:update-db-specs` | 仕様文書の検索インデックス（ToC）を再構築する   | specs | `doc-advisor:index-docs` | true           |

4 SKILL とも `user-invocable: true`。ユーザーが直接 `/forge:query-db-rules` 等を起動する運用も許容しつつ、forge の他 SKILL（review / start-* /
create-feature-from-markdown-plan 等）から `Skill` ツール経由で呼ばれる。

---

## 3. query 系（query-db-rules / query-db-specs）

### 引数

| 引数     | 必須 | 説明                             |
| -------- | ---- | -------------------------------- |
| `{task}` | 必須 | 検索クエリ（タスク記述・自然文） |

### 実行フロー

`Skill` ツールで `doc-advisor:query-docs --key {rules|specs} {task}` を 1 回呼び、応答をそのまま親に返す。
`doc-advisor` が available-skills に存在しなければその旨を報告して終了する。ToC 未生成（`TOC_NOT_FOUND`）なら
`/forge:update-db-{rules|specs}` で索引生成を案内する。

### 出力契約

応答の先頭は `Required documents:` 形式のパスリスト（プロジェクトルート相対）。構造変換は行わない。

### SKILL 契約 [MANDATORY]

`/forge:query-db-rules` / `/forge:query-db-specs` は **継承型 read-only 検索 SKILL**
（COMMON-DES-001 §3.1 デフォルト方針 / §6 規定リスト外、`context: fork` を指定しない）。
転送先の `doc-advisor:query-docs` も継承型 dispatcher であり、実検索は read-only なカスタム Agent（`doc-advisor:query-worker`）へ隔離される。隔離境界は Agent ツール起動が担うため、forge 側・doc-advisor 側のいずれも `context: fork` を使わない。
`allowed-tools: Skill`。書き込み・コミット・自己再帰は行わない。

呼び出し側は `args` を **検索キーワード + 短い自然文タスク記述のみ**に限定する。Issue 本文・実装指示・差分等の
親 context を貼り付けてはならない（COMMON-DES-001 §4）。

---

## 4. update 系（update-db-rules / update-db-specs）

### 実行フロー

1. `plugins/forge/skills/doc-structure/SKILL.md` の「検索対象ディレクトリの解決」手順に従い、`.doc_structure.yaml`
   から category `{rules|specs}` の `dirs`（`root_dirs`）と `exclude`（`patterns.exclude`）を取得する
   （`resolve_doc_structure.py` は経由しない。ディレクトリ単位での解決に留め、個別ファイルパスへの展開は行わない）。
2. `dirs`/`exclude` を `Skill` ツールで `doc-advisor:index-docs --key {rules|specs} --dirs-json '[...]' --exclude-json '[...]'`
   （常に dirs モード）として渡す。ディレクトリからファイル一覧への展開は doc-advisor 側（`expand_dirs.py`）が行う。
3. doc-advisor の完了レポート（added / updated / deleted / toc_path）をそのまま親に返す。

`allowed-tools: Read, Bash, Skill`。

> `resolve_doc_structure.py --type` はファイルパス単位の解決が必要な他 consumer（`review` の
> `resolve_review_context.py` 等）で引き続き使われるが、update 系はディレクトリ単位の `dirs`/`exclude` 転送に
> 移行済み（doc-advisor 側でのディレクトリ展開に統一するため）。

### desired-state

`--dirs-json`/`--exclude-json` は当該 key の完全な desired state。展開後に含まれないパスは ToC から削除される。
対象集合の正は `.doc_structure.yaml`。

---

## 5. 前提

- 外部 doc-advisor（`index-docs` / `query-docs`）がインストールされていること。未インストール時は各 SKILL が報告して終了する。
- key `rules` / `specs` は doc-advisor の予約語 `all` と衝突しない。
- doc-advisor は `.doc_structure.yaml` を読まない。対象ディレクトリ（`dirs`/`exclude`）は forge が解決して
  `--dirs-json`/`--exclude-json` で渡し、ディレクトリからファイル一覧への展開は doc-advisor 側が行う。

---

## 6. テスト

- `tests/forge/doc_structure/test_resolve_doc_structure.py` — `.doc_structure.yaml` のパス解決を検証する。
- `tests/common/test_query_skill_isolation.py` — 継承型 read-only 検索 SKILL（`query-forge-rules`）の
  Role 制約・引数解釈ガード・`Required documents:` 出力契約を機械検証する。
