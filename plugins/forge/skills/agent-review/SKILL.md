---
name: agent-review
description: |
  外部依存を持たないレビューバックエンドの可用性検査。
  カスタム Agent reviewer の定義と、reviewer が呼ぶ script が揃っているかを確かめ、
  available / missing / retains_context を本体へ返す。本体からのみ起動される。
user-invocable: false
allowed-tools: Read
---

このスキルはレビューの可用性検査だけを行います。reviewer の起動、対象解決、依頼の構築、所見の読み取り、評価、修正、親が依頼している他の作業を引き継いではなりません。reviewer を起動し所見を扱うのはレビュー本体です。

## 入出力契約

| 要求       | 入力 | 出力                                                        |
| ---------- | ---- | ----------------------------------------------------------- |
| 可用性検査 | なし | `available`、不足条件の `missing`、`retains_context: false` |

別バックエンドへ切り替えてはなりません。

## 可用性検査

Agent を起動せず、`${CLAUDE_PLUGIN_ROOT}/agents/reviewer.md` を Read して条件 1〜4 を、次の 6 ファイルを Read して条件 5 を、個別に確認します。

1. 定義ファイルが存在し、名前が `reviewer` である
2. frontmatter の `tools` が `Read, Grep, Glob, Bash` と一致し、編集専用ツール（`Write` / `Edit` / Notebook 編集）・Agent 起動・Skill 起動を含まない
3. `model: inherit` と `permissionMode: plan` がある
4. Role が read-only の禁止列挙（対象の作成・編集・削除の禁止、対象を変更し得るコマンドの禁止、修正・commit・push の禁止、他 Agent・Skill 起動の禁止、外部サービスへの書き込みの禁止）と、許可する git 読み取り操作の列挙を規定し、所見の書き出しを script 経由（`reviewer_add_finding` / `reviewer_finish` / `reviewer_abort`）と規定している。応答本文の宣言行や重大度マーカーを完了の条件にしていない
5. reviewer が呼ぶ script と読む文書が、プラグイン内に存在する
   - `${CLAUDE_PLUGIN_ROOT}/scripts/review/reviewer_resolve_request.py`
   - `${CLAUDE_PLUGIN_ROOT}/scripts/review/reviewer_add_finding.py`
   - `${CLAUDE_PLUGIN_ROOT}/scripts/review/reviewer_finish.py`
   - `${CLAUDE_PLUGIN_ROOT}/scripts/review/reviewer_abort.py`
   - `${CLAUDE_PLUGIN_ROOT}/scripts/doc_structure/resolve_doc_structure.py`
   - `${CLAUDE_PLUGIN_ROOT}/docs/criteria/review_target_types.md`

**条件 2 で「外部通信ツールを含まない」と断定しません**。`Bash` は外部通信も成果物の変更も可能にするため、断定すると検査条文が事実と食い違います。`Bash` を許可するのは、reviewer が差分・ブランチ対象を自分で確定し、所見を書き出す script を呼ぶために必要だからです（これを外すと差分・ブランチ対象のレビューも所見の書き出しも成立しません）。

不足ごとに `axis` / `detail` / `remedy` を持つ要素を `missing` へ追加します。全条件を満たす場合だけ `{"available": true, "missing": [], "retains_context": false}` を返します。

**`retains_context` は常に `false` です**。本バックエンドはラウンドごとに新しい reviewer が起動され、前ラウンドを覚えていません。本体はこの申告に従って、毎ラウンド同じ依頼を読む流れで進めます。申告を誤ると、レビューの流れが reviewer の実態と食い違います。

検査中に Agent、ファイル、DB、プロセスを作成しません。
