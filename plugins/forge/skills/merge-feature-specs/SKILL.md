---
name: merge-feature-specs
description: |
  完了した FEATURE の仕様 (docs/specs/{plugin}/{feature}/) を main 仕様棚 (docs/specs/{plugin}/{requirements,design}/) に統合する。
  feature 名依存の命名 (REQ-001_io_verb 等) から主題ベース命名 (REQ-003_skill_script_separation 等) へリネームし、
  永続原則と作業履歴 (棚卸し / 段階的移行記録 / 完了済みタスク) を分離する。plan/ と棚卸しは削除。
  トリガー: "feature を main にマージ", "FEATURE を仕様に統合", "merge feature specs", "feature 統合"
user-invocable: true
argument-hint: "[plugin/feature]"
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, AskUserQuestion, Skill
---

# /forge:merge-feature-specs

完了した FEATURE の仕様 (`docs/specs/{plugin}/{feature}/`) を、その plugin の main 仕様棚 (`docs/specs/{plugin}/{requirements,design}/`) に統合する汎用 skill。

- **目的**: feature ディレクトリは「実施プロジェクト単位」、main 仕様棚は「永続的な仕様主題単位」。完了 feature の永続原則のみを main に残し、作業記録 (棚卸し・段階的移行・完了タスク) は削除する
- **入力**: `docs/specs/{plugin}/{feature}/` ディレクトリ
- **出力**: main 側の `requirements/REQ-XXX_{主題}.md` / `design/DES-XXX_{主題}_design.md` への統合・削除済み feature ディレクトリ
- **対象外**: forge プラグイン全体のフロントマター移行など、横断テーマは別 Issue で扱う

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。判断が必要な箇所のみ AskUserQuestion で確認する。

---

## コマンド構文

```
/forge:merge-feature-specs [plugin/feature]
```

| 引数           | 内容                                                                               |
| -------------- | ---------------------------------------------------------------------------------- |
| plugin/feature | 対象 feature の相対指定 (例: `forge/io_verb`)。省略時は Phase 1 で対話的に特定する |

---

## Phase 1: 対象 feature の特定 [MANDATORY]

### 1.1 引数あり

`docs/specs/{plugin}/{feature}/` の存在を確認。なければ Phase 1.2 に落ちる。

### 1.2 引数なし → 候補列挙

```bash
ls -d docs/specs/*/*/ 2>/dev/null | grep -vE '/(requirements|design|plan)/$'
```

候補を AskUserQuestion で提示する (4 件超なら上位 3 件 + Other)。

### 1.3 確定後の表示

```
対象: docs/specs/{plugin}/{feature}/
これを main 仕様棚 (docs/specs/{plugin}/{requirements,design}/) に統合します。
```

---

## Phase 2: 棚卸しスキャン [MANDATORY]

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/scan_feature.py" docs/specs/{plugin}/{feature}
```

デフォルトでは forge 慣習の ID プレフィックス (`REQ` / `DES` / `INV` / `TASK` / `FNC` / `NFR`) を検出する。プロジェクトが別の体系を使う・あるいは ID 体系を持たない場合は以下のオプションを使う:

| オプション                   | 用途                                                                   |
| ---------------------------- | ---------------------------------------------------------------------- |
| `--id-prefixes RFC,ADR,SPEC` | 別プレフィックスを指定 (forge 推奨慣習に従わないプロジェクト用)        |
| `--no-id`                    | ID 検出を完全無効化 (ID 体系を持たないプロジェクト用)。全 `id` が null |

**判定の指針** (Phase 1 の確定後、script 実行前に判断する):

1. feature 配下に既に forge 慣習 ID (`REQ-001` 等) がある → デフォルトのまま
2. 別プレフィックス (`RFC-001` / `ADR-007` 等) が見える → `--id-prefixes` で指定
3. ID らしきものが見えない or プロジェクトルールで ID 不要 → `--no-id`

JSON 出力を読み、後続 Phase で参照する。主要フィールド:

| フィールド          | 用途                                                                  |
| ------------------- | --------------------------------------------------------------------- |
| `files[].kind`      | `requirement` / `design` / `plan` / `inventory` / `other`             |
| `files[].id`        | 検出済み ID。`null` なら ID なし (または `--no-id` 指定時は常に null) |
| `files[].h1`        | 本文 H1。主題抽出のヒント                                             |
| `id_prefixes`       | 採用された ID プレフィックス一覧 (`[]` なら ID 体系なし)              |
| `main_existing_ids` | main 側の既存 ID 一覧 (重複防止)。`--no-id` 時は空                    |
| `main_specs_dirs`   | main 側の `requirements` / `design` / `plan` 各ディレクトリの存在     |

---

## Phase 3: ファイルごとの分類判定 [MANDATORY]

各ファイルを以下の 4 分類に振り分ける。**判定は AI が行う** (機械的に決められない)。

| 分類             | 定義                                                   | 処理                         |
| ---------------- | ------------------------------------------------------ | ---------------------------- |
| **永続 (clean)** | 永続原則のみで構成。feature 固有記述なし               | リネーム + main へ移動       |
| **永続 (mixed)** | 永続原則と作業履歴が混在 (例: 旧 REQ-001_io_verb)      | 永続原則のみ抽出して新規作成 |
| **作業履歴**     | 着手前棚卸し (INV) / 段階的移行記録 / 完了タスクの記録 | 削除                         |
| **plan**         | `plan/` 配下の YAML 計画書                             | 無条件削除 (本 skill の方針) |

### 3.1 mixed ファイルから永続原則を抽出する判断基準

以下に該当する記述は **作業履歴** として削除候補:

- 「現状の実測」「着手前の状態」「現状把握」等の章
- 「移行手順」「段階的に変更」「既存互換」「deprecation 期間」
- 「成功基準」「完了条件」のうち、feature 固有の判定項目 (例: 「review パイプライン 1 サイクル完走」)
- 「リスクと対処」「障害シナリオ表」のうち feature 固有の運用記録
- 個別 30 本の実装表・カバレッジ対応表 (永続原則を導く根拠であり原則そのものではない)

以下は **永続原則** として残す:

- 設計判断の基準 (Yes/No 判定可能な性質)
- 命名規則・配置原則
- 例外層の制約条件 (将来の拡張時にも同じ条件で判定できる)
- 非採用案 (将来の再検討を防ぐ)
- 関連文書

### 3.2 削除候補の保守的判断

完全削除は git 履歴で復元可能だが、誤削除を防ぐため、判断に迷うものは **mixed として扱い永続部分を抽出** する側に倒す。

---

## Phase 4: 新名・新構成の提案 [MANDATORY]

### 4.1 主題ベース命名

feature 名 (`io_verb` 等) ではなく、その永続原則が扱う主題を表す名前にする。例:

| Before                      | After                                   |
| --------------------------- | --------------------------------------- |
| `REQ-001_io_verb.md`        | `REQ-003_skill_script_separation.md`    |
| `DES-024_io_verb_design.md` | `DES-024_skill_script_layout_design.md` |

### 4.2 ID 採番

**ID 体系ありの場合** (`id_prefixes` が空でない):
Phase 2 の `main_existing_ids` から重複しない最小番号を採用する。複数の永続ファイルを抽出する場合は **作成日順** に連番を振る (古いものが先)。既存 ID をそのまま再利用してよいのは「ファイル名のみリネームし、ID は変えない」ケース (元から正しい ID が振られていた場合)。

**ID 体系なしの場合** (`id_prefixes: []` または検出結果が全 `null`):
ID プレフィックスなしの **主題ベース命名のみ** にする。例:

| Before                     | After                                     |
| -------------------------- | ----------------------------------------- |
| `requirements/io_verb.md`  | `requirements/skill_script_separation.md` |
| `design/io_verb_design.md` | `design/skill_script_layout_design.md`    |

採番が不要なため `main_existing_ids` の衝突検査もスキップ。ファイル名衝突 (同名 main 既存ファイル) のみ Phase 5 直前に確認する。

### 4.3 提案表示

```
リネーム / 抽出計画:

  {feature}/requirements/{old.md}      → requirements/{REQ-XXX}_{subject}.md  ({永続 clean | 抽出})
  {feature}/design/{old.md}            → design/{DES-XXX}_{subject}_design.md ({永続 clean | 抽出})

削除予定:

  {feature}/plan/                      (plan は無条件削除)
  {feature}/requirements/inventory.md  (作業履歴)
  ...

参照更新候補 (Phase 7 で grep 確認):

  - {予想される参照元ファイル}
```

AskUserQuestion で確認:

```
この計画で進めますか?
- はい、このまま実行  (Recommended)
- 個別に修正したい (リネームを変えたい / 抽出範囲を調整したい)
```

---

## Phase 5: 実行 [MANDATORY]

**[MANDATORY] Phase 5 全体の前提**: 永続 repo file (`docs/specs/` 配下) を破壊する操作を含むため、本 Phase の冒頭で `plugin` / `feature` を bash 変数として束縛し、以降のコマンド内では `$plugin` / `$feature` を使う。これは forge の「永続 repo file 削除にはガード必須」慣習に準拠した安全策。

```bash
# Phase 1 で確定した値を AI が展開して bash 変数に束縛する
plugin="{plugin}"
feature="{feature}"
[ -n "$plugin" ] && [ -n "$feature" ] || { echo "plugin/feature 未確定"; exit 1; }
```

### 5.1 リネーム (clean)

`git mv` で移動。`docs/specs/$plugin/{requirements,design}/` 配下に置く。

```bash
git mv "docs/specs/$plugin/$feature/requirements/{old}.md" \
       "docs/specs/$plugin/requirements/{REQ-XXX}_{subject}.md"
```

### 5.2 抽出 (mixed)

新規ファイル (`Write`) を main 側に作成。Phase 3 の判定で永続原則とした節のみを書き写す。**章番号は 1 から振り直し**、メタデータ表を冒頭に追加する。メタデータ表のスキーマは既存 DES-010 〜 DES-023 のスタイルを踏襲:

```markdown
# {ID} {主題}

## メタデータ

| 項目       | 値                   |
| ---------- | -------------------- |
| {ID 種別}  | {ID}                 |
| プラグイン | {plugin}             |
| 種別       | 要件定義 / 設計 など |
| 関連要件   | (該当時) REQ-XXX     |
| 関連設計   | (該当時) DES-XXX     |
```

### 5.3 削除

Phase 5 冒頭で束縛した `$plugin` / `$feature` を使う:

```bash
git rm "docs/specs/$plugin/$feature/plan"/*.yaml
git rm "docs/specs/$plugin/$feature/requirements/{INV-*}.md"
git rm "docs/specs/$plugin/$feature/{他の作業履歴ファイル}"
```

mixed ファイルから抽出済みの場合、抽出元も削除:

```bash
git rm "docs/specs/$plugin/$feature/requirements/{元 mixed ファイル}.md"
```

### 5.4 空ディレクトリの除去

Phase 5 冒頭で束縛した変数を使う。`-delete` は git 管理外動作なので、ディレクトリ存在確認を追加で挟む:

```bash
[ -d "docs/specs/$plugin/$feature" ] && \
  find "docs/specs/$plugin/$feature" -type d -empty -delete
```

`$feature/` 自体が空になれば一緒に消える。

---

## Phase 6: 内容修正 (mixed 抽出ファイルの整合) [MANDATORY]

抽出した永続ファイルの相互参照を main 構成に合わせて更新する:

- 旧 mixed ファイルが参照していた他文書 (DES-011 等) のパスは、main 側の相対パスに直す (例: `../design/DES-011_*.md`)
- 削除した INV / plan / mixed への参照は除去する
- 章番号の振り直しに伴って残っていた古い `§N` 表記は新章番号に修正する

---

## Phase 7: 参照更新の一斉確認 [MANDATORY]

旧パス・旧名への参照を全文検索:

```bash
grep -rn '{feature}_requirements\|{feature}_design\|inventory\.md\|REQ-XXX_{feature}\|INV-XXX_{feature}' \
  docs/ plugins/ README.md CLAUDE.md AGENTS.md \
  --include='*.md' --include='*.yaml' --include='*.yml' 2>/dev/null
```

検出された参照は新ファイル名・新パスに置換 (Edit ツール)。ただし以下は **対象外**:

- `CHANGELOG.md` の過去記述 (履歴として残す)
- `.claude/doc-advisor/toc/specs/specs_toc.yaml` (自動再生成)
- `.claude/doc-advisor/index/specs/.embedding_checksums.yaml` (自動再生成)
- `.claude/doc-advisor/toc/specs/.toc_checksums.yaml` (自動再生成)

CHANGELOG 除外で残存 0 件になるまで確認する。

---

## Phase 8: フォーマット [MANDATORY]

```bash
dprint check 2>&1 | tail -20
```

差分があれば `dprint fmt` で適用。元から存在する別件の parse error が出たら本作業のスコープ外として記録する。

---

## Phase 9: 完了案内

完了後、以下を表示する:

```
{plugin}/{feature} を main 仕様棚に統合しました:

  リネーム + 移動: N 件
  抽出 (mixed → clean): N 件
  削除 (plan / 作業履歴): N 件
  参照更新: N ファイル

次のステップ:
  1. /update-forge-toc                  # doc-advisor ToC 再生成
  2. /anvil:commit                      # commit / push
  3. (必要なら) /anvil:create-pr        # PR 作成
```

---

## 制約事項

- **plan/ は無条件削除**: forge の plan.yaml は完了済み feature にとって永続価値がない (履歴は git に残る)
- **棚卸し (INV-*) も削除**: 着手時点の現状把握は完了後の参照価値ゼロ
- **抽出時は章番号を振り直す**: feature 内の章構成 (§1 背景 / §3 スコープ / §5 成功基準 等) は永続原則の構成として最適化されていない。main では「概要 → 要件 (FNC/NFR) → 適用対象 → 関連文書」の順に再構成する
- **既存 ID は重複しないよう main_existing_ids で確認**: Phase 4.2 の採番ロジックを必ず通す (ID 体系なしプロジェクトでは採番自体スキップ)
- **ID 体系はプロジェクトごとに違う**: forge 慣習 (REQ/DES/INV/TASK/FNC/NFR) は **推奨** であって強制ではない。Phase 2 で `--id-prefixes` / `--no-id` を使い分ける
- **本 skill は doc-advisor ToC を再生成しない**: 完了案内で `/update-forge-toc` を案内する。ToC 再生成は別 skill の責務
