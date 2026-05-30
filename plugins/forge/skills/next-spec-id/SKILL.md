---
name: next-spec-id
user-invocable: false
description: |
  ブランチ間で衝突しない、次の Spec ID（SCR / DES / TASK / ADR 等任意プレフィックス）を発行する。
  要件定義書・設計書・計画書・ADR（アーキテクチャ決定記録）の作成時に ID の重複を防ぐために呼び出される。
argument-hint: ""
---

# next-spec-id スキル

## 概要

仕様書（要件定義書・設計書・計画書）の次の連番 ID を、全ブランチスキャンで安全に取得する。
ブランチ間での ID 重複を防止する。

forge 内の他スキルからの呼び出し専用（`user-invocable: false`）。

## スクリプト

`${CLAUDE_PLUGIN_ROOT}/skills/next-spec-id/scripts/scan_spec_ids.py`

### CLI インターフェース

```bash
SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/next-spec-id/scripts/scan_spec_ids.py"

# 次の ID を取得（プレフィックス指定）
python3 "$SCRIPT" SCR
python3 "$SCRIPT" DES
python3 "$SCRIPT" TASK
python3 "$SCRIPT" ADR   # アーキテクチャ決定記録（設計書と同ディレクトリに配置）

# プロジェクトルート指定
python3 "$SCRIPT" --project-root /path/to/project SCR

# .doc_structure.yaml のパス指定
python3 "$SCRIPT" --doc-structure /path/to/.doc_structure.yaml SCR
```

### 出力形式（JSON）

#### 正常時

```json
{
  "status": "ok",
  "next_id": "SCR-016",
  "prefix": "SCR",
  "max_number": 15,
  "base_branch": "develop",
  "branches_scanned": 7,
  "ids_found": 15,
  "duplicates": []
}
```

#### 重複検出時

```json
{
  "status": "ok",
  "next_id": "SCR-016",
  "prefix": "SCR",
  "max_number": 15,
  "base_branch": "develop",
  "branches_scanned": 7,
  "ids_found": 17,
  "duplicates": [
    {
      "id": "SCR-013",
      "branches": ["feature/edit_pickup", "origin/feature/print_letter"]
    },
    {
      "id": "SCR-014",
      "branches": ["feature/edit_pickup", "origin/feature/print_letter"]
    }
  ]
}
```

#### エラー時

```json
{
  "status": "error",
  "message": ".doc_structure.yaml が見つかりません"
}
```

## プレフィックスについて

スクリプトは任意のプレフィックスを引数で受け取る。ID 体系の知識は持たない。

どのプレフィックスを使うかは **呼び出し側のスキル** が決定する:

1. プロジェクト固有の `spec_format.md` やルールがあればそれに従う
2. なければ forge の `${CLAUDE_PLUGIN_ROOT}/docs/spec_format.md` をフォールバック参照

## 他スキルからの呼び出し方

### 要件定義（start-requirements）での例

```bash
SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/next-spec-id/scripts/scan_spec_ids.py"
RESULT=$(python3 "$SCRIPT" SCR)
# → {"status": "ok", "next_id": "SCR-016", ...}
```

JSON の `next_id` フィールドをファイル名の先頭に使用する。

### 設計（start-design）での例

```bash
RESULT=$(python3 "$SCRIPT" DES)
# → {"status": "ok", "next_id": "DES-004", ...}
```

### ADR（アーキテクチャ決定記録）での例

設計判断の記録として ADR を新規作成する際は、番号衝突を防ぐため必ず採番する（手動で「既存の次」と判断しない）:

```bash
RESULT=$(python3 "$SCRIPT" ADR)
# → {"status": "ok", "next_id": "ADR-005", ...}
```

ADR は設計書と同じディレクトリに配置するため、`.doc_structure.yaml` に ADR 専用ディレクトリが無くても git スキャンで既存 ADR を検出できる。

## 動作概要

1. `.doc_structure.yaml` から specs の `root_dirs` を取得
2. `git fetch --quiet` でリモートを最新化
3. ベースブランチ（develop or main）を特定
4. ベースブランチから派生した全ブランチをスキャン（ローカル + リモート）
5. `git ls-tree` で各ブランチの specs ディレクトリを走査
6. 指定プレフィックスの最大番号を検出
7. 重複があれば `duplicates` に記録
8. 最大番号 + 1 を返す
