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

### Step 1: 対象を取得する

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/SKILL.md` の「検索対象ディレクトリの解決」手順に従い、
category `specs` で `dirs`/`exclude` を取得する。

`exclude` の裸名（`/` なし、例 `plan`）は doc-advisor の `--exclude-json` でも同じ意味（パスの任意の階層にある
同名ディレクトリに完全一致）で扱われるため、変換なしでそのまま渡せる（doc-advisor 0.4.4 `expand_dirs.py`
`should_exclude` で確認済み）。

### Step 1.5: dprint fmt を実行する [MANDATORY]

ToC の checksum は生成時点のファイル内容で計算される。後続で Skill ツール経由で起動される `/anvil:commit` の Phase 0 が実行する `dprint fmt` によって対象ファイルの本文が書き換わると、ToC 生成時点の checksum と実際に commit される内容が不一致になる（Issue #202）。ToC 生成前に `dprint fmt` を適用し、最終的な内容で checksum を計算させる。

`anvil:commit` Phase 0 と同一条件・同一コマンドを共有スクリプトで実行する（条件判定・実行ロジックのインライン重複を避けるため）:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/doc_structure/run_dprint_fmt.sh"
```

これによりファイル内容が変わった場合、変更は作業ツリーに残る（ToC 生成後に呼ばれる `/anvil:commit` がそのまま commit 対象に含める）。

### Step 2: index-docs へ転送

`Skill` ツールで `doc-advisor:index-docs` を **1 回だけ** 呼ぶ（常に dirs モード）:

```
/doc-advisor:index-docs --key specs --dirs-json '<root_dirs の JSON 配列>' --exclude-json '<exclude の JSON 配列>'
```

`exclude` が空の場合は `--exclude-json '[]'` を渡す（省略も可）。

`doc-advisor` プラグイン（外部 marketplace `BlueEventHorizon/DocAdvisor`）が未インストールで
`doc-advisor:index-docs` が available-skills に存在しない場合は、その旨を報告して終了する。

### Step 3: 応答の転送

`doc-advisor:index-docs` の完了レポート（added / updated / deleted / toc_path 等）をそのまま親に返す。

## Notes

- **desired-state**: `--dirs-json`/`--exclude-json` は key `specs` の完全な desired state。展開後に
  含まれないパスは ToC から削除される（`.doc_structure.yaml` が正）。
- 索引の出力先は `.claude/doc-advisor/toc/specs-<hash>/toc.yaml`（doc-advisor が管理）。
