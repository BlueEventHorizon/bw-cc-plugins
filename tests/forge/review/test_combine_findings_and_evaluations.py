#!/usr/bin/env python3
"""
combine_findings_and_evaluations.py のテスト（forge:DES-066 §3.10a / §6 テスト設計）。

reviewer の所見配列と evaluator の判定配列を index で機械的に結合する。件数不一致・
index の欠落・index の重複のいずれかがあれば結合を拒否すること、両配列の長さが一致し
index が過不足なく揃っている場合のみ 1 件ずつ結合することを検証する。

実行:
  python3 -m unittest tests.forge.review.test_combine_findings_and_evaluations -v
"""

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "review" / "scripts"
    / "combine_findings_and_evaluations.py"
)

_spec = importlib.util.spec_from_file_location(
    "forge_combine_findings_and_evaluations", _SCRIPT_PATH
)
combine_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(combine_mod)


def _finding(severity="major", text="dummy", location=None):
    return {
        "severity": severity,
        "text": text,
        "location": location if location is not None else {"path": "a.py", "line": 1},
    }


def _evaluation(index, disposition="valid", severity="major", confidence="confirmed",
                 fix_confident=True):
    return {
        "index": index,
        "disposition": disposition,
        "severity": severity,
        "reason": "根拠",
        "confidence": confidence,
        "fix_confident": fix_confident,
    }


class HappyPathTest(unittest.TestCase):
    """長さ一致・index 過不足なしの場合のみ index 昇順で 1 件ずつ結合する。"""

    def test_combines_by_index_in_ascending_order(self):
        findings = [_finding("critical", "f0"), _finding("minor", "f1")]
        # evaluations を逆順（index=1 が先）で渡しても index で対応させること。
        evaluations = [_evaluation(1, severity="minor"), _evaluation(0, severity="critical")]
        result = combine_mod.combine_findings_and_evaluations(findings, evaluations)
        self.assertEqual(result["status"], "ok")
        combined = result["combined"]
        self.assertEqual(len(combined), 2)
        self.assertEqual(combined[0]["text"], "f0")
        self.assertEqual(combined[0]["index"], 0)
        self.assertEqual(combined[0]["disposition"], "valid")
        self.assertEqual(combined[1]["text"], "f1")
        self.assertEqual(combined[1]["index"], 1)

    def test_empty_inputs_combine_to_empty(self):
        result = combine_mod.combine_findings_and_evaluations([], [])
        self.assertEqual(result, {"status": "ok", "combined": []})

    def test_evaluation_wins_on_key_collision(self):
        """キーが衝突した場合は evaluation 側の値を優先する。"""
        finding = _finding("major")
        finding["severity"] = "major"
        evaluation = _evaluation(0, severity="critical")
        result = combine_mod.combine_findings_and_evaluations([finding], [evaluation])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["combined"][0]["severity"], "critical")


class RejectionTest(unittest.TestCase):
    """いずれか不成立なら結合せずエラーを返す。"""

    def test_length_mismatch_is_rejected(self):
        findings = [_finding(), _finding()]
        evaluations = [_evaluation(0)]
        result = combine_mod.combine_findings_and_evaluations(findings, evaluations)
        self.assertEqual(result["status"], "error")
        self.assertNotIn("combined", result)

    def test_missing_index_is_rejected(self):
        """index 集合に欠落がある場合（{0,1,2} のうち 1 が無い）。"""
        findings = [_finding(), _finding(), _finding()]
        evaluations = [_evaluation(0), _evaluation(2), _evaluation(3)]
        result = combine_mod.combine_findings_and_evaluations(findings, evaluations)
        self.assertEqual(result["status"], "error")

    def test_duplicate_index_is_rejected(self):
        """index が重複している場合（{0,1} の代わりに {0,0}）。"""
        findings = [_finding(), _finding()]
        evaluations = [_evaluation(0), _evaluation(0)]
        result = combine_mod.combine_findings_and_evaluations(findings, evaluations)
        self.assertEqual(result["status"], "error")

    def test_out_of_range_index_is_rejected(self):
        findings = [_finding()]
        evaluations = [_evaluation(1)]
        result = combine_mod.combine_findings_and_evaluations(findings, evaluations)
        self.assertEqual(result["status"], "error")


class MainTest(unittest.TestCase):
    """main(): --findings-json / --evaluations-json 引数処理・単一 JSON 出力。"""

    def test_cli_processes_args_and_outputs_single_json(self):
        findings_json = json.dumps([_finding("critical", "f0")])
        evaluations_json = json.dumps([_evaluation(0, severity="critical")])
        result = subprocess.run(
            [
                "python3", str(_SCRIPT_PATH),
                "--findings-json", findings_json,
                "--evaluations-json", evaluations_json,
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["combined"][0]["text"], "f0")

    def test_cli_reports_error_status_without_raising(self):
        result = subprocess.run(
            [
                "python3", str(_SCRIPT_PATH),
                "--findings-json", json.dumps([_finding(), _finding()]),
                "--evaluations-json", json.dumps([_evaluation(0)]),
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")

    def test_cli_requires_both_arguments(self):
        result = subprocess.run(
            ["python3", str(_SCRIPT_PATH), "--findings-json", "[]"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
