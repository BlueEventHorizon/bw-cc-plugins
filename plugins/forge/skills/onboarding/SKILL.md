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

<!-- FORGE_ONBOARDING_COPY_START -->

## forge 必読文書 [MANDATORY]

**NEVER skip.** 下記を全て読み込み、深く理解すること。

- `${CLAUDE_PLUGIN_ROOT}/docs/document_style_guide.md` — 文書を書く・直すときの記述スタイル
- `${CLAUDE_PLUGIN_ROOT}/docs/adr_format.md` — ADR を直接起票するときの書式
- `${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md` — 設計書の保守と歴史的記録の扱い
- `${CLAUDE_PLUGIN_ROOT}/docs/adr_principles_spec.md` — ADR に何を書き何を書かないか、可変性と失効の扱い
- `${CLAUDE_PLUGIN_ROOT}/docs/forge_anti_patterns.md` — 実装・文書で踏んではならないアンチパターン
- `${CLAUDE_PLUGIN_ROOT}/docs/sensitive_information_spec.md` — リポジトリに含めてはならない情報
- `${CLAUDE_PLUGIN_ROOT}/docs/scope_proportionality_spec.md` — 比例性の原則（過剰設計の抑止）

## forge プロジェクト文書 [MANDATORY]

- プロジェクトルール文書の参照には `query-db-rules` SKILL を使う
- プロジェクトルール文書の更新後には `update-db-rules` SKILL を使う
- プロジェクト仕様の参照には `query-db-specs` SKILL を使う
- プロジェクト仕様の更新後には `update-db-specs` SKILL を使う

## forge 重要規約 [MANDATORY]

- **実装・文書改編に着手する前に `/forge:query-forge-rules`・`/forge:query-db-rules` で関連する原則・ルールを特定して読む**（スキル経由の作業は各スキルの調査 Phase がこれを担う。会話直の作業でも省略しない）
- **ルールはルール文書管理**: コンテキスト肥大化防止のため、CLAUDE.md にルールを詰め込まないことを推奨する
- **一般の作業で CHANGELOG.md・version 関連ファイルを編集しない**。リリースコミットでまとめて更新（`/forge:update-version` を使う）
- **`.toc_work/` 等の消えるべき一時物は `.gitignore` に入れない**。残存が `git status` に untracked として出ることで異常を検知できる
- セマンティック検索とは、字句の一致ではなく意味に基づいて文書を選ぶ検索であり、実現手段（ベクトル類似度か LLM による読解か）は問わない
- query-db-xxx SKILL はセマンティック検索であり、ワード一致検索（grep）ではない。**取りこぼしを出さないこと（false negative 厳禁）を規約として検索する**ため、意味的に近い文書を広く拾って返す。最終的に何を読むかは、何を求めて検索したかを知っている検索の実行主体が判断する
- doc-advisor のフロントマターを持つ文書を編集したら、`/doc-advisor:write-frontmatter --paths <編集した文書>` で再生成する。`Edit` / `Write` で直接書き換えてはならない（`body_hash` の打刻・値域検証・マージ規則は script の責務であり、手書きでは信頼されないフロントマターになる）。**編集した本人がその場で書いておく**。信頼できるフロントマターが原本にあれば、後日 `update-db-rules` / `update-db-specs` が走るときに AI 抽出が省かれ、索引が高速に作られる（信頼できなければ AI 抽出へフォールバックする）

<!-- FORGE_ONBOARDING_COPY_END -->

## 実行フロー

CLAUDE.md へ転記されるのは `FORGE_ONBOARDING_COPY_START` / `_END` で囲まれた範囲**のみ**である。範囲は見出し名に依存しないので、囲みの内側は節の追加・改名・並べ替えが自由にできる。逆にマーカーの外に書いたものは転記されない。マーカーが欠けている・対になっていない場合、script は転記を中止する（見出しからの推測は行わない）。

囲み内の `##` 見出しは、必ず `forge` で始める。転記先には同名の節が既にあることが多く、そのままでは見出しが重複してどちらが有効か判別できなくなるため。**転記は原文コピーであり、script は接頭辞を付けない**（変換に頼ると、効かなかったときに衝突が黙って戻る）。この規約は `tests/forge/onboarding/` が検証する。

### 1. 必読文書を読む [MANDATORY]

「必読文書」を全件 Read する。**転記済みでも毎回読む。** CLAUDE.md に転記されるのはパスだけで本文は入らないため、転記は読むことの代替にならない。

### 2. 転記ブロックの状態を確認する

抽出・ハッシュ計算・差し込みは決定論的処理なので、判定も生成も script が行う。手で転記しない。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/onboarding/scripts/onboarding_block.py" --check
```

返る JSON の `status` で分岐する。

| status   | 条件                   | 次の行動               |
| -------- | ---------------------- | ---------------------- |
| `fresh`  | 転記済みで最新         | 何もしない。ここで終了 |
| `absent` | `target_exists: true`  | 3-A の承認を求める     |
| `absent` | `target_exists: false` | 3-B の承認を求める     |
| `stale`  | 転記元が更新されている | 3-C の承認を求める     |

`error` が返った場合（マーカーの破損等）は、**内容をそのまま報告して中止する**。勝手に修復しない。

### 3. 承認を求める [MANDATORY]

CLAUDE.md は統治文書なので、書き込み前に必ず承認を得る。ただし**一行で聞く**。ハッシュ・マーカー名・スクリプトの引数・変更行数といった内部の詳細は見せない。毎セッション読まされる文章になり、承認の判断に必要でもない。

| status                   | 聞き方                                                                  |
| ------------------------ | ----------------------------------------------------------------------- |
| `absent`（ファイルあり） | forge の規範を CLAUDE.md に追記してよいですか（既存の記述は変えません） |
| `absent`（ファイルなし） | このプロジェクトには CLAUDE.md がありません。作成してよいですか         |
| `stale`                  | forge の規範が更新されました。CLAUDE.md の該当箇所を更新してよいですか  |

断られたら書き込まず、そのまま本来の作業に進む。理由は問わない。

### 4. 書き込む

承認が得られた場合のみ実行する。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/onboarding/scripts/onboarding_block.py" --write
```

書き込み後、プロジェクトがフォーマッタを使っている場合は適用し、再度 `--check` が `fresh` を返すことを確認する。`stale` に戻る場合はフォーマッタがブロックを書き換えているので、報告して中止する（放置すると毎回更新提案が出続ける）。
