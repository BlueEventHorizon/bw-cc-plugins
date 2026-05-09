import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT / "meta/scripts"))
sys.path.insert(0, str(ROOT / "plugins/doc-db/scripts"))

import evaluate


class EvaluateTests(unittest.TestCase):
    def test_precision_recall(self):
        precision, recall, fn = evaluate._precision_recall(
            ["a.md", "b.md"],
            ["a.md", "c.md"],
        )
        self.assertAlmostEqual(precision, 0.5)
        self.assertAlmostEqual(recall, 0.5)
        self.assertEqual(fn, ["c.md"])

    def test_false_negative_classification(self):
        self.assertEqual(evaluate.classify_false_negative("FNC-006", "x.md"), "ID検索失敗")
        self.assertEqual(evaluate.classify_false_negative("a" * 90, "x.md"), "長文希釈")
        self.assertEqual(evaluate.classify_false_negative("自然文クエリ", "x.md"), "自然文意味ズレ")

    def test_markdown_report_contains_summary(self):
        md = evaluate.render_markdown_report(
            {
                "doc-db": {
                    "recall": 0.8,
                    "precision": 0.7,
                    "false_negative_count": 2,
                    "api_calls": 3,
                    "token_usage": 123,
                    "false_negative_by_type": {"ID検索失敗": 2},
                }
            }
        )
        self.assertIn("| doc-db | 0.8000 | 0.7000 | 2 | 3 | 123 |", md)
        self.assertIn("ID検索失敗: 2", md)

    def test_temp_workspace_prepare_and_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / "plugins/doc-advisor/scripts").mkdir(parents=True)
            (root / "meta/test_docs").mkdir(parents=True)
            docs = root / "meta/test_docs/docs"
            docs.mkdir(parents=True)
            (docs / "a.md").write_text("# x\n", encoding="utf-8")
            (root / "plugins/doc-advisor/scripts/search_docs.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "plugins/doc-advisor/scripts/embedding_api.py").write_text(
                'EMBEDDING_MODEL = "text-embedding-3-small"\n',
                encoding="utf-8",
            )
            tmp = evaluate.prepare_temp_advisor_workspace(root, docs)
            self.assertTrue((tmp / "scripts/search_docs.py").exists())
            emb = (tmp / "scripts/embedding_api.py").read_text(encoding="utf-8")
            self.assertIn("text-embedding-3-large", emb)
            evaluate.cleanup_temp_workspace(tmp)
            self.assertFalse(tmp.exists())


if __name__ == "__main__":
    unittest.main()
