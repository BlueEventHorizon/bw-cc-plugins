"""json_to_html.py の単体テスト（anvil:prepare-figma）。

CSS injection 対策（数値・トークンの型限定）と、preview JSON からの
HTML 生成ロジックを固定する。
"""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "anvil" / "skills" / "prepare-figma" / "scripts" / "json_to_html.py"
)

_spec = importlib.util.spec_from_file_location("anvil_json_to_html", _SCRIPT_PATH)
json_to_html = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(json_to_html)


class AsNumberTest(unittest.TestCase):
    def test_accepts_int_and_float(self):
        self.assertEqual(json_to_html._as_number(3, field="x"), 3)
        self.assertEqual(json_to_html._as_number(1.5, field="x"), 1.5)

    def test_rejects_bool(self):
        with self.assertRaises(ValueError):
            json_to_html._as_number(True, field="x")

    def test_rejects_string(self):
        with self.assertRaises(ValueError):
            json_to_html._as_number("10", field="x")


class ParsePaddingTest(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(json_to_html.parse_padding(None))

    def test_single_number(self):
        self.assertEqual(json_to_html.parse_padding(16), "16px")

    def test_dict_form(self):
        result = json_to_html.parse_padding(
            {"top": 1, "right": 2, "bottom": 3, "left": 4}
        )
        self.assertEqual(result, "1px 2px 3px 4px")

    def test_dict_form_defaults_missing_sides_to_zero(self):
        self.assertEqual(json_to_html.parse_padding({"top": 8}), "8px 0px 0px 0px")

    def test_bool_raises(self):
        with self.assertRaises(ValueError):
            json_to_html.parse_padding(True)


class SizeTokenTest(unittest.TestCase):
    def test_fill_and_hug_pass_through(self):
        self.assertEqual(json_to_html._size_token("fill"), "fill")
        self.assertEqual(json_to_html._size_token("hug"), "hug")

    def test_number_becomes_px(self):
        self.assertEqual(json_to_html._size_token(120), "120px")

    def test_none_returns_none(self):
        self.assertIsNone(json_to_html._size_token(None))

    def test_bool_raises(self):
        with self.assertRaises(ValueError):
            json_to_html._size_token(True)

    def test_arbitrary_string_raises(self):
        # CSS injection 経路を塞ぐため、"fill"/"hug" 以外の文字列は拒否する。
        with self.assertRaises(ValueError):
            json_to_html._size_token("100%; background: url(evil)")


class SizeCssTest(unittest.TestCase):
    def test_fill_on_main_axis_uses_flex(self):
        result = json_to_html._size_css("fill", "width", "horizontal")
        self.assertEqual(result, ["flex: 1", "min-width: 0"])

    def test_fill_on_cross_axis_uses_percent(self):
        result = json_to_html._size_css("fill", "width", "vertical")
        self.assertEqual(result, ["width: 100%"])

    def test_hug_produces_no_styles(self):
        self.assertEqual(json_to_html._size_css("hug", "height", None), [])

    def test_fixed_number_sets_dimension_and_shrink(self):
        result = json_to_html._size_css(56, "height", None)
        self.assertEqual(result, ["height: 56px", "flex-shrink: 0"])


class RenderPartTest(unittest.TestCase):
    def test_text_part_escapes_content(self):
        html_out = json_to_html.render_part(
            {"id": "t", "type": "text", "content": "<script>alert(1)</script>"}
        )
        self.assertIn("&lt;script&gt;", html_out)
        self.assertNotIn("<script>alert(1)</script>", html_out)

    def test_container_renders_children_recursively(self):
        part = {
            "id": "root",
            "layout": "vertical",
            "children": [{"id": "child", "type": "text", "content": "hi"}],
        }
        html_out = json_to_html.render_part(part)
        self.assertIn('data-id="root"', html_out)
        self.assertIn('data-id="child"', html_out)

    def test_stack_layout_warns_and_falls_back(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            json_to_html.render_part({"id": "s", "layout": "stack"})
        self.assertIn("layout: stack", stderr.getvalue())


class BuildDocumentTest(unittest.TestCase):
    def test_missing_root_raises(self):
        with self.assertRaises(ValueError):
            json_to_html.build_document({})

    def test_builds_full_html_document(self):
        doc = json_to_html.build_document(
            {"meta": {"title": "T"}, "root": {"id": "r", "type": "text", "content": "x"}}
        )
        self.assertIn("<!DOCTYPE html>", doc)
        self.assertIn("<title>T</title>", doc)


class MainTest(unittest.TestCase):
    def _run_main(self, argv):
        import sys

        old_argv = sys.argv
        sys.argv = ["json_to_html.py", *argv]
        try:
            return json_to_html.main()
        finally:
            sys.argv = old_argv

    def test_valid_json_produces_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "input.json"
            out_path = Path(tmp) / "output.html"
            in_path.write_text(
                json.dumps(
                    {"preview": {"root": {"id": "r", "type": "text", "content": "hi"}}}
                ),
                encoding="utf-8",
            )
            exit_code = self._run_main([str(in_path), str(out_path)])
            self.assertEqual(exit_code, 0)
            self.assertIn("<!DOCTYPE html>", out_path.read_text(encoding="utf-8"))

    def test_invalid_json_reports_parse_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "input.json"
            out_path = Path(tmp) / "output.html"
            in_path.write_text("{not valid json", encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = self._run_main([str(in_path), str(out_path)])
            self.assertEqual(exit_code, 1)
            self.assertIn("JSON parse error", stderr.getvalue())

    def test_non_object_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "input.json"
            out_path = Path(tmp) / "output.html"
            in_path.write_text("[1, 2, 3]", encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = self._run_main([str(in_path), str(out_path)])
            self.assertEqual(exit_code, 1)
            self.assertIn("JSON root must be an object", stderr.getvalue())

    def test_missing_preview_root_reports_schema_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "input.json"
            out_path = Path(tmp) / "output.html"
            in_path.write_text(json.dumps({"preview": {}}), encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = self._run_main([str(in_path), str(out_path)])
            self.assertEqual(exit_code, 1)
            self.assertIn("Schema error", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
