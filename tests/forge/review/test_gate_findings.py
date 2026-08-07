#!/usr/bin/env python3
"""
gate_findings.py のテスト（DES-046 §3.2 / §5 テスト設計）

2 mode（auto-critical/auto）× 3 severity（critical/major/minor）の全6パターン、
および不明 severity の安全側フォールバックを検証する。

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


class GateFindingsTest(unittest.TestCase):
    """gate_findings(): 決定表どおりの振り分け（DES-046 §3.2、2 mode × 3 severity）。"""

    def test_auto_critical_fixes_only_critical(self):
        findings = [_finding("critical"), _finding("major"), _finding("minor")]
        result = gate_mod.gate_findings(findings, "auto-critical")
        self.assertEqual(result["auto_fix"], [_finding("critical")])
        self.assertEqual(result["excluded"], [_finding("major"), _finding("minor")])

    def test_auto_fixes_critical_and_major(self):
        findings = [_finding("critical"), _finding("major"), _finding("minor")]
        result = gate_mod.gate_findings(findings, "auto")
        self.assertEqual(result["auto_fix"], [_finding("critical"), _finding("major")])
        self.assertEqual(result["excluded"], [_finding("minor")])

    def test_auto_critical_excludes_major(self):
        result = gate_mod.gate_findings([_finding("major")], "auto-critical")
        self.assertEqual(result["auto_fix"], [])
        self.assertEqual(result["excluded"], [_finding("major")])

    def test_auto_critical_excludes_minor(self):
        result = gate_mod.gate_findings([_finding("minor")], "auto-critical")
        self.assertEqual(result["auto_fix"], [])
        self.assertEqual(result["excluded"], [_finding("minor")])

    def test_auto_fixes_critical(self):
        result = gate_mod.gate_findings([_finding("critical")], "auto")
        self.assertEqual(result["auto_fix"], [_finding("critical")])
        self.assertEqual(result["excluded"], [])

    def test_auto_excludes_minor(self):
        result = gate_mod.gate_findings([_finding("minor")], "auto")
        self.assertEqual(result["auto_fix"], [])
        self.assertEqual(result["excluded"], [_finding("minor")])

    def test_unknown_severity_is_excluded_in_both_modes(self):
        """不明な severity（重大度不明）は安全側に倒して excluded とする。"""
        finding = _finding("unknown")
        self.assertEqual(gate_mod.gate_findings([finding], "auto-critical")["auto_fix"], [])
        self.assertEqual(gate_mod.gate_findings([finding], "auto")["auto_fix"], [])

    def test_unknown_location_is_excluded_regardless_of_severity(self):
        """位置が確定していない所見は自動修正しない（DES-046 §3.2）。

        修正対象が確定していない所見を auto_fix に入れると、どこを直すかを推測で
        決めることになり、修正後の allowlist 検証も意図の判定に使えない。
        """
        for severity in ("critical", "major"):
            for mode in ("auto-critical", "auto"):
                with self.subTest(severity=severity, mode=mode):
                    finding = _finding(severity, location={"unknown": True})
                    result = gate_mod.gate_findings([finding], mode)
                    self.assertEqual(result["auto_fix"], [])
                    self.assertEqual(result["excluded"], [finding])

    def test_finding_without_location_key_is_excluded(self):
        """`location` を欠く不正な入力も安全側に倒して excluded とする。"""
        finding = {"severity": "critical", "text": "dummy"}
        self.assertEqual(gate_mod.gate_findings([finding], "auto")["auto_fix"], [])

    def test_empty_findings_list(self):
        result = gate_mod.gate_findings([], "auto")
        self.assertEqual(result, {"auto_fix": [], "excluded": []})


class MainTest(unittest.TestCase):
    """main(): --findings-json / --mode 引数処理・単一 JSON 出力（DES-046 §3.2）。"""

    def test_cli_processes_args_and_outputs_single_json(self):
        findings_json = json.dumps([_finding("critical"), _finding("minor")])
        result = subprocess.run(
            ["python3", str(_SCRIPT_PATH), "--findings-json", findings_json, "--mode", "auto-critical"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["auto_fix"], [_finding("critical")])
        self.assertEqual(payload["excluded"], [_finding("minor")])

    def test_cli_rejects_invalid_mode(self):
        result = subprocess.run(
            ["python3", str(_SCRIPT_PATH), "--findings-json", "[]", "--mode", "bogus"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
