# DES-047 review 本体の修正安全ガードレール設計書

## メタデータ

| 項目     | 値                     |
| -------- | ---------------------- |
| 設計 ID  | DES-047                |
| 関連要件 | REQ-013                |
| 関連設計 | DES-046、forge:ADR-066 |
| 作成日   | 2026-07-19             |

## 1. 概要

`/forge:review` 本体が `confirmed_fix` を適用するときの安全境界を定める。修正と安全検証は
review 本体の責務であり、msg-review を含むバックエンドは所見配列を返した時点でラウンドを終える。

安全境界は、所見単位の逐次適用、対象ファイル allowlist、無関係な変更の禁止、構文検証、
ラウンド終了時の独立した変更ファイル確認で構成する。

## 2. 修正フロー

### 2.1 baseline

`confirmed_fix` の適用前に、対象ファイルの構文・フォーマット違反を取得する。

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/capture_syntax_baseline.py" \
  --files-json '<target_files>'
```

baseline は既存違反と今回の修正による新規違反を区別するために使う。

### 2.2 所見単位の逐次適用

各 `confirmed_fix` を次の順で 1 件ずつ処理する。

1. 当該所見の修正だけを適用する
2. 実際に編集したファイルを記録する
3. `verify_fix_safety.py` で allowlist と構文を検証する
4. 結果を review 本体が判断する
5. 問題があれば本体が編集を戻し、対応しなかった理由を記録する
6. 正当な波及修正を維持する場合は理由を記録する

複数所見をまとめて適用してから検証しない。修正は当該所見が指摘した内容に限定し、無関係な
体裁変更やリファクタリングを同時に行わない。

### 2.3 安全検証 CLI

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/verify_fix_safety.py" \
  --allowed-files-json '<target_files>' \
  --modified-files-json '<当該所見で編集したファイル>' \
  --baseline-json '<baseline>'
```

検証内容:

- `modified_files - allowed_files` を `allowlist_violations` として返す
- Markdown、JSON、YAML、TOML は dprint で検証する
- Python は副生成物を作らない `ast.parse` で検証する
- Shell は `bash -n` で検証する
- 削除済みファイルは構文検証を省略して記録する
- 未対応拡張子はエラーにせず省略理由を記録する

スクリプトは検出と報告だけを行い、ファイルを書き換えたり自動ロールバックしたりしない。

### 2.4 ラウンド終了時の独立検証

所見ごとの自己申告に依存しない変更ファイル集合を取得する。

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/collect_modified_files.py"
```

出力の `files` を、`target_files` と正当な波及修正として記録したファイルの和集合に照らして
`verify_fix_safety.py` で再検証する。パス抽出は NUL 区切りの git porcelain 出力をスクリプトが
処理し、AI が行や rename 表現を手作業でパースしない。

## 3. 出力と判断

`verify_fix_safety.py` は次の構造を返す。

```json
{
  "status": "ok",
  "allowlist_violations": [],
  "syntax_errors": {},
  "syntax_skipped_preexisting": [],
  "syntax_skipped_unsupported": [],
  "syntax_skipped_deleted": [],
  "syntax_ok": []
}
```

`allowlist_violations` または `syntax_errors` が非空なら `status: "violations"` とする。
review 本体は、事故的な逸脱なら当該所見の編集を戻し、正当な波及修正なら理由を記録して維持する。

## 4. 責務境界

| 責務                                    | 所在           |
| --------------------------------------- | -------------- |
| 所見の 3 値判定と配列化                 | バックエンド   |
| `confirmed_fix` の決定                  | review 本体    |
| 修正の適用と取り消し                    | review 本体    |
| baseline、allowlist、構文の決定論的検査 | review scripts |
| 次ラウンドと終端の判定                  | review 本体    |

## 5. テスト設計

- `test_capture_syntax_baseline.py`
  - dprint の成功、対象外、違反、利用不能を区別する
- `test_verify_fix_safety.py`
  - allowlist 逸脱と拡張子別構文エラーを検出する
  - 既存違反、未対応拡張子、削除済みファイルを区別する
  - 検証がファイルを書き換えない
  - Python 検証が `__pycache__` を生成しない
- `test_collect_modified_files.py`
  - modified、added、deleted、renamed、untracked を抽出する
  - 空白、非 ASCII、改行、`->` を含むパスを正しく扱う

## 6. 未確定事項

なし。
