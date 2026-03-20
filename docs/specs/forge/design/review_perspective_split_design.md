# reviewer 観点別 agent 分割 設計書

> 対象プラグイン: forge | スキル: `/forge:reviewer`

---

## 1. 概要

現在の reviewer は 1 つの subagent に全レビュー観点を同時適用している。これにより:

1. **重大度バイアス**: 見つけやすい 🟢（スタイル）が過剰、見つけにくい 🔴（ロジックバグ）が過少
2. **深さの犠牲**: 全観点を広く浅くカバーし、各観点での深い分析ができない
3. **コンテキスト競合**: バグ探しとスタイルチェックが同じ注意リソースを奪い合う

本設計では review_criteria を観点（Perspective）別に分割し、Perspective ごとに専門の Agent を並列起動してレビュー品質を向上させる。

---

## 2. review_criteria の分割と配置

### 配置先

review_criteria_spec.md の唯一の起点は review オーケストレーター。他スキル（reviewer/evaluator/fixer）は refs.yaml 経由で読むだけ。→ review スキルディレクトリに配置する。

```
plugins/forge/skills/review/
  docs/
    review_criteria_requirement.md   # 要件定義書レビュー観点
    review_criteria_design.md        # 設計書レビュー観点
    review_criteria_plan.md          # 計画書レビュー観点
    review_criteria_code.md          # コードレビュー観点
    review_criteria_generic.md       # 汎用文書レビュー観点
```

各ファイルにはレビュー観点を詳細に記載する（現在の箇条書きレベルから大幅拡充）。旧ファイル `plugins/forge/docs/review_criteria_spec.md` は削除する。

### 設計変更

現在の `review_criteria_path`（単一パス）の概念はなくなる。refs.yaml には `review_criteria_path` を書かず、代わりに `perspectives` 配列で観点ごとの入力・出力を管理する。

### perspectives の収集

review オーケストレーターは以下の全てから perspectives を収集し、配列に追加する。

**プラグインデフォルト**（常に含む）: `${CLAUDE_SKILL_DIR}/docs/review_criteria_{type}.md` を読み込み、`## Perspective:` セクションから perspectives を構成する。セクションがない場合はファイル全体を単一 perspective として扱う。

**DocAdvisor**（`/query-rules` が利用可能なら追加）: DocAdvisor が返すプロジェクト固有のルール文書を、そのまま追加の perspective として渡す。`section: ""` でファイル全体を観点として使用。

```yaml
perspectives:
  - name: correctness
    criteria_path: "review/docs/review_criteria_code.md"
    section: "正確性 (Logic)"
    output_path: review_correctness.md
  - name: resilience
    criteria_path: "review/docs/review_criteria_code.md"
    section: "堅牢性 (Resilience)"
    output_path: review_resilience.md
  - name: project-rules
    criteria_path: "docs/rules/coding_standards.md"
    section: ""
    output_path: review_project_rules.md
```

`section: ""` の場合、agent はファイル全体を観点として使用する。

> **設計判断**: 層 2（review-config.yaml）はユーザーが明示的にカスタマイズした設定であるため、プラグインデフォルトとのマージは行わない。一方、DocAdvisor はプロジェクトルールの補完であり、種別固有の汎用観点は引き続き必要なためマージする。

---

## 3. 複数 Reviewer Agent の起動

### refs.yaml の拡張

#### perspectives オブジェクトのスキーマ

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `name` | string | Yes | perspective の一意識別子（例: `correctness`, `resilience`） |
| `criteria_path` | string | Yes | レビュー観点ファイルのパス（プラグインルートからの相対パス） |
| `section` | string \| null | No | criteria ファイル内の対象セクション名。`null` の場合はファイル全体を使用 |
| `output_path` | string | Yes | レビュー結果の出力先（session_dir からの相対パス） |

```yaml
target_files: [...]
reference_docs: [...]
perspectives:
  - name: correctness
    criteria_path: "review/docs/review_criteria_code.md"
    section: "正確性 (Logic)"
    output_path: review_correctness.md   # session_dir からの相対パス
  - name: resilience
    criteria_path: "review/docs/review_criteria_code.md"
    section: "堅牢性 (Resilience)"
    output_path: review_resilience.md
  - name: maintainability
    criteria_path: "review/docs/review_criteria_code.md"
    section: "保守性 (Maintainability)"
    output_path: review_maintainability.md
```

review オーケストレーターが criteria ファイルを読み、`## Perspective:` セクションを抽出して perspectives 配列を構成し refs.yaml に書き出す。reviewer は refs.yaml の perspectives を読むだけで、分割ロジックを持たない。各 reviewer Agent は自分の `criteria_path` + `section` を読み、該当観点に従ってレビュー。結果は `output_path` に Write する。

### Codex 対応

`run_review_engine.sh` は単一プロセス実行のまま維持する。並列制御は以下の方針でオーケストレーター側が担当する:

1. review オーケストレーターが perspectives の数だけ `run_review_engine.sh` をバックグラウンド起動する
2. 各プロセスには perspective 固有の `output_file`（= `output_path`）と `prompt`（= `criteria_path` + `section` を含む指示）を渡す
3. 全プロセスの完了を `wait` で待機する
4. いずれかのプロセスが失敗した場合、その perspective のレビュー結果は欠損として扱い、成功した perspective の結果のみで続行する

```bash
# オーケストレーター側の並列起動イメージ（疑似コード）
pids=()
for perspective in perspectives; do
    run_review_engine.sh "${session_dir}/${perspective.output_path}" \
        "$project_dir" "$prompt" &
    pids+=($!)
done

# 全プロセスの完了を待機
for pid in "${pids[@]}"; do
    wait "$pid" || echo "perspective failed: $pid"
done
```

Claude エンジンの場合は `/forge:reviewer` の subagent を perspectives の数だけ並列起動し、同様に全完了を待機する。

---

## 4. 複数結果の管理

```
{session_dir}/
  review_correctness.md     # Perspective A の結果
  review_resilience.md      # Perspective B の結果
  review_maintainability.md # Perspective C の結果
  review.md                 # マージ後の統合レビュー
  plan.yaml                 # 全指摘を統合管理
```

### extract_review_findings.py の拡張

現行の `extract_review_findings.py` は単一ファイル引数（`<review_md_path>`）を受け取る設計。perspectives 対応に伴い、以下のように変更する:

1. **引数を `session_dir` に変更**: 第1引数に session_dir パスを受け取り、`review_*.md` を glob で収集する
2. **ID はファイル間通し番号**: 複数ファイルをアルファベット順に処理し、ID はファイルをまたいで連番で付与する
3. **perspective タグの付与**: ファイル名から perspective 名を抽出する（`review_{perspective}.md` → `perspective: "{perspective}"`）。各指摘に `perspective` フィールドを追加し、evaluator が重複排除時に参考にする
4. **後方互換**: `review_*.md` が存在せず `review.md` のみの場合は、従来と同じく単一ファイルとして処理する（perspective タグなし）

```
# 新しい Usage
python3 extract_review_findings.py <session_dir> <output_plan_yaml_path>
```

### 統合 review.md の生成

`extract_review_findings.py` が `review_*.md` → `plan.yaml` 生成時に、統合 `review.md` も同時生成する。統合 review.md は各 perspective の結果を perspective 名見出し付きで連結したファイルである。

- evaluator は統合 `review.md` を読んで吟味を行う
- present-findings は統合 `review.md` を読んで段階的提示を行う
- 個別の `review_{perspective}.md` は参照用として残す

---

## 5. 観点の分割方針

**perspectives 配列の構成は review オーケストレーターの責務であり、reviewer は分割方針を持たない。** 各 review_criteria ファイルが `## Perspective:` セクションで分割を宣言し、review オーケストレーターがそれを読み取って perspectives 配列を構成する。reviewer は refs.yaml に記録された perspectives を読み取り、指定された観点に従ってレビューを実行するだけである。

責務の分離:

| コンポーネント | 責務 |
|--------------|------|
| review_criteria ファイル | `## Perspective:` セクションで観点の分割を宣言する |
| review オーケストレーター | criteria ファイルを読み、perspectives 配列を構成し refs.yaml に書き出す |
| reviewer | refs.yaml の perspectives を読み、指定された観点に従ってレビューを実行する |

---

## 6. 各種別の Perspective 定義

### requirement（要件定義書）— 3 perspectives

| Perspective | 観点 |
|-------------|------|
| **完全性 (Completeness)** | 必須要件の網羅性、非機能要件の不足（性能・運用・セキュリティ等）、例外系・異常系の考慮漏れ |
| **整合性 (Consistency)** | 要件間の矛盾・競合、用語定義の不統一、ビジネスゴールとの追跡性（トレーサビリティ） |
| **検証可能性 (Verifiability)** | 曖昧な表現の排除、定量的な受け入れ基準、技術的制約との矛盾、優先度・スコープの明確さ |

### design（設計書）— 3 perspectives

| Perspective | 観点 |
|-------------|------|
| **整合性 (Alignment)** | 要件定義書との不整合、外部システム・既存コンポーネントとのインターフェース、データフローの矛盾・欠落、設計判断の根拠不足 |
| **構造・品質 (Architecture)** | 責務分割（疎結合・高凝集）、アーキテクチャ原則の遵守、拡張性・保守性の問題 |
| **堅牢性 (Resilience)** | セキュリティ上の問題、エラーハンドリングの不足、可観測性（ログ・監視・追跡可能性） |

### plan（計画書）— 2 perspectives

| Perspective | 観点 |
|-------------|------|
| **整合性 (Alignment)** | 要件・設計との不整合、必須タスクの網羅、タスク間の依存関係の矛盾 |
| **現実性・リスク (Feasibility)** | タスク粒度の妥当性、ボトルネックの特定、リスク対策の妥当性、受け入れ基準の明確さ、優先順位 |

### code（コード）— 3 perspectives

| Perspective | 観点 |
|-------------|------|
| **正確性 (Logic)** | ロジックエラー、エッジケース、境界値、データ損失リスク、設計書・要件定義書との不整合 |
| **堅牢性 (Resilience)** | セキュリティ脆弱性（インジェクション、認証不備等）、エラーハンドリングの不足、リソース管理、入力バリデーション |
| **保守性 (Maintainability)** | コーディング規約遵守、可読性、テスト可能性（DI 等の構造）、テスト充足度、重複、パフォーマンス問題 |

### generic（汎用文書）— perspectives 分割なし（単一 agent）

汎用文書は内容が多様で、perspectives 分割のメリットが薄いため、従来通り単一 agent で全観点を適用する。
`review_criteria_generic.md` は `## Perspective:` セクションを持たず、全観点を一括記載する。

| 観点 |
|------|
| 事実の誤り、論理矛盾、参照切れ（リンク・ファイルパス・コマンド）、必須情報の欠落 |
| 論理構成の一貫性、用語の不統一、記述の重複、冗長性の排除 |

---

## 7. 影響範囲

| ファイル | 変更内容 |
|---------|---------|
| `review/SKILL.md` | perspectives 収集・構成追加、`review_criteria_path` 廃止 |
| `reviewer/SKILL.md` | `review_criteria_path` 廃止、perspectives 対応 |
| `evaluator/SKILL.md` | `review_criteria_path` 廃止 |
| `fixer/SKILL.md` | `review_criteria_path` 廃止 |
| `present-findings/SKILL.md` | 統合後の review.md を読む設計に更新 |
| `session_format.md` | refs.yaml スキーマに perspectives 追加、`review_criteria_path` 削除 |
| `extract_review_findings.py` | 複数 review_*.md のマージ対応 |
| `write_refs.py` | `review_criteria_path` を廃止し `perspectives` を必須フィールドに変更 |
| `README.md`, `README_ja.md` | パス参照更新 |
| `CLAUDE.md` | パス参照更新 |
| `review_workflow_design.md` | データフロー図更新 |

---

## 8. 調査 Sources

- [How to write a good spec for AI agents - Addy Osmani](https://addyosmani.com/blog/good-spec/)
- [Writing a good CLAUDE.md - HumanLayer](https://www.humanlayer.dev/blog/writing-a-good-claude-md)
- [Spec-driven development - Thoughtworks](https://thoughtworks.medium.com/spec-driven-development-d85995a81387)
- [Taxonomies in Software Engineering - ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0950584917300472)
