---
name: update-onboarding-copy
description: |
  onboarding の COPY 範囲（利用プロジェクトの CLAUDE.md へ転記される規範の蒸留要旨）を、
  供給源文書の現状と突合して更新する。forge / anvil の規範文書（plugins/forge/docs/ 等）で
  規範の追加・削除・反転を行ったとき、または蒸留要旨の陳腐化を疑ったときに使う。
  トリガー: "COPY 範囲を更新", "onboarding の規範ブロック", "蒸留要旨の見直し"
allowed-tools: Read, Edit, Bash, AskUserQuestion
---

# update-onboarding-copy

`plugins/forge/skills/onboarding/SKILL.md` の COPY 範囲（`FORGE_ONBOARDING_COPY_START` / `_END` マーカー内）を保守する。このスキルは COPY 範囲の内容更新と再転記のみを行う。**供給源文書そのものは編集しない**（供給源の改編は本スキルの起動契機であって作業対象ではない）。転記の仕組み（`onboarding_block.py`・マーカー方式・テスト）にも手を入れない。

## When To Use

- forge / anvil の規範文書で規範の**追加・削除・反転**を行った直後（字句修正・例の差し替えだけなら不要。要旨は抽象度が高く、字句変更にほぼ影響されない）
- 蒸留要旨が供給源と食い違っている疑いがあるとき
- COPY 範囲へ規範を足す・削る提案を検討するとき

供給源 → 要旨のドリフトを機械検出する仕組みは意図的に設けていない（hash 方式は字句修正でも失報し、無視される監視になる）。取りこぼしは本スキル起動時の突合で回収する。被害は「要旨が一時的に古い（全文の正本は無傷）」に留まる。

## 選定基準（判断の正本）

### 載せるもの

**会話直の作業（スキルを起動しない通常会話での実装・文書編集・調査）で AI の行動を変える規範だけ**を載せる。

- 「〜を書かない」「〜したら同じ変更で〜する」のような、会話直の編集・実装でも守るべき禁止・義務は対象
- スキル経由の作業でしか使わない内容は対象外。スキルは自分の調査 Phase・必須参照文書で規範を読むため、CLAUDE.md に無くても届く。COPY 範囲が塞ぐ穴は「スキル非経由の作業で規範が 0 になる」ことだけである

### 載せないもの

- format 文書のテンプレート本体（要件定義書・設計書・計画書の構成・記入例）
- レビュー用の重大度カタログ・criteria（SSOT 参照表・チェック順・判定ルール）
- スキルのワークフロー手順・agent への作業指示書
- 特定作業でのみ効く技術リファレンス（例: バージョンマイグレーション実装パターン）
- 特定分野の数値カタログ（例: UX/UI のタッチターゲット 44pt・コントラスト比。UI 作業が無いプロジェクトにはノイズ［利用者決定 2026-08-15］）
- 本リポジトリ固有の名称・パス・事情（COPY 範囲は配布物であるため）

### 粒度

- **蒸留要旨方式**: 供給源の全文・節構成を写さず、行動を変える規範だけを条文粒度で短文化する
- 出典文書への参照は書かない。転記先の CLAUDE.md では `${CLAUDE_PLUGIN_ROOT}` が解決されず、転記ブロックの定型注記が「実体を読むには onboarding スキルを起動する」と案内済みであるため
- 分量の目安は 60〜130 行。CLAUDE.md は毎リクエスト読み込まれるため、増やす価値と常時トークンコストを比較して判断する

## 供給源マップ

COPY 範囲の各節と蒸留元の対応。供給源側で規範の追加・削除・反転があったときに該当節を見直す。

| COPY 範囲の節          | 供給源（蒸留元）                                                                                                                                                                                                                                           |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| forge 文書規範         | `plugins/forge/docs/` の document_style_guide / spec_format / spec_design_boundary_spec / spec_priorities_spec / design_principles_spec / adr_principles_spec / additive_development_spec §6（frontmatter）                                                |
| forge 実装規範         | `plugins/forge/docs/` の additive_development_spec §1–§3 / scope_proportionality_spec、`plugins/forge/skills/start-implement/docs/task_execution_spec.md`、`plugins/anvil/skills/impl-issue/references/`（既存資産優先・推測禁止・共用部品・検証の裏取り） |
| forge 機密情報         | `plugins/forge/docs/sensitive_information_spec.md`                                                                                                                                                                                                         |
| forge 提示・議論の作法 | `plugins/forge/docs/consult_principles_spec.md`、`plugins/forge/skills/start-requirements/docs/requirements_interactive_workflow.md` 対話の基本原則 8（議論モードと決定モードの区別）                                                                      |
| forge プロジェクト文書 | COPY 範囲が正本（供給源からの蒸留ではない）                                                                                                                                                                                                                |
| forge 重要規約         | 同上（COPY 範囲が正本）                                                                                                                                                                                                                                    |

anvil 由来の規範を forge の COPY 範囲に載せることは利用者決定（2026-08-15）。転記するのは規範そのものであり anvil 文書への参照ではないため、配布境界に抵触しない。詳細版（各内蔵 docs・references）はスキル文脈の正本として残り、COPY 範囲はその**要旨**の出力構築点となる（要旨と詳細の関係であり、同一指示の重複ではない）。

重複統制:

- 差分 feature の frontmatter 規範は additive_development_spec §6 が正本。COPY 範囲では「`feature_type: temporary-feature-*` を付ける」の一言に畳む（format 3 文書の該当節は §6 の再掲であり、供給源として数えない）
- 「判断に迷う検出は混入として扱う」は sensitive_information_spec §3 と criteria/review_criteria_secrets.md に同旨があるが、COPY 範囲には 1 回だけ書く

## Workflow

### 1. 突合

供給源マップに従い、変更のあった供給源（不明なら全供給源）の本文と、現行 COPY 範囲の該当節を突き合わせる。差分は「規範の追加・削除・反転」だけを拾い、載せる/載せないは上記の選定基準で判定する。

### 2. COPY 範囲を編集する

`plugins/forge/skills/onboarding/SKILL.md` のマーカー内だけを編集する。制約:

- `##` 見出しは必ず `forge` で始める（`tests/forge/onboarding/` が検証する）
- 蒸留要旨方式・分量の目安を維持する
- マーカーの外（必読文書リスト・実行フロー）は本スキルの対象外

### 3. 整形と検証

```bash
dprint fmt plugins/forge/skills/onboarding/SKILL.md
python3 -m unittest tests.forge.onboarding.test_onboarding_block -v
```

### 4. CLAUDE.md へ再転記する

```bash
python3 plugins/forge/skills/onboarding/scripts/onboarding_block.py --check
```

`stale` なら AskUserQuestion で転記の承認を一行で求め、承認されたら `--write` を実行し、再度 `--check` が `fresh` を返すことを確認する。断られたら書き込まず終了する（次回 onboarding 実行時に再提案される）。

## Validation

- `tests.forge.onboarding.test_onboarding_block` が全 pass
- `onboarding_block.py --check` = `fresh`（転記した場合）
- COPY 範囲の各節が供給源マップと対応していること
