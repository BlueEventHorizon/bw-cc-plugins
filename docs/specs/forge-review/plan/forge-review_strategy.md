# forge-review 実装戦略

## アプローチ

**選択**: ボトムアップ + リスク駆動 (混合)

**根拠**:

- DES-028 は「ポリシー差分」と「SKILL/scripts 差分」の 2 系統で構成され、SKILL 側の挙動は principles 側の重大度カタログとグレーゾーン許容範囲を SoT として参照する強い依存関係を持つ (FNC-411 / FNC-402)。先に principles 側の「規範本体」を確定させないと criteria を 3 セクション固定構造に書き換えても severity の参照先が無効になるため、**ポリシー層 → 委譲経路 (refs.yaml/scripts) → SKILL 改修** の順で積み上げる必要がある (ボトムアップ)。
- 一方で、最大の構造リスクは「FNC-412 reviewer 1 起動原則の確立」と「refs.yaml の `perspectives[]` → `review_packet` スキーマ全面置換」であり、これが完了するまでは write_refs.py / write_interpretation.py / merge_evals.py / reviewer SKILL の挙動が同時に壊れる。回帰防止テストを含むこの中核スキーマ変更を **フェーズ 2 で先に潰し**、Issue #68 の再発リスクを早期検出する (リスク駆動)。
- フィーチャースライス的に「種別 1 個だけ E2E で通す」アプローチは、criteria 6 種が等価な置換対象であるため利得が少ない。ボトムアップで全種別を横並びに改修する方が整合性検証コストが低い。
- 既存 `run_review_engine.sh` / DES-022 出力契約 / per-flow orchestrator (DES-013) は温存するため、スケルトン先行は不要。差分対象を限定して既存基盤を流用する。

### 制約となる規約

- **frontmatter 規約 (REQ-004)**: 旧 principles 4 ファイルへの merge は本 feature 全タスク実装完了後の最終ステップに固定する。merge 前は addendum を SoT として criteria/reviewer/evaluator が参照可能になるよう、refs.yaml の `ssot_refs[].doc_path` を一時的に addendum 経路で運用するか、または merge を実装フェーズ末尾に先送りして reviewer 起動を行わない。本戦略では **merge を最終フェーズで実施し、それまでは reviewer の統合テストは「addendum を併読する一時経路」を許容する** 方針とする (タスク化時に明文化)。
- **plan_format**: 計画書は YAML 固定。タスク粒度は 1 Agent 実行で完結する単位 (5〜10 項目 / 1〜3 ファイル)。
- **テスト必須 (implementation_guidelines)**: 改修・新規追加する `plugins/` 配下の Python (write_refs / write_interpretation / merge_evals / findings_parser / findings_renderer / summarize_plan / resolve_review_context / init_session) はすべて unittest 追加または更新の対象。SKILL.md / criteria md / principles md はテキスト規約のためテスト対象外。

---

## フェーズ

### フェーズ 1: ポリシー層の確定 (review_priorities_spec 新設 + addendum 整合確認)

- **目標**: criteria が参照可能な SSOT (重大度カタログ / グレーゾーン許容範囲 / 観点別利用ガイド) を addendum 4 ファイル + 新設 `review_priorities_spec.md` の 5 文書で確定し、criteria 3 セクション固定構造のための「参照先表」を凍結する。SKILL 改修・スクリプト改修の前提となるポリシーの内容ぶれを潰す。
- **スコープ**:
  - `plugins/forge/docs/review_priorities_spec.md` (新設、DES-028 §3.2)
  - `plugins/forge/docs/forge_anti_patterns.md` (空ファイル新設、見出しのみ、DES-028 §3.1)
  - addendum 4 ファイルの整合性確認 (DES-028 §3.5 / 各 addendum の内容は確定済みのためコンテンツ変更なし、SKILL/criteria からの参照経路だけ確認)
  - criteria 6 ファイルの全面置換 (DES-028 §3.3 / §3.4)
- **検証ポイント**:
  - 新設 `review_priorities_spec.md` が固定 5 セクション (優先度定義 / priority と severity の関係 / 除外規定 / create_issue 3 条件 / criteria 構造) を持つ
  - criteria 6 ファイルから `## Perspective:` 見出しが完全に消えている (grep 確認)
  - criteria の SSOT参照表が addendum 4 ファイル + プロジェクト rules を正しく指している (DES-028 §3.4 一致)
  - addendum の merge は **行わない** (フェーズ 5 まで保留)

### フェーズ 2: refs.yaml スキーマ転換 + write_refs/write_interpretation/merge_evals 改修

- **目標**: `perspectives[]` を `review_packet { criteria_path / ssot_refs[] / check_order / severity_source / output_path }` に全面置換し、reviewer 起動を 1 体に絞る構造的基盤を完成させる。Issue #68 再発リスクを最も大きく持つ中核スキーマ変更を早期に潰す。
- **スコープ**:
  - `plugins/forge/scripts/session/write_refs.py` (旧 `_PERSPECTIVE_NAME_RE` / `validate_refs_data` / `build_refs_sections` を置換、新スキーマ検証: `criteria_path` / `output_path` 必須 / `ssot_refs[].priority` ∈ {P1,P2,P3} / `doc_type` ∈ {rules,principles,format} / `output_path` が `review_<種別>.md` 形式)
  - `plugins/forge/scripts/session/write_interpretation.py` (`--perspective` → `--kind`、`review_{perspective}.md` → `review_{kind}.md`、種別の値域 = code/design/requirement/plan/uxui/generic)
  - `plugins/forge/scripts/session/merge_evals.py` (perspective ベース統合 → priority ベース。`recommendation: create_issue` を `should_continue` から除外。`build_perspective_id_map` / `_perspective` / 「perspective 間で判定不一致」reason を撤廃。reviewer 1 起動原則により衝突解決ロジック自体を不要化)
  - `plugins/forge/scripts/review/findings_parser.py` (`priority: P1|P2|P3` 行のパースを追加)
  - `plugins/forge/scripts/review/findings_renderer.py` (priority セクション見出し描画を追加)
  - `plugins/forge/scripts/session/summarize_plan.py` (`create_issue` 状態を `by_status` に追加、`unprocessed_total` から除外)
  - 上記すべてに対する unittest 追加・更新 (`tests/forge/scripts/` / `tests/forge/review/`)
- **検証ポイント**:
  - 既存 unittest が新スキーマで通る (旧 `perspectives[]` テストは新スキーマテストに書き換え)
  - 新スキーマ refs.yaml を受け取って書き出し → 再パースが冪等
  - `create_issue` を含む eval を merge_evals が正しく扱う (should_continue 計算から除外、 by_status に出現)
  - findings_parser が priority と severity を独立に抽出できる
  - **回帰防止**: 旧スキーマ refs.yaml (perspectives[] あり) を渡したとき write_refs が拒否する (バリデーションエラー)

### フェーズ 3: SKILL 改修 (review / reviewer / evaluator / present-findings / fixer)

- **目標**: フェーズ 2 で確定したスキーマと criteria の上で SKILL 5 つを書き換え、CLI 引数体系 (`--diff` / `--files` / `--interactive` / `--auto-critical` / `--auto`) と 1 起動原則 (FNC-412) を確立する。テンプレ・関連スクリプトも同期する。
- **スコープ**:
  - `plugins/forge/skills/review/SKILL.md` (Phase 1 引数解析 / early validation / target_files 過多時の AskUserQuestion / Phase 2 入力解決 / Phase 3 review_packet 構築 / Phase 4 reviewer 1 起動 / Phase 5 介入軸分岐 / Phase 5 終了サマリ二軸表示)
  - `plugins/forge/skills/review/scripts/resolve_review_context.py` (`--files` バイパス経路、`--diff` を「現ブランチ未 commit 差分」に確定)
  - `plugins/forge/skills/review/scripts/init_session.py` (`--files` を session.yaml に保存、`--section` 受理経路を完全削除)
  - `plugins/forge/skills/reviewer/SKILL.md` (1 起動原則 / `review_packet` 入力契約 / P1→P2→P3 順次評価 / severity を principles 側カタログから取得 / 出力ファイル名 `review_<種別>.md` / finding に `priority` + `severity_source` 追加)
  - `plugins/forge/skills/reviewer/templates/review.md` (priority 行追加、severity 見出しは温存)
  - `plugins/forge/skills/evaluator/SKILL.md` (`recommendation` 値域に `create_issue` 追加 / 5 観点精査 × P1/P2/P3 直交表 / recommendation 決定フロー / `--auto-critical` は priority 不問で severity フィルタ)
  - `plugins/forge/skills/present-findings/SKILL.md` (severity 順 → priority 順の二段ソート / AskUserQuestion に「Issue 化する」を追加 / `/anvil:create-issue` 呼び出し / batch_update の値域拡張)
  - `plugins/forge/skills/fixer/SKILL.md` (`recommendation: fix` のみフィルタ / 抜粋元を `review_<種別>.md` に変更 / priority 併記)
  - 上記スクリプト変更分の unittest 追加 (resolve_review_context / init_session)
- **検証ポイント**:
  - `/forge:review code` と `/forge:review code --diff --interactive` が同一の内部状態 (省略形と明示形の正規化)
  - `--diff --files a.md` で early validation がエラー (対象軸の二重指定)
  - `--section "4.1"` 等の DROP 済みフラグが明示的に拒否される (案内メッセージ)
  - `--interactive --auto-critical` / `--auto --auto-critical` で early validation エラー
  - target_files が 5 を超えると AskUserQuestion で絞り込みを促す (reviewer は分割起動しない)
  - reviewer は 1 体のみ起動 (統合テスト: 全種別 × 任意の `--files` で agent 数 = 1)
  - present-findings で「Issue 化」を選ぶと `/anvil:create-issue` が呼ばれる

### フェーズ 4: テスト整備 + 回帰防止 (1 起動原則 / 旧 perspective 残存検出)

- **目標**: 既存テスト (固有 perspective 前提・観点軸並列前提) を新体系に書き換え、Issue #68 再発防止のための回帰テストを揃える。フェーズ 3 までの個別変更が結合した状態で全テストが通ることを保証する。
- **スコープ**:
  - `tests/forge/review/` 配下の固有 perspective 前提テスト書き換え (`test_init_session.py` / `test_resolve_review_context.py` / `test_findings_parser.py` / `test_findings_renderer.py` を `--files` / priority ラベル / 種別ベース命名に対応)
  - `tests/forge/scripts/session/` の write_refs / write_interpretation / merge_evals / summarize_plan テスト (フェーズ 2 で追加済みの個別テストを統合シナリオでも回す)
  - **回帰防止テストの新設**:
    - 全 `plugins/forge/skills/review/docs/review_criteria_*.md` に `## Perspective:` セクションが存在しない (テキスト grep テスト、`tests/forge/review/test_criteria_no_perspective.py` 等)
    - refs.yaml に旧 `perspectives:` キーが現れた場合 write_refs が必ず拒否する
    - reviewer SKILL.md / review SKILL.md / DES 文書から perspective_name の旧名残 (`review_logic.md` / `review_resilience.md` 等) が grep されない
  - 統合テスト (DES-028 §7.2 全項目: 引数なしデフォルト / 等価性 / `--files` / 二重指定エラー / `--section` DROP 拒否 / 介入軸二重指定エラー / `--auto-critical` の挙動 / Issue 化選択 / criteria 不在時フォールバック / **reviewer 1 起動原則の回帰防止**)
- **検証ポイント**:
  - `python3 -m unittest discover -s tests -p 'test_*.py' -v` が全件 pass
  - 回帰防止テストが追加され、Issue #68 系の構造逆戻りが将来 CI で検知できる
  - criteria 不在時 (プロジェクト固有 criteria 無し) でも generic + 内蔵 principles で review_packet が構築できる

### フェーズ 5: addendum merge と起草版削除 (最終ステップ)

- **目標**: 4 つの addendum を target principles 4 ファイルへ機械的に転記し、`docs/specs/forge-review/principles/*_addendum.md` を削除する。frontmatter 規約 (REQ-004) に従い、本 feature 実装完了後の最終ステップとして実施する。
- **スコープ**:
  - `plugins/forge/docs/spec_priorities_spec.md` ← `spec_priorities_spec_addendum.md` 転記 (観点別利用ガイド + 重大度カタログ + グレーゾーン許容範囲 + 非機能要件カテゴリ網羅性)
  - `plugins/forge/docs/spec_design_boundary_spec.md` ← `spec_design_boundary_spec_addendum.md` 転記 (§4 / §6 重大度カタログ + 許容範囲 + 軽量トレーサビリティ)
  - `plugins/forge/docs/design_principles_spec.md` ← `design_principles_spec_addendum.md` 転記 (アーキ依存方向 / 責務分割 / SPOF + 重大度カタログ)
  - `plugins/forge/docs/plan_principles_spec.md` ← `plan_principles_spec_addendum.md` 転記 (タスク受け入れ基準 / テスト必須 / 暗黙依存 / トレーサビリティ + 重大度カタログ)
  - `docs/specs/forge-review/principles/*_addendum.md` 4 ファイル削除
  - 各 target ファイルの改定履歴に merge 元 addendum バージョン (v0.1 / v0.2) を追記
  - フェーズ 1 で criteria の SSOT参照が addendum 経路で運用されていた場合、merge 後のパスへ書き換え (criteria 6 ファイル / refs.yaml 生成経路)
- **検証ポイント**:
  - 旧 principles 4 ファイルに重大度カタログ / グレーゾーン許容範囲 / 観点別利用ガイドがすべて含まれる
  - addendum 4 ファイルが削除されている
  - criteria の SSOT参照が `plugins/forge/docs/*.md` を正しく指している (addendum 経路の残存なし)
  - `/forge:query-forge-rules` の検索インデックス (`plugins/forge/toc/rules/rules_toc.yaml`) を `/update-forge-toc` で再生成し、新規範が検索可能
  - 全テスト再 pass

---

## 依存関係

```
フェーズ 1 (ポリシー層確定)
   │
   ├── criteria SSOT参照の凍結が後工程の前提
   │
   ▼
フェーズ 2 (refs.yaml スキーマ + scripts 改修)
   │
   ├── review_packet スキーマ確定が SKILL 改修の前提
   │
   ▼
フェーズ 3 (SKILL 5 つ改修)
   │
   ├── SKILL 挙動確定が回帰テストの前提
   │
   ▼
フェーズ 4 (テスト整備 + 回帰防止)
   │
   ├── 全テスト pass が merge 安全性の前提
   │
   ▼
フェーズ 5 (addendum merge / 起草版削除)
```

- フェーズ 1 内では `review_priorities_spec.md` 新設 → criteria 6 ファイル全面置換の順 (criteria が新設文書を参照するため)
- フェーズ 2 内では write_refs.py (基盤) → write_interpretation.py / merge_evals.py / findings_*.py / summarize_plan.py (依存) → 各 unittest
- フェーズ 3 内では `/forge:review` (オーケストレータ) → reviewer (入力契約変更) → evaluator (recommendation 値域拡張) → present-findings / fixer (下流) の順
- フェーズ 5 は他のすべてが完了してから実施 (frontmatter 規約)

---

## リスクと対策

| リスク                                                                                   | 影響度 | 対策 (どのフェーズで潰すか)                                                                                                                                                                                       |
| ---------------------------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| FNC-412 reviewer 1 起動原則の回帰 (観点軸 / 対象ファイル軸での分割起動が再混入)          | 高     | フェーズ 4 で「reviewer agent 起動数 = 1」を統合テストでアサート。フェーズ 3 の review SKILL.md / reviewer SKILL.md レビュー時に「並列起動を示唆する記述がない」を必須チェック項目化                                  |
| refs.yaml 旧 `perspectives[]` スキーマの残存 (移行期間なし、互換廃止)                    | 高     | フェーズ 2 で write_refs が旧スキーマを明示的に拒否するバリデーションを実装 + テスト。フェーズ 4 で grep ベース回帰テスト追加 (`perspectives:` キー検出時にテスト失敗)                                                |
| addendum merge タイミングのずれ (実装途中で merge してしまう / merge 漏れで起草版が残る) | 高     | フェーズ 5 を「他フェーズ全完了後の最終ステップ」として計画書に明示。merge 後の起草版削除 + 改定履歴追記 + ToC 再生成までを 1 セットのタスクグループ化 (`build_check: on_group_complete`)                          |
| criteria の SSOT参照経路がフェーズ 1〜4 で addendum を指し、merge 後に旧パスとなる       | 中     | フェーズ 1 で criteria の SSOT参照は **target ファイル (`plugins/forge/docs/*.md`)** を指す前提で記述し、フェーズ 5 までは addendum 内容が未 merge であってもパスは target を指したままにする (運用上は addendum 内容が target に未反映だが、reviewer が両方を読む経路は SKILL 側で吸収しない方針) |
| 旧 perspective 名 (`review_logic.md` / `review_resilience.md` 等) の grep 取りこぼし     | 中     | フェーズ 4 で各 SKILL.md / scripts / templates / DES 系文書を対象に旧 perspective 名 grep テストを追加。`perspective` 単語自体は文脈用語として温存されるため、ファイル名形式 (`review_<英単語非種別>.md`) に絞った検出パターンで一致を取る |
| 5 観点精査 (DES-028 §4.3) と P1/P2/P3 軸の直交関係を evaluator SKILL.md で誤実装         | 中     | フェーズ 3 で evaluator SKILL.md に DES-028 §4.3 の表 + recommendation 決定フローをそのまま転記。フェーズ 4 で「同一 finding に複数 priority が付かない」「全 finding に 5 観点が適用される」を統合テストで確認 |
| principles 拡充未取り込み項目 (Appendix A.1〜A.5, A.7, A.9, A.11, A.13, A.15〜A.18) の取りこぼし | 低     | 本 feature では Appendix A の (a) 5 項目を addendum 経由で取り込み済み。(c) 13 項目は **本 feature スコープ外** とし、フェーズ 5 完了時点で「TBD として保全」状態のまま、後続 Issue 化を計画書側で明示          |
| forge_anti_patterns.md 空ファイル新設で何も書かれていない状態が criteria 経路を壊す      | 低     | フェーズ 1 で空ファイルは「見出しのみ」とし、criteria の SSOT参照表に登場する場合でも「未整備のため発見次第 create_issue」とする運用を `review_priorities_spec.md §4` で吸収済み。SKILL 側の挙動変更不要        |
| 既存 `run_review_engine.sh` の起動経路温存と 1 起動原則の整合                            | 低     | DES-028 §6 で「基本機構は再利用、起動数は 1」が明示済み。フェーズ 3 で review SKILL.md の Phase 4 説明から「並列起動」表現を排除すれば run_review_engine.sh 自体は無改修で動作する                                  |

---

## 想定タスク粒度の目安 (計画書側で使う)

- 各タスクは 1 Agent 実行で完結する単位 (5〜10 項目 / 1〜3 ファイル)
- フェーズ 1: criteria 6 ファイル全面置換は 6 タスクに分割 (1 ファイル/タスク)、review_priorities_spec / forge_anti_patterns 新設は各 1 タスク → 計 8 タスク前後
- フェーズ 2: write_refs / write_interpretation / merge_evals / findings_parser / findings_renderer / summarize_plan の各スクリプト改修 + テストで 6 タスクグループ (1 タスクあたり script 改修 + 該当テスト追加を含む) → 計 6 タスク前後
- フェーズ 3: SKILL 5 つ × 1 タスク + 関連スクリプト 2 つ (resolve_review_context / init_session) + テンプレ 1 つ → 計 8 タスク前後
- フェーズ 4: 既存テスト書き換え 4〜6 タスク + 回帰防止テスト新設 3 タスク + 統合シナリオ 1〜2 タスク → 計 8〜11 タスク
- フェーズ 5: 4 ファイル merge を 1 グループ (`GROUP-*`, `build_check: on_group_complete`) + 起草版削除 + ToC 再生成 + 改定履歴追記 を含めて 4〜5 タスク

合計タスク見込み: 34〜38 タスク程度。フェーズ 5 のみグループ化必須、他フェーズはタスク単位でビルド・テストが通る独立タスクで設計可能。

---

## 注記

- 本戦略書は ephemeral (実装完了時に削除)
- 計画書側に転記すべき内容は「フェーズ分割」「依存関係」「リスクと対策」のみ。How の詳細 (プロパティ名 / メソッドシグネチャ) は計画書には書かない (plan_principles 規範)
- 必読文書のパスは計画書の `required_reading` 欄に DES-028 / 各 addendum / DES-015 / DES-021 / 該当 rules を相対パスで列挙する
