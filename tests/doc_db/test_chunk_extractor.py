import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "plugins/doc-db/scripts"))

import chunk_extractor


class ChunkExtractorTests(unittest.TestCase):
    def test_heading_hierarchy_and_ranges(self):
        text = "# A\nintro\n## B\nbody\n### C\nmore\n"
        chunks = chunk_extractor.extract_chunks("docs/a.md", text)
        self.assertEqual(chunks[0]["heading_path"], ["A"])
        self.assertEqual(chunks[1]["heading_path"], ["A", "B"])
        self.assertEqual(chunks[2]["heading_path"], ["A", "B", "C"])
        for chunk in chunks:
            start, end = chunk["char_range"]
            self.assertEqual(text[start:end], chunk["body"])

    def test_no_heading_single_chunk(self):
        text = "plain\ncontent\n"
        chunks = chunk_extractor.extract_chunks("docs/a.md", text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["heading_path"], [])
        self.assertEqual(chunks[0]["body"], text)

    def test_split_large_chunk(self):
        text = "# A\n" + ("x" * 30) + "\n\n" + ("y" * 30)
        chunks = chunk_extractor.extract_chunks("docs/a.md", text, max_chunk_chars=40)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(len(c["body"]) <= 40 for c in chunks))

    def test_chunk_id_collision_adds_suffix(self):
        class _FakeHash:
            def hexdigest(self):
                return "deadbeef" * 8

        text = "# A\nfirst\n## B\nsecond\n"
        with patch.object(chunk_extractor.hashlib, "sha256", return_value=_FakeHash()):
            chunks = chunk_extractor.extract_chunks("docs/a.md", text)
        self.assertEqual(chunks[0]["chunk_id"], "deadbeef")
        self.assertEqual(chunks[1]["chunk_id"], "deadbeef-2")


if __name__ == "__main__":
    unittest.main()
