# アジェンダ表示構造リファレンス

このファイルは `agenda_render.py` が生成する `agenda.html` の構造を説明する参照文書である。**保存形式ではない**。この文書の書式に従って討議ファイルを手動作成・編集する運用はない。

記録の実体は `agenda_store.py` が管理する JSON であり、`agenda.html` はそこから毎回生成される提示物である（`agenda.html` 本文にも「手編集しても保存されない」旨の生成物注記が表示される）。

## 全体構造

`agenda.html` は次の要素で構成される。

- `<head>`: `<meta charset="utf-8">`・`<title>アジェンダ: {identity}</title>`・`<style>` によるスタイル定義（ドット・バッジ等の配色を含む）
- `<h1>`: アジェンダ全体のタイトル（`アジェンダ: {identity}`）
- `.generated-notice`: 生成物であることを示す注記（生成日時を含む）
- `#agenda-summary` テーブル: 項目一覧。列は ID・項目・重要度・状態・結果・課題
- `<section id="item-{ID}" data-changed="..." data-current="...">`: 項目ごとの節。項目数だけ並ぶ
  - `.gutter` 内の `.state-dot`: 状態表示（下記「状態表示」参照）
  - `<h2>`: `[ID] 項目名` に続けて重要度バッジ（設定時のみ）
  - `<p>`: 背景・本質・決着の3行
- ページ末尾の2つの `<script>` ブロック: 数秒ごとの状態反映（下記「表示の更新」参照）とスクロール位置の保存・復元（`pagehide` イベントで保存し、再読み込み後に復元する）

## 状態表示

変更箇所・対話中の項目は、カード全体の背景色ではなく `<section>` 左側余白（`.gutter`）の小さなドットに集約して示す。ドット自体（`.state-dot.changed`/`.state-dot.current`）は常に出力されており、実際に可視・不可視を切り替えるのは `<section>` タグが持つ `data-changed`/`data-current` 属性である（CSS の属性セレクタ `section[data-changed="true"] .state-dot.changed` 等が、属性の値に応じてドットの配色を切り替える）。

- `data-changed="true"`: 直前の更新で変わった項目
- `data-current="true"`: 今対話中の項目

2つは別々の属性であり、同時に両方が立つ項目もありうる。

## 重要度バッジ

項目見出しの重要度バッジ（パステル配色 + テキストラベル）は、重要度を表すフィールドが設定されている場合にのみ表示される。設定されていない場合、バッジ要素自体が出力されない。バッジの値は呼び出し側が渡した文字列そのままであり、この機構は値の意味（重要度の順序等）を解釈しない。**現状の実装は `data-severity` 値ごとの配色分岐を持たず全て同一の灰色であり、仕様が要求するパステル配色は未実装である**（後述「既知の未解決事項」参照）。

## 決着欄

アジェンダ表の「結果・課題」列（`_result_summary()`）と項目節の「決着」行（`_decision_text()`）は、判定条件が異なる。「結果・課題」列は `decision.outcome` が設定されていれば表示し、未設定なら `-` を表示する。`decision.outcome` と `decision.reason` の両方が設定されている場合は `outcome: reason` の形式で連結して表示する（`decision.reason` 単独では表示の有無に影響せず、`decision.outcome` が無ければ `decision.reason` があっても `-` のままである）。「決着」行は `decision.outcome` が無くても `decision.reason` があればその内容を表示し、両方とも無い場合のみ `(未定)` を表示する。`decision.outcome` と `decision.reason` の両方が設定されている場合は `outcome（reason）`（全角括弧）の形式で連結する——「結果・課題」列の `outcome: reason` とは異なる書式である。そのため `decision.reason` のみを記入し `decision.outcome` を記入していない場合、「決着」行には内容が表示されるのに「結果・課題」列は未記入用の `-` のままになる、という非対称が生じうる。

## 表示の更新

`agenda.html` が再生成されるのは `content_version` が増える書き込み操作（`init`/`update`/`record-structural-judgment`）の直後だけである。`set-current` は `content_version` を増やさないため、`agenda_state.js` のみが再生成され、`agenda.html` 本体は再生成されない。対話中の項目・変更箇所のフラグ変化はページ内スクリプトが数秒ごとに軽量に反映し、内容そのものが変わった場合に限りページ全体が再読み込みされる。呼び出し側が明示的に再描画を指示する操作はない。

## ID 振り直し・削除操作を機構が提供しない

ID を後から振り直す操作、状態が「取り下げ」「対象外」の項目を削除する操作は、`agenda_store.py` の CLI（`init`/`update`/`next`/`pending`/`record-structural-judgment`/`set-current`）が提供していない。

## 既知の未解決事項

**決着後の記入欄が空にできてしまう**: `agenda_schema.py` の検証（`background`/`essence` の非空チェック等）は、差分パッチが `status` キーを含む場合にのみ働く（`agenda_store.py` の `upsert_item()` 参照）。決着済み項目に対して `status` を含まない差分パッチ（例: `background` だけを変更するパッチ）を送ると、`background`/`essence` は検証を経ずに書き換えられる。これは機構が機械的に強制していない挙動であり、呼び出し側（consult）が意図せず記入欄を空にしないよう注意する必要がある。

**重要度バッジの配色が未実装**: `.severity-badge` の CSS は `data-severity` の値に関わらず固定の灰色（`background: #eee; color: #555;`）であり、重要度ごとの配色分岐は実装されていない。
