# CommonMark 適合テスト用フィクスチャ

## spec.json

CommonMark 仕様書に収録された 652 の用例を機械可読にしたもの。1 件が
`{markdown, html, example, start_line, end_line, section}` を持つ。

- 出所: CommonMark Spec（<https://spec.commonmark.org/>）
- ライセンス: Creative Commons BY-SA 4.0
- 著作権: John MacFarlane 他、CommonMark の貢献者

**上流のまま置く。整形・並べ替え・部分削除をしてはならない。** 公式との byte
一致が、この用例集を規範として引ける根拠である。`dprint.jsonc` の `excludes`
がこのディレクトリを整形対象から外しているのはそのためである。

用例のうち何を適合の対象とし、何を対象外とするかは
`tests/forge/doc_reference/test_commonmark_conformance.py` が定める。
