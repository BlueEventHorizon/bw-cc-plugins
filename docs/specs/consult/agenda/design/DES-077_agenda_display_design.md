---
feature_type: temporary-feature
feature_note:
  - 正本は対応する追加 feature 要件定義書（[agenda:REQ-021](../requirements/REQ-021_agenda_display.md)）。本設計書と旧設計書が矛盾する場合は要件定義書を優先する。
  - 旧仕様ファイルは本 feature 実装完了まで書き換えない。新規ファイル / 新規ディレクトリとして切り出すこと。
  - 本 feature 実装完了後、旧設計書との齟齬を解消する（merge）。merge は意味の統合であり、文書の物理的な結合ではない。
  - 旧設計書と同一スコープの内容は旧設計書側へ移す。スコープが異なる内容は分離したまま維持し、この文書を残す。
---

# DES-077 agenda 表示層設計書

## メタデータ

| 項目     | 値                                                               |
| -------- | ---------------------------------------------------------------- |
| 設計ID   | DES-077                                                          |
| 関連要件 | agenda:REQ-021, agenda:REQ-019, consult:REQ-017                  |
| 親設計書 | [DES-075](DES-075_agenda_mechanism_design.md)（agenda 機構全体） |
| 作成日   | 2026-08-22                                                       |

## 1. 概要

agenda:REQ-021 が定める表示層（`agenda_render.py`）の設計。データ保存層・状態遷移・CLI 設計は [DES-075](DES-075_agenda_mechanism_design.md) が持つ。本文書は[DES-075](DES-075_agenda_mechanism_design.md) §8 から分離した（表示層の実装詳細が量的に増え、単一ファイルが肥大化したため。[design_principles_spec.md](../../../../../plugins/forge/docs/design_principles_spec.md)「階層構造ガイドライン」）。

## 2. 生成形式と初回表示

### 2.1 HTML の採用理由

HTML を採用する（識別子からの直接到達（FNC-005）をアンカーリンク `#item-01` で実現できる。[consult:REQ-017](../../requirements/REQ-017_consult_skill.md) §1.2 が示す 3 つの理由——大量情報の整理・番号指定ジャンプ・コンソールノイズからの分離——のうち後 2 つは HTML でのみ満たせる）。

### 2.2 初回表示のトリガー（`open` コマンド）

**consult は `agenda_store.py init` 実行直後、Bash で `open {path}/agenda.html` を実行し、ブラウザで自動的に開く。**

- **理由**: OS 標準の `open`（macOS）1 コマンドで、ローカルファイルをブラウザで開ける。専用の提示手段を追加せずに済み、既存の「サーバー不要・`file://` 前提」の設計方針を変えずに満たせる
- **2 回目以降は `open` を呼ばない**: 初回に開いたタブが§4 の更新機構で最新状態に追従する。`update` の度に `open` を呼ぶと、ブラウザによっては重複タブが開く

## 3. テンプレートの構造

既存 `plugins/forge/skills/consult/assets/discussion_file_template.md` が持つ構造（アジェンダ表 + `## [ID] 項目名` の項目節）を、レンダリング出力の構造としてそのまま引き継ぐ。ただし本テンプレートは**保存形式ではなく表示専用**（agenda:REQ-019 NFR-001 が禁じるのは「保存に使うこと」であり、読み戻さない生成専用の表示は対象外）。

```html
<h1>アジェンダ: {identity}</h1>
<!-- 生成物であることを示す注記（NFR-001） -->
<p class="generated-notice">この提示は agenda_render.py によって {generated_at} に生成された。手編集しても保存されない。</p>

<table id="agenda-summary"><!-- ID/項目/重要度/状態/結果・課題 の一覧。FNC-001 --></table>

<section id="item-01" data-changed="{is_last_changed}" data-current="{is_current}"><!-- FNC-005: アンカーリンク到達点 -->
  <h2>
    [01] {title}
    <span class="severity-badge" data-severity="{fields[severity_field]}">{fields[severity_field]}</span><!-- §3.1a。severity_field 未指定なら本要素を出力しない -->
  </h2>
  <p>背景: ...</p>
  <p>本質: ...</p>
  <p>決着: ...</p>
</section>
```

- **FNC-003（提示と記録の一致）**: `agenda_render.py` は `agenda.json` の内容のみから HTML 文字列を組み立てる。AI が HTML を直接書く経路を持たない
- 出力値は `html.escape()` を通す（`yaml_to_html.py` の既存パターンを踏襲。今回は入力が JSON のため PyYAML 依存は生じない）

### 3.1 状態表示は背景全面ではなく「ガターのドット 1 点」に集約する

変更箇所（FNC-002）・対話中の項目の強調は、**カード左側の余白（ガター）に置く小さなドット 1 点に色を集約する**方式で表す（カード全体の背景色 + 左ボーダーによる強調は採らない）。

- **理由**: カード全体を塗ると、severity バッジ（§3.1a）の配色と合わせて色の意味が重なり、画面が騒がしくなる。ガターの小さなドットに絞ることで、状態が「今どうなっているか」を示す信号を 1 箇所に限定できる
- 「変更」（`.state-dot.changed`）と「対話中」（`.state-dot.current`）は別々のドット（別クラス。§3.2）であり、同時に両方が立つ項目もありうる（別々の位置・別々の色で並べて表示する）

### 3.1a 重大度は絵文字ではなく「パステル配色 + テキストラベル」で表す

重大度（`critical`/`major`/`minor` 等）を絵文字（🔴🟡🟢）だけで表現しない。絵文字は「形が同じ円で色だけが違う」ため、**色以外の手がかりを持たない表現**であり、[WCAG 2.2 達成基準 1.4.1「色の使用」](https://www.w3.org/TR/WCAG22/#use-of-color)が要求する「色を、情報を伝える・操作を示す・応答を促す・視覚要素を区別するための唯一の視覚的手段として使用しない」に反するためである。

- 重大度は**パステル調（低彩度・高明度）の背景色またはボーダー + 短いテキストラベル**の併用で表す。色だけでなく文字でも重大度が判別できるようにする
- きつい原色は避ける（利用者の要望）
- 具体的な配色の値（色コード）は本設計書で確定しない。実装後に生成された `agenda.html` を見ながら利用者と調整する（§3.2 と同じ扱い）

**中立性原則との整合**: agenda 機構は `fields`（呼び出し側固有の項目属性）のキー名・値の意味を解釈しない（FNC-009）。したがって `agenda_render.py` は `severity` というキー名を決め打ちでバッジ表示するのではなく、**`config.severity_field`（[DES-075](DES-075_agenda_mechanism_design.md) §4）が指定するキー名**を参照する。`severity_field` が未指定（`null`）の場合、バッジは表示しない。

```html
<span class="severity-badge" data-severity="{fields[severity_field]}">{fields[severity_field]}</span>
```

- `data-severity` の値（`critical`/`major`/`minor` 等）は呼び出し側が渡した文字列そのままであり、agenda 側はこの値の意味（重大度の順序等）を解釈しない。CSS 側は `data-severity` の値ごとにパステル配色を対応させる（例: `[data-severity="critical"] { ... }`）が、これは表示層が呼び出し側の語彙に依存する数少ない箇所であり、[DES-075](DES-075_agenda_mechanism_design.md) §5.1 の `TransitionRule`（語彙の意味に立ち入らない）とは異なるレイヤーの話である

### 3.2 CSS の適用対象（値は実装時に決定）

どのセレクタが何をスタイリングするかは設計事項として以下に固定する。**具体的な値（色コード・px サイズ等）は本設計書で確定しない**——実装後に生成された `agenda.html` を実際に見て、利用者と調整しながら決める（[design_principles_spec.md](../../../../../plugins/forge/docs/design_principles_spec.md)「実行後に人間が体感して決める値」と同じ扱い）。

| セレクタ                                         | 適用対象                                              | 備考                                                                                                                                                          |
| ------------------------------------------------ | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `body`                                           | 全体のベースフォント・行間・背景色                    | 落ち着いたトーンとする（きつい原色は避ける）                                                                                                                  |
| `h1`, `h2`                                       | タイトル階層（アジェンダ全体タイトル / 項目タイトル） | 階層が視覚的に区別できる程度の差（フォントサイズ・太さ）                                                                                                      |
| `.generated-notice`                              | 生成物であることを示す注記（§2.1 NFR-001）            | 本文より控えめな見た目（例: 小さめ・薄い色）にして目立たせすぎない                                                                                            |
| `#agenda-summary`                                | アジェンダ表（ID/項目/重要度/状態/結果・課題）        | 罫線・余白で表として読みやすくする                                                                                                                            |
| `.state-dot.changed`（`section` 内のガター要素） | 変更箇所の状態表示（§3.1）                            | ガターに置く小さいドットのみに色を使う。カード背景・ボーダーは塗らない                                                                                        |
| `.state-dot.current`（`section` 内のガター要素） | 対話中の状態表示（§3.1）                              | `.state-dot.changed` とは別クラス・別位置。同時に両方が立つ項目もありうる                                                                                     |
| `.severity-badge[data-severity]`                 | 重大度バッジ（§3.1a）                                 | パステル配色（低彩度・高明度）+ テキストラベルを併用する。色だけに意味を依存させない（[WCAG 2.2 達成基準 1.4.1](https://www.w3.org/TR/WCAG22/#use-of-color)） |
| `section`                                        | 項目ごとの区切り（アンカーリンク到達点）              | 項目間の境界が視認できる程度の区切り（罫線・余白）。状態によらず常にニュートラル                                                                              |

## 4. 表示の更新方式

### 4.1 採用する技術的根拠: `<script src>` タグの動的差し替え

`fetch`/`XHR` は `file://` オリジンで CORS 制約によりブロックされるが、**`<script>` タグの `src` 読み込みはこの制約を受けない**。この性質を用いて、ページ全体を再読み込みしない部分更新を `file://` 環境でも実現する。

- `agenda_state.js`（`window.AGENDA_DATA = {...}` を代入するだけのファイル。§4.2）をページ内 JS が 2 秒ごとに新しい `<script src="agenda_state.js?t=<timestamp>">` として生成・差し替えることで、ファイルの内容変化を数秒以内にページへ反映できる（クエリのタイムスタンプはブラウザキャッシュの回避のため）

### 4.2 採用方式: 状態フラグは即時反映、本文の変化は全体再読み込みに委ねる

§4.1 の部分更新は、**軽量な状態フラグ（今どの項目が対話中か、どの項目が直前に変わったか）の反映には使えるが、本文（背景・本質・決着等のテキスト）や項目数の変化まで部分更新で扱うのは複雑になる**（新規項目の追加は、あらかじめ HTML 骨格に存在しない要素をどう生成するかという問題を生む）。したがって、次のハイブリッド方式を採る。

`agenda_render.py` は書き込み成功時（[DES-075](DES-075_agenda_mechanism_design.md) §8.1 のトリガー）に、書き込みコマンドの種類に応じて次のファイルを生成する。

| ファイル          | 内容                                                                                  | 再生成のタイミング                                                                         |
| ----------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `agenda.html`     | 全項目の完全な内容（本文含む）。§3 のテンプレートそのもの                             | `content_version` が増える操作（`init`・`update`・`record-structural-judgment`）のときのみ |
| `agenda_state.js` | `{ currentItemId, changedItemIds, contentVersion, updatedAt }` のみを持つ軽量ファイル | 書き込み系操作すべて（`set-current` を含む）のとき                                         |

`agenda_state.js` の各フィールドは `agenda.json`（[DES-075](DES-075_agenda_mechanism_design.md) §4）から次のように導出する。AI が新たに考案する値ではなく、既存フィールドの単純な転記・集約である。

| `agenda_state.js` のフィールド | 導出元                                                                    |
| ------------------------------ | ------------------------------------------------------------------------- |
| `currentItemId`                | `agenda.json` トップレベルの `current_item_id` をそのまま転記             |
| `changedItemIds`               | `items[]` のうち `last_changed_fields` が空でない項目の `id` を集めた配列 |
| `contentVersion`               | `agenda.json` トップレベルの `content_version` をそのまま転記             |
| `updatedAt`                    | 生成時刻                                                                  |

ページ内 JS（`agenda.html` に埋め込む固定スクリプト、`agenda_render.py` が生成する）は次のように振る舞う。

1. 2 秒ごとに `agenda_state.js` を §4.1 の手法（`<script src>` 差し替え）で読み込む
2. 読み込んだ `contentVersion` が、直前に自分が保持していた値と**同じ**なら、`currentItemId`/`changedItemIds` の変化だけを既存の DOM（`data-current`/`data-changed` 属性）へ反映する。ページの再読み込みは発生しない
3. `contentVersion` が**異なる**なら、本文自体が変わった（新規項目の追加・決着内容の記入等）とみなし、`location.reload()` でページ全体を再読み込みする

**`contentVersion` は `agenda_store.py` が書き込みごとにインクリメントする整数**とする（`items` 配列の要素数・内容が変わるたびに増える。単純なタイムスタンプではなく、比較が確実な整数を使う。増減の対象操作は [DES-075](DES-075_agenda_mechanism_design.md) §3.2「`content_version` のインクリメント対象」を参照）。

この方式により、対話中の移動や変更マーカーのような軽量な状態変化は瞬時に（ページ再読み込みなしに）反映され、本文自体の変化があった場合に限りページ全体を再読み込みする。**「短すぎるポーリング間隔でも読んでいる最中に何度もページ先頭へ戻される」という問題は、`contentVersion` が変わらない限り再読み込みが起きないことで解消される。**

### 4.3 スクロール位置の保持（全体再読み込み時のみ必要）

§4.2 の手順 3（`location.reload()`）が発生したときに限り、ページ全体の再読み込みでスクロール位置が失われる。これを防ぐため、`pagehide` 時にスクロール位置を `sessionStorage` へ保存し、読み込み後に復元する。

```html
<script>
  window.addEventListener("pagehide", function () {
    sessionStorage.setItem("agendaScrollY", String(window.scrollY));
  });
  (function () {
    var y = sessionStorage.getItem("agendaScrollY");
    if (y !== null) window.scrollTo(0, parseInt(y, 10));
  })();
</script>
```

- これらは `sessionStorage`・`window.scrollTo` という**ページ自身の中だけで完結する API** であり、`fetch`/`XHR` のような外部リソースアクセスを伴わない。`file://` の CORS 制約に抵触しない
- 双方向インタラクション（HTML 上での操作をサーバー経由で AI へ伝える等）は本機構のスコープ外である（agenda:REQ-021 §2.2）。これらのスクリプトは表示の追従のみを行い、判断の取得はコンソール（consult との対話）が担う

## 5. テスト設計

- **単体テスト対象**:
  - `agenda_render.py`: `last_changed_fields`/`current_item_id` に応じた `data-changed`/`data-current` 属性の付与、HTML エスケープ（機密情報・特殊文字を含む本文の安全な出力）、生成物注記の出力、`agenda_state.js` の `contentVersion`/`currentItemId` が `agenda.json` の同名フィールドと一致すること、`changedItemIds` が `last_changed_fields` が空でない項目の `id` 集合と一致すること、`config.severity_field` が指定されている場合に `fields[severity_field]` の値がバッジとして出力されること・未指定の場合にバッジ要素自体が出力されないこと（§3.1a）
  - ページ内 JS（生成される固定スクリプト）: `contentVersion` 不変時に DOM 属性のみ更新し `location.reload()` を呼ばないこと、`contentVersion` 変化時に `location.reload()` を呼ぶこと（ブラウザ実行が前提のため、実装時に手動確認 or ヘッドレスブラウザでの検証を検討する）
- **手動検証観点**（ブラウザの実際の挙動に依存し、単体テストで機械的に保証できない事項）:
  - `open` コマンドでの初回表示が実際のブラウザで動作すること
  - `<script src>` 差し替えによる部分更新が主要ブラウザで動作すること
  - スクロール位置保持が実際に機能すること

## 6. 使用する既存コンポーネント

| コンポーネント           | ファイルパス                                                      | 用途                                                                                                               |
| ------------------------ | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| 討議ファイルテンプレート | `plugins/forge/skills/consult/assets/discussion_file_template.md` | 表示テンプレートへリライトして転用（移行手順は実装戦略書が持つ。[DES-075](DES-075_agenda_mechanism_design.md) §1） |
| HTML エスケープパターン  | `plugins/anvil/skills/prepare-figma/scripts/yaml_to_html.py`      | `agenda_render.py` の `html.escape()` 使用箇所の参考（PyYAML 依存は踏襲しない）                                    |
