# SUBAGENT-REQ-001 SKILL / Agent / subagent 起動契約 整理要件

## メタデータ

| 項目         | 値                                                                                                                                                                                                                                                                                                    |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 要件 ID      | SUBAGENT-REQ-001                                                                                                                                                                                                                                                                                      |
| サブシステム | forge-subagent                                                                                                                                                                                                                                                                                        |
| 種別         | 要件定義 (整理 / 文書修正)                                                                                                                                                                                                                                                                            |
| 対象         | `/forge:review` 配下の reviewer / evaluator / fixer / present-findings / review                                                                                                                                                                                                                       |
| 起点 Issue   | [#89](https://github.com/BlueEventHorizon/bw-cc-plugins/issues/89) — review 系 SKILL の Skill / Agent / subagent 起動契約を整理する / [#32](https://github.com/BlueEventHorizon/bw-cc-plugins/issues/32) — Fixer SKILL の誤読があった (AI 自身が `subagent_type: "forge:fixer"` と誤指定した実害事例) |
| 作成日       | 2026-05-24                                                                                                                                                                                                                                                                                            |

---

## 1. 背景

### 1.1 現状の問題

`/forge:review` 系 SKILL では、Claude Code の **Skill 呼び出し**、SKILL frontmatter の `context: fork`、Agent ツールによる **general-purpose subagent 起動**、および Codex subprocess 起動の責務境界が混在している。

特に、起動される側の SKILL.md に「subagent として動作」「general-purpose subagent を起動」と書かれているが、frontmatter には `context: fork` / `agent:` がなく、呼び出し元が Agent ツールで直接起動する場合には、その SKILL.md が subagent に読まれる保証がない。

結果として、以下のリスクがある:

- SKILL.md に書いた workflow が実行時プロンプトとして使われず、実装仕様として機能しない
- 起動する側 / 起動される側のどちらが入力契約を持つのか曖昧になる
- `Skill` ツールで呼ぶのか、`Agent` ツールで subagent prompt として起動するのかが混ざる
- `reviewer/SKILL.md` が「誰の手順書として読まれるか」が曖昧 (orchestrator が prompt として展開する手順書か、subagent 内で読まれる手順書か)
- `allowed-tools` に `Agent` がない SKILL が「Agent / subagent を起動する」と記述している
- 軽量経路 (FNC-413) が追加され、修正の経路が「orchestrator 直接 / Agent ツール起動 / Skill ツール呼び」の 3 種に増えたが、責務境界の文書が未整理
- **AI 自身が誤読する実害事例が発生済み** (Issue #32): prompt 内に `/forge:fixer --batch` という slash command 表記があると、AI が「Skill 名で subagent 起動できる」と誤読し、`subagent_type: "forge:fixer"` のような無効指定を行う

### 1.2 関連既存ルール

- `docs/rules/skill_authoring_notes.md`
  - `subagent` という語は曖昧であり、Skill ツールの fork 型 SKILL と Agent ツールのサブエージェントは別物
  - `agent:` は `context: fork` と組み合わせてのみ意味がある
  - `allowed-tools` は「承認なしで使える」allowlist であり、指定外でも (permission 設定が許せば) 呼び出し可能 (= 動作上は破綻しないが、契約として読みづらい)
  - SKILL 内から別 SKILL を呼ぶ場合は Skill ツール経由であり、スクリプトから直接呼ぶ構文はない
- `docs/specs/common/design/COMMON-DES-001_skill_base_design.md`
  - `context: fork` がない SKILL は継承型
  - fork 型 SKILL は §4 の規定リストに限る
  - args に親タスクのプロンプトを渡してはならない
  - **継承型のまま Skill ツールで呼ぶことは §4 リストの更新不要**。継承型 Skill 呼びと fork 型 Skill 呼びを混同しないこと

### 1.3 本要件のスコープ

- 対象は **設計・SKILL 文書の責務境界整理**。実装変更 (Python スクリプト・hooks 等) は含まない
- 修正方針 (方針 A / B-1 / B-2 / C) は §6 で評価し、推奨を示す
- 静的検証テストの追加を **再発防止策** として要求する (`CLAUDE.md`「注意ではなく再発防止策を優先する」)
- **COMMON-DES-001 §4 (fork 型 SKILL 一覧) は本要件の検討において固定制約ではない**。必要であれば §4.3 のリスト変更手順 (PR での判断基準提示 / リスト更新 / SKILL.md 修正 / テスト追加) に沿って改訂してよい。すなわち reviewer / evaluator / fixer / present-findings を **fork 型化する選択肢** も評価対象に含める

---

## 2. 抽出された問題箇所

### 2.1 `plugins/forge/skills/evaluator/SKILL.md`

| 項目             | 状態                                                                                                                    |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------- |
| frontmatter      | `context: fork` / `agent:` なし → **継承型**                                                                            |
| `allowed-tools`  | `Read, Write, Bash` (`Agent` なし)                                                                                      |
| 本文の記述       | 「`/forge:review` から general-purpose subagent として起動される」(L23)                                                 |
| 呼び出し元の指示 | `/forge:review` 側 (L458) は evaluator を Agent ツールで起動と書くが、`evaluator/SKILL.md` を Read させる明示指示がない |

**問題**: `evaluator/SKILL.md` の workflow が実際に読まれない可能性がある。

該当箇所:

- `plugins/forge/skills/evaluator/SKILL.md:23`
- `plugins/forge/skills/review/SKILL.md:458`

### 2.2 `plugins/forge/skills/reviewer/SKILL.md`

| 項目             | 状態                                                                                            |
| ---------------- | ----------------------------------------------------------------------------------------------- |
| frontmatter      | `context: fork` / `agent:` なし → **継承型**                                                    |
| `allowed-tools`  | `Read, Write, Bash` (`Agent` なし)                                                              |
| 本文の記述       | 「subagent として動作」(L36) / 「general-purpose subagent を起動」(L155)                        |
| 呼び出し元の指示 | `/forge:review` 側 (L397) は reviewer 起動時に `reviewer/SKILL.md` を Read させる明示指示を持つ |

**問題**: 本文の Claude 実行パスにある「general-purpose subagent を起動」は **「reviewer subagent 自身がレビュー本文を返す経路のメタ説明」** として書かれているように読めるが、文面上「reviewer subagent がさらに subagent を起動する」とも読めてしまうため、誰の手順書として読まれるかが曖昧。

> **注**: 実行上「二重起動」が実際に走るわけではなさそうだが、SKILL.md の記述として **「reviewer subagent の中で読まれる手順書である」** と明示すべき。

該当箇所:

- `plugins/forge/skills/reviewer/SKILL.md:36`
- `plugins/forge/skills/reviewer/SKILL.md:37`
- `plugins/forge/skills/reviewer/SKILL.md:155`
- `plugins/forge/skills/review/SKILL.md:397`

### 2.3 `plugins/forge/skills/fixer/SKILL.md`

| 項目             | 状態                                                                                                                                    |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| frontmatter      | `context: fork` / `agent:` なし → **継承型**                                                                                            |
| `allowed-tools`  | `Read, Write, Edit, Bash` (`Agent` なし)                                                                                                |
| 本文の記述       | 「general-purpose subagent に実際の Edit/Write を委譲する」(L14) / 「general-purpose subagent を起動する」(L173)                        |
| 呼び出し元の指示 | `/forge:review` 側 (L538) は fixer を Agent ツールで起動 / `/forge:present-findings` 側 (L349, L393) は `/forge:fixer` を呼び出すと書く |

**問題**:

- fixer 自身の workflow を読ませるのか、fixer の prompt を review 側が直接構成するのかが曖昧
- Skill 呼び出しと Agent 起動の経路が混ざっている
- **設計原則「メインコンテキストの消費を抑える」(L24) は「方針 B (Skill ツール呼び)」と直接衝突する**。Skill ツール経由 (継承型) で呼ぶと親 context を消費するため、本原則を維持するなら方針 A (Agent ツール起動) を採るしかない

該当箇所:

- `plugins/forge/skills/fixer/SKILL.md:14`
- `plugins/forge/skills/fixer/SKILL.md:24` (設計原則「メインコンテキスト消費を抑える」)
- `plugins/forge/skills/fixer/SKILL.md:35`
- `plugins/forge/skills/fixer/SKILL.md:36`
- `plugins/forge/skills/fixer/SKILL.md:173`
- `plugins/forge/skills/review/SKILL.md:538` (prompt 内に `/forge:fixer --batch` 表記。Issue #32 の誤読源)
- `plugins/forge/skills/present-findings/SKILL.md:349` (prompt 内に `/forge:fixer --single` 表記。Issue #32 の誤読源)
- `plugins/forge/skills/present-findings/SKILL.md:393` (prompt 内に `/forge:fixer --batch` 表記。Issue #32 の誤読源)

### 2.4 `plugins/forge/skills/present-findings/SKILL.md`

| 項目                | 状態                                                                                                      |
| ------------------- | --------------------------------------------------------------------------------------------------------- |
| frontmatter         | `allowed-tools: Read, Write, Bash, AskUserQuestion, Skill` (`Agent` なし)                                 |
| 設計原則            | 「fixer は subagent 経由」「`/forge:fixer` を general-purpose subagent として起動する」(L21)              |
| 実際の手順          | `/forge:fixer --single` / `/forge:fixer --batch` を呼び出す → Skill 呼び出しなのか Agent 起動なのかが曖昧 |
| 旧 perspective 残存 | `review_{perspective}.md` 前提が大量に残存                                                                |

該当箇所:

- `plugins/forge/skills/present-findings/SKILL.md:21`
- `plugins/forge/skills/present-findings/SKILL.md:120`
- `plugins/forge/skills/present-findings/SKILL.md:168`
- `plugins/forge/skills/present-findings/SKILL.md:349`
- `plugins/forge/skills/present-findings/SKILL.md:361`
- `plugins/forge/skills/present-findings/SKILL.md:393`
- `plugins/forge/skills/present-findings/SKILL.md:395`
- `plugins/forge/skills/present-findings/SKILL.md:582`
- `plugins/forge/skills/present-findings/SKILL.md:603`
- `plugins/forge/skills/present-findings/SKILL.md:626`
- `plugins/forge/skills/present-findings/SKILL.md:632`
- `plugins/forge/skills/present-findings/SKILL.md:651`
- `plugins/forge/skills/present-findings/SKILL.md:676-687`
- `plugins/forge/skills/present-findings/SKILL.md:752`

### 2.5 `plugins/forge/skills/review/SKILL.md`

| 項目                                 | 状態                                                                                       |
| ------------------------------------ | ------------------------------------------------------------------------------------------ |
| reviewer Claude エンジン             | 「まず `reviewer/SKILL.md` を Read せよ」と明記 (L397)                                     |
| evaluator (L458) / fixer (L538) 起動 | 「対象 SKILL.md を Read せよ」の明示なし → 不統一                                          |
| 軽量経路 (FNC-413)                   | `--auto` / `--auto-critical` に追加されたが、fixer 経路との責務境界が未明文化 (L515, L538) |

該当箇所:

- `plugins/forge/skills/review/SKILL.md:397`
- `plugins/forge/skills/review/SKILL.md:458`
- `plugins/forge/skills/review/SKILL.md:515`
- `plugins/forge/skills/review/SKILL.md:538`
- `plugins/forge/skills/review/SKILL.md:554`

### 2.6 軽量経路 (FNC-413) との接続

最新コミット `0753f02` で導入された「軽量経路: orchestrator が直接 Edit する」(`review/SKILL.md` §Phase 5 Step 2-A、`present-findings/SKILL.md` §修正実行時の経路分岐) により、**修正実行の経路が 3 種に増えた**。

| # | 経路                            | 起動方法              | context 消費            | 用途                                            |
| - | ------------------------------- | --------------------- | ----------------------- | ----------------------------------------------- |
| 1 | orchestrator 直接 Edit (軽量)   | (起動なし)            | 親 context を消費       | 件数小・auto_fixable な finding の自動修正      |
| 2 | fixer を Agent ツールで起動     | Agent ツール (sub)    | 親 context を消費しない | 件数多 or 非 auto_fixable な finding の修正委譲 |
| 3 | fixer を Skill ツールで呼び出し | Skill ツール (継承型) | 親 context を消費       | present-findings からの呼び出し記述として混在   |

**問題**:

- 3 経路の分岐条件・責務境界が SKILL.md / 設計書 (DES-015 / DES-028 / REQ-004 FNC-413) のどこか 1 箇所に **整理された表として存在しない**
- 経路 3 (Skill ツール呼び) は present-findings の文面に登場するが、実装としては経路 2 (Agent ツール起動) と混在しており、設計原則 (fixer のメインコンテキスト消費を抑える) と矛盾する

該当箇所:

- `plugins/forge/skills/review/SKILL.md:491` (軽量経路判定 [FNC-413])
- `plugins/forge/skills/review/SKILL.md:515` (Step 2-A 軽量経路)
- `plugins/forge/skills/review/SKILL.md:538` (Step 2-B fixer 経路)
- `plugins/forge/skills/present-findings/SKILL.md:356` (修正実行時の経路分岐 [FNC-413])
- `plugins/forge/skills/present-findings/SKILL.md:407` (一括修正の軽量経路判定)

### 2.7 旧 perspective 並列起動仕様の残存

現在の `/forge:review` は reviewer 1 起動原則・`review_packet`・`review_<種別>.md` に寄せているが、旧 perspective 並列起動仕様が複数文書に残っている。

> **優先度 [重要]**: `docs/readme/forge/guide_review_ja.md` はユーザーが直接読む文書であり、内部仕様より優先度が高い。本要件の修正範囲が大きい場合、本節 (旧 perspective 文書整理) は **独立 PR として先行可能** (破壊的変更を含まない機械的な置換が中心)。

該当箇所:

- `plugins/forge/docs/session_format.md:57, 508, 807, 814, 816, 834`
- `docs/readme/forge/guide_review.md:50, 54, 123`
- `docs/readme/forge/guide_review_ja.md:50, 54, 123`
- `docs/specs/forge/design/DES-015_review_workflow_design.md:65, 69, 130, 132, 141, 221, 251, 259`
- `docs/specs/forge/design/DES-021_review_perspective_split_design.md:24, 129, 148, 172, 252, 346`
- `docs/specs/forge/design/DES-011_session_management_design.md:384`

### 2.8 同型不具合として除外したもの

以下は `Agent ツールで並列起動` の記載があるが、呼び出し元 SKILL の `allowed-tools` に `Agent` があり、専用の収集 agent / executor を prompt で直接起動する設計に見えるため、本要件の主問題からは除外する:

- `plugins/forge/skills/start-design/SKILL.md`
- `plugins/forge/skills/start-plan/SKILL.md`
- `plugins/forge/skills/start-implement/SKILL.md`
- `plugins/forge/skills/start-requirements/docs/requirements_reverse_engineering_workflow.md`

ただし、これらも「Agent prompt が自己完結しているか」「SKILL.md を読ませる前提になっていないか」は別途軽く確認してよい。

---

## 3. 起動経路の定義文書の不在 (根本原因)

本要件で扱う混乱の根本原因は、**「subagent」「fork 型 SKILL」「Skill ツール呼び」「Agent ツール起動」「Bash 経由 subprocess」を 1 箇所で定義した文書がない** こと。各文書に散発的に記述されているが、定義として集約されていない。

> **優先度 [重要・先行可能]**: 定義文書の追加は **方針選定 (A / B-2) と独立** に進めてよい。配置先と内容が確定すれば本要件の他項目を待たずに着手・PR 化可能であり、後続作業 (SKILL.md 修正 / 設計書改訂) は **本定義文書を参照する形で書ける** ようになるため、先行 PR 化が望ましい。`§2.7` の旧 perspective 文書整理と同じく「破壊的変更を含まない独立 PR」に分類する。

### 3.1 文書の性質 — 「定義文書」というカテゴリ

本文書は以下のいずれにも該当しない、**新規カテゴリ「定義文書」** として位置付ける:

| カテゴリ               | 性質                             | 該当否              |
| ---------------------- | -------------------------------- | ------------------- |
| 仕様 (specs)           | WHY / 設計判断 / 「こうする」    | ❌ WHY を述べない   |
| ルール (rules)         | HOW / 規約 / 「こう書け」        | △ 規約は派生する    |
| フォーマット           | テンプレート                     | ❌ テンプレではない |
| **定義 (definitions)** | **基盤 / 分類 / 「これは何か」** | ✅ **本文書はこれ** |

> 「正しく動作させるための必須ルールのための基盤」であり、ルール・仕様・フォーマットすべてが依拠する。ある意味フォーマットに近いが、テンプレートではなく **概念の分類定義** を提供する。

### 3.2 配置先 [確定]

**配置先**: `docs/rules/skill_launch_paths_definitions.md` (rules 直下、ファイル名で「定義」を明示)

#### 採用理由

- 既存の `docs/rules/` 配下で完結し、新規ディレクトリ不要
- `/query-rules` で自動ヒット (SKILL 作成者の参照導線にそのまま乗る)
- 既存の `skill_authoring_notes.md` と同階層で並ぶため、執筆者の視認性が高い
- ファイル名のサフィックス `_definitions` で「定義文書」性質を明示

#### 不採用とした候補と理由

| 候補                                                                        | 不採用理由                                                                                                                                                                                                                                         |
| --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs/rules/skill_authoring_notes.md` への節追加                            | 節タイトル (fork 型 / 継承型 SKILL の判別) との射程不整合。「定義」と「執筆規約」の分離が崩れる                                                                                                                                                    |
| `docs/specs/common/design/COMMON-DES-001` への節追加                        | 設計判断 (WHY) 文書であり「定義」とは性質が異なる。`/query-rules` 検索の導線にない                                                                                                                                                                 |
| `docs/definitions/skill_launch_paths.md` (新規ディレクトリ + 新規 doc_type) | `.doc_structure.yaml` への登録のみでは済まず、関連 script (`classify_dirs.py` / setup-doc-structure / query-rules / query-specs / query-db-rules / query-db-specs / 関連テスト) の改修が広く波及する。本要件のスコープ外。将来課題とする (TBD-006) |

> **将来検討 (TBD-006)**: 定義文書が増えた場合、`docs/definitions/` ディレクトリへの分離 + `.doc_structure.yaml` の独立 `doc_type` 化 (`definition`) を検討する。今回は **rules 直下で先行運用** し、定義文書の数・性質が増えてから昇格判断する。

### 3.3 文書の最低限の内容

```
起動経路:
  - Skill ツール (継承型 SKILL を呼ぶ)        ← 親 context を消費。SKILL.md は親が直接 Read
  - Skill ツール (fork 型 SKILL を呼ぶ)        ← 別 context が起動。SKILL.md は fork 先が Read
  - Agent ツール (general-purpose 等を起動)    ← サブエージェント (Task) を起動。prompt は呼び出し元が構成
  - Bash 経由 (codex exec 等の subprocess)     ← Claude Code の外で動く subprocess

「subagent」の用法統一:
  - SKILL.md / 設計書では「subagent」単独使用を避ける
  - fork 型 SKILL の隔離 context を指す場合 → 「fork 型 SKILL」と書く
  - Agent ツールで立てたサブエージェントを指す場合 → 「Agent サブエージェント」または「Task サブエージェント」と書く

よくある誤読 (Issue #32 系):
  - Agent ツールの subagent_type に Skill 名 (/forge:fixer 等) は指定できない
  - subagent_type の値域は general-purpose / Explore / Plan / カスタム agent 名
  - prompt 内の /forge:fixer 表記は「fixer のロールを演じさせる prompt 表現」であり、起動方式の指定ではない
```

### 3.4 `skill_authoring_notes.md` 該当節の改修 (先行 PR 内で同時実施)

定義文書を別出しにすることに伴い、`docs/rules/skill_authoring_notes.md` の **「fork 型 / 継承型 SKILL の判別と多重防御」節 (L59-)** を以下のように改修する:

- 節冒頭に「用語と起動経路の定義は `docs/rules/skill_launch_paths_definitions.md` を参照」の 1 行を挿入
- L70 引用ボックス (「subagent という言葉は曖昧...」) を **削除** し、定義文書へのリンクに置換
- L65-68 の表 (継承型 / fork 型の比較) は SSoT を **定義文書側** に置き、本文書はリンク参照に切り替える (重複防止)
- 「fork 型 / 継承型」固有の規約 (フィールド・必須事項・多重防御の層・誤解の訂正) は本文書に残す (執筆規約として機能するため)

> **責務分担の再確認**: `skill_authoring_notes.md` は SKILL **作成規約** に絞り、概念定義は新規定義文書に移譲する。両者の SSoT を分離する。

---

## 4. 機能要件

### FNC-S001: 起動契約の概念分離 [MANDATORY]

各 SKILL.md および設計書において、以下 3 概念が混同されていないこと:

- `Skill ツールで呼ぶ` (継承型 / fork 型を区別)
- `Agent ツールで起動する` (general-purpose / Explore / Plan / カスタム)
- `context: fork` (SKILL frontmatter による隔離 context)

### FNC-S002: 起動責務の単一箇所集約 [MANDATORY]

`reviewer`, `evaluator`, `fixer`, `present-findings`, `review` の起動責務が **1 箇所** に整理されていること。具体的には方針 A (§6) を採るなら orchestrator (`review/SKILL.md`) に集約する。

### FNC-S003: Agent prompt の自己完結性 [MANDATORY]

Agent prompt として起動する場合、対象 SKILL.md を読む必要があるなら呼び出し元 prompt に **明示** されていること。現状 reviewer のみ「SKILL.md を Read せよ」が明示されているが、**evaluator / fixer にも同様の明示を追加** する。

### FNC-S004: SKILL.md 側の文言整理 [MANDATORY]

起動される側 SKILL.md には:

- 「自分が同名の subagent を新規起動する」ように読める記述が **ない** こと
- 冒頭に「Agent サブエージェント内で読まれる手順書」または「Skill ツール呼び (継承型) で読まれる手順書」のいずれかが **明示** されていること

### FNC-S005: allowed-tools の整合 [MANDATORY]

`allowed-tools` に `Agent` がない SKILL が「Agent ツールで起動する」と書いていないこと。allowlist は「承認なしで使える」許可リストであり物理禁止ではないが、契約と allowed-tools の食い違いを解消する。

### FNC-S006: 旧 perspective 仕様の整合 [MANDATORY]

旧 `review_{perspective}.md` / perspective 並列起動前提が、現行仕様で obsolete なら obsolete と明記されるか、現行仕様 (`review_<種別>.md` / reviewer 1 起動原則) へ更新されていること。

### FNC-S007: 軽量経路 (FNC-413) 含む経路分岐の単一表 [MANDATORY]

軽量経路 (FNC-413) を含む修正経路 3 種 (orchestrator 直接 / Agent ツール起動 / Skill ツール呼び) の分岐条件・責務境界が **1 箇所の表** で整理されていること。最有力候補は `docs/specs/forge/design/DES-015_review_workflow_design.md` への追記。

### FNC-S008: 定義文書の追加 [MANDATORY]

新規定義文書 `docs/rules/skill_launch_paths_definitions.md` が追加されており、以下を満たすこと:

- §3.3 の最低限の内容 (起動経路 4 種 / 「subagent」用法統一 / Issue #32 系誤読の説明) を含む
- 文書冒頭で「これは定義文書である。仕様・ルール・フォーマットの基盤として、これらに依拠して書かれる」と性質を明示する
- 既存の `skill_authoring_notes.md` / `COMMON-DES-001` / 各 SKILL.md / 設計書から **本文書を参照する形** で記述されている (定義の二重管理を避ける)

> **配置先の選択理由は §3.2 参照**。`docs/rules/` 配下のファイル名サフィックス `_definitions` で性質を示す。

### FNC-S008a: skill_authoring_notes.md 該当節の改修 [MANDATORY]

`docs/rules/skill_authoring_notes.md` の **「fork 型 / 継承型 SKILL の判別と多重防御」節 (L59-)** が以下を満たすこと:

- 節冒頭に「用語と起動経路の定義は `docs/rules/skill_launch_paths_definitions.md` を参照」の 1 行が挿入されている
- L70 の引用ボックス (「subagent という言葉は曖昧...」) が **削除** され、定義文書へのリンクに置換されている
- L65-68 の「継承型 / fork 型」の表は定義文書側を SSoT とし、本文書はリンク参照に切り替えられている
- 「fork 型 / 継承型」の **作成規約** (フィールド・必須事項・多重防御の層・誤解の訂正) は本文書に残されている

### FNC-S009: prompt 内 slash command 表記の起動経路明示 [MANDATORY]

Issue #32 の再発防止として、SKILL.md または設計書内で **Agent prompt として展開されるテキスト** に `/forge:<skill>` / `/anvil:<skill>` 等の slash command 表記を含める場合、**同じ段落または直前のテキストに** 以下のいずれかを明示する:

- 「Agent ツール (general-purpose) で起動する」(= subagent_type は general-purpose 固定、slash command は **ロール演技用の表記**)
- 「Skill ツールで呼び出す」(= 親 context で Skill ツール経由で実行)
- 「Bash 経由で起動する」(= subprocess として実行)

明示なく slash command 表記単独で書かない。Issue #32 のように `subagent_type: "forge:fixer"` のような誤指定を AI が試みる経路を文書側で塞ぐため。

> **背景**: Claude Code の Agent ツールでは `subagent_type` は `general-purpose` / `Explore` / `Plan` / カスタム agent 名のいずれかであり、Skill 名 (slash command 名) は **指定できない**。`/forge:fixer` のような表記はあくまで「prompt 内で fixer のロールを演じさせる際の表現」であり、subagent タイプではない。

### FNC-S010: COMMON-DES-001 §4 改訂を許容する [MANDATORY]

本要件の検討において、`COMMON-DES-001 §4` (fork 型 SKILL 一覧) は **固定制約として扱わない**。reviewer / evaluator / fixer / present-findings のいずれかを fork 型 SKILL 化することが設計上有利と判断された場合、`COMMON-DES-001 §4.3` のリスト変更手順に沿って §4 を改訂してよい。

§4.3 のリスト変更手順 (本要件適用時の遵守事項):

1. §3.2 の判断基準 (具体的な実害 / 複数の独立タスクからの呼び出し / 親 context 肥大化) に該当することを **本要件または別 ADR で明示** する
2. §4 のリストを更新し、**fork 採用根拠** を明記する
3. SKILL.md を修正 (frontmatter / Role / 引数解釈ガード)
4. §7.1 静的検証の対象に追加する (本要件 §5 静的テストと整合)

> **意図**: 既存制約に縛られず、最適な設計判断を選べる余地を残す。一方で「fork 型を雑に増やさない」§3 のデフォルト継承型方針は維持する。fork 型化は **継承型では成立しない実害・必要性が示せた場合に限る** (§3.2)。

---

## 5. 再発防止策 (静的テスト) [MANDATORY]

`CLAUDE.md` の「同じ種類のミスを繰り返さない / 注意ではなく再発防止策を優先する」に従い、**静的検証テストを追加** する。`tests/common/` または `tests/forge/` に追加し、`python3 -m unittest discover -s tests` で実行可能とする。

### TEST-S001: Agent 言及と allowed-tools の整合性テスト

SKILL.md 本文に `Agent ツール` / `subagent を起動` / `Agent (Task)` 等の語があれば、frontmatter の `allowed-tools` に `Agent` が含まれることを要求する。

### TEST-S002: Skill 呼び出しと allowed-tools の整合性テスト

SKILL.md 本文に `/forge:<skill>` または `/anvil:<skill>` の Skill 呼び出し記述があれば、frontmatter の `allowed-tools` に `Skill` が含まれることを要求する。

### TEST-S003: 旧 perspective 文字列の完全削除テスト

`review_{perspective}.md` 文字列が `plugins/forge/` 配下と `docs/readme/forge/` 配下の Markdown に存在しないこと。

> **例外**: 「旧体系」「廃止済み」等の文脈で歴史的記述として残す場合は、当該段落に `[OBSOLETE]` マーカーを付ける運用とし、テスト側で除外可能にする。

### TEST-S004: 用語混用防止テスト [任意]

SKILL.md 内で `subagent` が単独で使われている箇所を列挙する (warning 相当)。`fork 型 SKILL` または `Agent サブエージェント` への置換を促す。

### TEST-S005: prompt 内 slash command 表記の起動経路明示テスト (Issue #32 再発防止)

Agent prompt として展開されるテキストブロック (`` ``` `` で囲まれた prompt 例や Agent 起動セクション内) に `/forge:<skill>` / `/anvil:<skill>` 表記がある場合、**同一テキストブロック内または直前段落** に以下のいずれかの明示があることを要求する:

- `Agent ツール` (general-purpose / Explore / Plan / カスタム)
- `Skill ツール` (継承型 / fork 型)
- `Bash 経由` (subprocess)

検出のヒューリスティクス例:

- prompt ブロック内に `/forge:fixer --batch` 等の表記がある
- かつ直近 N 行 (例: 5 行) に `Agent ツール` / `Skill ツール` / `Bash` のいずれかの文字列がない
- → 違反としてエラー報告

> **本テストは Issue #32 の AI 誤読 (subagent_type に Skill 名を指定) を文書側で塞ぐための具体的検証**。FNC-S009 と対応する。

---

## 6. 修正方針の評価

> **前提**: §1.3 / FNC-S010 に従い、`COMMON-DES-001 §4` (fork 型 SKILL 一覧) は固定制約ではなく、必要なら §4.3 手順で改訂してよい。以下の方針評価はこの前提に立つ。

### 方針一覧

| 方針 | 起動経路                                                      | context 消費 | §4 (fork 型リスト) 改訂 | 推奨度                                   |
| ---- | ------------------------------------------------------------- | ------------ | ----------------------- | ---------------------------------------- |
| A    | Agent ツール (general-purpose) で SKILL.md を Read させて起動 | 消費しない   | 不要                    | **第 1 推奨**                            |
| B-1  | Skill ツール (継承型) で呼ぶ                                  | **消費する** | 不要                    | 非推奨 (※)                               |
| B-2  | Skill ツール (fork 型) で呼ぶ                                 | 消費しない   | **§4 追加が必要**       | 第 2 候補                                |
| C    | Bash 経由で subprocess 起動                                   | 消費しない   | 不要                    | reviewer の Codex エンジン以外では非該当 |

※ B-1 は fixer の「メインコンテキスト消費を抑える」設計原則と衝突するため非推奨。

### 方針 A: `review` orchestrator が Agent 起動を担当する [第 1 推奨]

現行実装に最も近く、変更コストが小さい。

- `review` 側に reviewer / evaluator / fixer の Agent prompt を構成する責務を寄せる
- Agent prompt の冒頭に、対象 SKILL.md を Read して従うか、または必要な workflow を prompt 内に完全展開するかを統一する
- **現状 reviewer のみ「SKILL.md を Read せよ」が明示されているが、evaluator / fixer にも同様の明示を追加** する (FNC-S003)
- 起動される側 SKILL.md に「自分が同名の subagent を新規起動する」ように読める文言を削除し、**「Agent サブエージェント内で読まれる手順書」** であることを冒頭で明示する
- 起動される側 SKILL.md は「Agent prompt として読まれる実行手順」または「Skill ツールで呼ばれる実行手順」のどちらかを明記する

**メリット**:

- 既存実装の変更が小さい
- §4 改訂不要
- Issue #32 の誤読源 (prompt 内 slash command 表記) は FNC-S009 / TEST-S005 で対処済み

**デメリット**:

- 起動経路の責務が `review/SKILL.md` に集中するため、orchestrator が肥大化しやすい
- 起動される側 SKILL.md と Agent prompt の整合 (SKILL.md Read 指示 or workflow 完全展開) を文書側で保証する必要がある

### 方針 B-1: Skill ツール (継承型) で呼ぶ [非推奨]

設計としては明快だが、**現状の設計原則 (fixer の「メインコンテキスト消費を抑える」) と直接衝突する**。継承型 Skill ツール呼びは親 context を消費するため、本原則を維持するなら採用できない。

- 採用するなら fixer の設計原則を改訂する必要があり、別 ADR / 別 PR で context 消費許容範囲を再判断するべき
- COMMON-DES-001 §4 は **fork 型** SKILL のリストであり、**継承型 Skill ツール呼びには §4 更新は不要**
- 入力契約は「呼び出し元が何を渡すか」と「呼び出される側がどう解釈するか」に分けて明文化する
- present-findings 内のユーザー対話・確認を伴う処理など、親 context を活用したい場面では合理性が出る場面もあるが、現状の fixer はこれに該当しない

### 方針 B-2: Skill ツール (fork 型) で呼ぶ [第 2 候補。§4 改訂を伴う]

`/forge:fixer` / `/forge:reviewer` / `/forge:evaluator` を fork 型 SKILL 化し、Skill ツール経由で呼ぶ。fork 境界で親 context を遮断するため、**「メインコンテキスト消費を抑える」原則とは整合する**。

採用前提:

- COMMON-DES-001 §3.2 の判断基準 (具体的実害 / 複数の独立タスクからの呼び出し / 親 context 肥大化) のいずれかに該当することを示す
- COMMON-DES-001 §4 のリストに該当 SKILL を追加し、fork 採用根拠を明記する (FNC-S010 / §4.3 手順)
- fork 境界で `$ARGUMENTS` 経由の親タスク漏洩を防ぐ「引数解釈ガード」を SKILL.md 本文に明記する (COMMON-DES-001 §4.1 / ADR-002 §C)

**メリット**:

- 起動経路が「Skill ツール呼び」1 種に統一でき、概念的に明快
- 軽量経路 (FNC-413) との分岐表が単純になる (orchestrator 直接 / Skill ツール呼びの 2 種に縮約可能)
- 入力契約が SKILL.md 単独で完結 (Agent prompt の自己完結性確保が不要 = FNC-S003 が縮退)
- Issue #32 のような「subagent_type に Skill 名を指定」誤読は **構造的に解消** (Skill ツールは subagent_type を取らない)

**デメリット**:

- fork 型は SKILL.md + `$ARGUMENTS` を毎回入力として読み込むため、親 context にある情報を args で再供給すると **二重コスト** (COMMON-DES-001 §3.1)
- 「同一プラグイン内で fork → fork」となる二重 fork 経路の有無を検証する必要がある (§3.1 のデメリット)
- §4 リスト更新・SKILL.md 改訂・静的検証追加の作業量が方針 A より大きい
- fixer の「修正後に親 context へ戻る情報」が return 値のみに制限されるため、修正サマリーの設計を見直す必要がある

### 方針 C: Bash 経由 subprocess 起動

reviewer の Codex エンジン (`run_review_engine.sh` 経由) が該当する既存経路。fixer / evaluator / present-findings に同経路を採用する合理性は本要件のスコープでは見当たらないが、用語マップ (FNC-S008) で経路の 1 種として整理対象に含める。

### 方針選定の指針

- 段階移行を優先するなら **方針 A** を採用し、本要件のスコープを「文書整理 + 静的テスト追加」に閉じる
- 設計の明快さを優先するなら **方針 B-2** を採用し、§4 改訂を含めた設計フェーズで詳細検討する
- B-2 を採るかは設計フェーズで判断する。本要件は **「両方の選択肢を許容する」** ことを §1.3 / FNC-S010 で保証する

### 軽量経路 (FNC-413) の取り扱い

修正経路 (orchestrator 直接 / Agent ツール起動 / Skill ツール呼び (継承型 or fork 型) / Bash subprocess) の分岐条件・責務境界を **1 箇所に整理された表** で記述する。最有力候補は `docs/specs/forge/design/DES-015_review_workflow_design.md` への追記 (FNC-S007)。方針選定 (A / B-2) によって表に載る経路の組み合わせが変わる。

---

## 7. 受け入れ基準

### 7.1 機能要件 (FNC-S001 〜 FNC-S010, FNC-S008a を含む)

- §4 の機能要件すべてを満たしていること
- 新規定義文書 `docs/rules/skill_launch_paths_definitions.md` が追加されている (FNC-S008)
- `docs/rules/skill_authoring_notes.md` の該当節が定義文書を参照する形に改修されている (FNC-S008a)
- `.doc_structure.yaml` の変更を **伴わない** こと (rules 直下に配置するため、scripts / query-* 系 SKILL への波及をゼロに保つ)

### 7.2 静的検証 (TEST-S001 〜 TEST-S005)

- §5 のテストが `tests/` 配下に追加され、`python3 -m unittest discover -s tests` で pass すること

### 7.3 機械的検証

- `dprint check` が pass

### 7.4 方針 B-2 採用時の追加条件 [条件付き]

設計フェーズで方針 B-2 (fork 型 Skill 呼び) を採用した場合、以下を満たすこと:

- COMMON-DES-001 §4 のリストに対象 SKILL (fixer / reviewer / evaluator / present-findings のうち fork 化したもの) が **fork 採用根拠つきで追加** されている
- 対象 SKILL.md に `context: fork` / `agent:` / 引数解釈ガード / 否定的制約 (Edit/Write を使わない等の該当文言) が明記されている
- COMMON-DES-001 §7.1 の静的検証 (fork 型 frontmatter 検証 / Role 制約文言検証) の対象に追加されている
- 本要件 TEST-S001 / S002 / S005 と矛盾しない (例: fork 型 SKILL 内で Agent ツール起動を行うなら allowed-tools との整合を取る)

---

## 8. 分割案 (実装着手時の参考)

修正範囲が大きい場合は、以下に分割してよい。

### 先行 PR (方針選定と独立に着手可能) [推奨]

以下 2 つは破壊的変更を含まず、方針選定 (A / B-2) を待たずに先行 PR 化できる。本要件の後続作業は **これらの成果物を参照する形** で書ける:

| #  | 範囲                                                                                                                                  | 依存 |
| -- | ------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| P1 | **定義文書の追加** (`docs/rules/skill_launch_paths_definitions.md`) + skill_authoring_notes.md 該当節改修 (§3 / FNC-S008 / FNC-S008a) | なし |
| P2 | **旧 perspective 並列起動仕様の文書整理** (§2.7 / FNC-S006)。破壊的変更を含まない機械的置換                                           | なし |

### 方針 A を採用する場合

| # | 範囲                                                                                              | 依存                  |
| - | ------------------------------------------------------------------------------------------------- | --------------------- |
| 1 | review 系 SKILL の起動契約整理 (方針 A の適用 + evaluator / fixer への「SKILL.md Read 指示」追加) | P1 完了後が望ましい   |
| 2 | present-findings / fixer の Skill vs Agent 経路整理 + 軽量経路 (FNC-413) の分岐表整理             | 1 完了後              |
| 3 | 静的検証テストの追加 (TEST-S001 〜 S005)                                                          | 1〜2 + P1 + P2 完了後 |

### 方針 B-2 を採用する場合 (§4 改訂を伴う)

| # | 範囲                                                                                                     | 依存                  |
| - | -------------------------------------------------------------------------------------------------------- | --------------------- |
| 1 | fork 採用根拠の文書化 (本要件への追記 or 別 ADR 起票)                                                    | なし                  |
| 2 | COMMON-DES-001 §4 リスト改訂 (対象 SKILL を fork 採用根拠つきで追加)                                     | 1 完了後              |
| 3 | 対象 SKILL.md の改訂 (`context: fork` / `agent:` / 引数解釈ガード / 否定的制約 / 自己再帰禁止文言の追加) | 2 完了後              |
| 4 | review / present-findings の Skill ツール呼び出しへの切り替え + 軽量経路 (FNC-413) の分岐表整理          | 3 完了後              |
| 5 | 静的検証テストの追加 (本要件 §5 + COMMON-DES-001 §7.1 拡張)                                              | 1〜4 + P1 + P2 完了後 |

> **P1 / P2 は両方針で共通の先行作業**。本要件全体の方針選定 (TBD-004) を待つ必要はない。

---

## 9. 未確定事項

| ID          | 内容                                                                                                                                                                                                                                                                                                                                       | 期限                        |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------- |
| ID          | 内容                                                                                                                                                                                                                                                                                                                                       | 期限                        |
| -------     | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------                                                                              | --------------------------  |
| ~~TBD-001~~ | ~~用語マップ文書の配置先~~ → **解消** (§3.2 で `docs/rules/skill_launch_paths_definitions.md` に確定)                                                                                                                                                                                                                                      | -                           |
| TBD-002     | TEST-S001 / S002 の判定ロジック (正規表現ベースか AST ベースか)                                                                                                                                                                                                                                                                            | 設計フェーズで決定          |
| TBD-003     | TEST-S003 の `[OBSOLETE]` マーカー運用 (どこに付与するか・テスト除外条件)                                                                                                                                                                                                                                                                  | 設計フェーズで決定          |
| TBD-004     | 方針選定 (A / B-2)。B-2 採用時は対象 SKILL の fork 採用根拠 (COMMON-DES-001 §3.2) を本要件または別 ADR に追記し、§4 リストを改訂する                                                                                                                                                                                                       | 設計フェーズで決定          |
| TBD-005     | TEST-S005 の検出ヒューリスティクス (近傍行数 N の値、テキストブロックの境界判定、誤検知許容度)                                                                                                                                                                                                                                             | 設計フェーズで決定          |
| TBD-006     | 「定義文書」を独立カテゴリに昇格させる判断。`docs/definitions/` ディレクトリ新設 + `.doc_structure.yaml` 独立 doc_type (`definition`) 化を伴う。影響範囲は `classify_dirs.py` / `setup-doc-structure` / `query-rules` / `query-specs` / `query-db-rules` / `query-db-specs` / 関連テスト。定義文書が **2 件以上に増えた時点** で再検討する | 将来 (定義文書が増えたとき) |

---

## 10. 関連事項 (別 Issue 候補)

本要件の主題からは外れるが、調査中に判明した事項:

- AI 専用スキル (evaluator / reviewer / fixer / present-findings) は `user-invocable: false` だが `disable-model-invocation` が未設定。description に「`/forge:review` から呼び出される」と明記されているため、Claude が自動呼び出しする経路は理論上残っている。`docs/rules/skill_authoring_notes.md` L55「副作用ある操作 → `disable-model-invocation: true`」推奨と照らし、別 Issue で検討する余地あり

---

## 11. 関連文書

| 種別   | パス                                                                      | 関係                                                                                       |
| ------ | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Issue  | [#89](https://github.com/BlueEventHorizon/bw-cc-plugins/issues/89)        | 本要件の起点 (起動契約整理の提起)                                                          |
| Issue  | [#32](https://github.com/BlueEventHorizon/bw-cc-plugins/issues/32)        | AI 自身が `subagent_type: "forge:fixer"` と誤指定した実害事例。FNC-S009 / TEST-S005 の動機 |
| ルール | `docs/rules/skill_authoring_notes.md`                                     | SKILL.md frontmatter / 構造の規約                                                          |
| 設計書 | `docs/specs/common/design/COMMON-DES-001_skill_base_design.md`            | SKILL 実行モデル・fork 型リスト                                                            |
| 設計書 | `docs/specs/forge/design/DES-015_review_workflow_design.md`               | review ワークフロー全体                                                                    |
| 設計書 | `docs/specs/forge/design/DES-021_review_perspective_split_design.md`      | 旧 perspective 並列起動設計 (要 obsolete 化)                                               |
| 設計書 | `docs/specs/forge/design/DES-028_review_policy_design.md`                 | review_packet / 1 起動原則                                                                 |
| 要件   | `docs/specs/forge/requirements/REQ-004_review_policy.md`                  | FNC-411 / FNC-412 / FNC-413 の出典                                                         |
| ADR    | `docs/specs/doc-advisor/design/ADR-002_query_skill_subagent_isolation.md` | fork 型採用根拠 (COMMON-DES-001 §4 経由)                                                   |

---

## 変更履歴

| 日付       | 変更者  | 内容                                                                                                                                                                                                                                                                                                                                                                     |
| ---------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 2026-05-24 | k2moons | 初版作成。Issue #89 の議論結果を要件として整理。方針 A 推奨・静的テスト 4 種・用語マップ追加を明文化                                                                                                                                                                                                                                                                     |
| 2026-05-24 | k2moons | Issue #32 (AI が `subagent_type: "forge:fixer"` と誤指定した実害事例) を取り込み。FNC-S009 / TEST-S005 追加。起点 Issue に #32 を併記                                                                                                                                                                                                                                    |
| 2026-05-24 | k2moons | COMMON-DES-001 §4 (fork 型 SKILL 一覧) を固定制約から外す方針を反映。FNC-S010 追加。§6 方針評価を A / B-1 / B-2 / C の 4 区分に再構成し、方針 B-2 (fork 型 Skill 呼び) を第 2 候補として明文化。§7.4 / §8 方針 B-2 採用時の分割案 / TBD-004・TBD-005 を追加                                                                                                              |
| 2026-05-24 | k2moons | §3 用語マップを「先行 PR 化可能」と明示。§3.2 配置先選定の判断材料を追加。§8 分割案に「先行 PR (P1 / P2)」セクションを新設し、用語マップ (P1) と旧 perspective 整理 (P2) を方針選定と独立に先行可能と明文化。TBD-001 を「先行 PR レビューで決定」に変更                                                                                                                  |
| 2026-05-24 | k2moons | §3 を「用語マップ」から「定義文書」概念に再構築。§3.1 で「定義 (definitions)」を新規カテゴリとして位置付け。§3.2 で配置先を `docs/rules/skill_launch_paths_definitions.md` に確定 (候補 C)。`.doc_structure.yaml` 変更を伴う候補 D は将来課題 (TBD-006) として残す。FNC-S008 を更新し FNC-S008a (skill_authoring_notes.md 該当節改修) を新設。TBD-001 解消・TBD-006 追加 |
