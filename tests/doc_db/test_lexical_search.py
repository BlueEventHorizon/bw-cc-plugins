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


if __name__ == "__main__":
    unittest.main()
