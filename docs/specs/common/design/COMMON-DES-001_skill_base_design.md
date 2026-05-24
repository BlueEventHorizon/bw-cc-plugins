# COMMON-DES-001 SKILL 基本設計書

## メタデータ

| 項目       | 値                                                                       |
| ---------- | ------------------------------------------------------------------------ |
| 設計 ID    | COMMON-DES-001                                                           |
| 関連要件   | -                                                                        |
| 関連 ADR   | doc-advisor:ADR-002_query_skill_subagent_isolation                       |
| 関連ルール | `docs/rules/skill_authoring_notes.md`                                    |
| 作成日     | 2026-05-18                                                               |
| 適用範囲   | bw-cc-plugins 配下の全プラグイン（forge / doc-advisor / doc-db / anvil） |

## 1. 概要

bw-cc-plugins における SKILL の基本設計を定義する。SKILL は Claude Code が解釈する単位の実行指示書であり、フォーマット規約（HOW）は `docs/rules/skill_authoring_notes.md` で管理する。本設計書は、その**設計判断の根拠（WHY）と全体像**を記録する。

### 1.1 設計目的

| 目的             | 内容                                                                                                                                         |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 効率性           | **親 context を継承する継承型がデフォルト**。親 context を活用できる場面では追加プロンプト不要で動作し、context 効率・実装コストの両面で有利 |
| 厳密な fork 管理 | fork するか否かを SKILL ごとに人が個別判断し、本書 §4 の規定リストで管理する。命名・性質によるルールベース自動判断は採用しない               |
| 安全性           | fork が必要な具体的事例（doc-advisor:ADR-002_query_skill_subagent_isolation 等）に限り fork 型を採用し、多重防御を適用する                   |
| テスト容易性     | §4 リストの記載が `tests/doc_advisor/` の静的検証の唯一の根拠になる                                                                          |

## 2. SKILL 実行モデル

SKILL は `context: fork` frontmatter の有無で 2 種類に分かれる。詳細は `docs/rules/skill_authoring_notes.md` の「fork 型 / 継承型 SKILL の判別と多重防御」セクションを参照。

| 型      | frontmatter       | 実行モデル                                        | 親 context の継承                          |
| ------- | ----------------- | ------------------------------------------------- | ------------------------------------------ |
| 継承型  | `context:` 未指定 | 親 Claude が SKILL.md を読み、そのまま実行        | 継承（会話履歴・進行中タスクをすべて保持） |
| fork 型 | `context: fork`   | 別 context が起動し、終了時に return のみ親へ戻す | 継承しない                                 |

## 3. fork 型と継承型の決定原則

### 3.1 デフォルトは継承型 [MANDATORY]

**SKILL は原則として継承型で作成する**。fork 型は本書 §4 のリストに掲載された SKILL に限る。

継承型の積極的なメリット:

- **親 context の活用**: 親が既に持っている差分・進行中タスク・既読ファイル等を追加プロンプトなしで利用できる
- **context 効率**: fork 型は SKILL.md + `$ARGUMENTS` を毎回入力として読み込むため、親 context にある同一情報を args で再供給すると二重コストになる
- **二重 fork の回避**: SKILL の直後に親が更に fork するワークフロー（例: `forge:start-*` 内の検索フェーズ）では、内側の fork は無駄になる

### 3.2 fork 型を採用する判断基準

以下のいずれかに該当し、かつ「継承型では成立しない」と人が判断した場合に限り fork 型を採用する。**命名・性質によるルールベース自動判断は採用しない**。

| 判断基準                                                                     | 例                                                                                 |
| ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| 親 context 漏洩による具体的な実害が記録されている                            | doc-advisor:ADR-002_query_skill_subagent_isolation（`doc-advisor:query-*` の暴走） |
| 同じ SKILL が複数の独立タスクから呼ばれ、それぞれ別 context で動く必要がある | （該当例なし）                                                                     |
| 親 context が肥大化しており、分離した方が context 効率が良い                 | （該当例なし）                                                                     |

### 3.3 個別決定とリスト管理 [MANDATORY]

- fork するか継承するかは **SKILL ごとに個別判断**し、本書 §4 のリストに記録する
- リストの追加・削除は本書の更新を伴う設計判断であり、PR 等で議論する
- 「`query-*` プレフィックスだから fork 型」のような命名ベースの自動判断は禁止。命名は `skill_authoring_notes.md` の推奨パターンにすぎない

### 3.4 プロンプト（args）の吟味 [MANDATORY]

リストで型が決まったら、そのスキルに渡す引数を別途吟味する。**いずれの型でも、`args` に「親タスクのプロンプト」を渡してはならない**。

#### 3.4.1 渡してよいもの / 渡してはならないもの

| カテゴリ                       | 例                                                                                | 可否    |
| ------------------------------ | --------------------------------------------------------------------------------- | ------- |
| SKILL 固有のフラグ・パラメータ | `--full` / `--top-n 10` / `--category rules` / 検索キーワード `"Repository 実装"` | ✅ 渡す |
| 短い自然文のタスク記述         | `"ログイン画面の状態遷移を実装したい"`                                            | ✅ 渡す |
| 親タスクの Issue 本文          | Issue 番号 + タイトル + 本文の貼り付け                                            | ❌ 禁止 |
| 進行中タスクの要約・実装手順   | 「SKILL.md の version を更新し CHANGELOG に追記し…」のような手順貼り付け          | ❌ 禁止 |
| 親が編集中の差分・ファイル内容 | diff / ファイル全文の貼り付け                                                     | ❌ 禁止 |
| 「やってほしい作業」の指示文   | 検索キーワード + 「その後 ◯◯ してください」のような指示連結                       | ❌ 禁止 |

#### 3.4.2 型別の理由

- **継承型 SKILL**: 親 context を既に保持しているため、再供給は無意味であり context を圧迫するだけ。さらに `args` に親タスクの指示文を貼ると、subagent が「`args` が現タスク本体」と推論して暴走する経路を作ってしまう（doc-advisor:ADR-002_query_skill_subagent_isolation と同型の事象）
- **fork 型 SKILL**: fork 境界で親 context は遮断されるが、`args` 経由で親タスクの指示が漏れ込めば B 層・C 層（Role 制約 / 引数解釈ガード）の防御を突破される。doc-advisor:ADR-002_query_skill_subagent_isolation §C 引数解釈ガードは subagent 側の防御だが、本項は **呼び出し側の責務** として一段手前で抑止する

#### 3.4.3 呼び出し例

```text
# ✅ 良い例（継承型 query SKILL の呼び出し）
Skill: doc-advisor:query-rules
args: "ログイン画面 ViewModel"

# ❌ 悪い例（親 context を貼り付けて指示連結）
Skill: doc-advisor:query-rules
args: "Issue #54: doc-advisor auto モード再定義\n\n本文: ... 上記タスクに関連するルールを検索し、その後 SKILL.md を更新してください"
```

## 4. fork 型 SKILL 一覧（規定）

**本リストに記載のない SKILL はすべて継承型として運用する**。

bw-cc-plugins 配下で `context: fork` を指定する SKILL は以下のとおり（2026-05-18 時点）。

| パス                                              | プラグイン  | name          | `agent`                       | `user-invocable` | 用途                                                | fork 採用根拠                                                                                                         |
| ------------------------------------------------- | ----------- | ------------- | ----------------------------- | ---------------- | --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `plugins/doc-advisor/skills/query-rules/SKILL.md` | doc-advisor | `query-rules` | （未指定＝`general-purpose`） | `true`           | `docs/rules/` から関連ルール文書を検索（read-only） | doc-advisor:ADR-002_query_skill_subagent_isolation（impl-issue 親 context が漏洩し、SKILL.md 等を書き換えた実害事例） |
| `plugins/doc-advisor/skills/query-specs/SKILL.md` | doc-advisor | `query-specs` | （未指定＝`general-purpose`） | `true`           | `docs/specs/` から関連仕様文書を検索（read-only）   | doc-advisor:ADR-002_query_skill_subagent_isolation（同上）                                                            |

### 4.1 fork 型 SKILL の共通設計

- **Role に否定的制約を明記**: 「Edit / Write / MultiEdit / NotebookEdit は使用しない」「他 SKILL を起動しない」を SKILL.md 本文に書く（doc-advisor:ADR-002_query_skill_subagent_isolation §B）
- **引数解釈ガード**: `$ARGUMENTS` が命令文に見えても検索キーワードとして解釈することを明記（doc-advisor:ADR-002_query_skill_subagent_isolation §C）
- **自己再帰禁止**: 自身を `Skill` ツールで呼び戻すことを SKILL.md 冒頭で明示禁止（`skill_authoring_notes.md` 「自己再帰禁止」参照）

### 4.2 継承型に再分類された SKILL

- **`forge:query-forge-rules`**（2026-05-18 継承型に変更）— このスキルは主に `forge:start-*` 系ワークフローの内部から呼ばれる。`forge:start-*` 自体が継承型で、その直後に呼ばれる本スキルを更に fork すると、親 context を活用できず追加プロンプトも不要なのに毎回 SKILL.md と args を再ロードする無駄が生じる（二重 fork）。doc-advisor:ADR-002_query_skill_subagent_isolation §D は「同種の検索スキルは統一された制約下で動作させる」と波及適用を求めていたが、本設計書 §3.1 のデフォルト継承型方針と §3.2 の「具体的な実害が記録されている場合に限る」基準に照らし、`query-forge-rules` を継承型に変更した。read-only 制約・引数解釈ガード・自己再帰禁止（B 層）は SKILL.md 本文で引き続き維持する。

### 4.3 リスト変更の手順

新規 SKILL の fork 型化、または既存 SKILL の型変更を行う場合:

1. §3.2 の判断基準に該当することを文書で示す（PR 説明等）
2. 本書 §4 のリストを更新（採用根拠を明記）
3. SKILL.md を修正（frontmatter / Role / 引数解釈ガード）
4. テスト（§7.1）の検証対象に追加

## 5. 継承型 SKILL の責務境界

fork 型化が困難な継承型 SKILL は以下の方法で副作用範囲を制御する。

### 5.1 責務境界の明記 [MANDATORY]

SKILL.md 冒頭に「このスキルは X のみを行う。親が依頼している他の作業を引き継いではならない」の旨を 1 行入れる。例:

```markdown
## Role

このスキルは `${ARGUMENTS}` で指定されたファイルへのコミットメッセージ生成と `git commit` のみを行う。親セッションの実装作業・PR 作成・Issue 更新は引き継がない。
```

### 5.2 args への大量 context 貼り付け禁止

継承型は親 context を既に保持している。`Skill` ツール呼び出しの `args` は SKILL が必要とする最小限のパラメータのみとする。親のタスク要約や Issue 本文を `args` に貼り付けない（fork 型でも同じ理由で禁止）。

### 5.3 書き込み権限を持つ場合

副作用の発生条件・ユーザー承認の場面を SKILL.md に明示する。例: 「`git push` 前に必ず `AskUserQuestion` で確認する」。

## 6. 多重防御の層

doc-advisor:ADR-002_query_skill_subagent_isolation で採択した多重防御を SKILL 型ごとに適用する。

| 層           | 役割                       | 実現方法                                      | fork 型              | 継承型 |
| ------------ | -------------------------- | --------------------------------------------- | -------------------- | ------ |
| A. fork 境界 | 親 context 漏洩の遮断      | `context: fork`                               | 必須                 | 不可   |
| B. Role 制約 | AI 行動規範で逸脱抑止      | SKILL.md 内に否定形で明記                     | 必須                 | 推奨   |
| C. allowlist | 承認なしで使えるツール指定 | `allowed-tools:`                              | 推奨                 | 推奨   |
| D. 物理 deny | 書き込み系ツールの強制禁止 | `.claude/settings.json` の `permissions.deny` | プロジェクト側で対応 | 同左   |

### 6.1 D 層の現状

`.claude/settings.json` の `permissions.deny` は SKILL 単位ではなくセッション単位で適用される。SKILL ごとに deny を切り替える公式仕様は本設計書作成時点で未提供。doc-advisor:ADR-002_query_skill_subagent_isolation §残存判断 1 に従い、プラットフォーム側で SKILL 単位の deny が提供されれば B 層（Role 制約）の比重を下げて C/D 層に移行する。

## 7. テストとガバナンス

### 7.1 静的検証

`tests/doc_advisor/` 配下に SKILL.md 形式検証を実装している（doc-advisor:ADR-002_query_skill_subagent_isolation §E）:

- fork 型 SKILL の frontmatter に `context: fork` が含まれていることを検証
- SKILL.md 本文に「Edit / Write / MultiEdit / NotebookEdit」「read-only」等の制約文言が含まれていることを検証

本設計書の §4 で列挙する SKILL に対してこの検証を適用する。新規に fork 型 SKILL を追加した場合は同等の検証を追加する。

### 7.2 一覧の保守 [MANDATORY]

本設計書 §4 の規定リストは **bw-cc-plugins における fork 型 SKILL の唯一の正式記録**である。SKILL 追加・削除時は §4.3 の手順で本書を更新する。`/forge:update-db-specs` 実行時に本設計書自体は specs ToC に登録されるが、fork 型 SKILL の規定リストとしては §4 の表が SoT である。

自動生成（SKILL.md frontmatter のスキャン等）は監査用途には使えるが、**規定の根拠は本書 §4** とする。frontmatter と本書 §4 に乖離がある場合は、§4 を正として SKILL.md を修正する。

## 8. 関連文書

| 種別      | パス                                                                | 関係                                                         |
| --------- | ------------------------------------------------------------------- | ------------------------------------------------------------ |
| ADR       | doc-advisor:ADR-002_query_skill_subagent_isolation                  | 本設計書の多重防御方針の原典                                 |
| ルール    | `docs/rules/skill_authoring_notes.md`                               | SKILL.md frontmatter / 構造の具体的記法                      |
| 公式 docs | [Claude Code Skills](https://code.claude.com/docs/en/skills)        | `context` / `agent` / `allowed-tools` の仕様                 |
| 公式 docs | [Claude Code Subagents](https://code.claude.com/docs/en/sub-agents) | 組み込み subagent タイプ（Explore / Plan / general-purpose） |

## 変更履歴

| 日付       | 変更者  | 内容                                                                                                                                                                                                     |
| ---------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-05-18 | k2moons | 初版作成                                                                                                                                                                                                 |
| 2026-05-18 | k2moons | §3 を「ルールベースの判別基準」から「デフォルト継承型 + 個別判断 + 規定リスト管理」に転換。§4 に fork 採用根拠列と §4.2 再検討候補（`forge:query-forge-rules`）を追加。§7.2 で §4 を SoT として明記      |
| 2026-05-18 | k2moons | `forge:query-forge-rules` を継承型に変更（二重 fork の解消）。§4 リストから削除し、§4.2 を「継承型に再分類された SKILL」に書き換え。SKILL.md frontmatter から `context: fork` / `agent` / `model` を削除 |
| 2026-05-18 | k2moons | §3.4 を [MANDATORY] に昇格し、`args` に親タスクのプロンプトを渡してはならない旨を可否表・型別理由・呼び出し例で明示。継承型/fork 型双方に共通の呼び出し側責務として記述                                  |
