---
name: evaluator
user-invocable: false
description: |
  レビュー指摘を吟味し修正/スキップ/要確認を判定する。
  /forge:review から perspective ごとに並列起動される。
argument-hint: "(内部使用)"
---

# /evaluator Skill

レビュー指摘事項を吟味し、「修正する / スキップ / 要確認」を判定する AI 専用 Skill。
perspective ごとに並列起動され、担当の `review_{perspective}.md` の指摘を吟味する。
全モードで AI 推奨（`recommendation`）を `plan.yaml` に記録する。`--interactive` モードでは `/forge:present-findings` が人間の最終判断に基づき `plan.yaml` を上書き更新する。

---

## 設計原則

| 原則                    | 説明                                                                                           |
| ----------------------- | ---------------------------------------------------------------------------------------------- |
| **subagent として動作** | `/forge:review` から general-purpose subagent として起動される。メインコンテキストを消費しない |
| **perspective ごとに並列起動** | オーケストレーターが perspectives の数だけ evaluator を並列起動する。各 evaluator は担当の `review_{perspective}.md` のみ処理する |
| 判定は AI の責務        | レビューエンジンの出力をそのまま修正に渡さない。必ず吟味を挟む                                 |
| 参考文書に基づく判定    | ルール・設計意図を参照して false positive を排除する                                           |
| 副作用リスクの考慮      | 修正が他箇所に影響しないか確認してから判定する                                                 |
| 渡された情報のみ使用    | 参考文書・関連コードの収集・探索は行わない                                                     |
| 全モード共通ロジック    | auto / interactive を問わず、plan.yaml 更新・should_continue 判定を実行                       |

---

## 入力

呼び出し元（/forge:review）から以下を受け取る:

| 項目             | 必須 | 説明                                                                                      |
| ---------------- | ---- | ----------------------------------------------------------------------------------------- |
| session_dir      | 必須 | セッションワーキングディレクトリのパス                                                    |
| レビュー種別     | 必須 | `code` / `requirement` / `design` / `plan` / `generic`                                    |
| perspective_name | 必須 | 担当する perspective の識別子（例: `logic`, `resilience`）                           |
| 修正対象フラグ   | 必須 | `--auto`: 🔴+🟡を対象 / `--auto-critical`: 🔴のみ対象 / `--interactive`: 全件AIが推奨判定 |

※ レビュー結果は `{session_dir}/review_{perspective_name}.md` から読む
※ 参考文書・対象ファイル・related_code はすべて `{session_dir}/refs.yaml` から読む

---

## ワークフロー

### Step 1: session_dir からデータを読み込む

1. `{session_dir}/refs.yaml` を Read して `reference_docs` / `related_code` / `target_files` を取得
2. `{session_dir}/review_{perspective_name}.md` を Read してレビュー結果（指摘事項リスト）を取得
3. `refs.yaml` の `reference_docs` / `related_code` のパスを全て Read して内容を把握する

（収集・探索は行わない。`refs.yaml` に記載されたパスのみ使用する）

### Step 2: 各指摘を吟味する [MANDATORY]

修正対象フラグに応じて吟味対象を絞り込む:

- `--auto`: 🔴致命的 + 🟡品質問題
- `--auto-critical`: 🔴致命的のみ
- `--interactive`: 全件（🔴🟡🟢）

> **吟味対象外の指摘の扱い**: `--auto` では 🟢 が、`--auto-critical` では 🟡🟢 が吟味対象外となる。吟味対象外の指摘は plan.yaml に `recommendation: skip`、`reason: "吟味対象外（モードによるフィルタ）"` として記録し、`status` を `skipped` に更新する。

#### 判定の原則 [MANDATORY]

**reviewer の主張を鵜呑みにしない。** reviewer はレビューエンジンの出力であり、false positive を含む。evaluator の責務は各指摘が本当に問題かを**対象ファイルを読んで検証する**ことである。

- **対象ファイルを Read して問題の実在を確認できない場合は skip とする**
- reviewer が「L77 に問題がある」と主張しても、L77 を読んで確認する
- 入力バリデーション不足の指摘は、上流のバリデーションコードを確認してから判定する
- 実行順序に依存する指摘は、呼び出し元のワークフローを確認してから判定する

#### 吟味の5観点

各指摘について以下の5つの観点で評価し、`修正する / スキップ / 要確認` を判定する:

| 観点                   | 確認内容                                                                               |
| ---------------------- | -------------------------------------------------------------------------------------- |
| **対象ファイルの確認** | 指摘された箇所を Read し、reviewer の主張が正しいか検証する [MANDATORY — 全件で実施] |
| **ルール照合**         | 参考文書（ルール・規約）に照らして本当に違反しているか                                 |
| **設計意図**           | 現状の実装に意図がある可能性はないか（例: `\|\| true` は意図的な設計かもしれない）     |
| **副作用リスク**       | この修正が他の箇所に影響しないか（例: `set -e` + `pipefail` の組み合わせによるデグレ） |
| **false positive**     | エンジンの誤認識・過剰指摘ではないか（例: optional なフィールドを必須と誤判定、バリデーション済みの入力を未検証と誤認） |

**判定結果:**

- **修正する**: 対象ファイルを読んで問題の実在を確認でき、副作用リスクが低い → `recommendation: fix`
- **スキップ**: 対象ファイルを読んで問題が存在しない・設計意図がある・既に対処済み → `recommendation: skip`（理由を記録）
- **要確認**: 対象ファイルを読んでも判断が難しい → `recommendation: needs_review`

**auto_fixable フラグ:**

`recommendation: fix` の指摘に対して、さらに `auto_fixable: true/false` を判定する:

| 条件             | 説明                                  |
| ---------------- | ------------------------------------- |
| 修正が一意       | 選択肢がなく、修正内容が1通りに決まる |
| 影響が局所的     | 他の項目や設計判断に波及しない        |
| 機械的に修正可能 | 判断・設計決定を伴わない              |

**auto_fixable の例（コード）**: 末尾スペース削除、タイポ修正、未使用importの削除、単純な置換
**auto_fixable の例（文書）**: フラグ名・項目名の単純置換、条件チェック一行の追加、メニューへの項目追加、注記の追加
**auto_fixable にしない例**: アーキテクチャ変更、複数の対応案がある問題、影響範囲が広い修正

判断に迷ったら `auto_fixable: false` とする。

> **注意**: `auto_fixable: true` と判定する前に、修正が本当に一意に決まるか対象ファイルのコンテキスト（上流のバリデーション、呼び出し元のワークフロー、関連する他ファイル）を確認すること。

### Step 3: 結果ファイルを書き出す [MANDATORY]

evaluator は 2 種類のアーティファクトを書き出す:

1. `eval_{perspective_name}.json` — 判定メタ情報（plan.yaml に反映される真実）
2. `review_{perspective_name}.md` — evaluator 整形済みの最終系 Markdown
   （`write_interpretation.py` 経由で**常に**全面書き換え・判断分岐なし）

**「書き換えるか否か」の判断は行わない。** 判定に同意する場合でも、
present-findings が段階的提示に必要とする情報粒度（該当コード抜粋・ルール引用・修正案）に
整形する責務を evaluator が負う。reviewer 原文は `write_interpretation.py` が
`.raw.md` に自動バックアップするため失われない。

#### 3-1: review_{perspective_name}.md の全面書き換え（常に実行）[MANDATORY]

判定の同意・不同意にかかわらず**必ず実行**する。スキップ不可。

**必ず `write_interpretation.py` 経由で書き換える**（Write ツールでの直接編集は禁止）。
スクリプトが `.raw.md` バックアップ・冪等性を保証する。

```bash
cat <<'EOF' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session/write_interpretation.py \
  {session_dir} --perspective {perspective_name}
# evaluator 評価（perspective: {perspective_name}）

## 🔴致命的問題
1. **[問題名]**: [問題の所在 — 1-2文]
   - 箇所: `path/to/file.ext:42-58`
   - 該当コード:
     ```<lang>
     (reviewer 原文または evaluator が対象ファイルから抜粋したコード)
     ```
   - なぜ問題か: [規約・設計意図 — reference_docs からの引用は `> ...` 形式]
   - 修正案:
     | 現在 | 修正後 |
     | ---- | ------ |
     | ...  | ...    |
     ```<lang>
     (修正後コード例。A 案 / B 案がある場合は両方)
     ```
   - 推奨: [1-2 文のまとめ]

## 🟡品質問題
(同上)

## 🟢改善提案
(同上)

## ❌却下（evaluator 判定: false positive / 設計意図 / 既対処）
1. **[問題名]**: [却下理由]
   - 箇所: `path/to/file.ext:42`
   - 却下根拠: [evaluator が Read して確認した事実 / 関連コード・規約の引用]

## サマリー
- 修正推奨: X 件
- 却下: Y 件
EOF
```

スクリプトの動作:
- 初回実行: `review_{perspective}.md` を `review_{perspective}.raw.md` にバックアップ → stdin の内容で上書き
- 2 回目以降（`.raw.md` が既に存在）: `.raw.md` は保護（再作成しない）→ `review_{perspective}.md` のみ上書き
- 冪等性: 同一内容での連続呼び出しは結果が変わらない

**書き換えの品質要件:**
- reviewer の要点を保持しつつ、対象ファイルを Read した確認結果を反映する
- present-findings が現状の提示フォーマット（段階的解決）で説明できる粒度で記述する
  （「問題の所在」「なぜ問題か」「修正案」「推奨と要約」を各項目で揃える）
- 却下項目は削除せず「❌却下」セクションで保持し、却下理由を evaluator 視点で説明する
- 推測・曖昧表現を避け、Read した事実のみを記述する
- フォーマットは reviewer の `templates/review.md` 互換を維持する

#### 3-1.1: ローカル ID 順序の保持 [MANDATORY]

`eval_{perspective_name}.json` に記載する `updates[].id` は **reviewer 原文の出現順に対応する 1-based ローカル ID** である。`review_{perspective}.md` を書き換える際、**この順序と一致するよう各項目を並べる責務**が evaluator にある。

**契約:**
- **ローカル ID = 項目の登場順**。reviewer 原文で n 番目に登場した項目が local_id=n となる
- `review_{perspective}.md` 書き換え時、🔴 / 🟡 / 🟢 / ❌却下 を跨いで **原文の出現順を保持**する
- severity セクション順 (🔴→🟡→🟢→❌) は維持してよいが、**同 severity 内の項目順は原文の出現順に従う**
- 項目を新設 / 削除 / 結合してはならない。原文の全項目を保持し、却下判断は `❌却下` セクションへ移動するだけ

**なぜ重要か:**
`merge_evals.py` は `eval_{perspective_name}.json` の local_id を `plan.yaml` 上の項目順（= reviewer 原文の出現順）と突き合わせてグローバル ID に変換する。evaluator が `review_{perspective}.md` 内の項目順序を変えると、**reviewer が検出した順序と evaluator が判定した順序の対応関係が崩れ**、`plan.yaml` の判定結果が別項目に誤マッピングされる。

**具体例:**
reviewer 原文が `1=A, 2=B, 3=C` （🔴 A / 🟡 B / 🟢 C）なら、evaluator は
- `eval_*.json` の `updates`: `[{id:1,...}, {id:2,...}, {id:3,...}]`
- `review_{perspective}.md`: 🔴 セクションに A（書き換え or ❌却下移動）、🟡 セクションに B、🟢 セクションに C（同様）

のように、**同じ local_id=N の項目は `review_{perspective}.md` 上で N 番目に出現する**ことを保証する。B を 🔴 に昇格させて順序を入れ替える等の改変は禁止（severity 変更は `severity` フィールドではなく `recommendation` / `reason` で表現する）。

**reviewer 原文に完全同意する場合のコスト削減:**
- reviewer 原文の構造が十分であれば、原文を踏襲して必要な情報を補完する軽整形で済む
- 該当コード抜粋・ルール引用が既に含まれている場合はそのまま流用する
- 追加の確認（対象ファイル Read）は Step 2 の判定プロセスで既に実施済みのため追加コストは小さい

> **重要**: present-findings は定常フローで target_files / reference_docs を再 Read しないため、
> evaluator が書き換え時に「該当コード抜粋」「ルール引用」「修正案」を
> `review_{perspective}.md` に**含めておく責務**がある。省略すると present-findings の提示品質が劣化する。
>
> `.raw.md` は監査・デバッグ用。定常フローで読み手（present-findings / fixer）は参照しない。

#### 3-2: eval_{perspective_name}.json の書き出し

吟味結果を JSON に構造化し、`{session_dir}/eval_{perspective_name}.json` に Write する。**plan.yaml には直接書き込まない**（並列 agent の出力契約パターン。設計書 §4 参照）。

以下のルールで各項目の更新内容を決定する:

- `recommendation: fix` → `status: pending` のまま（fixer が後で `fixed` にする）。`auto_fixable` と `reason` を付与
- `recommendation: skip` → `status: skipped` / `skip_reason` と `reason` を記録
- `recommendation: needs_review` → `status: needs_review` / `reason` を記録

結果ファイルのフォーマット:
```json
{
  "perspective": "{perspective_name}",
  "updates": [
    {"id": 1, "status": "pending", "recommendation": "fix", "auto_fixable": true, "reason": "判定理由"},
    {"id": 2, "status": "skipped", "skip_reason": "理由", "recommendation": "skip", "reason": "判定理由"},
    {"id": 3, "status": "needs_review", "recommendation": "needs_review", "reason": "判定理由"}
  ]
}
```

Write 先: `{session_dir}/eval_{perspective_name}.json`

> **plan.yaml の更新は orchestrator の責務**: 全 evaluator 完了後、review orchestrator が `eval_*.json` を収集し `merge_evals.py` を1回だけ呼び出す。これにより並列書き込み競合が根本的に排除される。
> **interactive モードの場合**: orchestrator が plan.yaml を更新した後、present-findings がユーザーの最終判断で上書き更新する。

### Step 4: 次サイクル判定

全モード共通で判定する:

- `recommendation: fix` が0件 → `should_continue: false`（修正不要）
- `recommendation: fix` が1件以上 → `should_continue: true`（fixer を呼び出す）

> **interactive モードの場合**: `should_continue: true` でも、review オーケストレーターは
> fixer を直接呼び出さず present-findings を経由する。present-findings がユーザーの判断に基づき fixer を制御する。

---

## 出力

結果ファイルを書き出した旨を呼び出し元（/forge:review）に報告する。
全モードで `should_continue` フラグを返す。

```
## 吟味結果（perspective: {perspective_name}）

結果ファイル: {session_dir}/eval_{perspective_name}.json

### 修正する（X件）
1. **[問題名]**
   - 判定理由: [なぜ修正すべきか]

### スキップ（Y件）
1. **[問題名]**
   - スキップ理由: [false positive / 設計意図 / リスク等]

### 要確認（Z件）
1. **[問題名]**
   - 確認理由: [判断が難しい理由]

### 判定サマリー
- 修正する: X件
- スキップ: Y件
- 要確認: Z件
- 次サイクル: [継続 / 終了]
```

---

## エラーハンドリング

| エラー                                              | 対応                                                                |
| --------------------------------------------------- | ------------------------------------------------------------------- |
| `session_dir` が存在しない / `refs.yaml` が読めない | エラーを呼び出し元に返して処理を中断する                            |
| `review_{perspective_name}.md` が空 / 読めない       | `should_continue: false` で呼び出し元に返す                         |
| 参考文書が読めない                                  | 参考文書なしで吟味を続行し、その旨を記録する                        |
| 判定困難な指摘が多数                                | 「要確認」として全件を `plan.yaml` に書き込み呼び出し元に返す       |
