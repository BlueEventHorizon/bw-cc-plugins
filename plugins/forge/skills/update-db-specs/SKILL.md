---
name: update-db-specs
description: |
  要件定義書・設計書の追加・改訂後に検索インデックスを最新化する。
  新しい仕様文書を /forge:query-db-specs で検索可能にしたいときに実行する。
  トリガー: "仕様検索インデックス更新", "仕様検索インデックス再構築", "設計書インデックス更新"
user-invocable: true
argument-hint: ""
allowed-tools: Read, Bash, Skill
---

仕様文書（key `specs`）の検索インデックス（ToC）を再構築するラッパー。`.doc_structure.yaml` から
specs の対象パスを解決して `doc-advisor:index-docs` へ転送する。

> ❌ 自己再帰禁止: `Skill` ツールで自分自身や他の `/forge:*-db-*` 抽象 SKILL を呼ばないこと（無限再帰）

## Procedure

### Step 1: `.doc_structure.yaml` を読んで呼び出しモードを決定する

`Read` ツールで `.doc_structure.yaml` を読み、`specs.root_dirs` と `specs.patterns.exclude` を取得する。

**モード判定（必須）: 判定軸は `exclude` の有無のみ。グロブの有無では分岐しない**
（`doc-advisor:index-docs` の `--dirs-json` はグロブメタ文字 `*` `?` `[` を展開できるため）:

| 条件 | モード |
| ---- | ------ |
| `exclude` が空（`[]`） | **dirs モード**: `--dirs-json` に `root_dirs` をそのまま渡す（doc-advisor が rglob / グロブ展開する） |
| `exclude` が非空 | **ファイル列挙モード**: `resolve_doc_structure.py` → `--paths-json` |

> ⚠️ **exclude を `--dirs-json` + `--exclude-json` で渡してはならない**: forge の `exclude`（例 `[plan]`）は
> **パスの任意の階層**にある同名ディレクトリにマッチする（裸名マッチ）が、doc-advisor の `--exclude-json` は
> **完全一致 / パス前置きマッチ**のため、裸名 `plan` は `docs/specs/forge/plan/` を除外できない。
> exclude が非空のときは forge 側の `resolve_doc_structure.py` でファイル列挙し、`--paths-json` で渡すこと。
> （現在の specs 設定は `exclude: [plan]` のため、このプロジェクトでは常にファイル列挙モードになる）

**ファイル列挙モードの場合のみ** 以下を実行する:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py" --type specs
```

stdout の JSON から `specs` 配列（project-root-relative パスのリスト）を読む。
`status` が `error` の場合は `message` を報告して終了する。

### Step 2: index-docs へ転送

モードに応じて `Skill` ツールで `doc-advisor:index-docs` を **1 回だけ** 呼ぶ:

```
# dirs モード（exclude が空）— root_dirs をそのまま渡す（グロブ含む場合も doc-advisor が展開）
/doc-advisor:index-docs --key specs --dirs-json '<root_dirs の JSON 配列>'

# ファイル列挙モード（exclude が非空）
/doc-advisor:index-docs --key specs --paths-json '<specs 配列の JSON>'
```

`doc-advisor` プラグイン（外部 marketplace `BlueEventHorizon/DocAdvisor`）が未インストールで
`doc-advisor:index-docs` が available-skills に存在しない場合は、その旨を報告して終了する。

### Step 3: 応答の転送

`doc-advisor:index-docs` の完了レポート（added / updated / deleted / toc_path 等）をそのまま親に返す。

## Notes

- **desired-state**: `--paths-json` は key `specs` の完全な desired state。Step 1 で解決した一覧に
  含まれないパスは ToC から削除される（`.doc_structure.yaml` が正）。
- 索引の出力先は `.claude/doc-advisor/toc/specs-<hash>/toc.yaml`（doc-advisor が管理）。
