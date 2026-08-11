#!/usr/bin/env python3
"""
gate_findings.py のテスト（forge:DES-066 §3.10 / §6 テスト設計）

分けているのは所見の性質（位置が確定しているか）だけであり、介入軸にも重大度にも
依存しない。この不依存が壊れると、確信の無い修正が重大度を理由に通ってしまう。

実行:
  python3 -m unittest tests.forge.review.test_gate_findings -v
"""

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "review" / "scripts" / "gate_findings.py"
)

_spec = importlib.util.spec_from_file_location("msg_review_gate_findings", _SCRIPT_PATH)
gate_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate_mod)


def _finding(severity, text="dummy", location=None):
    """共通 parser の出力形に合わせた finding。

    parser は位置を必ず持たせる（`path` + `line`、または `unknown: true`）ため、
    既定では確定した位置を与える。位置未確定の振り分けを検査する場合だけ
    `location` を明示して上書きする。
    """
    return {
        "severity": severity,
        "text": text,
        "location": location if location is not None else {"path": "a.py", "line": 1},
    }


class LocationDecidesTest(unittest.TestCase):
    """修正できるかを決めるのは位置だけである。"""

    def test_located_findings_are_fixable(self):
        findings = [_finding("critical"), _finding("major"), _finding("minor")]
        result = gate_mod.gate_findings(findings)
        self.assertEqual(result["auto_fix"], findings)
        self.assertEqual(result["excluded"], [])

    def test_unknown_location_is_excluded(self):
        """位置が確定していない所見は修正対象を特定できない。"""
        finding = _finding("critical", location={"unknown": True})
        result = gate_mod.gate_findings([finding])
        self.assertEqual(result["auto_fix"], [])
        self.assertEqual(result["excluded"], [finding])

    def test_missing_location_key_is_excluded(self):
        """`location` を欠く不正な入力も安全側に倒して excluded とする。"""
        finding = {"severity": "critical", "text": "dummy"}
        result = gate_mod.gate_findings([finding])
        self.assertEqual(result["auto_fix"], [])
        self.assertEqual(result["excluded"], [finding])

    def test_empty_findings_list(self):
        self.assertEqual(gate_mod.gate_findings([]), {"auto_fix": [], "excluded": []})

    def test_order_is_preserved(self):
        """並べ替えは提示側の仕事であり、ここでは入力順を保つ。"""
        findings = [_finding("minor", "m"), _finding("critical", "c")]
        self.assertEqual(gate_mod.gate_findings(findings)["auto_fix"], findings)


class SeverityIsIrrelevantTest(unittest.TestCase):
    """重大度は修正の可否を決めない（REQ-013 FNC-1304）。

    決めるのは本体の確信度であり、所見の中身を読んで初めて決まる。決定論的な処理では
    ないため本スクリプトは扱わない。ここで重大度による絞り込みが復活すると、
    **確信の無い修正が「重大度が高いから」という理由で通る**。
    """

    def test_minor_is_fixable(self):
        finding = _finding("minor")
        self.assertEqual(gate_mod.gate_findings([finding])["auto_fix"], [finding])

    def test_unknown_severity_is_fixable(self):
        """severity は提示順の材料でしかない。判定できなくても位置があれば直せる。"""
        finding = _finding("bogus")
        self.assertEqual(gate_mod.gate_findings([finding])["auto_fix"], [finding])

    def test_severity_absent_is_fixable(self):
        finding = {"text": "dummy", "location": {"path": "a.py", "line": 1}}
        self.assertEqual(gate_mod.gate_findings([finding])["auto_fix"], [finding])


class ContractTest(unittest.TestCase):
    """介入軸を受け取らないこと自体が契約である。"""

    def test_function_takes_no_mode(self):
        """mode を渡せてしまうと、介入軸で結果が変わる余地が戻る。"""
        with self.assertRaises(TypeError):
            gate_mod.gate_findings([], "auto")

    def test_output_has_exactly_two_keys(self):
        self.assertEqual(set(gate_mod.gate_findings([])), {"auto_fix", "excluded"})


class MainTest(unittest.TestCase):
    """main(): --findings-json 引数処理・単一 JSON 出力。"""

    def test_cli_processes_args_and_outputs_single_json(self):
        findings_json = json.dumps(
            [_finding("critical"), _finding("minor", location={"unknown": True})]
        )
        result = subprocess.run(
            ["python3", str(_SCRIPT_PATH), "--findings-json", findings_json],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["auto_fix"], [_finding("critical")])
        self.assertEqual(
            payload["excluded"], [_finding("minor", location={"unknown": True})]
        )

    def test_cli_rejects_mode_argument(self):
        """`--mode` を復活させない（介入軸で振り分けを変える口を作らない）。"""
        result = subprocess.run(
            ["python3", str(_SCRIPT_PATH), "--findings-json", "[]", "--mode", "auto"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_cli_requires_findings(self):
        result = subprocess.run(
            ["python3", str(_SCRIPT_PATH)], capture_output=True, text=True
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
