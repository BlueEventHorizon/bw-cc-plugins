---
name: agent-review
description: |
  /forge:review の外部依存を持たないレビューバックエンド。
  read-only カスタム Agent reviewer を 1 ラウンドにつき 1 回起動し、
  approved / findings / failure を本体へ返す。本体からのみ起動される。
user-invocable: false
allowed-tools: Agent, Read, Write, Bash
---

このスキルはレビューの可用性検査、1 ラウンドの実行、応答解釈、終了通知だけを行います。対象解決、依頼本文の構築、所見評価、修正、親が依頼している他の作業を引き継いではなりません。

## 入出力契約

本体から次の要求のいずれかを受け取ります。

| 要求         | 入力                                            | 出力                                                            |
| ------------ | ----------------------------------------------- | --------------------------------------------------------------- |
| 可用性検査   | なし                                            | `available` と不足条件の `missing`                              |
| ラウンド実行 | `review_id`、ラウンド番号、パターン、純粋な本文 | `approved` / `findings` / `failure` と所見、解釈時の `warnings` |
| 終了通知     | `review_id`                                     | 受理結果                                                        |
| 履歴復元     | `review_id`                                     | `unsupported` と非永続である旨。履歴は返さない                  |

`failure` を `approved` または空の `findings` に変換してはなりません。別バックエンドへ切り替えてはなりません。

## 可用性検査

Agent を起動せず、`${CLAUDE_PLUGIN_ROOT}/agents/reviewer.md` を Read して次を個別に確認します。

1. 定義ファイルが存在し、名前が `reviewer` である
2. frontmatter の `tools` が `Read, Grep, Glob, Bash` と一致し、編集専用ツール（`Write` / `Edit` / Notebook 編集）・Agent 起動・Skill 起動を含まない
3. `model: inherit` と `permissionMode: plan` がある
4. Role が read-only の禁止列挙と、許可する git 操作の列挙・変更操作の禁止列挙を規定し、他 Agent 起動を禁じ、共通完了宣言を規定している
5. このスキルの `allowed-tools` に `Agent` があり、現在のホストで Agent ツールを利用できる

**条件 2 で「外部通信ツールを含まない」と断定しません [MANDATORY]**。`Bash` は外部通信も成果物の変更も可能にするため、断定すると検査条文が事実と食い違います。`Bash` を許可するのはレビュアーが差分・ブランチ対象を自分で確定するために必要だからです（これを外すと `--diff` / `--branch` のレビューが成立しません）。

不足ごとに `axis` / `detail` / `remedy` を持つ要素を `missing` へ追加します。全条件を満たす場合だけ `{"available": true, "missing": []}` を返します。検査中に Agent、ファイル、DB、プロセスを作成しません。

## ラウンド実行

1. `review_id` が空でない文字列、ラウンド番号が 1 以上の整数、本文が空でない文字列であることを確認します。不正なら `failure` を返します。パターンは受け取るだけで、判定にも Agent 起動にも使いません（本バックエンドはワイヤヘッダを持たないため用途がありません）。
2. 本文先頭行が厳密なワイヤヘッダ形 `[msg-review] <pattern> review_id=<id> round=<n>` に一致した場合だけ、共通本文への固有ヘッダ混入として `failure` を返します。本文中の説明や引用に単なる `[msg-review]` が含まれるだけなら拒否しません。
3. Agent ツールでカスタム Agent `forge:reviewer` を **1 回だけ foreground 起動**します（`run_in_background: false`）。resume ID、前ラウンドの transcript、前回応答を渡してはなりません。prompt には受け取った本文だけを、レビュー依頼としてそのまま渡します。
4. 起動失敗、timeout、応答欠落は段階と説明を伴う `failure` にします。
5. Agent の最終応答を Write で一時ファイルへ保存し、次を 1 回実行します。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/review/parse_findings.py" \
  --body-file "<Agent 最終応答の一時ファイル>"
```

6. 一時ファイルを削除します。JSON の `judgment` と `findings` をそのまま本体へ返します。`judgment: failure` の場合は `error` を失敗理由として返します。

**`warnings` があればそれも本体へ返します [MANDATORY]**。判定と所見配列だけを返して `warnings` を捨ててはなりません。位置未確定として受理した所見の件数はここにしか現れず、捨てると本体は利用者へ通知できません（本体はその通知を義務づけられています）。同じ共通 parser を使う他のバックエンドは `warnings` を渡すため、捨てるとバックエンドを替えただけで通知が消える非対称になります。

各ラウンドで必ず新しい `forge:reviewer` を起動し、Agent の識別子や応答を保持しません。

## 終了通知

`review_id` を受理して成功として直ちに返す no-op です。Agent の探索・停止、履歴保存、追加通信を行いません。

## 履歴復元

履歴復元には `{"status": "unsupported", "reason": "agent-review は非永続バックエンドのため履歴を復元できません"}` を返します。`messages: []` などの空履歴を返してはなりません。同一 `review_id` の継続を偽装せず、本体が新しいレビューとして再実行できるようにします。
