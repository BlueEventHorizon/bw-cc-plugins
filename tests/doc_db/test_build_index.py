import json
import os
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT / "plugins/doc-db/scripts"))

import build_index


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


class BuildIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "docs/rules").mkdir(parents=True)
        (self.root / "docs/rules/a.md").write_text("# Title\nbody", encoding="utf-8")
        _write_doc_structure(self.root)
        os.environ["OPENAI_API_KEY"] = "dummy"
        self._old_embed = build_index.call_embedding_api
        build_index.call_embedding_api = lambda texts, _: [[0.1, 0.2] for _ in texts]

    def tearDown(self):
        build_index.call_embedding_api = self._old_embed
        self.tmp.cleanup()

    def test_build_chunk_index(self):
        rc = build_index.run_build(self.root, "rules", full=True)
        self.assertEqual(rc, 0)
        index_path = build_index.get_index_path(self.root, "rules")
        data = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(data["metadata"]["build_state"], "complete")
        self.assertGreater(len(data["entries"]), 0)

    def test_schema_mismatch_requires_full(self):
        index_path = build_index.get_index_path(self.root, "rules")
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(
            json.dumps({"metadata": {"schema_version": "0.0"}, "entries": {}}),
            encoding="utf-8",
        )
        rc = build_index.run_build(self.root, "rules", full=False)
        self.assertEqual(rc, 2)

    def test_failed_chunks_mark_incomplete(self):
        def _raise(*_args, **_kwargs):
            raise RuntimeError("boom")

        build_index.call_embedding_api = _raise
        rc = build_index.run_build(self.root, "rules", full=True)
        self.assertEqual(rc, 0)
        data = json.loads(build_index.get_index_path(self.root, "rules").read_text(encoding="utf-8"))
        self.assertEqual(data["metadata"]["build_state"], "incomplete")
        self.assertGreater(len(data["metadata"]["failed_chunks"]), 0)


if __name__ == "__main__":
    unittest.main()
