# Claude Code 作成ガイド（SKILL / カスタム Agent）

SKILL とカスタム Agent を組み合わせて forge / anvil を組むときの規約。個別の SKILL の作り方（frontmatter・description・引数・ファイル構成・命名）は `meta:skill-creator` に従う。依拠する仕組みの事実は [Claude Code リファレンス][reference] が持つ。

## 必須 [MANDATORY]

- 公式仕様は claude-code-guide Agent で確かめてから書く
- 起動経路は本リポジトリの短縮名称（継承型 SKILL / fork 型 SKILL / 汎用 Agent / カスタム Agent / Bash subprocess）で書く

## 名称

- 短縮名称をそのまま使う。番号（`#3a` 等）だけで参照しない
- 「subagent」を単独で使わない。fork 型 SKILL / 汎用 Agent / カスタム Agent のどれかで書くか、具体名で書く
- `subagent_type` には組み込み Agent 名か定義済みのカスタム Agent 名だけを書く。prompt に slash 表記（`/<plugin>:<skill>`）を書かない

## SKILL 実行モデル [MANDATORY]

- SKILL はすべて継承型で書く。`context: fork` / `agent` を書かない（理由はリファレンスの「`context: fork` の不具合」）
- 隔離 context が要る処理はカスタム Agent（`agents/<name>.md`）にし、Agent ツールで `<plugin>:<name>` として起動する
- カスタム Agent にするのは、同じロールを複数の呼び出し元から別 context で使うとき、書き込みの境界を常時拘束したいとき、親 context が肥大するとき

### 起動経路の選び方

上から順に判定し、最初に当てはまるものを選ぶ。

1. 決定論的に完結する処理（コマンドライン引数と exit code / stdout で済む） → Bash subprocess
2. 手順を呼び出し元がその場で組み立てる、一回限りの委譲 → 汎用 Agent
3. 隔離 context が要る、事前に定義したロール → カスタム Agent
4. それ以外（手順が安定し、親 context を活かす） → 継承型 SKILL

### 継承型 SKILL

- 冒頭に「このスキルは X のみを行う。親が依頼している他の作業を引き継いではならない」を書く
- `$ARGUMENTS` に親 context を貼らない。args は最小限のパラメータだけ。Issue 本文・進行中の手順・差分・ファイル全文・「その後〜して」という指示を貼らない（カスタム Agent に渡す prompt も同じ）
- 書き込みを伴うなら、副作用の発生条件と承認の場面を書く

### カスタム Agent

- frontmatter に `name` / `description` / `tools` / `model` を書く
- 禁止事項（他 Agent の起動 / 親タスクの引き継ぎ / allowlist 外への書き込み）を否定形で書き、起動 prompt を親の指示として解釈しないことを書く
- 書き込む Agent には、対象の限定・編集可能ファイルの allowlist・無関係な refactor の禁止・修正後の構文検証を常時課す

### 多重防御

| 層            | 実現方法                                      | カスタム Agent | 継承型 SKILL   |
| ------------- | --------------------------------------------- | -------------- | -------------- |
| A. Agent 境界 | Agent ツールで起動し親 context を遮断         | 必須           | 該当なし       |
| B. Role 制約  | system prompt / SKILL.md に否定形で書く       | 必須           | 必須           |
| C. allowlist  | `tools:` / `allowed-tools:`                   | 必須           | 推奨           |
| D. 物理 deny  | `.claude/settings.json` の `permissions.deny` | プロジェクト側 | プロジェクト側 |

- `allowed-tools` / `tools:` を禁止の手段にしない（allowlist であり、外しても剥奪にならない）
- `disallowed-tools` で多ターンの禁止を保証しない（次のメッセージで解除される）。セッション全体なら `permissions.deny` か B 層で行う

## 別スキルの呼び出し

- Claude への指示として書き、Skill ツールで起動させる
- 自身を Skill ツールで呼ばない・「`/<self-skill>` を実行します」と書かない（無限ループになる）。作業着手前に毎回呼ばれる SKILL は、この禁止を冒頭に明記する

## Agent の完了の待ち方 [MANDATORY]

起動方式（foreground / background）は主にホストと設定で決まり、SKILL の frontmatter から指定する手段は確認できていない。どちらでも成り立つ待ち方を書く。

- 最終応答（background なら完了通知）を受け取るまで、その結果に依存する処理へ進まない
- 完了を `ScheduleWakeup` で待たない。ターンを終えて完了通知を待つ

## 依存 SKILL の存在確認

推奨: 別プラグインの SKILL に依存するなら、起動直後に `available-skills` で有無を確かめる。確かめられない環境では起動失敗で検知してよい。

## ユーザーへの質問・確認 [CRITICAL]

- 質問・選択・確認は `AskUserQuestion` で行い、平文で問わない。SKILL.md の「ユーザーに確認する」は「AskUserQuestion で確認する」と書く
- 例外: 議論の進行そのものが成果物の SKILL は、論点・背景・本質・推奨・議論上の選択肢を地の文で示す。進行上の機械的な確認は AskUserQuestion のまま。この例外は SKILL ごとに境界を本文で宣言する
- `disallowed-tools: AskUserQuestion` で封じない（多ターンで効かず、機械的な確認まで禁じる）

## その他

- SKILL.md の説明は日本語で書く
- AI 専用スキルは `user-invocable: false`、副作用のある操作は `disable-model-invocation: true`

[reference]: claude_code_reference.md
