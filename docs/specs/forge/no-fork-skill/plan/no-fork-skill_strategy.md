# no-fork-skill 実装戦略

## 1. 目標

REQ-006 / DES-032 に基づき、fork 型 SKILL (reviewer / evaluator / fixer) を `plugins/forge/agents/<name>.md` のカスタム Agent へ置き換える。session_dir のファイル契約は維持し、`/forge:review` の挙動を変えずに起動経路だけを差し替える。

## 2. 段階区分（フィーチャー単位）

DES-032 §3.7 / §11 の F-1〜F-5 に対応。本計画書は F-1 完了後の F-2 〜 F-5 を扱う:

| 段階 | フィーチャーブランチ              | 範囲                                                                                   |
| ---- | --------------------------------- | -------------------------------------------------------------------------------------- |
| F-1  | feature/no-fork-skill-adr (本 PR) | REQ-006 + DES-032 作成（完了済み）                                                     |
| F-2  | feature/no-fork-reviewer          | reviewer Agent 化 + 静的検証テスト 2 種新設 + review/SKILL.md Phase 3 改訂             |
| F-3  | feature/no-fork-evaluator         | evaluator Agent 化 + review/SKILL.md Phase 5 改訂                                      |
| F-4  | feature/no-fork-fixer             | fixer Agent 化 + 安全境界テスト + review/SKILL.md Phase 6 改訂 + present-findings 改訂 |
| F-5  | feature/no-fork-cleanup           | 設計書 / ルール文書改訂 + 旧 SKILL.md と旧テスト削除 + 全テスト pass + 最終 E2E        |

## 3. 各段階の実装フロー

### 3.1 F-2: reviewer Agent 化

**先にテストを書く** (回帰防止):

1. `tests/common/test_no_fork_skill.py` 新設 — 全 SKILL.md frontmatter から `context: fork` が消えていることを検証。**F-2 段階では reviewer 1 件だけ消える状態を許容するため、検証対象に「fork が残っていない」を assert する場合は段階的に該当 SKILL を allowlist に追加する形にする。最終段階 F-5 で allowlist を空にする**
2. `tests/forge/agents/test_agent_frontmatter.py` 新設 — `plugins/forge/agents/` の各 .md frontmatter (name / description / tools / model) 妥当性検証

次に Agent と orchestrator を書く:

3. `plugins/forge/agents/reviewer.md` 作成 — DES-032 §3.1 の `tools: Read, Write, Bash` allowlist で frontmatter を組む。system prompt には DES-029 §6.2 の Role 制約 + reviewer/SKILL.md の既存ロジック (engine 分岐 / 1 起動原則 / output_path に `review_<種別>.md` を Write) を継承
4. `plugins/forge/skills/review/SKILL.md` Phase 3 (Step 2) の `/forge:reviewer` を Skill ツール (fork) で起動する記述を、Agent ツール (`subagent_type: forge:reviewer`) で起動する記述に書き換え
5. F-2 E2E: `/forge:review code --files <小さなファイル> --auto-critical` が完走し `review_code.md` が生成されること

### 3.2 F-3: evaluator Agent 化

1. `plugins/forge/agents/evaluator.md` 作成 — `tools: Read, Bash` allowlist。system prompt には 5 観点精査 + `apply_eval.py` 経由の plan.yaml 直接更新ロジックを記述
2. `plugins/forge/skills/review/SKILL.md` Phase 5 (Step 1) の `/forge:evaluator` 起動を Agent ツールに書き換え
3. F-3 E2E: `/forge:review code --files <小さなファイル> --auto` が完走し plan.yaml の evaluator 判定 (`recommendation`, `auto_fixable`, `reason`) が付与されること

### 3.3 F-4: fixer Agent 化

**先にテストを書く** (安全境界の検証):

1. `tests/forge/agents/test_fixer_safety_prompt.py` 新設 — fixer.md の system prompt に DES-032 §3.5 の 4 制約 (allowlist / 単一 finding / 無関係 refactor 禁止 / 構文検証) が含まれることを検証

次に Agent と orchestrator を書く:

2. `plugins/forge/agents/fixer.md` 作成 — `tools: Read, Edit, Write, Bash` allowlist。system prompt には DES-032 §3.5 の 4 制約を否定形で明記。構文検証 (py_compile / dprint / yaml / json / bash / tomllib) ロジックを含む
3. `plugins/forge/skills/review/SKILL.md` Phase 6 Step 2-B (fixer 経路) を Agent 経由 fixer 経路に書き換え + 修正経路分岐表 (DES-028 §4.5) の文言更新
4. `plugins/forge/skills/present-findings/SKILL.md` の fixer 起動 (--single / --batch) を Agent ツール起動に書き換え。**`--batch` は orchestrator 側の id 単位ループに変換** (DES-032 §3.5.1 単一 finding 起動)
5. F-4 E2E: `/forge:review code --files <小さなファイル> --auto` が finding を 1 件以上自動修正し commit 候補が出ること + 軽量経路 (FNC-413) との分岐が正しく動作すること

### 3.4 F-5: 設計書・ルール・旧ファイル最終クリーンアップ

1. `docs/specs/common/design/COMMON-DES-001_skill_base_design.md` §6 / §3.2 / §8 / §9 改訂 (DES-032 §4.2)
2. `docs/specs/forge/design/DES-029_skill_agent_launch_contract_design.md` 全面改訂 — fork 採用根拠 → Agent 採用根拠
3. `docs/specs/forge/design/DES-015_review_workflow_design.md` 起動経路図 (mermaid) を Agent 起動に追随
4. `docs/specs/forge/design/DES-028_review_policy_design.md` 修正経路分岐表 (FNC-413) を Agent 経由 fixer 経路に書き換え
5. `docs/rules/skill_launch_paths_definitions.md` §1 fork 型 SKILL 項目に「採用しない (廃止)」注記
6. `docs/rules/skill_authoring_notes.md` fork 型関連節 (判別表 / 多重防御 A 層 / fork 型必須事項 / 命名規約 fork 関連) を非推奨化
7. 旧 SKILL.md 削除: `plugins/forge/skills/{reviewer,evaluator,fixer}/SKILL.md`
8. 旧テスト削除: `tests/forge/subagent/test_fork_skill_frontmatter.py` / `tests/forge/subagent/test_fork_skill_call_contract.py`
9. F-5 完了条件: `python3 -m unittest discover -s tests -p 'test_*.py' -v` が全 pass + `/forge:review code --files <小さなファイル> --auto` が最終 E2E で完走

## 4. クロスカット観点

- **reviewer 1 起動原則 (FNC-412)**: Agent 化後も維持。`review/SKILL.md` Phase 3 改訂時に「Agent 1 起動原則」として再宣言する
- **session_dir ファイル契約**: 各段階で `refs.yaml` / `plan.yaml` / `review_<種別>.md` / `patch_result.json` のスキーマ・キー・型を変更しない (DES-032 §3.4)
- **不変条件**: 各段階完了時点で `/forge:review code --auto` が手動 E2E で完走すること。完走しない段階は revert して fix-forward しない (DES-032 §3.7)
- **PR 分離**: 各段階 F-2〜F-5 を独立 PR として `feature/no-fork-{stage}` ブランチで作成 (REQ-006 §5.1)

## 5. リスクと緩和

| リスク                                    | 緩和                                                                                  |
| ----------------------------------------- | ------------------------------------------------------------------------------------- |
| Agent ツールの引数受け渡しが想定と異なる  | F-2 で最初に reviewer Agent を起動し、Agent prompt スキーマを実測してから F-3 へ進む  |
| 旧 SKILL.md と新 Agent が並存する移行期間 | `user-invocable: false` を旧 SKILL.md に維持し、ユーザー直接呼出を防ぐ                |
| fixer allowlist 違反検知の漏れ            | F-4 で `test_fixer_safety_prompt.py` が prompt 内 4 制約の存在を文字列マッチで強制    |
| 旧テスト削除タイミングのミス              | F-5 で旧テストを削除する **直前** に新 `test_no_fork_skill.py` が PASS することを確認 |

## 6. 完了条件

- F-2〜F-5 すべての PR がマージされている
- `python3 -m unittest discover -s tests -p 'test_*.py' -v` が全 pass
- COMMON-DES-001 §6 リストが「fork 型 SKILL は採用しない」へ転換されている
- REQ-006 / DES-032 が `merge` 対象として要件・設計書の正本 (旧 DES-015/028/029) へ反映されたら、本フィーチャー文書 (REQ-006 / DES-032 / `no-fork-skill_strategy.md` / `no-fork-skill_plan.yaml`) を削除する
