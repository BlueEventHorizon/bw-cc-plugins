---
name: merge-feature-specs
description: |
  完了した FEATURE の仕様ディレクトリを main 仕様棚 (requirements/ design/) に統合する。
  feature 名依存の命名から主題ベース命名へリネームし、永続原則と作業履歴 (棚卸し / 段階的移行記録 / 完了済みタスク) を分離する。plan/ と棚卸しは削除。
  ディレクトリ構造は .doc_structure.yaml を尊重し、plugin 階層の有無に依存しない。
  トリガー: "feature を main にマージ", "FEATURE を仕様に統合", "merge feature specs", "feature 統合"
user-invocable: true
argument-hint: "[feature-dir]"
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, AskUserQuestion, Skill
---

# /forge:merge-feature-specs

完了した FEATURE の仕様ディレクトリを、その親階層の main 仕様棚 (`requirements/`, `design/`) に統合する汎用 skill。

- **目的**: feature ディレクトリは「実施プロジェクト単位」、main 仕様棚は「永続的な仕様主題単位」。完了 feature の永続原則のみを main に残し、作業記録 (棚卸し・段階的移行・完了タスク) は削除する
- **入力**: feature ディレクトリのパス (例: `docs/specs/forge/io_verb`, `docs/specs/auth`)。`.doc_structure.yaml` 尊重で `plugin` 階層の有無に依存しない
- **出力**: main 仕様棚 (`{main_specs_root}/requirements/`, `{main_specs_root}/design/`) への統合・削除済み feature ディレクトリ
- **対象外**: 個別プラグインのフロントマター移行など、横断テーマは別 Issue で扱う

> **main_specs_root の決定**:
>
> 1. Phase 2 で `--main-specs-root` を明示すれば最優先
> 2. 省略時は `feature_dir.parent` を採用する
> 3. Phase 1 の feature 候補列挙は `forge:doc-structure` 経由 (`.doc_structure.yaml` 必須)

## 前提条件 [MANDATORY]

本 skill は以下を **必須前提** とする。Phase 0 で検査し、欠けていればユーザに通知して終了する。

| 前提                  | 必須/任意 | 用途                                                              |
| --------------------- | --------- | ----------------------------------------------------------------- |
| `.doc_structure.yaml` | 必須      | feature 列挙・main 仕様棚解決の根拠                               |
| doc-advisor           | 必須      | Phase 7 の `.claude/doc-advisor/` 除外、Phase 9 の ToC 再生成案内 |
| anvil                 | 任意      | Phase 9 の commit 案内 (`/anvil:commit`)。無ければ `git commit`   |
| dprint                | 任意      | Phase 8 のフォーマット。無ければスキップ                          |

forge エコシステム前提のため、必須項目は **存在しなければ即終了** する。フォールバック推測は行わない (誤動作の温床になるため)。

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。判断が必要な箇所のみ AskUserQuestion で確認する。

---

## コマンド構文

```
/forge:merge-feature-specs [feature-dir]
```

| 引数        | 内容                                                                                                             |
| ----------- | ---------------------------------------------------------------------------------------------------------------- |
| feature-dir | 対象 feature ディレクトリのパス (例: `docs/specs/forge/io_verb`, `docs/specs/auth`)。省略時は Phase 1 で特定する |

---

## Phase 0: 前提条件の検査 [MANDATORY]

必須前提を最初に検査する。1 件でも欠けたらユーザに通知して **即終了** する。

### 0.1 `.doc_structure.yaml` の存在

```bash
PROJECT_ROOT="$(git rev-parse --show-toplevel)"
if [ ! -f "$PROJECT_ROOT/.doc_structure.yaml" ]; then
  echo "ERROR: .doc_structure.yaml が見つかりません ($PROJECT_ROOT)"
  echo ""
  echo "プロジェクトルートに .doc_structure.yaml を作成してください。"
  echo "フォーマット仕様: plugins/forge/docs/doc_structure_format.md"
  exit 1
fi
```

### 0.2 doc-advisor プラグインの存在

doc-advisor の `resolve_doc_structure.py` を Phase 1 / Phase 7 / Phase 9 で利用するため、forge プラグインからの相対パスで検査する:

```bash
DOC_STRUCTURE="${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py"
if [ ! -f "$DOC_STRUCTURE" ]; then
  echo "ERROR: forge:doc-structure skill が見つかりません"
  echo "forge プラグインを再インストールしてください: /plugin install forge@bw-cc-plugins"
  exit 1
fi
```

> 注: `forge:doc-structure` は forge プラグイン内の skill のため、forge が install されていれば必ず存在する。`doc-advisor` プラグイン本体は Phase 9 の ToC 再生成案内で必要だが、Claude が会話文脈の slash command 一覧から判定する (`/doc-advisor:` が利用可能か)。利用不可ならユーザに案内して終了:
>
> ```
> ERROR: doc-advisor プラグインが install されていません
> /plugin install doc-advisor@bw-cc-plugins でインストールしてください
> ```

### 0.3 オプショナルツールの状態確認 (任意)

dprint / anvil は **任意**。Phase 0 で検査せず、各 Phase で必要時に分岐する (Phase 8 / Phase 9)。

---

## Phase 1: 対象 feature の特定 [MANDATORY]

### 1.1 引数あり

引数で指定された feature ディレクトリの存在を確認。なければ Phase 1.2 に落ちる。

### 1.2 引数なし → 候補列挙

`forge:doc-structure` 経由で feature を列挙する (`.doc_structure.yaml` は Phase 0 で確認済み):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py" \
  --features --project-root "$PROJECT_ROOT"
```

候補を AskUserQuestion で提示する (4 件超なら上位 3 件 + Other)。

### 1.3 確定後の表示

```
対象 feature: {feature_dir}
main 仕様棚: {main_specs_root}/{requirements,design}/

これを main 仕様棚に統合します。
```

main_specs_root が `feature_dir.parent` で適切でない場合 (例: 上位ディレクトリが main 仕様棚ではないプロジェクト構造) は、AskUserQuestion で明示指定するか確認する:

```
main 仕様棚を {feature_dir.parent} と認識しました。これで合っていますか?
- はい (Recommended)
- いいえ、別ディレクトリを指定する → --main-specs-root <path> を Phase 2 で渡す
```

---

## Phase 2: 棚卸しスキャン [MANDATORY]

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/scan_feature.py" {feature_dir}
```

デフォルトでは forge 慣習の ID プレフィックス (`REQ` / `DES` / `INV` / `TASK` / `FNC` / `NFR`) と 3 桁ハイフン区切りを検出する。プロジェクトが別形式を使う・あるいは ID 体系を持たない場合は以下のオプションを使う:

| オプション                   | 用途                                                                   |
| ---------------------------- | ---------------------------------------------------------------------- |
| `--main-specs-root <path>`   | main 仕様棚を明示指定 (feature_dir.parent が適切でない場合)            |
| `--id-prefixes RFC,ADR,SPEC` | 別プレフィックスを指定 (forge 推奨慣習に従わないプロジェクト用)        |
| `--id-digits 4`              | ID 数字部分の桁数を変更 (デフォルト 3)                                 |
| `--id-separator _`           | プレフィックスと数字の区切り文字を変更 (デフォルト `-`)                |
| `--no-id`                    | ID 検出を完全無効化 (ID 体系を持たないプロジェクト用)。全 `id` が null |

**判定の指針** (Phase 1 の確定後、script 実行前に判断する):

1. feature 配下に既に forge 慣習 ID (`REQ-001` 等) がある → デフォルトのまま
2. 別プレフィックス (`RFC-001` / `ADR-007` 等) が見える → `--id-prefixes` で指定
3. 桁数や区切り文字が違う (`REQ-0001` / `REQ_001` 等) → `--id-digits` / `--id-separator` で調整
4. ID らしきものが見えない or プロジェクトルールで ID 不要 → `--no-id`
5. main 仕様棚が `feature_dir.parent` でない (例: ルート docs/specs/ を main にしたい) → `--main-specs-root` で指定

JSON 出力を読み、後続 Phase で参照する。主要フィールド:

| フィールド          | 用途                                                                  |
| ------------------- | --------------------------------------------------------------------- |
| `feature_dir`       | feature の絶対パス                                                    |
| `feature_name`      | feature 名 (= ディレクトリ末尾)                                       |
| `main_specs_root`   | main 仕様棚の絶対パス (`requirements/` `design/` `plan/` の親)        |
| `files[].kind`      | `requirement` / `design` / `plan` / `inventory` / `other`             |
| `files[].id`        | 検出済み ID。`null` なら ID なし (または `--no-id` 指定時は常に null) |
| `files[].h1`        | 本文 H1。主題抽出のヒント                                             |
| `id_prefixes`       | 採用された ID プレフィックス一覧 (`[]` なら ID 体系なし)              |
| `main_existing_ids` | main 側の既存 ID 一覧 (重複防止)。`--no-id` 時は空                    |
| `main_specs_dirs`   | main 側の `requirements` / `design` / `plan` 各ディレクトリの存在     |
| `warnings`          | 構造的問題 (main 仕様棚が空・存在しない 等)。空配列なら問題なし       |

**warnings がある場合**: 続行可能だが、Phase 5 の `git mv` で問題が起きる可能性があるため AskUserQuestion で確認する:

```
警告: {warnings の内容}
このまま続行しますか?
- はい、続行する
- 中断 (--main-specs-root を見直す等)
```

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

#### 作業履歴として削除候補

時間軸を持つ記述・着手プロジェクト固有の判定はすべて作業履歴とみなす:

- **時点の記録**: 「現状の実測」「着手前の状態」「現状把握」「移行前のスナップショット」等
- **遷移過程**: 「移行手順」「段階的に変更」「既存互換」「deprecation 期間」「N 段階で実施」
- **プロジェクト固有の判定基準**: 「成功基準」「完了条件」のうち feature 固有の判定項目
- **プロジェクト固有の運用記録**: 「リスクと対処」「障害シナリオ表」のうち、その feature 実施時の運用記録
- **個別実装一覧表**: タスク表・カバレッジ対応表など (永続原則を導く根拠であり原則そのものではない)

> **forge プラグインでの例** (参考):
>
> - 「review パイプライン 1 サイクル完走」(完了条件として feature 固有)
> - 「30 本の実装表」(個別実装一覧)
> - 「INV-* で記録した着手前棚卸し」(時点の記録)

#### 永続原則として残す

時間軸を持たず、将来の判断に再利用できるものを永続原則とみなす:

- **設計判断の基準** (Yes/No 判定可能な性質。例: 「`script` を呼ぶ責務は SKILL.md ではなく wrapper script にある」)
- **命名規則・配置原則** (例: 「テストは `tests/{plugin}/{skill}/` に配置する」)
- **例外層の制約条件** (将来の拡張時にも同じ条件で判定できるもの)
- **非採用案** (将来の再検討を防ぐ。「なぜ X を採用しなかったか」)
- **関連文書のリンク**

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

**[MANDATORY] Phase 5 全体の前提**: 永続 repo file を破壊する操作を含むため、本 Phase の冒頭で `feature_dir` / `main_specs_root` を bash 変数として束縛し、以降のコマンド内では `$feature_dir` / `$main_specs_root` を使う。これは forge の「永続 repo file 削除にはガード必須」慣習に準拠した安全策。

```bash
# Phase 2 で scan_feature.py の出力から取得した値を AI が展開して bash 変数に束縛する
feature_dir="{feature_dir からのリポジトリ相対パス}"  # 例: docs/specs/forge/io_verb
main_specs_root="{main_specs_root からのリポジトリ相対パス}"  # 例: docs/specs/forge

[ -n "$feature_dir" ] && [ -n "$main_specs_root" ] \
  || { echo "feature_dir / main_specs_root 未確定"; exit 1; }
[ -d "$feature_dir" ] || { echo "feature_dir が存在しません: $feature_dir"; exit 1; }
[ -d "$main_specs_root" ] || { echo "main_specs_root が存在しません: $main_specs_root"; exit 1; }
```

### 5.1 リネーム (clean)

`git mv` で移動。`$main_specs_root/{requirements,design}/` 配下に置く。

```bash
# main 側ディレクトリが未作成なら作る (Phase 2 warnings で検出済みの場合)
mkdir -p "$main_specs_root/requirements" "$main_specs_root/design"

git mv "$feature_dir/requirements/{old}.md" \
       "$main_specs_root/requirements/{REQ-XXX}_{subject}.md"
```

### 5.2 抽出 (mixed)

新規ファイル (`Write`) を main 側に作成。Phase 3 の判定で永続原則とした節のみを書き写す。**章番号は 1 から振り直し**、メタデータ表を冒頭に追加する。メタデータ表のスキーマは「ID 種別」「種別」「関連要件」「関連設計」の 4 項目を基本とし、main_specs_root が plugin 名のような階層名を持つプロジェクトでは「プラグイン」行を任意で追加する:

```markdown
# {ID} {主題}

## メタデータ

| 項目      | 値                   |
| --------- | -------------------- |
| {ID 種別} | {ID}                 |
| 種別      | 要件定義 / 設計 など |
| 関連要件  | (該当時) REQ-XXX     |
| 関連設計  | (該当時) DES-XXX     |

# 任意行 (main_specs_root が plugin 階層を持つプロジェクト)

# | プラグイン | {main_specs_root.basename} |
```

「プラグイン」行を出すかどうかは、プロジェクトの既存 main 仕様ファイル (`$main_specs_root/{requirements,design}/*.md`) のメタデータ表を参照して既存スタイルに合わせる。

### 5.3 削除

Phase 5 冒頭で束縛した変数を使う:

```bash
git rm "$feature_dir/plan"/*.yaml 2>/dev/null || true
git rm "$feature_dir/requirements/{INV-*}.md" 2>/dev/null || true
git rm "$feature_dir/{他の作業履歴ファイル}"
```

mixed ファイルから抽出済みの場合、抽出元も削除:

```bash
git rm "$feature_dir/requirements/{元 mixed ファイル}.md"
```

### 5.4 空ディレクトリの除去

`-delete` は git 管理外動作なので、ディレクトリ存在確認を追加で挟む:

```bash
[ -d "$feature_dir" ] && find "$feature_dir" -type d -empty -delete
```

`$feature_dir` 自体が空になれば一緒に消える。

---

## Phase 6: 内容修正 (mixed 抽出ファイルの整合) [MANDATORY]

抽出した永続ファイルの相互参照を main 構成に合わせて更新する:

- 旧 mixed ファイルが参照していた他文書 (DES-011 等) のパスは、main 側の相対パスに直す (例: `../design/DES-011_*.md`)
- 削除した INV / plan / mixed への参照は除去する
- 章番号の振り直しに伴って残っていた古い `§N` 表記は新章番号に修正する

---

## Phase 7: 参照更新の一斉確認 [MANDATORY]

旧パス・旧名への参照を全文検索する。**対象は `git ls-files` の結果に限定**してリポジトリ構造に依存しないようにする:

```bash
# 検索パターン (AI が Phase 4 のリネーム計画から組み立てる)
PATTERN='{feature_name}_requirements\|{feature_name}_design\|inventory\.md\|REQ-XXX_{feature_name}\|INV-XXX_{feature_name}'

# git ls-files で対象拡張子のみ抽出して grep
git ls-files -z '*.md' '*.yaml' '*.yml' \
  | xargs -0 grep -nE "$PATTERN" 2>/dev/null \
  | grep -v '^CHANGELOG\.md:' \
  | grep -v '^\.claude/doc-advisor/'
```

検出された参照は新ファイル名・新パスに置換 (Edit ツール)。除外対象 (上記 grep で除外済み):

- `CHANGELOG.md` の過去記述 (履歴として残す)
- `.claude/doc-advisor/` 配下の自動生成インデックス (`toc/`, `index/`, `*_checksums.yaml`)

doc-advisor は Phase 0 で必須前提として確認済みのため、`.claude/doc-advisor/` 除外は常に有効。

除外を適用した上で残存 0 件になるまで確認する。

---

## Phase 8: フォーマット [MANDATORY]

dprint がインストールされている場合のみ実行する:

```bash
if command -v dprint >/dev/null 2>&1; then
  dprint check 2>&1 | tail -20
  # 差分があれば dprint fmt で適用
else
  echo "[skip] dprint 未導入のためフォーマット確認をスキップ"
fi
```

元から存在する別件の parse error が出たら本作業のスコープ外として記録する。

---

## Phase 9: 完了案内

完了後、以下を表示する:

```
{feature_name} を {main_specs_root} の main 仕様棚に統合しました:

  リネーム + 移動: N 件
  抽出 (mixed → clean): N 件
  削除 (plan / 作業履歴): N 件
  参照更新: N ファイル

次のステップ:
  - ToC 再生成: /update-forge-toc または /doc-advisor:create-specs-toc
  - commit: /anvil:commit または git commit
```

doc-advisor は Phase 0 で必須前提として確認済みのため ToC 再生成は常に案内する。anvil は任意のため `/anvil:commit または git commit` と並列で書く (anvil 未導入なら `git commit` を使えばよい)。

---

## 制約事項

- **plan/ は無条件削除**: 計画 YAML は完了済み feature にとって永続価値がない (履歴は git に残る)
- **棚卸し (INV-\* / inventory.md) も削除**: 着手時点の現状把握は完了後の参照価値ゼロ
- **抽出時は章番号を振り直す**: feature 内の章構成は永続原則の構成として最適化されていない。main では「概要 → 要件 → 適用対象 → 関連文書」の順に再構成する
- **既存 ID は重複しないよう main_existing_ids で確認**: Phase 4.2 の採番ロジックを必ず通す (ID 体系なしプロジェクトでは採番自体スキップ)
- **ID 体系はプロジェクトごとに違う**: forge 慣習 (REQ/DES/INV/TASK/FNC/NFR、3 桁ハイフン区切り) は **推奨** であって強制ではない。Phase 2 で `--id-prefixes` / `--id-digits` / `--id-separator` / `--no-id` を使い分ける
- **plugin 階層に依存しない**: feature_dir.parent を main_specs_root と仮定するが、適切でなければ Phase 2 で `--main-specs-root` を明示する
- **必須前提は Phase 0 で検査して即終了**: `.doc_structure.yaml` と doc-advisor は必須。フォールバック推測は誤動作の温床のため行わない
- **任意ツールのみ動作分岐**: dprint (Phase 8 のみ) / anvil (Phase 9 案内に並列表記) のみ「あれば使う・なければ別手段」で対応
- **本 skill は ToC / 検索インデックスを再生成しない**: 完了案内で別 skill (`/update-forge-toc`, `/doc-advisor:create-specs-toc` 等) を提示する。再生成は別 skill の責務
