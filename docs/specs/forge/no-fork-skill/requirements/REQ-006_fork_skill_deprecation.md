---
type: temporary-feature-requirement
notes:
  - この文書が正。旧仕様（ソースコード・設計書・計画書）と矛盾する場合はこの文書を優先して判断・実装すること。
  - 旧仕様ファイルは本 feature 実装完了まで書き換えない。新規ファイル / 新規ディレクトリとして切り出すこと。
  - 本 feature 実装完了後、この文書は旧仕様書へ merge され削除される予定。
---

# REQ-006 fork 型 SKILL 全廃と Agent 起動への置き換え 要件定義

## メタデータ

| 項目         | 値                                                                                                                                                                                                                                                                                            |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 要件 ID      | REQ-006                                                                                                                                                                                                                                                                                       |
| フィーチャー | no-fork-skill                                                                                                                                                                                                                                                                                 |
| サブシステム | forge-subagent / common-skill-base                                                                                                                                                                                                                                                            |
| 種別         | 要件定義 (アーキテクチャ転換)                                                                                                                                                                                                                                                                 |
| 対象         | bw-cc-plugins 配下の全 fork 型 SKILL（現状: reviewer / evaluator / fixer の 3 SKILL）+ 今後の fork 型 SKILL 採用方針                                                                                                                                                                          |
| 起点 Issue   | [#127](https://github.com/BlueEventHorizon/bw-cc-plugins/issues/127) — reviewer / fixer / evaluator を汎用 Agent にするか？                                                                                                                                                                   |
| 関連要件     | REQ-005_skill_agent_launch_contract（方針 B-2 で fork 型 SKILL を採用した直近決定）                                                                                                                                                                                                           |
| 関連設計     | COMMON-DES-001_skill_base_design（§6 fork 型 SKILL 一覧の改訂対象）、forge:DES-029_skill_agent_launch_contract_design（fork 型 SKILL 採用の根拠文書、改訂対象）、forge:DES-015_review_workflow_design（起動経路図の改訂対象）、forge:DES-028_review_policy_design（修正経路分岐表の改訂対象） |
| 関連ルール   | `docs/rules/skill_launch_paths_definitions.md`、`docs/rules/skill_authoring_notes.md`                                                                                                                                                                                                         |
| 作成日       | 2026-06-20                                                                                                                                                                                                                                                                                    |

---

## 1. 背景

### 1.1 直近決定との位置関係

REQ-005 §5 で reviewer / evaluator / fixer の起動契約を整理した際、方針 B-2 (fork 型 SKILL) を第 1 推奨として採択し、DES-029 で具体化、COMMON-DES-001 §6 に 3 SKILL を fork 採用根拠つきで追加した（2026-05-24 〜 2026-05-26）。本要件はこの決定を **覆す** ものではなく、**前提となっていた `context: fork` の信頼性が想定より低いことが運用で判明した** ことを受け、Claude Code の `context: fork` 機構に依存しない設計へアーキテクチャ転換を行うものである。

### 1.2 運用で観測された問題

`/forge:review` 経路で reviewer / evaluator / fixer を fork 型 SKILL として起動した際、**何もせずに終了する** 現象が複数回再現している。具体的には:

- 起動直後に出力なしで処理が終わる
- spinner が回って消えるだけで結果が UI に出ない
- 親 context のまま実行されてしまい session_dir のファイル契約が空振りする
- `$ARGUMENTS` が置換されず、reviewer/evaluator/fixer がパラメータ不在として fallback する

これらは reviewer 1 起動原則 (FNC-412) と直交した実行基盤側の不安定さであり、SKILL.md 側の改訂では治せない。

### 1.3 公式リポジトリで報告されている根拠

`anthropics/claude-code` リポジトリで `context: fork` 関連の構造的バグが多数報告されている。本要件はこれらが「散発的不具合」ではなく **fork 機構の信頼性そのものが構造的に不足している** 証拠と見なす。

| #                                                                | 状態   | バージョン        | 内容（一行要約）                                                                                                           |
| ---------------------------------------------------------------- | ------ | ----------------- | -------------------------------------------------------------------------------------------------------------------------- |
| [#18394](https://github.com/anthropics/claude-code/issues/18394) | CLOSED | 2.1.1             | `context: fork` が 95%+ の確率で効かず、既存 context でそのまま実行される                                                  |
| [#17283](https://github.com/anthropics/claude-code/issues/17283) | CLOSED | -                 | Skill ツール経由の起動で `context: fork` / `agent:` が honor されない（feature request 扱いに転換）                        |
| [#34164](https://github.com/anthropics/claude-code/issues/34164) | CLOSED | -                 | fork 型 SKILL を別 SKILL から Skill ツールで起動すると `$ARGUMENTS` 置換が効かず、リテラル `$ARGUMENTS[1]` が渡る          |
| [#34328](https://github.com/anthropics/claude-code/issues/34328) | CLOSED | 2.1.76            | fork 型 SKILL を起動しても subagent が立たない（回帰）                                                                     |
| [#60720](https://github.com/anthropics/claude-code/issues/60720) | CLOSED | -                 | fork 型 SKILL の出力が Desktop UI に届かず無音終了。`<local-command-stdout>` ブロックに次ターン用に注入されるのみ          |
| [#55592](https://github.com/anthropics/claude-code/issues/55592) | CLOSED | Sonnet 4.6 で再現 | fork 型 SKILL が無限再帰し、forked subagent が自分自身を再 dispatch する（102+ subagent / 5 分で手動停止）                 |
| [#19751](https://github.com/anthropics/claude-code/issues/19751) | CLOSED | -                 | fork 型 SKILL 内で AskUserQuestion が機能しない                                                                            |
| [#17351](https://github.com/anthropics/claude-code/issues/17351) | OPEN   | -                 | nested skill が呼び出し元 skill context に戻らず main context に戻ってしまう（model も session のものに戻る）              |
| [#68233](https://github.com/anthropics/claude-code/issues/68233) | OPEN   | 2.1.177           | Fork-Subagent recursion guard が `<fork-boilerplate` 部分文字列に false-positive し、top-level からの fork dispatch が失敗 |

特に **#18394 / #34164 / #60720 / #55592** はいずれも `/forge:review` で観測された「何もしないで終了する」現象と症状が一致する。`docs/rules/skill_authoring_notes.md` で記述している多重防御 (A〜D 層) は、A 層 (fork 境界) 自体が信頼できない場合に全体が崩れる。

### 1.4 アーキテクチャ転換の対象

REQ-005 で fork 型 SKILL に再分類された 3 SKILL（reviewer / evaluator / fixer）が直接の対象だが、本要件は **COMMON-DES-001 §6 リスト全体の廃止** を提案する。すなわち今後 bw-cc-plugins では `context: fork` を採用せず、隔離 context が必要な処理はすべて Agent ツール（汎用 Agent / カスタム Agent）経由で起動する方針へ転換する。

> **注**: doc-advisor は 2026 年前半に外部リポジトリ ([BlueEventHorizon/DocAdvisor](https://github.com/BlueEventHorizon/DocAdvisor)) へ分離済みで、そちら側で既に **継承型 dispatcher + read-only カスタム Agent worker** モデルへ移行している (`doc-advisor:query-worker` 等)。本要件は同パターンを bw-cc-plugins 配下にも適用する。

---

## 2. スコープ

### 2.1 本要件で扱う範囲

- bw-cc-plugins 配下の **全 fork 型 SKILL の廃止** 方針確定
- 代替手段の候補評価 (汎用 Agent / カスタム Agent / 親実装) と選定基準の明文化
- 各 fork 型 SKILL (reviewer / evaluator / fixer) の置換方針案
- fixer の書き込み副作用の安全境界要件（単一 finding / 編集対象限定 / worktree isolation の要否）
- session_dir ファイル契約（refs.yaml / plan.yaml / `review_<種別>.md` / patch_result.json）の維持要件
- ルール文書 (`skill_launch_paths_definitions.md` / `skill_authoring_notes.md`) と設計書 (COMMON-DES-001 / DES-015 / DES-028 / DES-029) の改訂方針
- 静的検証テストの更新方針
- 段階移行 vs 一括移行の分割案

### 2.2 本要件で扱わない範囲

- 設計書 (DES) の具体的記述
- `agents/<name>.md` のカスタム Agent system prompt 具体内容
- `plugins/forge/skills/{reviewer,evaluator,fixer}/` の SKILL.md 改訂・削除作業
- `plugins/forge/skills/review/SKILL.md` の Phase 3 / 5 / 6 起動経路書き換え
- `tests/forge/subagent/test_fork_skill_*.py` のリプレース実装
- `tests/common/test_query_skill_isolation.py` の改訂
- `permissions.deny` 設定の変更

上記は別フィーチャー（feature/no-fork-skill-impl 等）で着手する。

---

## 3. 機能要件

### FNC-N01: fork 型 SKILL の新規採用禁止 [MANDATORY]

bw-cc-plugins 配下で `context: fork` を frontmatter に持つ SKILL を **新規に作成しない**。既存の fork 型 SKILL は §3.2 の置換方針に従って Agent 化または継承型化する。

`docs/rules/skill_authoring_notes.md` の「fork 型 / 継承型 SKILL の判別と多重防御」節は、本要件適用後に「fork 型は採用しない（既知不具合のため）」へ書き換える。COMMON-DES-001 §6 リストは **節そのものを「fork 型 SKILL は採用しない」へ書き換える**（空リスト維持ではなく、節の意味を反転させて新規追加経路自体を閉じる）。

> **用語統一**: 本要件で「廃止」「採用しない」を併用するが、いずれも **同義** として扱う（fork 型 SKILL を新規にも既存にも使わない・既存は §3.2 で置換する）。文書側 (ルール / 設計書) を改訂するときは、項目自体を残して「採用しない（廃止）」と注記する方針で統一する（削除はしない。判断履歴を残すため）。

### FNC-N02: 既存 fork 型 SKILL の置換 [MANDATORY]

現在 COMMON-DES-001 §6 にリストされている 3 SKILL を以下のいずれかに置換する。具体的な選定は設計フェーズ (DES) で行うが、本要件で **選定肢と評価軸** を確定する。

| 既存 fork 型 SKILL | 置換候補                                                                                                 |
| ------------------ | -------------------------------------------------------------------------------------------------------- |
| reviewer           | (A) 汎用 Agent / (B) read-only カスタム Agent / (C) 親 (review) が継承型で内包                           |
| evaluator          | (A) 汎用 Agent / (B) read-only カスタム Agent / (C) 親 (review) が継承型で内包                           |
| fixer              | (A) 汎用 Agent / (B) カスタム Agent + 安全境界 / (D) 親 (review / present-findings) が Edit/Write を実行 |

(D) は fixer 固有のオプションで、Agent は修正案生成までに留め、ファイル書き込みは親が行う構成（issue #127 提示の案A）。

### FNC-N03: session_dir ファイル契約の維持 [MANDATORY]

Agent 化後も session_dir 配下のファイル契約 (`refs.yaml` / `plan.yaml` / `review_<種別>.md` / `patch_result.json`) は維持する。Agent 起動時の prompt にはこれらのパスを含め、Agent は自力で Read / Write する。**親 context の Issue 本文・差分・ファイル全文を prompt に貼り付けてはならない**（COMMON-DES-001 §4 [MANDATORY] と整合）。

### FNC-N04: 起動契約の単一箇所集約 [MANDATORY]

reviewer / evaluator / fixer の起動契約 (`subagent_type` の値 / prompt の骨格 / 期待される return スキーマ) は、orchestrator (`review/SKILL.md`) の 1 箇所に集約する。各 worker 側 (旧 SKILL.md / 新 agent system prompt) は「**起動された側が読む手順書**」として位置付け、起動経路の記述を含めない。

### FNC-N05: fixer の安全境界 [MANDATORY]

fixer を Agent 化する場合 (置換候補 (A) / (B))、以下の安全境界を要件として満たすこと:

- **単一 finding 単位での修正**: 1 起動につき 1 finding ID を引数とする (`--single` 相当)。`--batch` は親が複数回起動する形に変える
- **編集対象ファイルの限定**: prompt 内に「対象ファイルパスの集合」を渡し、それ以外への書き込みを禁止する（明文化）
- **関係ない refactor の禁止**: 「指摘の修正以外の変更を加えない」を Role 制約として明記
- **テスト実行と結果報告**: 修正後のテスト実行有無は scope 内で決める。最低限、修正対象ファイルへの構文影響 (parse error 等) を観測して return に含めること
- **worktree isolation の要否**: 検討すべき選択肢として残す。採用する場合は親が `git worktree add` で隔離し、Agent はその worktree で作業する設計とする（採用是非は設計フェーズで判断）

置換候補 (D) (親実装) を採用する場合は上記の多くが「親 Claude の責務」として再分配されるが、編集対象ファイルの限定・無関係 refactor 禁止は親側にも適用する。

### FNC-N06: 汎用 Agent と カスタム Agent の選定基準 [MANDATORY]

各 worker をどちらの Agent タイプに置換するかは、以下の基準で設計フェーズ判断する:

| 観点                 | 汎用 Agent (general-purpose)                                            | カスタム Agent (`agents/<name>.md`)                                           |
| -------------------- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| 手順書の所在         | 呼び出し元 prompt 全体（毎回構成）                                      | `agents/<name>.md` の system prompt（固定）+ タスク prompt                    |
| 起動契約の自己完結性 | 呼び出し元 prompt と対象 SKILL.md (旧) / 内部手順の整合保証が呼び出し側 | system prompt が一次情報。タスク prompt は finding ID 等の最小情報のみ        |
| プラグイン配布       | プラグイン外（呼び出し元 prompt 経由）                                  | `plugins/forge/agents/` 配下として配布可                                      |
| ロール固定の強さ     | 弱い（毎回 prompt 次第で変動）                                          | 強い（system prompt で固定）                                                  |
| 推奨ケース           | 一回性が高く finding ID のみで完結する短ジョブ                          | 複数経路から同じロールで呼ばれる worker (reviewer / evaluator / fixer は該当) |

> **指針**: reviewer / evaluator は read-only な独立ロールで再利用性が高いため **カスタム Agent** が第 1 候補。fixer は書き込み副作用と安全境界の責務をどこに置くかで分かれるが、ロール固定の強さを優先するならカスタム Agent。

### FNC-N07: 起動経路定義の改訂 [MANDATORY]

`docs/rules/skill_launch_paths_definitions.md` §1 の起動経路 5 種のうち **fork 型 SKILL** の項を「採用しない（既知不具合のため。FNC-N01 / §1.3 参照）」と明示する（項目自体は削除せず、判断履歴を残すため注記で意味を反転させる）。同 §2「subagent」の用法統一は維持する。

`docs/rules/skill_authoring_notes.md` の「fork 型 / 継承型 SKILL の判別と多重防御」は以下のように改訂する:

- fork 型 / 継承型 の判別表 → 「継承型のみ採用する」へ統一
- 多重防御の表 → A 層 (fork 境界) を削除し、B (Role 制約) / C (allowlist) / D (物理 deny) に縮約
- fork 型必須事項 → 削除
- 命名規約 → fork 型関連の記述を削除

### FNC-N08: 設計書の改訂 [MANDATORY]

以下の設計書を改訂する（具体的記述は設計フェーズで作成）:

- **COMMON-DES-001**: §3.2 fork 型採用判断基準を削除、§6 fork 型 SKILL 一覧を「廃止済み」節へ転換、§8 多重防御表から A 層を削除、§9 静的検証から fork 型 frontmatter 検証を削除
- **DES-029**: 「fork 型 SKILL として Skill ツールで呼ぶ」前提を全廃し、Agent 起動経路に書き換え。§5 fork 採用根拠は §1.3 公式バグ群を根拠とした「Agent 採用根拠」に転換
- **DES-015**: フローチャート (`flowchart TD`) の `/forge:reviewer × 1 起動` を Agent 起動 (`subagent_type: <chosen>`) に書き換え。Phase 3 / 5 / 6 の起動方法記述を更新
- **DES-028**: 修正経路分岐表（軽量経路 + fork 型 fixer 経路の 2 種）を「軽量経路 + Agent 起動 fixer 経路」へ更新

### FNC-N09: 静的検証テストの更新 [MANDATORY]

`tests/` 配下の以下を更新する（実装は別フィーチャー）:

- `tests/common/test_query_skill_isolation.py` → 「fork 型 SKILL が存在しないこと」を検証する形に転換、または削除
- `tests/forge/subagent/test_fork_skill_frontmatter.py` → 削除、または「`context: fork` を持つ SKILL が存在しないこと」を検証
- `tests/forge/subagent/test_fork_skill_call_contract.py` → 「Skill ツールで fork 型 SKILL を呼んでいないこと」または Agent 起動契約のテストへ転換
- `test_agent_allowedtools_consistency.py` / `test_skill_allowedtools_consistency.py` / `test_subagent_term_usage.py` / `test_slash_command_launch_context.py` → 起動経路の変更に追随して expectation を更新

新規追加テストの候補:

- bw-cc-plugins 配下のすべての SKILL.md frontmatter に `context: fork` が含まれないことを検証
- 起動側 SKILL.md / 設計書中の Agent 起動経路と `subagent_type` 値の整合 (Issue #32 系の再発防止)

### FNC-N10: 段階移行の選択 [推奨]

reviewer / evaluator は read-only なため Agent 化のリスクが低く先行可能。fixer は書き込み副作用と安全境界の設計が必要なため後段に置く。本要件では以下の分割を **推奨** する（必須ではない。設計フェーズで一括移行を選んでも良い）:

- Phase 1: reviewer + evaluator を Agent 化（DES + 実装 + テスト）
- Phase 2: fixer を Agent 化（安全境界設計を伴う）
- Phase 3: COMMON-DES-001 §6 / ルール文書 / fork 型関連テストの最終クリーンアップ

---

## 4. 受け入れ基準

### 4.1 本要件 (REQ-006) の完了条件

- §3 の FNC-N01 〜 FNC-N10 がすべて要件として記述されていること（本文書）
- §1.3 の公式バグ一覧が「fork 機構の信頼性が構造的に不足している」根拠として整理されていること
- §3.2 の置換候補 ((A) / (B) / (C) / (D)) が各 worker について評価可能な形で列挙されていること
- FNC-N05 (fixer の安全境界要件) が明文化されていること

### 4.2 後続フィーチャーが満たすべき条件 (参考)

設計フェーズ (DES) およびそれ以降で、以下を満たすこと:

- 各 worker (reviewer / evaluator / fixer) の置換先 Agent タイプが選定されていること
- COMMON-DES-001 §6 が「廃止」または空リストへ改訂されていること
- DES-015 / DES-028 / DES-029 が Agent 起動前提に書き換えられていること
- ルール文書 (`skill_launch_paths_definitions.md` / `skill_authoring_notes.md`) が fork 型不採用方針へ更新されていること
- 静的検証テストが新方針に追随していること
- `/forge:review code --auto` を含む E2E が手動で正常完了すること

---

## 5. 分割案 (実装着手時の参考)

### 5.1 推奨分割

| #   | フィーチャー名候補        | 範囲                                                                                                                   | 依存              |
| --- | ------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ----------------- |
| F-1 | feature/no-fork-skill-adr | 本 REQ-006 + 設計 ADR (worker タイプ選定 / fixer 安全境界の決定) を作成                                                | なし              |
| F-2 | feature/no-fork-reviewer  | reviewer を Agent 化（`agents/<name>.md` 新設 + review/SKILL.md Phase 3 改訂 + 単独修正レビュー経路改訂 + テスト追従） | F-1 完了後        |
| F-3 | feature/no-fork-evaluator | evaluator を Agent 化（同様の構造）                                                                                    | F-1 完了後        |
| F-4 | feature/no-fork-fixer     | fixer を Agent 化（安全境界実装 + present-findings/SKILL.md Step 2-B 改訂 + 軽量経路との分岐表更新）                   | F-1 / F-2 完了後  |
| F-5 | feature/no-fork-cleanup   | COMMON-DES-001 §6 / ルール文書 / 静的検証テストの最終クリーンアップ + 旧 fork 型 SKILL ファイル削除                    | F-2 〜 F-4 完了後 |

### 5.2 一括分割（小規模 PR を許容しない場合）

| #     | 範囲                                                    |
| ----- | ------------------------------------------------------- |
| F-all | F-2 〜 F-5 を 1 PR にまとめる（巨大 PR 化のリスクあり） |

---

## 6. リスク

### 6.1 移行中の reviewer 1 起動原則の維持

DES-015 / FNC-412 の reviewer 1 起動原則は Agent 化後も維持する必要がある。Agent を engine ごとに分割起動する誘惑が生まれやすいため、設計フェーズで明示的に「Agent 1 起動原則」として再定式化する。

### 6.2 軽量経路 (FNC-413) との分岐

軽量経路 (orchestrator 直接 Edit) は Agent 起動なしのため本要件の影響を受けないが、修正経路分岐表 (DES-028 §4.5) の「fork 型 fixer 経路」を「Agent 経由 fixer 経路」に書き換える必要がある。

### 6.3 fixer 安全境界の設計負荷

fixer を Agent 化する場合、編集対象ファイルの限定・無関係 refactor 禁止・worktree isolation の必要性判断は新規設計が必要。安全境界設計を軽視するとレビューバグの修正で別箇所を壊す事故が起きうる。

### 6.4 既存テストの破壊範囲

`tests/forge/subagent/` 配下と `tests/common/test_query_skill_isolation.py` の検証 expectation が変わる。テスト改訂を漏らすと CI 偽陽性または偽陰性が長期化する。

### 6.5 Agent 起動経路自体のバグ

Agent ツール側にも独自のバグ（例: Issue #68981 nested skill コンテキスト、#34164 系の引数受け渡し問題の Agent 版）が存在しうる。設計フェーズで Agent ツールの既知バグも調査し、回避策を要件に追記する。

---

## 7. 未確定事項

| ID      | 内容                                                                                                                   | 解消予定段階                                                                                        |
| ------- | ---------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| TBD-N01 | reviewer / evaluator / fixer 各々を 汎用 Agent / カスタム Agent / 親実装 のどれに置換するか                            | 設計フェーズ                                                                                        |
| TBD-N02 | fixer の worktree isolation 採用是非                                                                                   | 設計フェーズ                                                                                        |
| TBD-N03 | カスタム Agent 採用時、`agents/<name>.md` を `plugins/forge/agents/` 配下に置くか、リポジトリルート `agents/` に置くか | 設計フェーズ                                                                                        |
| TBD-N04 | session_dir ファイル契約のスキーマは現行維持で良いか（Agent 起動時の prompt サイズ最適化で簡略化する余地）             | 設計フェーズ または 実装フェーズ（現行スキーマで Agent 化を進めた上で実測してから判断する余地あり） |
| TBD-N05 | 静的検証テスト「fork 型 SKILL が存在しないこと」の実装方式（frontmatter スキャン or grep）                             | 実装フェーズ                                                                                        |
| TBD-N06 | 段階移行 (F-2 〜 F-5) を採るか一括 (F-all) を採るか                                                                    | 設計フェーズ                                                                                        |

---

## 8. 関連文書

| 種別     | パス                                                                                           | 関係                                                                                              |
| -------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| 定義     | `docs/rules/skill_launch_paths_definitions.md`                                                 | 起動経路 5 種の定義文書。本要件で fork 型 SKILL の項を「廃止」へ更新                              |
| ルール   | `docs/rules/skill_authoring_notes.md`                                                          | SKILL.md 規約。fork 型関連節を非推奨化                                                            |
| 設計書   | `docs/specs/common/design/COMMON-DES-001_skill_base_design.md`                                 | SKILL 実行モデル + fork 型一覧。§6 を「廃止」へ                                                   |
| 設計書   | `docs/specs/forge/design/DES-029_skill_agent_launch_contract_design.md`                        | 直近の fork 型採用根拠文書。Agent 起動契約へ書き換え                                              |
| 設計書   | `docs/specs/forge/design/DES-015_review_workflow_design.md`                                    | review ワークフロー図。Agent 起動に追随                                                           |
| 設計書   | `docs/specs/forge/design/DES-028_review_policy_design.md`                                      | 修正経路分岐表 (FNC-413)。fork 型 fixer 経路を Agent 経由へ書き換え                               |
| 直近要件 | `docs/specs/forge/requirements/REQ-005_skill_agent_launch_contract.md`                         | 方針 B-2 採択の起点。本要件はその前提（fork 型の信頼性）を再評価                                  |
| 外部参考 | (外部リポジトリ) [BlueEventHorizon/DocAdvisor](https://github.com/BlueEventHorizon/DocAdvisor) | `doc-advisor:query-worker` — 継承型 dispatcher + read-only カスタム Agent worker モデルの参照実装 |

> **公式バグ群への参照**: fork 機構の構造的不具合の根拠は §1.3 のテーブルに集約している（外部 Issue URL のため本表の `パス` 列に含めない）。

---

## 変更履歴

| 日付       | 変更者  | 内容                                                                                                                                     |
| ---------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-06-20 | k2moons | 初版作成。Issue #127 の検討結果を要件として整理。fork 型 SKILL 全廃方針、公式バグ群 9 件の根拠、置換候補 (A)/(B)/(C)/(D)、分割案を明文化 |
