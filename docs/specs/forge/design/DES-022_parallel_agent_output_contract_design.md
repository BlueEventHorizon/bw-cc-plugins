# DES-022 並列 agent 出力契約パターン 設計書

## メタデータ

| 項目   | 値         |
| ------ | ---------- |
| 設計ID | DES-022    |
| 作成日 | 2026-03-22 |

---

> 対象プラグイン: forge | 適用範囲: 全オーケストレーター

---

## 1. 概要

Claude Code の Agent ツールで複数の Agent を並列起動する場合、共有リソース（YAML/JSON ファイル等）への同時書き込みが競合する問題がある。Agent ツールは OS プロセスレベルの排他制御を提供しないため、並列 Agent が同一ファイルに Write すると後勝ちで上書きされ、先の Agent の結果が消失する。

本設計書は、この問題を**発生させない**出力契約を定義する。競合を検出・調停するのではなく、agent に共有リソースを書かせないことで race condition の成立条件そのものを無くす。

---

## 2. 問題

### 2.1 並列書き込み競合

```
orchestrator
  ├─ Agent A ──Write──→ 共有ファイル  ← 書き込み①
  └─ Agent B ──Write──→ 共有ファイル  ← 書き込み②（①を上書き）
```

Agent A と Agent B が同時に同一ファイルを更新すると、最後に Write した agent の内容のみが残る。Read-Modify-Write の間に他の agent が割り込む典型的な race condition である。

### 2.2 Claude Code 環境での制約

- Agent ツールは独立したサブプロセスとして実行される
- ファイルロック機構は提供されない
- agent 間のメッセージパッシングは Agent ツールの戻り値のみ

---

## 3. 出力契約 [MANDATORY]

### 3.0 適用範囲

本契約が規定するのは**並列 agent の結果を orchestrator へ受け渡す経路**である。

書き込み系 agent（start-implement の実装 executor 等）が**担当範囲の成果物を編集すること自体は本契約の対象ではない**。その安全性は編集可能ファイルの allowlist・対象を絞った起動・指摘と無関係なリファクタリングの禁止・構文検証が担う（COMMON-DES-001 §6.2）。並列起動する場合も、allowlist が担当範囲を分離していれば複数 agent が同一リソースを触らないため、§2.1 の競合は成立しない。

### 3.1 基本原則

**agent は結果の受け渡しに共有リソースを使わない。結果は Agent ツールの return value として orchestrator へ返す。**

1. 各 agent は**結果そのものを return value で返す**（markdown / 構造化テキスト）
2. orchestrator は return value を **main context に保持**し、必要なら統合する
3. **収集系 agent**（調査・検索・レビュー等）は成果物を書かない。収集結果に基づく成果物（文書・設定ファイル等）への書き込みは **orchestrator が main context で行う**

```
orchestrator
  ├─ Agent A → return value  ← ファイルを介さない（競合の余地がない）
  └─ Agent B → return value
  │
  ▼ 全 agent 完了後
  orchestrator が return value を統合し、必要なら成果物を1回だけ書く
```

### 3.2 結果受け渡しのための中間ファイルを作らない [MANDATORY]

agent の結果を orchestrator へ渡すための**中間ファイル・セッションディレクトリを作らない**。

理由:

- 受け渡し経路をファイルにすると、命名規則・収集・後片付け・部分失敗時のマージ戦略という付随的な仕組みが一式必要になる。return value ならいずれも不要である
- 中間ファイルは処理が途中で終わったときに残骸として残る。作らなければ残骸も生じない

### 3.3 agent の責務

| 責務                       | 説明                                                 |
| -------------------------- | ---------------------------------------------------- |
| 結果を return value で返す | 結果の受け渡しに共有リソースも中間ファイルも使わない |
| 自己完結した結果を返す     | orchestrator が後処理できる構造で返す                |
| 読み取りは自由             | Read は競合しないため制限なし                        |

### 3.4 orchestrator の責務

| 責務                  | 説明                                                                             |
| --------------------- | -------------------------------------------------------------------------------- |
| 全 agent の完了を待機 | `run_in_background` で起動した場合、全通知を受け取るまで待つ                     |
| return value の統合   | main context で行う                                                              |
| 成果物への書き込み    | 収集系 agent の結果に基づく書き込みは orchestrator のみが行う（§3.0）            |
| 部分失敗の扱い        | 一部 agent が結果を返さなかった場合の方針を決める（収集系は fail-open。DES-013） |

---

## 4. 適用例

### 4.1 コンテキスト収集（start-requirements / start-design / start-plan / start-implement）

```
orchestrator
  ├─ specs agent → return value（仕様書リスト）
  ├─ rules agent → return value（ルールリスト）
  └─ code agent  → return value（既存コードリスト）
  │
  ▼ 全 agent 完了後
  orchestrator が return value を統合し、必要なファイルを Read して後続工程へ進む
```

タスクの内容・返却形式は DES-013 が定める。

---

## 5. アンチパターン

### 5.1 共有ファイルへの直接書き込み [MANDATORY]

```
# NG: 並列 agent が同一ファイルに書き込む
Agent A → 共有ファイル
Agent B → 共有ファイル  ← Agent A の結果が消失
```

### 5.2 agent 内での Read-Modify-Write

```
# NG: agent が共有リソースを Read → 加工 → Write
Agent A: Read 共有ファイル → 加工 → Write
Agent B: Read 共有ファイル → 加工 → Write  ← Agent A の変更が消失
```

Read は安全だが、Read した内容に基づく Write は race condition を引き起こす。

### 5.3 ファイルロックによる排他制御

Claude Code の Agent 環境ではファイルロック（`flock` 等）の信頼性が保証されない。ロックに依存するのではなく、結果の受け渡しを return value へ集約する本契約を使用する。

### 5.4 結果受け渡しのための中間ファイル

§3.2 のとおり作らない。「個別ファイルへ書かせて orchestrator が収集する」方式は、書き込み先を分離することで競合は避けられるが、§3.2 の付随的な仕組みを丸ごと抱えることになる。return value で足りる場面でこれを選ばない。

---

## 6. 新しい並列 agent を設計する際のチェックリスト

| # | 確認項目                                                                             |
| - | ------------------------------------------------------------------------------------ |
| 1 | agent は結果を return value で返すか（ファイルを介していないか）                     |
| 2 | 収集系 agent が共有リソース・成果物へ Write していないか（書き込み系 agent は §3.0） |
| 3 | orchestrator は全 agent の完了を待機してから統合するか                               |
| 4 | 一部の agent が結果を返さなかった場合の方針は定義されているか                        |
| 5 | 結果の受け渡しに中間ファイル・セッションディレクトリを使っていないか                 |
