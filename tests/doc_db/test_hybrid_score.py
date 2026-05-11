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

    # 施策3: emb-only フォールバックテスト
    def test_emb_fallback_when_lex_ratio_low(self):
        """lex ヒット率が EMB_FALLBACK_LEX_RATIO 未満の場合、emb スコア順でフォールバックする"""
        # emb 100 件に対して lex ヒット 4 件 → lex_ratio = 0.04 < 0.05
        emb = [{"chunk_id": str(i), "emb_score": 1.0 - i * 0.01} for i in range(100)]
        lex = [{"chunk_id": str(i), "lex_score": float(i)} for i in range(4)]
        result = hybrid_score.rrf_fuse(emb, lex, k=60)
        # フォールバック時は emb スコア降順になる
        scores = [r["score"] for r in result[:5]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # rank 1 は emb スコア最高の chunk_id="0"
        self.assertEqual(result[0]["chunk_id"], "0")

    def test_rrf_used_when_lex_ratio_sufficient(self):
        """lex ヒット率が EMB_FALLBACK_LEX_RATIO 以上なら通常 RRF を使用する"""
        # emb 10 件に対して lex 1 件 → lex_ratio = 0.1 >= 0.05 → RRF
        emb = [{"chunk_id": str(i), "emb_score": 1.0 - i * 0.1} for i in range(10)]
        lex = [{"chunk_id": "9", "lex_score": 100.0}]  # lex 最高スコアは emb 最低スコアのチャンク
        result = hybrid_score.rrf_fuse(emb, lex, k=60)
        # RRF なら chunk "9" が上位に来る（lex ブーストがかかるため）
        top_ids = [r["chunk_id"] for r in result[:3]]
        self.assertIn("9", top_ids)

    def test_emb_fallback_with_zero_lex(self):
        """lex ヒットが 0 件の場合も emb only フォールバックが動作する"""
        emb = [{"chunk_id": "a", "emb_score": 0.9}, {"chunk_id": "b", "emb_score": 0.5}]
        result = hybrid_score.rrf_fuse(emb, [], k=60)
        self.assertEqual(result[0]["chunk_id"], "a")
        self.assertEqual(result[1]["chunk_id"], "b")


if __name__ == "__main__":
    unittest.main()
