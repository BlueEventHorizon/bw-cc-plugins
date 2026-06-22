# COMMON-DES-001 SKILL 基本設計書

## メタデータ

| 項目       | 値                                                 |
| ---------- | -------------------------------------------------- |
| 設計 ID    | COMMON-DES-001                                     |
| 関連要件   | -                                                  |
| 関連 ADR   | doc-advisor:ADR-002_query_skill_subagent_isolation |
| 関連ルール | `docs/rules/skill_authoring_notes.md`              |
| 作成日     | 2026-05-18                                         |
| 適用範囲   | bw-cc-plugins 配下の全プラグイン（forge / anvil）  |

## 1. 概要

bw-cc-plugins における SKILL の基本設計を定義する。SKILL は Claude Code が解釈する単位の実行指示書であり、フォーマット規約（HOW）は `docs/rules/skill_authoring_notes.md` で管理する。本設計書は、その**設計判断の根拠（WHY）と全体像**を記録する。

### 1.1 設計目的

| 目的          | 内容                                                                                                                                                                                                          |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 効率性        | **親 context を継承する継承型がデフォルト**。親 context を活用できる場面では追加プロンプト不要で動作し、context 効率・実装コストの両面で有利                                                                  |
| fork 型不採用 | bw-cc-plugins では `context: fork` を持つ fork 型 SKILL を **採用しない** (§6 参照)。隔離 context が必要な場合は Agent ツール (汎用 Agent / カスタム Agent) を使う。根拠は REQ-005 §11.1 公式バグ群 9 件      |
| 安全性        | 隔離 context が必要な事例 (doc-advisor:ADR-002_query_skill_subagent_isolation 等) では **カスタム Agent** (`plugins/<plugin>/agents/<name>.md`) を採用し、多重防御 (Role 制約 / allowlist / 物理 deny) を適用 |
| テスト容易性  | §6 の不採用方針は `tests/common/test_no_fork_skill.py` で「`context: fork` を持つ SKILL が存在しないこと」として静的検証する                                                                                  |

## 2. SKILL 実行モデル

bw-cc-plugins では SKILL は **継承型のみ** を採用する (§6)。fork 型 (`context: fork`) は Claude Code の構造的不具合 (REQ-005 §11.1) により採用しない。隔離 context が必要な場合は Agent ツール (汎用 Agent / カスタム Agent) を使う。

| 型             | frontmatter        | 実行モデル                                                                                 | 親 context の継承                          | 採否                                         |
| -------------- | ------------------ | ------------------------------------------------------------------------------------------ | ------------------------------------------ | -------------------------------------------- |
| 継承型 SKILL   | `context:` 未指定  | 親 Claude が SKILL.md を読み、そのまま実行                                                 | 継承（会話履歴・進行中タスクをすべて保持） | **採用**                                     |
| fork 型 SKILL  | `context: fork`    | 別 context が起動し、終了時に return のみ親へ戻す                                          | 継承しない                                 | **採用しない (廃止)** §6 / REQ-005 §11       |
| カスタム Agent | (Agent ツール経由) | `plugins/<plugin>/agents/<name>.md` の system prompt + タスク prompt で独立 context を起動 | 継承しない (確実に遮断)                    | **採用** (隔離 context が必要な場合の置換先) |

詳細は `docs/rules/skill_authoring_notes.md` の「SKILL 実行モデルと多重防御」セクションを参照。

## 3. SKILL 型の決定原則

### 3.1 SKILL はすべて継承型 [MANDATORY]

**bw-cc-plugins 配下のすべての SKILL は継承型で作成する**。fork 型 (`context: fork`) は §6 の決定により採用しない。

継承型の積極的なメリット:

- **親 context の活用**: 親が既に持っている差分・進行中タスク・既読ファイル等を追加プロンプトなしで利用できる
- **context 効率**: 親 context にある同一情報を args で再供給する二重コストが発生しない
- **二重 fork の回避**: SKILL の直後に親が更に fork するワークフロー（例: `forge:start-*` 内の検索フェーズ）は構造的に発生しない

### 3.2 隔離 context が必要な場合は Agent を使う [MANDATORY]

以下のいずれかに該当する場合、SKILL ではなく **Agent ツール** (汎用 Agent または カスタム Agent) を使う:

| 判断基準                                                               | 採用する Agent タイプ                                                                                                   |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| 親 context 漏洩による具体的な実害が記録されている                      | カスタム Agent (`plugins/<plugin>/agents/<name>.md`)。例: doc-advisor:ADR-002, forge:reviewer/evaluator/fixer (DES-029) |
| プロジェクト内専門ロールとして固定し、複数経路から同じロールで呼びたい | カスタム Agent                                                                                                          |
| 一回性が高く呼び出し元 prompt 全体で手順を構成する短ジョブ             | 汎用 Agent (`general-purpose` / `Explore` / `Plan`)                                                                     |

> fork 型 SKILL を採用しない根拠: Claude Code の `context: fork` 機構には 9 件の構造的不具合が公式に報告されている (Issue #18394: fork が 95%+ 効かない / #34164: `$ARGUMENTS` 不達 / #60720: 出力消失 / #55592: 無限再帰 ほか)。詳細は REQ-005 §11.1。

### 3.3 個別決定の記録 [MANDATORY]

- SKILL は継承型固定。隔離が必要なら Agent を選ぶ
- カスタム Agent の追加・削除は本書 §6 (旧 fork SKILL 一覧の改廃履歴) または個別設計書 (例: DES-029) で記録する
- 「`query-*` プレフィックスだから別 context」のような命名ベースの自動判断は禁止。命名は `skill_authoring_notes.md` の推奨パターンにすぎない

## 4. SKILL 呼び出し args の原則 [MANDATORY]

§3 / §6 で SKILL 型が決まったら、そのスキルに渡す引数を別途吟味する。**いずれの型でも、`args` に「親タスクのプロンプト」を渡してはならない**。

### 4.1 渡してよいもの / 渡してはならないもの

| カテゴリ                       | 例                                                                                | 可否    |
| ------------------------------ | --------------------------------------------------------------------------------- | ------- |
| SKILL 固有のフラグ・パラメータ | `--full` / `--top-n 10` / `--category rules` / 検索キーワード `"Repository 実装"` | ✅ 渡す |
| 短い自然文のタスク記述         | `"ログイン画面の状態遷移を実装したい"`                                            | ✅ 渡す |
| 親タスクの Issue 本文          | Issue 番号 + タイトル + 本文の貼り付け                                            | ❌ 禁止 |
| 進行中タスクの要約・実装手順   | 「SKILL.md の version を更新し CHANGELOG に追記し…」のような手順貼り付け          | ❌ 禁止 |
| 親が編集中の差分・ファイル内容 | diff / ファイル全文の貼り付け                                                     | ❌ 禁止 |
| 「やってほしい作業」の指示文   | 検索キーワード + 「その後 ◯◯ してください」のような指示連結                       | ❌ 禁止 |

### 4.2 型別の理由

- **継承型 SKILL**: 親 context を既に保持しているため、再供給は無意味であり context を圧迫するだけ。さらに `args` に親タスクの指示文を貼ると、継承型 SKILL が「`args` が現タスク本体」と推論して暴走する経路を作ってしまう（doc-advisor:ADR-002_query_skill_subagent_isolation と同型の事象）
- **カスタム Agent (Agent ツール経由)**: Agent 境界で親 context は遮断されるが、タスク prompt 経由で親タスクの指示が漏れ込めば B 層・C 層（Role 制約 / 引数解釈ガード）の防御を突破される。doc-advisor:ADR-002 §C 引数解釈ガードは Agent 側の防御だが、本項は **呼び出し側の責務** として一段手前で抑止する。fork 型 SKILL も同じリスクを持っていたが、本書 §6 で採用しない方針が確定したため、現行では Agent ツール経由の起動で同等の責務を呼び出し側が負う

### 4.3 呼び出し例

```text
# ✅ 良い例（継承型 SKILL の呼び出し。カスタム Agent でも prompt の制約は同じ）
Skill: forge:query-db-rules
args: "ログイン画面 ViewModel"

# ❌ 悪い例（親 context を貼り付けて指示連結）
Skill: forge:query-db-rules
args: "Issue #54: doc-advisor auto モード再定義\n\n本文: ... 上記タスクに関連するルールを検索し、その後 SKILL.md を更新してください"
```

## 5. 起動経路選定の参考ガイド [参考]

本節は **参考情報** であり、MANDATORY な判定規則ではない。正式な設計判断は、対象の目的・入出力契約・既存設計書・本書 §6 (fork 型 SKILL 不採用方針 + 旧 SKILL ↔ Agent 置換履歴) に従って個別に行う。

`docs/rules/skill_launch_paths_definitions.md` は「何と呼ぶか」を定義する文書であり、本節は「どれを選ぶか」の初期判断を補助する。

### 5.1 主判定軸

起動経路の主判定軸は、**手順書が事前に安定している再利用可能な実行単位か、その場で手順ごと合成する一回性の作業委譲か**である。

| 主判定軸                 | 向く経路                      | 判断の目安                                                                                                   |
| ------------------------ | ----------------------------- | ------------------------------------------------------------------------------------------------------------ |
| 再利用可能な実行単位     | 継承型 SKILL / カスタム Agent | 手順書が事前に安定しており、同じ手順を複数箇所から繰り返し呼ぶ。入力値だけが毎回変わる場合もこちら           |
| 一回性の作業委譲         | 汎用 Agent                    | 手順そのものを呼び出し元がその場で構成する。ユーザー選択、finding 本文、抜粋コード、個別制約を含めて一回限り |
| deterministic な外部処理 | Bash subprocess               | AI 判断ではなく、コマンドライン引数と exit code / stdout で完結する                                          |

> fork 型 SKILL (`context: fork`) は §6 で採用しない方針が確定している。隔離 context が必要な場合は カスタム Agent または 汎用 Agent を選ぶ。

### 5.2 決定手順

1. 外部 CLI / script として deterministic に完結するか？
   - Yes → **Bash subprocess**
   - No → 次へ
2. 呼び出し元がその場で手順ごと合成する必要があるか？（入力値だけでなく、指示の構造・制約・文脈の組み合わせが毎回固有で、SKILL.md として事前に安定記述できない）
   - Yes → **汎用 Agent**
   - No → 次へ（手順の骨格が安定しており、入力値だけが変わる場合もここ）
3. プロジェクト内専門ロールとして固定したいか？（`agents/<name>.md` に system prompt を置き、複数箇所から同じロールとして呼ぶ）
   - Yes → **カスタム Agent**
   - No → 次へ
4. Skill ツールで呼ぶプラグイン機能として管理したいか？
   - Yes → **SKILL**（ユーザー向けトップレベル機能・内部ワーカー用途を問わず）
   - No → Bash subprocess / 通常ドキュメント化 / 設計の再分解を検討する
5. SKILL として扱う場合、ユーザーまたは親 workflow がトップレベル機能として呼び、親 context の活用が設計上の利点になるか？
   - Yes → **継承型 SKILL**
   - No、内部ワーカー用途である → 次へ
6. 内部ワーカー用途の SKILL として扱う場合、以下のどれに該当するか？
   - 隔離 context が必要 → SKILL ではなく **カスタム Agent** を採用 (`plugins/<plugin>/agents/<name>.md`)。fork 型 SKILL は §6 で不採用
   - 継承型 SKILL として内部から呼ぶ明確な理由がある → **継承型 SKILL**。ただし通常経路ではなく例外扱いとし、§7.1 の条件をすべて満たすこと
   - 上記のどちらにも該当しない → SKILL として実装せず、ステップ 1 から再判断する（汎用 Agent / Bash subprocess / 通常ドキュメント化 / 設計の再分解を含む）

### 5.3 隔離 context が必要な場合は カスタム Agent を選ぶ

旧設計では「fork 型 SKILL とカスタム Agent の分岐」を判断軸としていたが、本書改訂 (§6) で fork 型 SKILL は採用しなくなった。隔離 context + 事前定義ロールが必要な場合は **カスタム Agent** (`plugins/<plugin>/agents/<name>.md`) を採用する。

| 選ぶ経路       | 選ぶ条件                                                                                                                                                          |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| カスタム Agent | プロジェクト内の専門ロールとして固定したい。`agents/<name>.md` に system prompt を置き、呼び出し元がタスク prompt を渡す。複数経路から同じロールで呼ばれる worker |
| 汎用 Agent     | 一回性が高く呼び出し元 prompt 全体で手順を構成する短ジョブ。ロール固定が不要で、入力ごとに手順が変動する場合                                                      |

`subagent_type` には `general-purpose` / `Explore` / `Plan` / `<plugin>:<name>` のいずれかを指定する。Skill 名や slash 表記を指定してはならない。SKILL として実行するなら Skill ツール、Agent として実行するなら Agent ツールを使う。

## 6. fork 型 SKILL は採用しない（廃止）

**bw-cc-plugins 配下で `context: fork` を指定する SKILL は存在しない。新規にも作成しない**。

### 6.1 不採用の根拠

Claude Code の `context: fork` 機構には以下の構造的不具合が公式に報告されており、`/forge:review` 経路でも「何もせずに終了する」現象が複数回再現していた:

| 公式 Issue                                                       | 内容                                                                                             |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| [#18394](https://github.com/anthropics/claude-code/issues/18394) | `context: fork` が 95%+ の確率で効かず、既存 context でそのまま実行される                        |
| [#34164](https://github.com/anthropics/claude-code/issues/34164) | fork 型 SKILL を別 SKILL から起動すると `$ARGUMENTS` 置換が効かず、リテラルが渡る                |
| [#60720](https://github.com/anthropics/claude-code/issues/60720) | fork 型 SKILL の出力が UI に届かず無音終了                                                       |
| [#55592](https://github.com/anthropics/claude-code/issues/55592) | fork 型 SKILL が無限再帰し、102+ fork / 5 分で手動停止                                           |
| [#34328](https://github.com/anthropics/claude-code/issues/34328) | fork 型 SKILL を起動しても subagent が立たない (回帰)                                            |
| [#19751](https://github.com/anthropics/claude-code/issues/19751) | fork 型 SKILL 内で AskUserQuestion が機能しない                                                  |
| [#17283](https://github.com/anthropics/claude-code/issues/17283) | Skill ツール経由起動で `context: fork` / `agent:` が honor されない                              |
| [#17351](https://github.com/anthropics/claude-code/issues/17351) | nested skill が呼び出し元 skill context に戻らず main context に戻る                             |
| [#68233](https://github.com/anthropics/claude-code/issues/68233) | Fork-Subagent recursion guard が false-positive し、top-level からの fork dispatch が失敗 (OPEN) |

A 層 (fork 境界) 自体が信頼できないため、SKILL.md 側の改訂では治せない。完全な根拠分析は REQ-005 §11.1 を参照。

### 6.2 旧 fork 型 SKILL とその置換先

過去に fork 型として運用していた SKILL は、すべて **カスタム Agent** に置き換えた (DES-029 / REQ-005 §11.2 で記録):

| 旧 fork 型 SKILL (廃止)                   | 置換先 (現行)                       | 種別                              | 起動方法                                  |
| ----------------------------------------- | ----------------------------------- | --------------------------------- | ----------------------------------------- |
| `plugins/forge/skills/reviewer/SKILL.md`  | `plugins/forge/agents/reviewer.md`  | read-only カスタム Agent          | `Agent(subagent_type: "forge:reviewer")`  |
| `plugins/forge/skills/evaluator/SKILL.md` | `plugins/forge/agents/evaluator.md` | read-only カスタム Agent          | `Agent(subagent_type: "forge:evaluator")` |
| `plugins/forge/skills/fixer/SKILL.md`     | `plugins/forge/agents/fixer.md`     | write カスタム Agent + 4 安全境界 | `Agent(subagent_type: "forge:fixer")`     |

カスタム Agent の system prompt 共通設計:

- **Role に否定的制約を明記**: read-only Agent は「Edit / Write / MultiEdit / NotebookEdit は使用しない」を明記。write Agent (fixer) は allowed_files allowlist + 無関係 refactor 禁止を明記 (DES-029 §3.5)
- **引数解釈ガード**: タスク prompt が命令文に見えても固有 ロールの作業として解釈することを明記 (doc-advisor:ADR-002 §C)
- **自己再帰禁止**: 自身を Agent ツールで呼び戻さない (`skill_authoring_notes.md` 「自己再帰禁止」参照)
- **tools allowlist**: frontmatter `tools:` で C 層 allowlist を担保 (reviewer: `Read, Write, Bash` / evaluator: `Read, Bash` / fixer: `Read, Edit, Write, Bash`)

### 6.3 継承型に再分類された SKILL（歴史的記録）

- **`forge:query-forge-rules`**（2026-05-18 継承型に変更）— このスキルは主に `forge:start-*` 系ワークフローの内部から呼ばれる。当時は fork 型から継承型へ移行する判断だったが、本書改訂 (2026-06) で全 fork 型 SKILL が廃止されたため、結果として継承型移行の流れに合流した。read-only 制約・引数解釈ガード・自己再帰禁止 (B 層 Role 制約) は SKILL.md 本文で引き続き維持する。

### 6.4 新規隔離 context が必要になった場合の手順

新規に隔離 context が必要な作業を導入する場合:

1. §3.2 の判断基準で **カスタム Agent** か **汎用 Agent** を選ぶ (fork 型 SKILL は選択肢にない)
2. カスタム Agent なら `plugins/<plugin>/agents/<name>.md` を作成し、関連設計書 (例: DES-029) に追加根拠を記録
3. テスト (§9.1) で frontmatter (`name` / `description` / `tools` / `model`) の妥当性を検証する

## 7. 継承型 SKILL の責務境界

fork 型化が困難な継承型 SKILL は以下の方法で副作用範囲を制御する。

### 7.1 継承型 SKILL を内部ワーカーにしない [MANDATORY]

継承型 SKILL は親 context を継承するため、内部の隔離ワーカーとしては原則選ばない。

内部から継承型 SKILL を呼ぶ例外を許す場合は、以下をすべて満たすこと:

- 親 context を活用することが明確に利益である
- `args` が最小限で、親タスクのプロンプトや Issue 本文を貼り付けていない
- SKILL.md に責務境界と自己再帰禁止が明記されている
- 汎用 Agent / カスタム Agent / Bash subprocess では不適切な具体的理由が説明できる（例: 汎用 Agent では親 context の差分・既読情報が得られず情報不足になる、カスタム Agent では専用ロール定義の保守コストが過大になる、Bash では AI 判断が必要で deterministic に完結しない、等）

上記を満たす場合でも、**採用理由を SKILL.md の Role セクション冒頭に記録する**（例: 「このスキルを継承型として内部から呼ぶのは〇〇のため。Agent 経由では△△が不適切」）。§6 の不採用方針に準じて根拠を残すことで、後続の設計判断で再利用できる。

内部の隔離実行が目的なら、継承型 SKILL ではなく汎用 Agent / カスタム Agent / Bash subprocess を検討する。

### 7.2 責務境界の明記 [MANDATORY]

SKILL.md 冒頭に「このスキルは X のみを行う。親が依頼している他の作業を引き継いではならない」の旨を 1 行入れる。例:

```markdown
## Role

このスキルは `${ARGUMENTS}` で指定されたファイルへのコミットメッセージ生成と `git commit` のみを行う。親セッションの実装作業・PR 作成・Issue 更新は引き継がない。
```

### 7.3 args は §4 に従う [MANDATORY]

継承型 SKILL の `args` は §4 の原則に従う。継承型は親 context を既に保持しているため、親タスクの要約・Issue 本文・差分・ファイル全文を `args` に再供給する必要はない。再供給すると context を圧迫し、`args` を現タスク本体と誤認する経路を作る。

### 7.4 書き込み権限を持つ場合

副作用の発生条件・ユーザー承認の場面を SKILL.md に明示する。例: 「`git push` 前に必ず `AskUserQuestion` で確認する」。

## 8. 多重防御の層

doc-advisor:ADR-002_query_skill_subagent_isolation で採択した多重防御を SKILL / Agent 型ごとに適用する。fork 型 SKILL の廃止 (§6) により A 層 (fork 境界) は **カスタム Agent の Agent 境界** で代替する。

| 層            | 役割                       | 実現方法                                      | カスタム Agent       | 継承型 SKILL |
| ------------- | -------------------------- | --------------------------------------------- | -------------------- | ------------ |
| A. Agent 境界 | 親 context 漏洩の遮断      | Agent ツール (`subagent_type: ...`) で起動    | 必須                 | 不可         |
| B. Role 制約  | AI 行動規範で逸脱抑止      | system prompt / SKILL.md 内に否定形で明記     | 必須                 | 必須（§7.2） |
| C. allowlist  | 承認なしで使えるツール指定 | frontmatter `tools:` / `allowed-tools:`       | 必須 (frontmatter)   | 推奨         |
| D. 物理 deny  | 書き込み系ツールの強制禁止 | `.claude/settings.json` の `permissions.deny` | プロジェクト側で対応 | 同左         |

> 旧 A 層 (`context: fork`) は廃止。Claude Code の fork 機構が構造的に信頼できない (§6.1) ため、隔離 context が必要な場合は Agent ツール起動の Agent 境界に置き換える。Agent 境界は doc-advisor:query-worker 等での運用実績がある。

### 8.1 D 層の現状

`.claude/settings.json` の `permissions.deny` は SKILL / Agent 単位ではなくセッション単位で適用される。Agent / SKILL ごとに deny を切り替える公式仕様は本設計書作成時点で未提供。doc-advisor:ADR-002_query_skill_subagent_isolation §残存判断 1 に従い、プラットフォーム側で粒度の細かい deny が提供されれば B 層（Role 制約）の比重を下げて C/D 層に移行する。

## 9. テストとガバナンス

### 9.1 静的検証

SKILL / Agent の静的検証を以下のテストで実装している:

- `tests/common/test_no_fork_skill.py`: すべての SKILL.md frontmatter に `context: fork` が **含まれない** ことを検証 (§6 不採用方針の担保)
- `tests/forge/agents/test_agent_frontmatter.py`: `plugins/forge/agents/{reviewer,evaluator,fixer}.md` の frontmatter (`name` / `description` / `tools` / `model`) が DES-029 §3.1 と整合することを検証
- `tests/forge/agents/test_fixer_safety_prompt.py`: fixer Agent の system prompt に §3.5 の 4 安全境界 (単一 finding / allowlist / 無関係 refactor 禁止 / 構文検証) が記述されていることを検証

新規にカスタム Agent を追加した場合は同等の静的検証 (frontmatter + Role 制約) を追加する。fork 型 SKILL を新規追加する経路は閉じている (§6)。

### 9.2 一覧の保守 [MANDATORY]

本設計書 §6 は **bw-cc-plugins における fork 型 SKILL 不採用方針の唯一の正式記録**である。カスタム Agent (forge:reviewer / evaluator / fixer 等) の追加・削除時は §6.4 の手順で関連設計書 (例: DES-029) を更新し、本書 §6.2 の旧 fork SKILL ↔ 置換先カスタム Agent 対応表に履歴を残す。

自動生成（SKILL.md frontmatter のスキャン等）は監査用途には使えるが、**規定の根拠は本書 §6** とする。frontmatter で `context: fork` が検出された場合は、§6 の不採用方針を正として SKILL.md を修正する (該当 SKILL を継承型化するか、カスタム Agent に置き換える)。

## 10. 関連文書

| 種別      | パス                                                                | 関係                                                                                       |
| --------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| ADR       | doc-advisor:ADR-002_query_skill_subagent_isolation                  | 本設計書の多重防御方針の原典                                                               |
| ルール    | `docs/rules/skill_authoring_notes.md`                               | SKILL.md frontmatter / 構造の具体的記法                                                    |
| 公式 docs | [Claude Code Skills](https://code.claude.com/docs/en/skills)        | `context` / `agent` / `allowed-tools` の仕様                                               |
| 公式 docs | [Claude Code Subagents](https://code.claude.com/docs/en/sub-agents) | 汎用 Agent の組み込みタイプ（Explore / Plan / general-purpose）およびカスタム Agent の定義 |

## 変更履歴

| 日付       | 変更者  | 内容                                                                                                                                                                                                                                                                                                                                                        |
| ---------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-05-18 | k2moons | 初版作成                                                                                                                                                                                                                                                                                                                                                    |
| 2026-05-18 | k2moons | §3 を「ルールベースの判別基準」から「デフォルト継承型 + 個別判断 + 規定リスト管理」に転換。§4 に fork 採用根拠列と §4.2 再検討候補（`forge:query-forge-rules`）を追加。§7.2 で §4 を SoT として明記                                                                                                                                                         |
| 2026-05-18 | k2moons | `forge:query-forge-rules` を継承型に変更（二重 fork の解消）。§4 リストから削除し、§4.2 を「継承型に再分類された SKILL」に書き換え。SKILL.md frontmatter から `context: fork` / `agent` / `model` を削除                                                                                                                                                    |
| 2026-05-18 | k2moons | §3.4 を [MANDATORY] に昇格し、`args` に親タスクのプロンプトを渡してはならない旨を可否表・型別理由・呼び出し例で明示。継承型/fork 型双方に共通の呼び出し側責務として記述                                                                                                                                                                                     |
| 2026-05-25 | Codex   | §5 起動経路選定ガイド追加、§7.1 内部ワーカー制約を [MANDATORY] に格上げ、決定手順・例外条件・多重防御表を §5/§7/§8 で整合                                                                                                                                                                                                                                   |
| 2026-05-26 | k2moons | §6 fork 型 SKILL 一覧に reviewer / evaluator / fixer の 3 行を追加（forge:DES-029 §5.1–§5.3 に基づく）                                                                                                                                                                                                                                                      |
| 2026-06-22 | k2moons | REQ-006 / DES-032 (no-fork-skill feature) を fold。§1.1 設計目的 / §2 実行モデル表 / §3 SKILL 型決定原則 / §6 fork 一覧 / §8 多重防御 A 層 / §9.1 静的検証を改訂。fork 型 SKILL の全廃を方針として確定し、reviewer / evaluator / fixer を `plugins/forge/agents/` 配下のカスタム Agent に置換した記録を §6.2 に残す。根拠は REQ-005 §11.1 の公式バグ群 9 件 |
