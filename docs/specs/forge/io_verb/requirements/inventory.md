# io_verb 棚卸し: SKILL.md 上の痛点一覧

## メタデータ

| 項目       | 値                                                             |
| ---------- | -------------------------------------------------------------- |
| 棚卸し ID  | INV-001                                                        |
| feature ID | io_verb                                                        |
| 種別       | 棚卸し（要件定義書 §R6 実測ベースの原材料）                    |
| 作成日     | 2026-04-23                                                     |
| 対象       | `plugins/forge/skills/*/SKILL.md`（計 18 ファイル）            |
| 用途       | 設計書の「対象一覧」の原材料。解決策（ラッパー設計）は含まない |
| 関連要件   | REQ-001                                                        |

---

## 1. 集計

### 1.1 対象 SKILL.md

script 呼び出しを含む SKILL.md: **16 / 18 ファイル**（query-forge-rules / help は script 呼び出しなし）

| SKILL.md                      | script 参照行数 |
| ----------------------------- | --------------: |
| review/SKILL.md               |              25 |
| update-version/SKILL.md       |               9 |
| present-findings/SKILL.md     |               9 |
| evaluator/SKILL.md            |               6 |
| start-plan/SKILL.md           |               5 |
| start-implement/SKILL.md      |               5 |
| start-design/SKILL.md         |               5 |
| start-uxui-design/SKILL.md    |               4 |
| start-requirements/SKILL.md   |               4 |
| setup-doc-structure/SKILL.md  |               4 |
| doc-structure/SKILL.md        |               4 |
| reviewer/SKILL.md             |               3 |
| next-spec-id/SKILL.md         |               3 |
| clean-rules/SKILL.md          |               3 |
| setup-version-config/SKILL.md |               1 |
| fixer/SKILL.md                |               1 |

### 1.2 問題種類別件数

| 種類                                        | 件数 |
| ------------------------------------------- | ---: |
| flag 露出（`--foo` が SKILL.md に露出）     |   22 |
| 多引数呼び出し（flag が 3 つ以上連なる）    |    6 |
| 選択肢列挙（AI に status 等の値を選ばせる） |    3 |
| 禁止警告（script 直接呼ぶな型）             |    0 |

**禁止警告が 0 件**: 要件 R4 が懸念していた「別 script を直接呼ぶな」型の警告は、過去の refactor で既に除去済み。本要件で新規に削除する対象はない。evaluator/SKILL.md:130 の「Write ツールでの直接編集は禁止」は tool vs script の選択に関する指示であり、script 間の禁止警告ではない。

---

## 2. 問題箇所の詳細

### 2.1 flag 露出

#### パターン A: `resolve_doc_structure.py --doc-type`（7 件）

SKILL.md が「どの文書タイプを解決するか」を flag で指定している。AI は SKILL の文脈から自明に知っている情報。

| SKILL.md                    |  行 | 呼び出し                                          |
| --------------------------- | --: | ------------------------------------------------- |
| start-plan/SKILL.md         |  61 | `resolve_doc_structure.py --doc-type plan`        |
| start-implement/SKILL.md    |  56 | `resolve_doc_structure.py --doc-type plan`        |
| start-requirements/SKILL.md |  84 | `resolve_doc_structure.py --doc-type requirement` |
| start-design/SKILL.md       |  61 | `resolve_doc_structure.py --doc-type design`      |
| start-uxui-design/SKILL.md  |  73 | `resolve_doc_structure.py --doc-type requirement` |
| review/SKILL.md             | 781 | `resolve_doc_structure.py --type rules`           |
| review/SKILL.md             | 782 | `resolve_doc_structure.py --type specs`           |
| clean-rules/SKILL.md        |  67 | `resolve_doc_structure.py --type rules`           |

#### パターン B: `session_manager.py find --skill`（6 件）

| SKILL.md                    |  行 | 呼び出し                                             |
| --------------------------- | --: | ---------------------------------------------------- |
| start-plan/SKILL.md         |  94 | `session_manager.py find --skill start-plan`         |
| start-implement/SKILL.md    | 113 | `session_manager.py find --skill start-implement`    |
| start-requirements/SKILL.md |  97 | `session_manager.py find --skill start-requirements` |
| start-design/SKILL.md       |  97 | `session_manager.py find --skill start-design`       |
| start-uxui-design/SKILL.md  |  86 | `session_manager.py find --skill start-uxui-design`  |
| review/SKILL.md             | 263 | `session_manager.py find --skill review`             |

#### パターン C: `update_plan.py --batch` / `--id --status`（5 件）

| SKILL.md                  |  行 | 呼び出し                                                               | 備考                             |
| ------------------------- | --: | ---------------------------------------------------------------------- | -------------------------------- |
| review/SKILL.md           | 740 | `update_plan.py {dir} --batch` + stdin JSON                            | `updates` 配列を AI が組み立てる |
| present-findings/SKILL.md | 230 | `update_plan.py {dir} --batch` + stdin JSON                            | 重複グループ統合                 |
| present-findings/SKILL.md | 323 | `update_plan.py {dir} --id {id} --status in_progress`                  | 選択肢列挙（§2.3 参照）          |
| present-findings/SKILL.md | 324 | `update_plan.py {dir} --id {id} --status needs_review`                 | 選択肢列挙（§2.3 参照）          |
| present-findings/SKILL.md | 326 | `update_plan.py {dir} --id {id} --status skipped --skip-reason "理由"` | 選択肢列挙（§2.3 参照）          |

#### パターン D: `update_version_files.py --version-path / --filter / --optional`（3 件）

| SKILL.md                |  行 | 呼び出し                                                                      |
| ----------------------- | --: | ----------------------------------------------------------------------------- |
| update-version/SKILL.md | 153 | `update_version_files.py {path} {cur} {new} --version-path {path}`            |
| update-version/SKILL.md | 168 | `update_version_files.py {path} {cur} {new} [--optional]`                     |
| update-version/SKILL.md | 172 | `update_version_files.py {path} {cur} {new} --filter "{filter}" [--optional]` |

### 2.2 多引数呼び出し（`session_manager.py init`）

6 箇所。すべて 4〜6 個の flag を SKILL.md に記述。AI は各 flag の値をすべて個別に埋める必要がある。

| SKILL.md                    |  行 | flag 数 | 内容                                                          |
| --------------------------- | --: | ------: | ------------------------------------------------------------- |
| start-plan/SKILL.md         | 105 |       4 | `--skill --feature --mode --output-dir`                       |
| start-implement/SKILL.md    | 124 |       3 | `--skill --feature --task-id`                                 |
| review/SKILL.md             | 277 |       5 | `--skill --review-type --engine --auto-count --current-cycle` |
| start-requirements/SKILL.md | 108 |       4 | `--skill --feature --mode --output-dir`                       |
| start-design/SKILL.md       | 108 |       4 | `--skill --feature --mode --output-dir`                       |
| start-uxui-design/SKILL.md  |  97 |       4 | `--skill --feature --mode --output-dir`                       |

### 2.3 選択肢列挙（AI に値を選ばせる構造）

present-findings/SKILL.md:315-326 がメイン痛点。ユーザーの選択に応じて 3 種類の status 値を AI が組み立てる。

```
| ユーザー選択      | SKILL.md が指示する呼び出し                                                         |
| ----------------- | ----------------------------------------------------------------------------------- |
| 修正を選択        | update_plan.py {dir} --id {id} --status in_progress → fixer 呼び出し                |
| このまま対応しない| update_plan.py {dir} --id {id} --status needs_review                                |
| スキップ          | update_plan.py {dir} --id {id} --status skipped --skip-reason "理由"                |
```

R1.1（引数最小化）・R3（AI に選択させない）の明示的な違反。1 operation = 1 script に分解すべき候補。

### 2.4 禁止警告（0 件）

前述の通り、script 直接呼ぶな型の警告は現状 SKILL.md 上に残存しない。要件 R4 の「SKILL.md での禁止警告削除」は実施対象が 0 件となる（確認用の grep 済み）。

---

## 3. 集約: 関与する低レベル script

痛点と関連する低レベル script（本要件では変更しない）:

| script                             | 関係箇所数 | 主な痛点              |
| ---------------------------------- | ---------: | --------------------- |
| `session_manager.py` (find / init) |         12 | flag 露出・多引数     |
| `resolve_doc_structure.py`         |          8 | flag 露出             |
| `update_plan.py` (--batch / --id)  |          5 | flag 露出・選択肢列挙 |
| `update_version_files.py`          |          3 | flag 露出             |

この 4 本の低レベル script に対するラッパーを作ると、痛点 28 件のうち 28 件がカバーされる計算（ただし多引数 init の一部は SKILL 固有の文脈を持つため、ラッパー設計は設計書で検討）。

---

## 4. 設計書で決めること（本棚卸しの範囲外）

- ラッパー script の命名・インターフェース
- SKILL 配下のどこに置くか（skill 単位 vs 共有）
- ラッパーの実装順序・優先度
- 既存の配置ずれ（`extract_review_findings.py`）の移動先
