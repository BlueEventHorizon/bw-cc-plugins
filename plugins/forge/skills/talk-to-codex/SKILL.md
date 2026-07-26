---
name: talk-to-codex
description: |
  msg-sys 通信基盤（常駐 Codex セッションとの Stop フック経由の非同期往復）の上で、
  レビューの findings/完了判定契約を持たない自由な相談・会話を Codex と行う。
  msg-sys 共有部品の push 起床・ブロッキング待機をそのまま使う。
  依頼モードのトリガー句: "Codexに相談したい", "常駐Codexと話したい", "talk-to-codexで聞いて",
  "Codexの意見を聞きたい", "Codexとブレストしたい", "常駐Codexセッションに質問したい"。
  受信モードの起動契機（トリガー句ではなくメッセージ本文の形式で成立）: Stop フックが差し戻した
  メッセージ本文の先頭が `[msg-talk] topic_id=<topic_id>` である。
user-invocable: true
disable-model-invocation: true
argument-hint: "<message>"
allowed-tools: Read, Write, Bash, Monitor, AskUserQuestion
---

このスキルは、常駐 Codex セッションとの msg-sys 経由の自由な相談・会話（依頼の送信・返信の受領と提示）のみを行う。所見の重大度評価・自動修正・`REVIEW_RESULT` 完了宣言行のような契約は一切持たない。親が依頼している他の作業を引き継いではならない。

> **`disable-model-invocation: true` [MANDATORY]**: 本スキルは実際に常駐 Codex セッションへメッセージを送信し起床させる副作用のある操作であり、`docs/rules/skill_authoring_notes.md`「副作用ある操作 → `disable-model-invocation: true`」の対象に該当する。`description` のトリガー句は Claude の自動呼び出し判定には使われない（`disable-model-invocation: true` により description 自体が Claude の context から除外される）。利用者が「Codexに相談したい」等と話しただけで自動的に副作用を発生させないよう、利用者による明示的な `/forge:talk-to-codex` の入力、または利用者からの明確な依頼を受けた親ターンでの `Skill` ツール明示呼び出しのみを起動契機とする。

## コマンド構文

```
/forge:talk-to-codex <message>
```

利用者が `/forge:talk-to-codex <message>` を明示的にタイプして起動する。または、利用者から Codex への相談・会話を明確に依頼された親ターンが `Skill` ツールで明示的に呼び出す（`disable-model-invocation: true` のため、Claude が会話の流れだけから自律的に起動することはない）。`<message>` は自由記述のメッセージ本文で、`$ARGUMENTS` としてそのまま渡される。

## 概要

`/forge:talk-to-codex` は msg-sys（通信路のみを提供）の上に成り立つ、レビュー以外の自由会話オーケストレーションである。msg-sys が提供する共有部品——push 起床（`wake_codex.sh`）・ブロッキング待機（`wait_for_reply.py`）——を使うが、話す内容に構造上の制約を課さない。

**1往復単位の設計**: 本スキルは「メッセージを送る → Codex の返信を1件受け取り提示する」までを1回の呼び出しで完結させる。会話を続けたい場合は、同じ `topic_id` を保持したまま本スキルを再度呼び出す（`--in-reply-to` でスレッドを継続する）。複数ラウンドの自動往復ループは持たない（所見評価・自動修正の対象がそもそも存在しないため、往復を自動で回す意味がない）。

| モード         | 起動契機                                                                   | このセクションへ |
| -------------- | -------------------------------------------------------------------------- | ---------------- |
| **依頼モード** | 利用者による `/forge:talk-to-codex <message>` の明示起動                   | 「依頼モード」   |
| **受信モード** | 差し戻されたメッセージ本文の先頭が `[msg-talk] topic_id=<topic_id>` である | 「受信モード」   |

## 依頼モード

### Step 1: メッセージ内容の確定

`$ARGUMENTS` を Codex へ送るメッセージ本文とする。空の場合は AskUserQuestion で確認する。

**会話の継続判定 [MANDATORY・topic_id 運用規則]**: 直前のターンまでにこの会話で使った `topic_id` と、直近で受信した Codex 発メッセージの `id` を**自身のコンテキストに保持している場合のみ**、それらを「継続」として Step 3・Step 4 で使う。保持していない場合は常に新規会話として扱う（Step 3 で `--topic-id` を省略し新規発行させる）。

**コンテキスト消失時に履歴から topic_id を推測してはならない [MANDATORY]**（Codex とのディスカッションで提起された改善提案への対応）: セッション再開・compaction 等でコンテキストを失った場合、`history.py`/`filter_review_history.py` 相当の手段で過去の `[msg-talk]` ヘッダを検索し、topic_id を推測して継続扱いにしてはならない。複数の会話（topic）が並行して存在しうる以上、推測は誤った topic への合流（無関係な会話の混線）を招く。利用者が「さっきの続き」等と述べても、対象の topic_id が本文・コンテキストのいずれからも一意に確定できない場合は、AskUserQuestion で利用者に該当 topic_id か新規会話かを確認する。確定できる場合（例: 利用者が直近の Codex 発言を引用・言及した）のみ、その根拠を明示したうえで継続として扱ってよい。

### Step 1.5: Codex 側フックの自己修復 [MANDATORY]

Codex は Claude Code のプラグイン hooks 自動登録機構を持たず、`.codex/hooks.json`（Codex CLI 自身がプロジェクトルート直下でのみ読む設定）に登録されたコマンドのパスは常に静的な文字列である。このパスが実在しないまま Codex の Stop フックが発火すると、コマンド自体が実行に失敗し、Codex はそれが解消されるまでブロックし続ける無限ループに陥る。これを避けるため、送信前に毎回実行して symlink・登録内容を自己修復する:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/msg-sys/ensure_codex_hook.py" \
  --project-root "$(git rev-parse --show-toplevel)" \
  --plugin-msg-sys-dir "${CLAUDE_PLUGIN_ROOT}/scripts/msg-sys"
```

`symlink.status` が `"conflict"`（symlink であるべき場所に人間由来の実ファイル・ディレクトリが存在する）・`hooks_json.status` が `"error"`（既存 `.codex/hooks.json` が壊れた JSON 等）の場合は書き換えを行わず、その旨を利用者に報告して手動確認を促す（自動修復を諦めるのみで、送信自体は Step 2 の前提検査結果に従う）。

### Step 2: 前提検査

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/msg-sys/check_setup.py" [--project-root <path>]
```

`status: error` の場合、依頼を送信せず終了する（fail closed）。`checks` の中で `ok: false` の項目を利用者に提示し、対処を具体的に案内する。`warnings`（Codex 常駐・trust 登録は機械検査不能）は送信前の予告として提示するが、これのみでは送信を止めない（fail-open）。

### Step 3: 依頼本文の組み立て

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/build_talk_request.py" --message "<Step 1 のメッセージ>" [--topic-id <継続する場合の既存 topic_id>]
```

標準出力に依頼本文（テキスト）が書かれる。本文は `topic_id`（新規の場合はこのスクリプトが uuid4 で新規生成する不透明トークン）を含むヘッダ行で始まる。この `topic_id` を以後のやり取り（継続呼び出し）で使うためコンテキストに保持する。

### Step 4: 送信

Write ツールで依頼本文を一時ファイルへ書き出し、msg-sys の `send.py` を Bash subprocess として呼ぶ。**シェル経由の本文書き出し（heredoc・`echo`・`printf` 等）は行わない**——本文に含まれる引用符・`$` 変数展開・改行がシェルに解釈され、本文が壊れる・意図しないコマンドが実行される事故を避けるため:

```bash
FORGE_MSG_PROJECT_ROOT="$(git rev-parse --show-toplevel)" \
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/msg-sys/send.py" claude codex - [--in-reply-to <継続の場合は直前に受信した Codex メッセージ id>] < "一時ファイルパス"
```

送信後、一時ファイルを削除する。`send.py` が非ゼロ終了した場合は送信失敗として報告し終了する。

### Step 5: push型起床 [MANDATORY]

**本 Step の実行（`wake_codex.sh` の呼び出し自体）は必須であり、省略してはならない**（結果が `skipped`/`failed` であっても構わないが、呼び出さないことは許されない）。常駐 Codex の Stop hook は Codex 自身のターン終了時にしか発火しない（pull型）。人間が対話しない専用の常駐 Codex セッションでは、送信側からこの呼び出しを行わない限り Codex のターンが自然に終わる契機自体が存在せず、Step 6 の受動ポーリングは無期限に応答を得られない。したがって本 Step は待機を高速化するだけの最適化ではなく、専用常駐運用における配信の唯一の起点である。

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/msg-sys/cmux/wake_codex.sh" "$(git rev-parse --show-toplevel)"
```

`{"status": "sent"|"skipped"|"failed"}` のいずれの結果であっても本スキルの完了判定には影響しない（結果内容は問わないが、呼び出し自体は必須。終了コードは常に0）。cmux 環境でない・対象ペインが見つからない・複数候補で曖昧、のいずれの場合も `skipped` として次へ進む。

### Step 6: 応答のブロッキング待機

`wait_for_reply.py`（msg-sys 共有・プロトコル非依存）を `run_in_background: true` で**1回だけ**起動する。`--db-path` を渡さない場合は Step 4 と同じ `FORGE_MSG_PROJECT_ROOT` の前置が必須である（省略すると `RuntimeError: DB path could not be resolved` で即エラー終了する）。talk-to-codex のスレッド識別には `topic_id` ヘッダの正規表現を `--header-regex` として渡す:

```bash
FORGE_MSG_PROJECT_ROOT="$(git rev-parse --show-toplevel)" \
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/msg-sys/wait_for_reply.py" claude codex \
    --header-regex '^\[msg-talk\]\s+topic_id=(\S+)\s*$' --thread-id <topic_id> \
    --max-seconds 600 --progress-interval 10 [--db-path <path>]
```

`Monitor` ツールでこのジョブを監視し、10秒おきの進捗行と最終結果を受け取る。

**`nohup`・末尾 `&` での二重バックグラウンド化は禁止 [MANDATORY]**: `run_in_background: true` を指定した時点で既にバックグラウンド実行されるため、二重の `nohup`/`&` は不要かつ有害である。これを重ねると実際のポーリングプロセスがハーネスの追跡から外れ（ハーネスが完了を検知できるのは自身が起動したプロセスの終了のみ）、`replied`/`timeout` の完了通知が二度と届かなくなる。

- 最終結果が `{"status": "replied", "messages": [...], "delivered_ids": [...]}` の場合 → Step 7 へ。**`delivered_ids` に含まれる id のメッセージ本文**を Codex の返信として使う（`messages` 全体を `sent_at` だけで走査して選んではならない。同一 poll 内で ack の成否がメッセージごとに異なりうるため、`sent_at` 最大値だけで選ぶと他プロセスが既に配信を受けたメッセージを二重処理する。`delivered_ids` はこの呼び出しが実際に配信権を得た返信のみを表す）
- 最終結果が `{"status": "timeout", "last_observed_request_read_by_agent_b": ...}` の場合 → 確定したタイムアウト失敗として報告してターンを終える（フォールバックしない）。`last_observed_request_read_by_agent_b`（タイムアウト宣言の瞬間の状態ではなく、最後に完了したポーリング時点の観測値）が `false` の場合は「Codex は最後の確認時点では依頼をまだ読んでいませんでした（常駐していない・停止している可能性があります）」を、`true` の場合は「Codex は最後の確認時点では依頼を読んでいましたが応答していませんでした（処理中の可能性があります）」を追記する（`null` の場合は追記しない）

### Step 7: 返信の提示

`delivered_ids` が指すメッセージの本文（ヘッダ行を除いた自由記述部分）を、Codex からの回答としてそのまま利用者に提示する。所見評価・自動修正・完了判定は行わない。返信メッセージの `id` を、会話を継続する場合の `--in-reply-to` として次回呼び出しのためにコンテキストに保持する。

会話を続けたい場合は、利用者に本スキルの再呼び出し（同じ `topic_id` を使う）を促すか、追加のメッセージが既に与えられていれば続けて依頼モードへ進む。

## 受信モード

差し戻されたメッセージ本文の先頭が `[msg-talk] topic_id=<topic_id>` であるターンで実行する。

### Step 1: 内容の提示

受信本文からヘッダ行を除いた自由記述部分を、Codex からの発話としてそのまま利用者に提示する。完了宣言行の照合・所見評価は行わない（そもそもレビューではないため）。

会話を続けたい場合は、依頼モード Step 1〜7 に従って返信する（`--topic-id` に同じ値、`--in-reply-to` に受信メッセージの `id` を使う）。

## エラーフロー一覧

| 異常系                                 | 挙動                                                                                              |
| -------------------------------------- | ------------------------------------------------------------------------------------------------- |
| 前提検査 error                         | 依頼を送信せず、不足項目と対処を報告して終了                                                      |
| `send.py` 非ゼロ終了                   | 送信失敗を報告して終了                                                                            |
| Codex から返信が来ない（待機予算内）   | `wait_for_reply.py` が指数バックオフでポーリングを継続する                                        |
| Codex から返信が来ない（待機予算超過） | フォールバックせず、確定したタイムアウト失敗として報告して終了。利用者に Codex 側の状態確認を促す |

## 対象外（v1 スコープ外）

- 複数ラウンドの自動往復ループ（所見評価・自動修正の対象がそもそも無いため不要）
- 他のレビュー系スキルとの統合（本スキルは msg-sys 通信路と共有部品のみに依存し、レビュー系スキルからは独立して動作する）
- Codex セッションの自動起動・管理（人間が手動起動して常駐させる前提）
- msg-sys 既存実装の変更（`send.py` / `inbox.py` / `wait_for_reply.py` 等を利用者として呼ぶのみ）
