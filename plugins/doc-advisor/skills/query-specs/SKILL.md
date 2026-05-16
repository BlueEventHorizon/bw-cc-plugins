---
name: query-specs
description: |
  ユーザーの依頼や現在の作業に関連する要件定義書・設計書・計画書を docs/specs/ から見落としなく特定する。
  要件作成・設計・計画・実装・レビュー・仕様変更・既存仕様の確認など、プロジェクト仕様を参照するあらゆる場面で使用（特定フェーズに限定されない）。
  デフォルト (auto) は doc-db Hybrid 検索（Embedding + Lexical + LLM Rerank）で高精度に抽出。
  doc-db 未インストール時は ToC keyword 検索へ自動フォールバック。`--toc` で keyword 検索のみ、`--index` で doc-advisor Embedding 検索に固定可能。
  対象範囲: docs/specs/（ルールは /doc-advisor:query-rules、forge 内部仕様は /forge:query-forge-rules）。
  トリガー: "関連仕様を確認", "specs 検索", "要件/設計/計画を探す", "What specs apply"
context: fork
agent: general-purpose
model: sonnet
user-invocable: true
argument-hint: "[--toc|--index] task description"
---

> **【最重要・無限再帰防止】**
> このファイルは fork されたサブエージェントである **あなた自身への実行指示書** である。
> 親エージェントから渡された `$ARGUMENTS`（タスク説明）に対して、以下の手順を**あなた自身で実行**せよ。
>
> - ❌ 禁止: `Skill` ツールで `query-rules` / `query-specs` / `query-forge-rules` を呼ぶこと（無限再帰でハーネスが詰まる）
> - ❌ 禁止: 「`/query-specs` を実行します」のように、自分が呼び出されたスキルを再起動すること
> - ✅ 必須: 下記 Procedure に従って Read / Bash / AskUserQuestion 等の基本ツールで処理を完了させ、結果を返す

## Role

タスク内容を分析し、関連する仕様文書のパスリストを返す。

## 引数パース

`$ARGUMENTS` を解析する:

- `--toc` で始まる → `mode = toc`、残りを `{task}` とする
- `--index` で始まる → `mode = index`、残りを `{task}` とする
- フラグなし → `mode = auto`、全体を `{task}` とする

---

## mode = toc

`${CLAUDE_PLUGIN_ROOT}/docs/query_toc_workflow.md` を Read し、`category = specs` として手順に従う。

- ToC が存在しない場合: AskUserQuestion で `/doc-advisor:create-specs-toc` の実行を案内する。**Index にフォールバックしない**
- 候補あり → Step: 最終判定 へ

## mode = index

`${CLAUDE_PLUGIN_ROOT}/docs/query_index_workflow.md` を Read し、`category = specs` として手順に従う。

- Index 構築に失敗した場合（OPENAI_API_DOCDB_KEY/OPENAI_API_KEY 未設定等）: AskUserQuestion でエラー内容を通知する。**ToC にフォールバックしない**
- 候補あり → Step: 最終判定 へ

## mode = auto（デフォルト）

### 動作概要

subagent（`context: fork`）自身が doc-db plugin の SKILL を `Skill` ツールで順次呼び出し、Hybrid 検索を fork 内で完結させる **subagent 内完結フロー**（DES-006 §2.4 参照）。doc-db plugin が未インストールの場合、subagent は起動直後の available-skills 参照（Step 1a）でその不在を即時検知し、`Skill` ツールを起動することなく ToC 検索ワークフロー（`query_toc_workflow.md`）に切り替える。

subagent は判定・実行・結果集約をすべて fork 内で行い、**最終的に集約した候補パス + 内容要約のみを親 Claude に return する**。親 Claude は subagent が return した結果を受け取り、ユーザーへ応答する。

shell 安全性: `{task}` はユーザー入力のため、`Skill` ツールで `/doc-db:query` を呼び出す際の `--query` 引数には引用符・シェルメタ文字を含むユーザー入力をそのまま渡せる形（`Skill` ツールが argv を構造化引数として扱うため、shell 展開は発生しない）で記述する。subagent 内で shell 経由のコマンド組み立てを行わないこと。

### Step 1a: doc-db plugin 未インストール検出 (OP-01)

subagent は起動直後にシステムリマインダで提供される **available-skills リスト** を参照し、以下の SKILL 名が含まれているかを確認する:

- `/doc-db:build-index`
- `/doc-db:query`

判定:

| 分類            | 判定根拠                                                                                    | 次の動作                                                                                                                |
| --------------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `not_installed` | available-skills に `/doc-db:build-index` または `/doc-db:query` のいずれかが含まれていない | `${CLAUDE_PLUGIN_ROOT}/docs/query_toc_workflow.md` を Read し、`category = specs` として ToC 検索ワークフローへ切り替え |
| `installed`     | available-skills に両 SKILL 名が含まれている                                                | Step 1b（Index 鮮度確認）へ進む                                                                                         |

> 未インストール検出はここで一元化する。`Skill` ツールの起動失敗（`unresolved`）を待つ事後的な検知ではなく、available-skills の **事前参照** で完結する。

### Step 1b: Index 鮮度確認 (IDX-01)

Step 1a で `installed` を確認できた場合、subagent は `Skill` ツールで以下を起動する:

```
/doc-db:build-index --category specs --check
```

`Skill` ツール起動の結果を以下の **戻り契約** で 2 分類する:

| 分類              | 判定根拠                                                 | 次の動作                                                                                                      |
| ----------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `execution_error` | `exit_code != 0` または stdout/stderr の JSON parse 失敗 | error + hint を集約して親 Claude に return → 親がユーザーに通知して停止（SRC-02、ToC へフォールバックしない） |
| `success`         | `exit_code == 0` かつ stdout JSONL の parse 成功         | 次の stale 判定へ進む                                                                                         |

`success` 分類後の stale 判定（`build_index.py --check` の出力契約）:

- stdout JSONL の各行は `{"status": "fresh"|"stale", "reason": "..."}`。specs カテゴリの場合は `resolve_specs_doc_types()` の返却順に複数行が返る
- **全行が `"fresh"` → Step 3 へ**
- **いずれかが `"stale"` かつ `reason = "index_not_found"` → Step 2 へ**
- **いずれかが `"stale"` かつ `reason ≠ "index_not_found"`（`"checksum_mismatch"` 等）→ Step 3 へ**（`/doc-db:query` 側で差分自動再生成されるため明示ビルド不要）

### Step 2: Index 自動ビルド (IDX-01 / IDX-02)

subagent はユーザー向け通知文 "doc-db の検索 Index が未構築のため、自動的に構築します..." を return メッセージに含める準備をしつつ、`Skill` ツールで以下を起動する:

```
/doc-db:build-index --category specs
```

判定（`build_index.py` の `run_build` 集約 stdout に整合）:

- **SKILL 実行成功、stdout JSON の `status == "ok"` → Step 3 へ**
- **SKILL 実行エラー（`exit_code != 0`）、または stdout JSON の `status == "error"` → error + hint を集約して親 Claude に return → 親がユーザーに通知して停止**（表示形式: "{error}。{hint}"）

進行イベントは `/doc-db:build-index` SKILL が stderr に JSONL 形式で出力する。subagent は fork 内で stderr の JSONL を受信し、要約（進行段階・失敗 chunk 数等）を return メッセージに含めて親 Claude へ伝える。最終判定は stdout の JSON `status` フィールドのみを使用する。

### Step 3: Hybrid 検索 (SRC-01)

subagent は `Skill` ツールで以下を起動する。**query-specs（category = specs）は DES-006 §10.6 の `--doc-type` 絞り込みポリシーに従い `--doc-type requirement,design` を明示する**（互換性維持のため当面の運用。将来仕様変更予定）:

```
/doc-db:query --category specs --query "{依頼内容}" --mode rerank --doc-type requirement,design
```

成否判定（`search_index.py` の出力契約は stdout 最終行に `results` キーを含む JSON 1 行を返す。`status` キーは存在しない）:

- **成功**: **`exit_code == 0` かつ stdout が JSON として parse 可能かつ `results` 配列が存在する** → 結果の path リストを候補として保持し最終判定へ
  - `results` が空配列の場合は「検索結果 0 件」として扱う（後述）
- **失敗**: `exit_code != 0`、または stdout の JSON parse に失敗、または parse 成功しても `results` 配列が存在しない → stderr の `error` / `hint` フィールド（存在する場合）を集約して親 Claude に return → 親がユーザーに error + hint を通知して停止（SRC-02、**ToC にはフォールバックしない**）
- **検索結果 0 件**: `results` 配列が空 → 「該当する文書が見つかりませんでした」を return メッセージとして親 Claude に return → 親がユーザーに通知して停止（**ToC にはフォールバックしない**。fresh Index に対する 0 件は障害ではなく仕様）

注: `/doc-db:query` SKILL は内部で grep 補完を含むため、subagent 側で grep の追加呼び出しは不要（DES-026 / `/doc-db:query` の責務）。

---

## Step: 最終判定

1. Step 1a → Step 3 のいずれかで得た候補パスリストの各ファイルを Read して関連性を確認する
2. 確認済みのパスのみを最終リストに含める
3. **false negative 厳禁。迷ったら含める**
4. **集約結果（候補パス + 内容要約）のみを親 Claude に return する**（subagent 内完結フロー）

## Output Format

```
Required documents:
- specs/requirements/login_screen.md
- specs/requirements/user_authentication.md
- specs/design/login_screen_design.md
```

## Notes

- False negative 厳禁。迷ったら含める

## Error Handling

スクリプトが `{"status": "config_required", ...}` を出力した場合:
AskUserQuestion で `/forge:setup-doc-structure` の実行を案内する
