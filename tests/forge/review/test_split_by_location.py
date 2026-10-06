#!/usr/bin/env python3
"""
split_by_location.py のテスト

分けているのは所見の性質（位置が確定しているか）だけであり、介入軸にも重大度にも
依存しない。この不依存が壊れると、確信の無い修正が重大度を理由に通ってしまう。
位置の形は文字列の配列で、特定できないときは `位置未確定` だけを要素とする
（REQ-029 DM-304、DES-084 §5.3）。

実行:
  python3 -m unittest tests.forge.review.test_split_by_location -v
"""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "review" / "scripts" / "split_by_location.py"
)

_spec = importlib.util.spec_from_file_location("forge_split_by_location", _SCRIPT_PATH)
split_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(split_mod)

UNKNOWN = "位置未確定"


def _finding(finding_id=1, location=None, body="dummy"):
    """reviewer の所見の形に合わせた finding（`finding_id`・`location`・`body`）。

    既定では確定した位置を与える。位置未確定の振り分けを検査する場合だけ
    `location` を明示して上書きする。
    """
    return {
        "finding_id": finding_id,
        "location": location if location is not None else ["/abs/a.py:1"],
        "body": body,
    }


class LocationDecidesTest(unittest.TestCase):
    """修正できるかを決めるのは位置だけである。"""

    def test_located_findings_are_fixable(self):
        findings = [
            _finding(1, ["/abs/a.py:1"]),
            _finding(2, ["/abs/a.py:3-9"]),
            _finding(3, ["/abs/a.py:1", "/abs/b.py:5"]),
        ]
        result = split_mod.split_by_location(findings)
        self.assertEqual(result["located"], findings)
        self.assertEqual(result["unlocated"], [])

    def test_only_unknown_marker_is_unlocated(self):
        """`位置未確定` だけを要素とする配列は、修正対象を特定できない。"""
        finding = _finding(1, [UNKNOWN])
        result = split_mod.split_by_location([finding])
        self.assertEqual(result["located"], [])
        self.assertEqual(result["unlocated"], [finding])

    def test_unknown_marker_mixed_with_a_confirmed_location_is_located(self):
        """確定した位置を 1 つでも持つなら、その位置は修正対象を特定できる。"""
        finding = _finding(1, [UNKNOWN, "/abs/a.py:2"])
        self.assertEqual(split_mod.split_by_location([finding])["located"], [finding])

    def test_repeated_unknown_markers_are_unlocated(self):
        finding = _finding(1, [UNKNOWN, UNKNOWN])
        self.assertEqual(split_mod.split_by_location([finding])["unlocated"], [finding])

    def test_missing_location_key_is_unlocated(self):
        """`location` を欠く不正な入力も安全側に倒して unlocated とする。"""
        finding = {"finding_id": 1, "body": "dummy"}
        result = split_mod.split_by_location([finding])
        self.assertEqual(result["located"], [])
        self.assertEqual(result["unlocated"], [finding])

    def test_empty_location_array_is_unlocated(self):
        """空の配列に「確定した」の意味を持たせない。"""
        finding = _finding(1, [])
        self.assertEqual(split_mod.split_by_location([finding])["unlocated"], [finding])

    def test_non_array_location_is_unlocated(self):
        """旧い形（辞書・文字列）の位置は、確定した位置とは見なさない。"""
        for location in ({"path": "a.py", "line": 1}, "/abs/a.py:1", None):
            with self.subTest(location=location):
                finding = {"finding_id": 1, "location": location, "body": "dummy"}
                self.assertEqual(
                    split_mod.split_by_location([finding])["unlocated"], [finding]
                )

    def test_non_string_or_blank_entries_are_not_a_confirmed_location(self):
        for location in ([None], [1], [""], ["   "]):
            with self.subTest(location=location):
                finding = _finding(1, location)
                self.assertEqual(
                    split_mod.split_by_location([finding])["unlocated"], [finding]
                )

    def test_empty_findings_list(self):
        self.assertEqual(split_mod.split_by_location([]), {"located": [], "unlocated": []})

    def test_order_is_preserved(self):
        """並べ替えは提示側の仕事であり、ここでは入力順を保つ。"""
        findings = [_finding(5), _finding(2), _finding(9, [UNKNOWN]), _finding(1, [UNKNOWN])]
        result = split_mod.split_by_location(findings)
        self.assertEqual([f["finding_id"] for f in result["located"]], [5, 2])
        self.assertEqual([f["finding_id"] for f in result["unlocated"]], [9, 1])


class SeverityIsIrrelevantTest(unittest.TestCase):
    """重大度は修正の可否を決めない。

    所見は重大度を持たず、決めるのは本体の確信度であり、所見の中身を読んで初めて決まる。
    決定論的な処理ではないため本スクリプトは扱わない。ここで重大度による絞り込みが復活すると、
    **確信の無い修正が「重大度が高いから」という理由で通る**。
    """

    def test_severity_value_does_not_change_the_split(self):
        for severity in ("critical", "major", "minor", "bogus", None):
            with self.subTest(severity=severity):
                located = dict(_finding(1), severity=severity)
                unlocated = dict(_finding(2, [UNKNOWN]), severity=severity)
                result = split_mod.split_by_location([located, unlocated])
                self.assertEqual(result["located"], [located])
                self.assertEqual(result["unlocated"], [unlocated])


class ContractTest(unittest.TestCase):
    """介入軸を受け取らないこと自体が契約である。"""

    def test_function_takes_no_mode(self):
        """mode を渡せてしまうと、介入軸で結果が変わる余地が戻る。"""
        with self.assertRaises(TypeError):
            split_mod.split_by_location([], "auto")

    def test_output_has_exactly_two_keys(self):
        self.assertEqual(set(split_mod.split_by_location([])), {"located", "unlocated"})


class MainTest(unittest.TestCase):
    """main(): --findings-file 引数処理・単一 JSON 出力・失敗の返し方。"""

    def _run(self, *args):
        return subprocess.run(
            ["python3", str(_SCRIPT_PATH), *args], capture_output=True, text=True
        )

    def _write(self, directory, payload):
        path = Path(directory) / "review_result.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def test_cli_reads_the_result_file_and_outputs_single_json(self):
        located = _finding(1, ["/abs/a.py:1"])
        unlocated = _finding(2, [UNKNOWN])
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"findings": [located, unlocated], "exit": "0"})
            result = self._run("--findings-file", path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout), {"located": [located], "unlocated": [unlocated]}
        )

    def test_cli_keeps_a_body_with_quotes_and_newlines_intact(self):
        """所見の本文は自由記述であり、ファイル経由なら値が変形しない。"""
        body = '引用符 " と \' とバッククォート ` と\n改行'
        unlocated = _finding(1, [UNKNOWN], body=body)
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"findings": [unlocated], "exit": "0"})
            result = self._run("--findings-file", path)
        self.assertEqual(json.loads(result.stdout)["unlocated"][0]["body"], body)

    def test_cli_accepts_zero_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"findings": [], "exit": "0"})
            result = self._run("--findings-file", path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"located": [], "unlocated": []})

    def test_cli_fails_with_errors_when_the_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run("--findings-file", str(Path(tmp) / "none.json"))
        self.assertEqual(result.returncode, 1)
        self.assertTrue(json.loads(result.stdout)["errors"])

    def test_cli_fails_with_errors_when_findings_is_not_an_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            for payload in ({"findings": "x"}, {"exit": "0"}, [1, 2]):
                with self.subTest(payload=payload):
                    result = self._run("--findings-file", self._write(tmp, payload))
                    self.assertEqual(result.returncode, 1)
                    self.assertTrue(json.loads(result.stdout)["errors"])

    def test_cli_rejects_mode_argument(self):
        """`--mode` を復活させない（介入軸で振り分けを変える口を作らない）。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"findings": []})
            result = self._run("--findings-file", path, "--mode", "auto")
        self.assertEqual(result.returncode, 2)

    def test_cli_no_longer_takes_an_inline_json_argument(self):
        """所見の本文を含む JSON を、シェル文字列として埋め込む口を残さない。"""
        result = self._run("--findings-json", "[]")
        self.assertEqual(result.returncode, 2)

    def test_cli_requires_findings_file(self):
        result = self._run()
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
