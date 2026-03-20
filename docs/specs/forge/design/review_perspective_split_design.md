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

### 3階層フォールバックの再設計

review_workflow_design.md §3 Phase 2 Step 4 で定義された「レビュー観点の3段階フォールバック」は、`review_criteria_path`（単一パス）を確定する設計だった。本設計で `review_criteria_path` を廃止し `perspectives` 配列に置き換えるにあたり、3階層フォールバックを以下のように再設計する。

フォールバックの優先順は従来と同一（DocAdvisor → review-config.yaml → プラグインデフォルト）。各層で `perspectives` 配列への変換方法が異なる。

#### 層 1: プラグインデフォルト（最低優先）

`${CLAUDE_PLUGIN_ROOT}/skills/review/docs/review_criteria_{type}.md` を読み込み、`## Perspective:` セクションから perspectives 配列を自動構成する。

```yaml
# 例: review_criteria_code.md から自動構成
perspectives:
  - name: correctness
    criteria_path: "review/docs/review_criteria_code.md"
    section: "正確性 (Logic)"
    output_path: review_correctness.md
  - name: resilience
    criteria_path: "review/docs/review_criteria_code.md"
    section: "堅牢性 (Resilience)"
    output_path: review_resilience.md
  # ...
```

各 criteria ファイルの `## Perspective:` セクションが perspectives の単位となる。セクションが1つもない場合はファイル全体を単一 perspective として扱う。

#### 層 2: `.claude/review-config.yaml`（中優先）

従来は単一パスを指定するスキーマだったが、以下の2形式をサポートするよう拡張する:

**形式 A: perspectives 配列を直接指定**

```yaml
review:
  perspectives:
    - name: correctness
      criteria_path: "path/to/custom_criteria.md"
      section: "正確性"
    - name: security
      criteria_path: "path/to/security_criteria.md"
      section: "セキュリティ"
```

**形式 B: 単一パス指定（後方互換）**

```yaml
review:
  criteria_path: "path/to/custom_criteria.md"
```

単一パスが指定された場合は、層 1 と同じく `## Perspective:` セクションをパースして perspectives 配列を自動構成する。`## Perspective:` セクションが存在しない場合はファイル全体を単一 perspective として扱う。

#### 層 3: `/query-rules` Skill — DocAdvisor（最高優先）

DocAdvisor が返すルール文書にはプラグイン側の `## Perspective:` セクション分割が存在するとは限らない。以下のルールで変換する:

- **`## Perspective:` セクションあり** → セクション単位で perspectives 配列を構成（層 1 と同じ）
- **`## Perspective:` セクションなし** → 返されたルール文書全体を**単一 perspective**（name: `docadvisor_rules`）として扱う

```yaml
# DocAdvisor のルール文書にセクション分割がない場合
perspectives:
  - name: docadvisor_rules
    criteria_path: "{DocAdvisor が返したルール文書パス}"
    section: null  # ファイル全体を使用
    output_path: review_docadvisor_rules.md
```

#### フォールバック統合ルール

上位の層で perspectives が確定した場合、下位の層はスキップする。ただし、DocAdvisor（層 3）が返した perspectives とプラグインデフォルト（層 1）の perspectives は**マージ**される。DocAdvisor は主にプロジェクト固有のルールを提供し、プラグインデフォルトは種別固有の汎用観点を提供するため、両者は補完関係にある。

| 確定パターン | 結果 |
|-------------|------|
| 層 3 のみ確定 | 層 3 の perspectives + 層 1 のプラグインデフォルトをマージ |
| 層 2 のみ確定 | 層 2 の perspectives をそのまま使用（プラグインデフォルトで補完しない） |
| 層 1 のみ確定 | 層 1 のプラグインデフォルトをそのまま使用 |

> **設計判断**: 層 2（review-config.yaml）はユーザーが明示的にカスタマイズした設定であるため、プラグインデフォルトとのマージは行わない。一方、DocAdvisor はプロジェクトルールの補完であり、種別固有の汎用観点は引き続き必要なためマージする。

---

## 3. 複数 Reviewer Agent の起動

### データ受け渡し: refs.yaml に perspectives を記録

プロンプト直接埋め込みではなく refs.yaml を採用する。

| 比較観点 | プロンプト埋め込み | refs.yaml |
|---------|-----------------|-----------|
| 検査可能性 | ❌ セッションファイルから見えない | ✅ 全情報が可視 |
| 再開可能性 | ❌ 中断時に消失 | ✅ 永続化 |
| 設計一貫性 | ❌ 旧設計（プロンプト経由）への回帰 | ✅ ファイル経由原則と一貫 |
| Read コスト | ✅ 不要 | △ 微小（1回の Read） |

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

> **並列書き込みとの整合性**: session_format.md では「reviewer は並列書き込み不要のため refs.yaml を使用」と注記しているが、本設計の perspectives 追加はこれと矛盾しない。refs.yaml はオーケストレーター（review）がコンテキスト収集フェーズで一括書き出すため、並列書き込みの問題は発生しない。各 reviewer agent の出力は `review_{perspective}.md` として分離されるため、agent 間のファイル競合も起きない。

### 後方互換性

refs.yaml に `perspectives` が存在しない場合（= 現行の `review_criteria_path` 方式）のフォールバック動作を定義する。

reviewer は refs.yaml の `perspectives` フィールド有無で分岐する:

| `perspectives` | 動作 |
|----------------|------|
| **あり** | perspectives 配列に基づき、観点別に並列 Agent を起動。各 Agent は `output_path` にレビュー結果を書き出す |
| **なし** | `review_criteria_path` を使用し、従来の単一 Agent でレビューを実行。結果は `review.md` に書き出す |

この分岐により、perspectives 導入前のセッション（手動作成や旧バージョン）でもレビューが正常に動作する。perspectives への完全移行後に `review_criteria_path` のサポートを廃止する。

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

理由:
- レビュー種別によって自然な分割は異なる（コード vs 要件定義書 vs 設計書）
- 固定的な分割は抽象的すぎて実際の観点と乖離する
- 観点の追加・変更が criteria ファイルの編集だけで完結する（reviewer 側の変更不要）
- perspectives の構成をオーケストレーターに集約することで、reviewer は単純な「指示されたレビューを実行する」役割に徹する

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

> Gemini による外部レビュー結果を反映:
> - requirement: 「実現可能性・明確性」→「検証可能性」に改名（AI の判定基準として具体的）
> - requirement: 完全性に「例外系・異常系の考慮漏れ」を追加
> - design: 堅牢性に「可観測性（ログ・監視）」を追加
> - design: 整合性に外部システムとの接続を追加
> - code: 「規約・品質」→「保守性」に改名。テスト可能性（DI 等）を追加
> - code: 堅牢性にリソース管理・入力バリデーションを追加
> - 全 Perspective に英語名を併記（Agent ペルソナ付与に有用）

---

## 7. 影響範囲

| ファイル | 変更内容 |
|---------|---------|
| `review/SKILL.md` | 3階層フォールバック再設計、perspectives 構成追加 |
| `reviewer/SKILL.md` | `review_criteria_path` 廃止、perspectives 対応 |
| `evaluator/SKILL.md` | `review_criteria_path` 廃止 |
| `fixer/SKILL.md` | `review_criteria_path` 廃止 |
| `present-findings/SKILL.md` | 統合後の review.md を読む設計に更新 |
| `session_format.md` | refs.yaml スキーマに perspectives 追加、`review_criteria_path` 削除 |
| `extract_review_findings.py` | 複数 review_*.md のマージ対応 |
| `write_refs.py` | perspectives フィールド対応 + 排他バリデーション（下記参照） |
| `README.md`, `README_ja.md` | パス参照更新 |
| `CLAUDE.md` | パス参照更新 |
| `review_workflow_design.md` | データフロー図更新 |

### write_refs.py のバリデーション方針

`review_criteria_path` と `perspectives` は排他関係にある。write_refs.py は以下のバリデーションを行う:

| `review_criteria_path` | `perspectives` | 結果 |
|------------------------|---------------|------|
| あり | なし | ✅ 有効（後方互換モード） |
| なし | あり | ✅ 有効（新方式） |
| あり | あり | ✅ 有効（後方互換期間中は両方許容。perspectives を優先使用） |
| なし | なし | ❌ エラー（どちらか一方が必須） |

後方互換期間中は両方の指定を許容し、perspectives が存在する場合はそちらを優先する。perspectives への完全移行後に `review_criteria_path` のみの指定をエラーとする。

---

## 8. 設計判断の記録

### トークンコスト分析

perspectives 並列実行は単一 Agent 実行と比べてトークンコストが増加する。トレードオフを以下に整理する。

| 項目 | 単一 Agent | perspectives 並列 |
|------|-----------|------------------|
| 入力トークン | 1× (全観点 + 対象ファイル) | 最大 N× (各 Agent に対象ファイルが重複) |
| 出力トークン | 1× | ≈1× (総指摘数は同程度) |
| 合計コスト | 1× | 最大 3× (code レビューの場合 3 perspectives) |
| 実行時間 | 直列のため長い | 並列実行により短縮 |
| レビュー品質 | 広く浅い | 各観点で深い分析が可能 |

**許容範囲の判断**: 単一 Agent 比で最大 3 倍のトークンコスト増。ただし (1) 各 Agent が専門観点に集中することでレビュー品質が向上し、(2) 並列実行により壁時計時間は短縮される。コストと品質・時間のトレードオフとして許容する。perspectives 数が 2-3 の設計としているのは、この上限を意識した結果でもある。

---

## 9. 調査 Sources

- [How to write a good spec for AI agents - Addy Osmani](https://addyosmani.com/blog/good-spec/)
- [Writing a good CLAUDE.md - HumanLayer](https://www.humanlayer.dev/blog/writing-a-good-claude-md)
- [Spec-driven development - Thoughtworks](https://thoughtworks.medium.com/spec-driven-development-d85995a81387)
- [Taxonomies in Software Engineering - ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0950584917300472)
