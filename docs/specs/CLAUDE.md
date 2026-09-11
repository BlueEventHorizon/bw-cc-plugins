# docs/specs/ 配下の作業規約

このディレクトリ配下の文書（要件定義書・設計書・計画書）にだけ当たる規約を置く。プロジェクト全体に当たるものはリポジトリルートの `CLAUDE.md`、配布物に当たるものは `plugins/forge/docs/` 側が持つ。

## 配置と命名

- **設計文書は `docs/specs/**/{requirements,design}/` に置き、`REQ-` / `DES-` / `ADR-` で命名する**（plan モードの成果も同じ）

## レビュー

### レビューは `/forge:review` を起動する

このディレクトリ配下の文書をレビューするときは、**`/forge:review` を起動する**。`forge:reviewer` / `forge:evaluator` を Agent ツールで直接起動しない（所見の提示と記録の工程が丸ごと抜ける）。
