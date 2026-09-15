# evaluator-perspective 検討メモ

要件定義書へ整形する前のワーキングメモ。3 分類で管理する（BlueEventHorizon/bw-cc-plugins#55）。

- **決まったこと** — 確定済み。以後の前提にできる
- **提案状態で未決** — 誰かが出した案だが、承認・却下のどちらもされていない
- **懸念事項** — 未解決の疑問・リスク。誰も答えを出していない

## 背景（なぜこの feature が要るか）

`forge:REQ-013` FNC-1322 は「所見を返した主体とは別の主体による独立評価」を課している。
だが実際には、reviewer と evaluator が**同じ観点文書を同じ向きで読む**ため、同じ誤りを
繰り返すことがある（実例: `consult_principles_spec.md` §7 の「判断」の定義不足を、
reviewer も evaluator も見抜けなかった）。

FNC-1322 が「単一の視点に依存しない確からしさ」を担保しようとしたのに、
**主体を分けるだけでは成立しない**。evaluator に、reviewer とは異なる層を見せる必要がある。

**本題（詳細を詰める前に必ずここへ戻る）**: reviewer は「観点文書に照らして違反を探す」向き。
evaluator は追加で、**指摘の奥にある本質・対象文書の情報**を疑う向きを持つ（詳細は
冒頭「evaluator の観点リスト」節）。観点文書側の欠陥（`flawed_premise`）は稀な結果でしか
なく主眼ではなく、決定（ADR 等）の当否はそもそも判定してはならない（Chesterton's Fence）。

**求めているのは俯瞰であって捏造ではない。** 所見群を広く見て、複数の指摘の奥にある
共通の本質・より根源的な原因が無いかを確かめる態度を持たせたい。ただし本質が
無いこともあり、無いのに有るかのように作り出してはならない。俯瞰は義務だが、俯瞰した結果「無い」と判断することも
正当な結論である。

JSON 構造やデータモデルの詳細を詰めているうちに、この本題自体を何度も見失った。

---

## evaluator の観点リスト（本題そのもの・決着）

**前提（メタ観点の違い）**: reviewer と evaluator に渡される文書は物理的に同一
（`plugins/forge/skills/review/SKILL.md:318`）。違うのはその文書の読み方である。
reviewer は文書を基準として使い、対象がそれに違反していないかを探す。evaluator は
同じ文書を検証の材料の一つとして扱い、文書・対象・指摘の妥当性そのものを疑う。

**位置づけ（重要な訂正）**: 5 項目は既存の disposition 判定（`invalid` /
`misunderstanding` / `out_of_scope` / `valid`）と並列の新工程ではない。**reviewer の
指摘が正しいかをまず判定する**——それは従来どおり disposition が担う。5 項目は、
その判定（特に `invalid`/`misunderstanding` へドロップするかどうかの判断）を行う際に
evaluator が使う目のつけ所である。指摘が間違っていれば、その時点でドロップする。

**観点リスト**（確立された手法を踏まえて整理。個別の手順ではなく態度として課す）:

1. **本質を疑う**（5 Whys・Systems Thinking の症状/構造の区別）。指摘された問題は
   本当にそれが原因か。個々の指摘の奥に、もっと本質的な原因は無いか。複数の指摘が
   実は 1 つの原因から出ていないか
2. **対象の情報を疑う**。修正の元になった開発文書・ソースコードの情報自体が
   誤っていないか。所見はその誤った情報を正しく指摘しているだけかもしれない
3. **決定は当事者のものと心得る**（Chesterton's Fence）。既存の決定（ADR 等）を
   外から「正しい・間違っている」と判定しない。判定できるのは形式・論理的整合性・
   書き換え禁止のような手続きの違反までで、決定そのものの当否ではない
4. **まず最も強い解釈を試す**（Steelmanning）。所見や規範文書を、いきなり疑って
   かかったり字面だけで衝突と決めつけたりしない。まず最も合理的な読み方（目的に
   照らした読み方）を試し、それでも成立しないときだけ欠陥を疑う
5. **逆から検証する**（Pre-mortem／インバージョン）。この所見・この判定が
   間違っているとしたら、どこがどう間違っているか。先に失敗の形を想定してから検証する

`flawed_premise`（規範文書側の欠陥）は、4 を尽くしてもなお成立しないときの**結果**として
位置づける。独立した最優先観点ではない（今日の実例（§7）は稀な例であり、主眼は
1・2 である）。

**決定**: 5 項目は絞らず、態度としてまとめて要件へ載せる（FNC-201）。ADR（項目 3）のような
個別の適用除外は要件ではなく `evaluator.md`（実装）側に書く。実効性の検証は懸念事項（下記）を参照。

### FNC-201: evaluator は指摘の奥にある本質・対象情報を疑う

`disposition` を判定する際、次を手がかりとして考える。網羅を課すものではなく、態度として持つ。

- 指摘された問題は本当にそれが原因か。個々の指摘の奥に、もっと本質的な原因は無いか。
  複数の指摘が実は 1 つの原因から出ていないか
- 修正の元になった開発文書・ソースコードの情報自体が誤っていないか
- 既存の決定（ADR 等）は、外から正しい・間違っていると判定しない。判定できるのは
  形式・論理的整合性・書き換え禁止のような手続きの違反までである
- 所見や規範文書は、まず最も合理的な読み方（目的に照らした読み方）を試し、それでも
  成立しないときだけ欠陥を疑う
- この所見・この判定が間違っているとしたら、どこがどう間違っているか

**本質・原因が無いこともある。作り出さないこと**——成立しない共通原因を書いてはならない。
無いと判断したなら、その判断と根拠を `reason` に述べる。

規範文書自体の欠陥（`flawed_premise`）は、上記を尽くしてもなお成立しないときの結果であり、
独立して優先的に探すものではない。

---

## 決まったこと

### reviewer と evaluator に渡される観点文書は同一（実物で確認済み）

`plugins/forge/skills/review/SKILL.md:318` に明記——evaluator へ渡す依頼本文は
「reviewer へ渡したものと同一（観点文書・重点観点・到達目標を含む）」。

観点文書は 3 層構造で、パターン（種別）ごとに異なる:

| パターン                              | criteria（種別固有・1 本）               | severity の SoT（共通・1 本） | principles（原則文書・種別ごとに異なる）                                                                                                                                                                                                                          |
| ------------------------------------- | ---------------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `code`                                | `review_criteria_code.md`                | `review_priorities_spec.md`   | `forge_anti_patterns.md`<br>`scope_proportionality_spec.md`                                                                                                                                                                                                       |
| `design`                              | `review_criteria_design.md`              | `review_priorities_spec.md`   | `design_format.md`<br>`adr_format.md`<br>`adr_principles_spec.md`<br>`design_principles_spec.md`<br>`spec_design_boundary_spec.md`<br>`document_style_guide.md`<br>`additive_development_spec.md`<br>`spec_priorities_spec.md`<br>`scope_proportionality_spec.md` |
| `requirement`                         | `review_criteria_requirement.md`         | `review_priorities_spec.md`   | `requirement_format.md`<br>`spec_design_boundary_spec.md`<br>`spec_priorities_spec.md`<br>`document_style_guide.md`<br>`additive_development_spec.md`<br>`scope_proportionality_spec.md`                                                                          |
| `plan`                                | `review_criteria_plan.md`                | `review_priorities_spec.md`   | `plan_principles_spec.md`<br>`additive_development_spec.md`<br>`spec_priorities_spec.md`<br>`scope_proportionality_spec.md`<br>`document_style_guide.md` §5.3                                                                                                     |
| `uxui`                                | `review_criteria_uxui.md`                | `review_priorities_spec.md`   | `document_style_guide.md`<br>`spec_priorities_spec.md`<br>`scope_proportionality_spec.md`                                                                                                                                                                         |
| `secrets`                             | `review_criteria_secrets.md`             | `review_priorities_spec.md`   | `sensitive_information_spec.md`                                                                                                                                                                                                                                   |
| `branch` / `diff`（種別未指定・混在） | 上記 5 criteria を種別ごとに分岐して列挙 | `review_priorities_spec.md`   | `forge_anti_patterns.md`<br>`spec_design_boundary_spec.md`<br>`spec_priorities_spec.md`<br>`scope_proportionality_spec.md`<br>`design_principles_spec.md`<br>`plan_principles_spec.md`<br>`requirement_format.md`<br>`design_format.md`                           |

**含意**: observability の追加は、特定の principles 1 本を狙い撃つ設計にできない。
`secrets` は principles 1 本、`design` は 9 本というように、パターンごとに規範文書の本数が
大きく異なる。**種別ごとに 1〜9 本ある principles 群のどれに対しても機能する、汎用的な
問いの立て方**でなければならない。

### Phase 1: 機能概要メモ

| 確認項目         | 内容                                                                                                                                                                   |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 機能の目的       | evaluator が reviewer と異なる層を見るようにする                                                                                                                       |
| ユーザーのゴール | レビューが正しく機能する状態——誤った指摘を正しくドロップし、見落とされた指摘を拾い上げ、指摘の根底にあるより根源的な問題（前提文書の欠陥を含む）を発見できる状態にする |
| 既存機能との関係 | `forge:REQ-013` FNC-1322（独立評価）・FNC-1321（自己検証）を強化する。`agenda:REQ-019`／`consult-agenda` の下流にある                                                  |

evaluator の役割は 3 つ（対等、優劣なし）:

- 誤った指摘をドロップする（`disposition: invalid` / `misunderstanding`）
- 見落とされた指摘を拾い上げる（finding_ids が空の新規 evaluation）
- 指摘の根底にあるより根源的な問題を発見する（`flawed_premise` を含む）

### evaluator に持たせる観点・書き方の方針（Phase 2）

- **過程は課さない**。手順・順序を指示しない
- どう疑うか・何を読むかは書かない（対象は依頼本文で既に渡っている）

**観点の中身は冒頭「evaluator の観点リスト」節（5 項目）を参照。**

**「チェックリストの形」という出力構造は不採用（訂正）。** 検討当初は 5 項目を「見た/見て
該当なし」と自己申告させる形を考えたが、**本当に検討したかを確かめる手段が無く、チェック欄を
機械的に埋めるだけの形骸化を招く**（severity・flawed_premise で辿った「強制しても実効性が
無いものは作らない」と同じ結論）。`FNC-201` は観点を態度として課すだけで、出力構造は求めない。

### 用語（Phase 1）

| 用語                                   | 定義                                                                                                                                                                                                                               |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `finding_id`                           | 所見 1 件を指す一意な識別子（採番の実装方式は設計の責務）                                                                                                                                                                          |
| evaluation                             | `finding_id` を 0 個以上引ける。件数は所見の件数と一致しない場合がある（束ねて減る・新規立項で増える、いずれも正当）。同じ finding_id を複数の evaluation が引くことも許される                                                     |
| `finding_ids` の特別値 `全部`（`all`） | reviewer が返した所見**全件**を指す速記——逐一列挙しなくてよい。個々の ID を列挙する場合（一部）・空配列（新規、下記）と意味が異なり、後工程（review 本体・agenda）はこの値を「全件」として認識できればよい（認識方法は設計の責務） |

**要件（What）**: 全 finding_id が、いずれかの evaluation に紐づくこと。
**設計（How、この feature の外）**: それをどう検証するか（機械検証の方式・スクリプト名等）。

### reviewer は変えない

- reviewer の応答形式（重大度マーカー + 完了宣言行）は変えない
- 理由: `REQ-013:245` が「バックエンドごとに依頼テンプレートを分岐させない」ことを求めている。
  reviewer は交換可能な実行主体（`agent-review`/`msg-review`/`codex-appserver`）であり、
  JSON を課すと崩れたときに全件を失うリスクを負わせることになる
- `finding_id` の採番は reviewer の出力形式を変えずに実現できる（採番の実装方式は設計の責務）

### evaluation のデータモデル（Phase 4）

| フィールド      | 型                              | 必須                         | 内容                                                                                                                             |
| --------------- | ------------------------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `finding_ids`   | 文字列配列、または特別値 `全部` | 必須（0 個以上、空配列も可） | 参照する所見の ID。一部なら列挙、全件なら `全部`（逐一列挙しない）、evaluator が reviewer の見落としを新規に指摘する場合は空配列 |
| `disposition`   | enum                            | 必須                         | `invalid` / `misunderstanding` / `flawed_premise` / `out_of_scope` / `valid`                                                     |
| `severity`      | enum                            | 必須                         | 重大度カタログから決まる値                                                                                                       |
| `reason`        | 文字列                          | 必須                         | 判定根拠。`flawed_premise` の場合は、どの文書のどこが誤りかをここに書く                                                          |
| `confidence`    | enum                            | `valid` のとき必須           | `confirmed` / `inferred` / `unverified`                                                                                          |
| `fix_confident` | 真偽値                          | `valid` のとき必須           | `confidence: confirmed` でなければ真になれない                                                                                   |

**severity は必須フィールドとして定義する。ただし severity の値そのものに、他の判断
（disposition の当否・修正するかどうか等）を振り回されてはいけない。** 判断の実質を持つのは
`reason`（具体的な評価の文言）であり、severity を取り違えても人間が `reason` を読めば重大さは
伝わる。`flawed_premise` を含むすべての disposition について、severity の特定不能時の扱いを
新たに規則化しない（既存の緩い運用のままでよい）。

**disposition_cause や flawed_premise_detail のような専用フィールドは作らない**
（`disposition` に 1 値足す・`reason` に書く、で足りる。上位概念で吸収できるものを
別構造に分けすぎる失敗を今日何度も繰り返した）。

現行の `evaluator.md` は「所見の件数と `index` の集合が過不足なく一致すること」を機械検証の
対象にしているが、`finding_ids` 方式では件数が変わりうるため成立しない。**この検証は、下記
「全 finding_id が evaluation に紐づかない場合の扱い」節の検証へ置き換える**（件数一致から
参照網羅性へ）。

### 全 finding_id が evaluation に紐づかない場合の扱い（Phase 4、What のみ）

- **`retains_context: true` の reviewer**（例: `msg-review`）→ 欠落があれば聞き直す。
  返ってきた答え（disposition が何であれ、ドロップ含む）はそのまま採用する（検証しない）
- **`retains_context: false` の reviewer**（例: `agent-review`）→ 聞き直せない。
  その finding は未回答のまま残る。**これへの追加対応（記録・弾く・人間へ回す）は作らない**
  （起こる頻度が未知数で、対処を書いても実行する主体がいないため）

### flawed_premise の自動修正（Phase 2）

- `disposition: flawed_premise` は、`confidence`/`fix_confident` の値に関わらず
  **`--auto` でも自動修正の対象にしない**（修正対象がレビュー対象の外にあるため）
- 常に提示して採否を得る

### agenda はこの feature のスコープ外。consult は本 feature の実装期間中 agenda を呼ばない

- **背景**: agenda（`agenda_store.py`・`structural_judgment` の必須ブロック等）は、この feature の
  後に別の差分 feature として全面刷新される予定。新しい `evaluator` の出力形式
  （`finding_ids` の `全部`/一部/空という表現）は、いまの `structural_judgment` の必須フィールドとは
  対応関係が無く、整合を取ろうとすると二度手間になる
- **決定**: consult は本 feature の実装期間中、**agenda への記録を行わない**
  （`agenda_wrapper.py` の呼び出しを行わない）。所見の提示（1 件ずつの採否確認）は継続する。
  agenda への永続化（ファイルに残す・後で見返す・4 欄表示等）は失われる——これは
  「agenda 全面刷新」という別の差分 feature が復元する
- **手段（設計側の実装イメージ。要件には結果だけを書く）**: 現行の `plugins/forge/skills/consult/`
  を別名（例: `consult-legacy`）へ rename して残し、`consult` という名前の場所には
  agenda を呼ばず提示だけ行うスタブを置く。`review/SKILL.md` Step 7.5 の「consult へ委譲する」
  という既存の呼び出し記述を書き換えずに済む
- **他への影響なし（確認済み）**: consult は agenda の唯一の呼び出し元（`consult:DES-078`）。
  agenda に依存する他の主体は無いため、`additive_development_spec.md` §3.1 の
  「旧実装を残す必要がある場合」に該当しない——呼び出しを止めても何も壊れない

---

## 懸念事項

1. `finding_id` の採番方式の詳細（設計の責務、要件定義には残らない見込みだが未確認）
2. 参照検証の実装方式（設計の責務、要件定義には残らない見込みだが未確認）
3. **観点リスト 5 項目のうち、evaluator が実際に実行できるかが未検証**。項目 3
   （Chesterton's Fence）・項目 4（Steelmanning）は既存手順（対象実体・観点文書を
   実際に読む）の延長で実行できそうだが、項目 1（本質を疑う）・項目 2（対象の情報を疑う）は
   所見を俯瞰する material や判定基準を evaluator が持っているか怪しい。項目 5
   （インバージョン）は既存の自己検証（`evaluator.md:22`）との違いが不明瞭。
   要件には 5 項目を書くが、実効性の検証は実装後の別タスクとする
4. **5 項目それぞれの「実際の判定例」が無いと、要件として妥当かの評価がしづらい**
   （例: この所見にこの観点を当てるとどう判定が変わるか）。ただし例をここ（メモ・要件定義書）に
   書くべきではない——例は実装側（`evaluator.md`）の具体例として持つのが適切。5 項目の
   確定前に、いくつか実例で試してみる必要がある
5. **重大度カタログという仕組み自体の位置づけが不明確（この feature の範囲外。
   BlueEventHorizon/bw-cc-plugins#57 として起票済み）**。`review_priorities_spec.md:63`「severity の単一の真実源 (SoT) は委譲先 principles
   の重大度カタログである」は、カタログを重く（厳密な唯一の真実源として）扱っている。
   一方 severity 自体は目安に過ぎず「値に他の判断を振り回されてはいけない」と決めた
   （→「決まったこと」参照）。**severity という値の軽さと、それを決めるカタログという
   仕組みの重さが、ちぐはぐしている。** これは「severity の値に振り回されるか」とは別軸の話で、
   Issue #47（重大度カタログの置き場の整理）とも別軸（#47 は「どこに書くか」、これは
   「どれだけ重く扱うべきものとして書くか」）。#47 の置き場整理が先決という依存関係がある。

   **さらに**: カタログは判断の**材料**であって、SoT はカタログそのものではなく、
   **それを使って evaluator が導き出した評価（`reason` を伴う判断）自体**にあるのではないか。
   カタログを絶対視すると、カタログに載っていない新種の判定（`flawed_premise` 等）が
   出たときに「SoT が無いから決められない」状態に陥る。だが実際にはそこで evaluator が
   下した評価そのものが SoT になり得る。`review_priorities_spec.md:63` の「単一の真実源は
   カタログ」という定義そのものを見直す必要があるかもしれない
