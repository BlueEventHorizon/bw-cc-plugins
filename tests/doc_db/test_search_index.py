import json
import os
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT / "plugins/doc-db/scripts"))

import build_index
import search_index


def _write_doc_structure(root: pathlib.Path):
    (root / ".doc_structure.yaml").write_text(
        "\n".join(
            [
                "rules:",
                "  root_dirs:",
                "    - docs/rules/",
                "  doc_types_map:",
                "    docs/rules/: rule",
                "  patterns:",
                "    target_glob: \"**/*.md\"",
                "    exclude: []",
                "specs:",
                "  root_dirs: []",
                "  doc_types_map: {}",
                "  patterns:",
                "    target_glob: \"**/*.md\"",
                "    exclude: []",
            ]
        ),
        encoding="utf-8",
    )


class SearchIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "docs/rules").mkdir(parents=True)
        (self.root / "docs/rules/a.md").write_text("# FNC-006\nalpha body", encoding="utf-8")
        _write_doc_structure(self.root)
        os.environ["OPENAI_API_KEY"] = "dummy"

        self._old_embed = build_index.call_embedding_api
        self._old_qembed = search_index.call_embedding_api_single
        build_index.call_embedding_api = lambda texts, _: [[0.1, 0.2] for _ in texts]
        search_index.call_embedding_api_single = lambda *_: [0.1, 0.2]
        build_index.run_build(self.root, "rules", full=True)

    def tearDown(self):
        build_index.call_embedding_api = self._old_embed
        search_index.call_embedding_api_single = self._old_qembed
        self.tmp.cleanup()

    def test_modes(self):
        for mode in ("emb", "lex", "hybrid"):
            rc = search_index.search(self.root, "rules", "FNC-006", mode, 5)
            self.assertEqual(rc, 0)

    def test_generated_at_mismatch(self):
        checksums_path = build_index.get_checksums_path(build_index.get_index_path(self.root, "rules"))
        txt = checksums_path.read_text(encoding="utf-8").replace("generated_at:", "generated_at: 1999-01-01T00:00:00Z #")
        checksums_path.write_text(txt, encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            search_index.search(self.root, "rules", "x", "lex", 3)
        self.assertEqual(ctx.exception.code, 2)

    def test_stale_auto_rebuild(self):
        (self.root / "docs/rules/a.md").write_text("# FNC-006\nupdated body", encoding="utf-8")
        rc = search_index.search(self.root, "rules", "updated", "hybrid", 3)
        self.assertEqual(rc, 0)
        index = json.loads(build_index.get_index_path(self.root, "rules").read_text(encoding="utf-8"))
        bodies = [v["body"] for v in index["entries"].values()]
        self.assertTrue(any("updated body" in b for b in bodies))


if __name__ == "__main__":
    unittest.main()
