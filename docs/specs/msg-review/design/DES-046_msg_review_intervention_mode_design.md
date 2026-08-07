# DES-046 review 本体の介入軸設計書

## メタデータ

| 項目     | 値                     |
| -------- | ---------------------- |
| 設計 ID  | DES-046                |
| 関連要件 | REQ-013                |
| 関連設計 | DES-045、forge:ADR-066 |
| 作成日   | 2026-07-19             |

## 1. 概要

`/forge:review` 本体は、バックエンドから受け取った所見を介入軸に従って自動修正候補と対象外へ
振り分ける。所見の評価、修正、再レビュー、完了判定は本体の責務であり、msg-review を含む
バックエンドは関与しない。

バックエンドは共通 parser 契約を満たす `critical` / `major` / `minor` の所見だけを返す。
重大度が欠落した応答は `failure` となるため、`severity: unclassified` は介入軸へ渡らない。

## 2. 介入軸

| 指定                         | 内部 mode       | 自動修正候補    | 対象外       |
| ---------------------------- | --------------- | --------------- | ------------ |
| `--interactive` または未指定 | `auto`          | critical、major | minor        |
| `--auto-critical`            | `auto-critical` | critical        | major、minor |
| `--auto`                     | `auto`          | critical、major | minor        |

`--interactive` の段階的な所見提示は実装しない。現在は `auto` と同じ振り分けを適用する。

## 3. 振り分け設計

### 3.1 CLI

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/gate_findings.py" \
  --findings-json '<バックエンドが返した所見配列>' \
  --mode <auto-critical|auto>
```

### 3.2 出力

```json
{
  "auto_fix": [],
  "excluded": []
}
```

`auto_fix` は重大度による候補であり、修正確定ではない。本体は各候補をレビュー基準、対象の実態、
重点観点、到達目標に照らして評価し、妥当な所見だけを `confirmed_fix` とする。

`excluded` は現在の mode の自動修正範囲外である。応答に不正な severity が混入した場合は防御的に
`excluded` へ入れるが、通常は共通 parser が重大度欠落を `failure` とするため到達しない。

### 3.3 本体フロー

1. バックエンドから `findings` と所見配列を受け取る
2. `gate_findings.py` で `auto_fix` / `excluded` に分ける
3. `auto_fix` を所見ごとに評価して `confirmed_fix` を決める
4. `confirmed_fix` が 0 件なら再レビューを要求せず終端処理へ進む
5. 1 件以上なら本体が修正と安全検証を行う
6. 同じ `review_id` の次ラウンドをバックエンドへ要求する

所見が `findings` のままでも `confirmed_fix` が 0 件なら、承認とは区別した未対応所見ありの終端とする。

## 4. 責務境界

| 責務                                   | 所在         |
| -------------------------------------- | ------------ |
| 応答本文の完了宣言・重大度・位置の解釈 | バックエンド |
| 3 値と所見配列の返却                   | バックエンド |
| 介入軸の解釈                           | review 本体  |
| 所見の重大度別振り分け                 | review 本体  |
| 所見評価、修正、安全検証               | review 本体  |
| 再レビューと終端の判定                 | review 本体  |

## 5. テスト設計

- `test_gate_findings.py`
  - `auto-critical` は critical だけを `auto_fix` に入れる
  - `auto` は critical と major を `auto_fix` に入れる
  - minor は両 mode で `excluded` に入れる
  - 不正 severity は防御的に `excluded` に入れる
- `test_parse_findings.py`
  - severity 欠落は `failure` となり所見配列を返さない
  - 完了宣言行は最終有効行かつ一意である

## 6. 未確定事項

なし。
