import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "plugins/doc-db/scripts"))

import hybrid_score


class HybridScoreTests(unittest.TestCase):
    def test_rrf_is_deterministic(self):
        emb = [{"chunk_id": "a", "emb_score": 0.9}, {"chunk_id": "b", "emb_score": 0.8}]
        lex = [{"chunk_id": "b", "lex_score": 5.0}, {"chunk_id": "a", "lex_score": 2.0}]
        r1 = hybrid_score.rrf_fuse(emb, lex, k=60)
        r2 = hybrid_score.rrf_fuse(emb, lex, k=60)
        self.assertEqual(r1, r2)

    def test_linear_alpha_boundaries(self):
        emb = [{"chunk_id": "a", "emb_score": 0.9}]
        lex = [{"chunk_id": "a", "lex_score": 0.1}]
        only_lex = hybrid_score.linear_fuse(emb, lex, alpha=0.0)[0]["score"]
        only_emb = hybrid_score.linear_fuse(emb, lex, alpha=1.0)[0]["score"]
        self.assertEqual(only_lex, 0.1)
        self.assertEqual(only_emb, 0.9)

    def test_empty_input(self):
        self.assertEqual(hybrid_score.combine_scores([], [], method="rrf"), [])
        self.assertEqual(hybrid_score.combine_scores([], [], method="linear"), [])


if __name__ == "__main__":
    unittest.main()
