---
name: onboarding
description: |
  セッション起動直後に 1 回実行するオンボーディング。スキルを経由しない直接作業でも
  守るべき基盤文書（forge 内蔵の開発基盤規範・規範文書と、利用プロジェクトの README・
  開発手順書）を全件 Read する。文書を読まない推測ベースの作業による規約違反・手戻りを防ぐ。
  あわせて、本スキルを起動しない会話直の作業でも規範が文脈に入るよう、規範をプロジェクトの
  CLAUDE.md へ承認のうえ転記する（マーカーで囲った専用ブロック。既存の記述は変更しない）。
  トリガー: "作業をやって", "これを調べて"
allowed-tools: Read, Bash
user-invocable: true
---

## 1. 必読文書を読む

**NEVER skip.** 下記を全件 Read し、深く理解する。**CLAUDE.md へ転記済みでも毎回読む**（転記されるのは規範の要旨であり全文ではないため、転記は読むことの代替にならない）。

- `${CLAUDE_PLUGIN_ROOT}/docs/document_style_guide.md` — 文書を書く・直すときの記述スタイル
- `${CLAUDE_PLUGIN_ROOT}/docs/adr_format.md` — ADR を直接起票するときの書式
- `${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md` — 設計書の保守と歴史的記録の扱い
- `${CLAUDE_PLUGIN_ROOT}/docs/adr_principles_spec.md` — ADR に何を書き何を書かないか、可変性と失効の扱い
- `${CLAUDE_PLUGIN_ROOT}/docs/forge_anti_patterns.md` — 実装・文書で踏んではならないアンチパターン
- `${CLAUDE_PLUGIN_ROOT}/docs/sensitive_information_spec.md` — リポジトリに含めてはならない情報
- `${CLAUDE_PLUGIN_ROOT}/docs/scope_proportionality_spec.md` — 比例性の原則（過剰設計の抑止）

## 2. 規範ブロックの状態を確認する

判定・承認文言・次の行動はすべて status から一意に決まるので、script が返す。手で転記しない。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/onboarding/scripts/onboarding_block.py" \
  --check --target "${CLAUDE_PROJECT_DIR}/CLAUDE.md"
```

**これ以外のオプションを使う必要はない。** 以降は返ってきた `on_approve` / `verify` のコマンドをそのまま実行する。

返る JSON に従う。

- `action: "none"` — 転記済みで最新。**ここで終了する**
- `action: "propose"` — `block_body` が forge の規範の**正本**。セッション開始時に読んだ転記ブロックは失効しているので、以後は `block_body` に従う（**承認の可否とは無関係に適用する**。読むことに承認は要らない）。そのうえで `ask` の文言を**そのまま一行で尋ねる**。承認されたら `on_approve` を実行する。断られたら書き込まず、本来の作業に進む。理由は問わない
- `error` がある — **内容をそのまま報告して中止する**。勝手に修復しない

`on_approve` の実行後、`written_status` が `fresh` なら書き込みは完了している。プロジェクトがフォーマッタを使っている場合だけ適用し、`verify` が `fresh` を返すことを確認する。返さない場合はフォーマッタがブロックを書き換えているので、報告して中止する（放置すると毎回更新提案が出続ける）。
