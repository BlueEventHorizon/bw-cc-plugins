"""extract_preview_json.py の単体テスト（anvil:prepare-figma）。

デザイン仕様書 Markdown 内の ```json フェンスから、トップレベルキー
``preview`` を持つ JSON ブロックだけを正しく選び出すことを固定する。
"""

import importlib.util
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "anvil" / "skills" / "prepare-figma" / "scripts"
    / "extract_preview_json.py"
)

_spec = importlib.util.spec_from_file_location(
    "anvil_extract_preview_json", _SCRIPT_PATH
)
extract_preview_json = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extract_preview_json)


class ExtractPreviewBlockTest(unittest.TestCase):
    def test_extracts_single_preview_block(self):
        md = '''# spec

```json
{ "preview": { "root": { "id": "r" } } }
```
'''
        body = extract_preview_json.extract_preview_block(md)
        self.assertIsNotNone(body)
        self.assertIn('"preview"', body)

    def test_picks_preview_block_among_multiple_json_fences(self):
        md = '''# spec

```json
{ "sample_api_response": { "status": "ok" } }
```

```json
{ "preview": { "root": { "id": "r" } } }
```
'''
        body = extract_preview_json.extract_preview_block(md)
        self.assertIn('"preview"', body)
        self.assertNotIn("sample_api_response", body)

    def test_skips_invalid_json_fence_and_tries_next(self):
        md = '''# spec

```json
{ this is not valid json
```

```json
{ "preview": { "root": { "id": "r" } } }
```
'''
        body = extract_preview_json.extract_preview_block(md)
        self.assertIn('"preview"', body)

    def test_legacy_yaml_fence_is_ignored(self):
        md = '''# spec

```yaml
preview:
  root:
    id: r
```
'''
        body = extract_preview_json.extract_preview_block(md)
        self.assertIsNone(body)

    def test_non_object_top_level_returns_none(self):
        md = '''# spec

```json
[1, 2, 3]
```
'''
        body = extract_preview_json.extract_preview_block(md)
        self.assertIsNone(body)

    def test_object_without_preview_key_returns_none(self):
        md = '''# spec

```json
{ "root": { "id": "r" } }
```
'''
        body = extract_preview_json.extract_preview_block(md)
        self.assertIsNone(body)

    def test_no_fence_returns_none(self):
        md = "# spec\n\nno code blocks here.\n"
        self.assertIsNone(extract_preview_json.extract_preview_block(md))


class MainTest(unittest.TestCase):
    def _run_main(self, argv):
        import sys

        old_argv = sys.argv
        sys.argv = ["extract_preview_json.py", *argv]
        try:
            return extract_preview_json.main()
        finally:
            sys.argv = old_argv

    def test_writes_extracted_block_to_output_file(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "spec.md"
            out_path = Path(tmp) / "preview.json"
            spec_path.write_text(
                '# spec\n\n```json\n{ "preview": { "root": { "id": "r" } } }\n```\n',
                encoding="utf-8",
            )
            exit_code = self._run_main([str(spec_path), str(out_path)])
            self.assertEqual(exit_code, 0)
            self.assertIn('"preview"', out_path.read_text(encoding="utf-8"))

    def test_no_preview_block_returns_error(self):
        import io
        import tempfile
        from contextlib import redirect_stderr

        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "spec.md"
            out_path = Path(tmp) / "preview.json"
            spec_path.write_text("# spec\n\nno json here.\n", encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = self._run_main([str(spec_path), str(out_path)])
            self.assertEqual(exit_code, 1)
            self.assertIn("No preview JSON block found", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
