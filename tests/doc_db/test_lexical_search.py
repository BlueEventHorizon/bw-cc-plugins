import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "plugins/doc-db/scripts"))

import lexical_search


class LexicalSearchTests(unittest.TestCase):
    def test_id_exact_match_boost(self):
        chunks = [
            {"chunk_id": "a", "body": "this has fnc-006 only once"},
            {"chunk_id": "b", "body": "natural language query text repeated repeated"},
        ]
        results = lexical_search.score_chunks("FNC-006", chunks)
        self.assertEqual(results[0]["chunk_id"], "a")

    def test_nfkc_normalization(self):
        chunks = [{"chunk_id": "a", "body": "ＡＢＣ１２３"}]
        results = lexical_search.score_chunks("abc123", chunks)
        self.assertEqual(results[0]["chunk_id"], "a")

    # 施策1: TOKEN_RE 修正テスト
    def test_tokenize_splits_cjk_and_ascii(self):
        """日本語と ASCII の境界でトークン分割される"""
        tokens = lexical_search.tokenize("のコンテキスト外検索と3モード検索方式")
        self.assertIn("3", tokens)
        # 「のコンテキスト外検索と3モード検索方式」が1トークンになっていないこと
        self.assertNotIn("のコンテキスト外検索と3モード検索方式", tokens)

    def test_tokenize_splits_cjk_and_latin(self):
        """日本語の直後に ASCII が続く場合に分割される"""
        tokens = lexical_search.tokenize("見落としゼロの検索精度要件とGolden Set")
        self.assertIn("golden", tokens)
        self.assertIn("set", tokens)
        # 「見落としゼロの検索精度要件とgolden」が1トークンになっていないこと
        self.assertNotIn("見落としゼロの検索精度要件とgolden", tokens)

    def test_tokenize_digits_separate(self):
        """数字が独立したトークンになる"""
        tokens = lexical_search.tokenize("3モード検索方式")
        self.assertIn("3", tokens)

    def test_cjk_keyword_matches_in_body(self):
        """施策1修正後、クエリの重要語が body 内に存在すれば score が付く"""
        chunks = [
            {"chunk_id": "target", "body": "3 モード検索方式が使用される"},
            {"chunk_id": "other",  "body": "関係ない文書"},
        ]
        results = lexical_search.score_chunks("doc-advisor のコンテキスト外検索と3モード検索方式", chunks)
        chunk_ids = [r["chunk_id"] for r in results]
        self.assertIn("target", chunk_ids)
        target_score = next(r["lex_score"] for r in results if r["chunk_id"] == "target")
        self.assertGreater(target_score, 0)

    # 施策5: 同義語展開テスト
    def test_phrase_synonym_en_to_ja(self):
        """英語フレーズクエリで日本語表記の文書がヒットする"""
        chunks = [
            {"chunk_id": "ja",  "body": "ゴールデンセットによる評価"},
            {"chunk_id": "en",  "body": "golden set evaluation"},
            {"chunk_id": "other", "body": "関係ない文書"},
        ]
        results = lexical_search.score_chunks("Golden Set", chunks)
        chunk_ids = [r["chunk_id"] for r in results]
        self.assertIn("ja", chunk_ids, "日本語表記のチャンクが同義語展開でヒットすること")
        self.assertIn("en", chunk_ids)

    def test_phrase_synonym_ja_to_en(self):
        """日本語フレーズクエリで英語表記の文書がヒットする"""
        chunks = [
            {"chunk_id": "en", "body": "golden set evaluation method"},
            {"chunk_id": "other", "body": "関係ない文書"},
        ]
        results = lexical_search.score_chunks("ゴールデンセット評価", chunks)
        chunk_ids = [r["chunk_id"] for r in results]
        self.assertIn("en", chunk_ids, "英語表記のチャンクが同義語展開でヒットすること")


if __name__ == "__main__":
    unittest.main()
