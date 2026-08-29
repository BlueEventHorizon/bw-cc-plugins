#!/usr/bin/env python3
"""
parse_evaluation.py のテスト。

evaluator（forge:evaluator カスタム Agent）の応答は自由記述ではなく厳密な JSON
契約であるため、parse_findings.py（自由記述 markdown の解釈）とは別の検証観点を持つ:
件数の過不足・index の重複や範囲外・disposition の値域・severity の値域（disposition に
よらず必須）・confidence と fix_confident の整合（confirmed でなければ fix_confident は
真になれない）。

実行:
  python3 -m unittest tests.forge.review.test_parse_evaluation -v
"""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "review" / "scripts" / "parse_evaluation.py"
)

_spec = importlib.util.spec_from_file_location("forge_parse_evaluation", _SCRIPT_PATH)
parse_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(parse_mod)


def _valid_entry(index, confidence="confirmed", fix_confident=True, severity="major"):
    return {
        "index": index,
        "disposition": "valid",
        "severity": severity,
        "reason": "根拠",
        "confidence": confidence,
        "fix_confident": fix_confident,
    }


def _drop_entry(index, disposition="invalid", severity="minor"):
    return {"index": index, "disposition": disposition, "severity": severity, "reason": "根拠"}


class HappyPathTest(unittest.TestCase):
    def test_all_dispositions_accepted(self):
        raw = json.dumps(
            {
                "evaluations": [
                    _valid_entry(0),
                    _drop_entry(1, "invalid"),
                    _drop_entry(2, "misunderstanding"),
                    _drop_entry(3, "out_of_scope"),
                ]
            }
        )
        result = parse_mod.interpret_evaluation(raw, findings_count=4)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([e["index"] for e in result["evaluations"]], [0, 1, 2, 3])

    def test_out_of_order_indices_are_sorted(self):
        raw = json.dumps({"evaluations": [_drop_entry(1), _valid_entry(0)]})
        result = parse_mod.interpret_evaluation(raw, findings_count=2)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([e["index"] for e in result["evaluations"]], [0, 1])

    def test_fenced_json_is_unwrapped(self):
        body = json.dumps({"evaluations": [_drop_entry(0)]})
        raw = f"```json\n{body}\n```"
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "ok")

    def test_prose_before_fenced_json_is_ignored(self):
        """実測: 指示（前置き文を書かない）に反して説明文を書いてから ```json を出す応答がある。"""
        body = json.dumps({"evaluations": [_drop_entry(0)]})
        raw = f"## 検証結果\n\n所見0 は事実誤認でした。\n\n```json\n{body}\n```"
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "ok")

    def test_prose_before_unfenced_json_is_ignored(self):
        """実測: コードフェンスすら付けず、前置き文の直後に生の JSON を返す応答がある。"""
        body = json.dumps({"evaluations": [_drop_entry(0)]})
        raw = f"No catalog entry found. Finalizing.\n\n{body}"
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "ok")

    def test_last_fenced_block_is_used_when_multiple_present(self):
        """途中に例示コードブロックを挟んでいても、最後のブロックを結論として使う。"""
        example = json.dumps({"evaluations": []})
        body = json.dumps({"evaluations": [_drop_entry(0)]})
        raw = f"例えばこういう形式です:\n```json\n{example}\n```\n\n実際の結論:\n```json\n{body}\n```"
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "ok")

    def test_valid_without_extra_fields_is_not_required_for_drops(self):
        """drop 系 disposition は confidence/fix_confident を持たなくてよい。"""
        raw = json.dumps({"evaluations": [_drop_entry(0, "misunderstanding")]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "ok")


class ContractViolationTest(unittest.TestCase):
    """fail closed: 契約違反は status: error として返し、推測で埋めない。"""

    def test_not_json(self):
        result = parse_mod.interpret_evaluation("not json at all", findings_count=1)
        self.assertEqual(result["status"], "error")

    def test_prose_with_stray_braces_and_no_real_json_stays_error(self):
        """寛容な抽出は json.loads の成否までは保証しない。抽出範囲がゴミなら fail closed のまま。"""
        raw = "設定は `{key: value}` のような形にしてください（JSON ではない）。"
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "error")

    def test_missing_evaluations_key(self):
        result = parse_mod.interpret_evaluation(json.dumps({}), findings_count=1)
        self.assertEqual(result["status"], "error")

    def test_evaluations_not_a_list(self):
        result = parse_mod.interpret_evaluation(
            json.dumps({"evaluations": "nope"}), findings_count=1
        )
        self.assertEqual(result["status"], "error")

    def test_count_mismatch_too_few(self):
        raw = json.dumps({"evaluations": [_drop_entry(0)]})
        result = parse_mod.interpret_evaluation(raw, findings_count=2)
        self.assertEqual(result["status"], "error")

    def test_count_mismatch_too_many(self):
        raw = json.dumps({"evaluations": [_drop_entry(0), _drop_entry(1)]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "error")

    def test_duplicate_index(self):
        raw = json.dumps({"evaluations": [_drop_entry(0), _drop_entry(0)]})
        result = parse_mod.interpret_evaluation(raw, findings_count=2)
        self.assertEqual(result["status"], "error")

    def test_index_out_of_range(self):
        raw = json.dumps({"evaluations": [_drop_entry(5)]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "error")

    def test_index_must_be_int_not_bool(self):
        entry = _drop_entry(0)
        entry["index"] = True
        raw = json.dumps({"evaluations": [entry]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "error")

    def test_unknown_disposition(self):
        raw = json.dumps({"evaluations": [_drop_entry(0, "bogus")]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "error")

    def test_empty_reason(self):
        entry = _drop_entry(0)
        entry["reason"] = "   "
        raw = json.dumps({"evaluations": [entry]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "error")

    def test_missing_severity(self):
        entry = _drop_entry(0)
        del entry["severity"]
        raw = json.dumps({"evaluations": [entry]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "error")

    def test_unknown_severity(self):
        entry = _drop_entry(0, severity="urgent")
        raw = json.dumps({"evaluations": [entry]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "error")

    def test_severity_required_even_for_valid(self):
        entry = _valid_entry(0)
        del entry["severity"]
        raw = json.dumps({"evaluations": [entry]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "error")

    def test_valid_missing_confidence(self):
        entry = _valid_entry(0)
        del entry["confidence"]
        raw = json.dumps({"evaluations": [entry]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "error")

    def test_valid_bad_confidence_value(self):
        entry = _valid_entry(0, confidence="very_sure")
        raw = json.dumps({"evaluations": [entry]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "error")

    def test_valid_fix_confident_not_boolean(self):
        entry = _valid_entry(0)
        entry["fix_confident"] = "yes"
        raw = json.dumps({"evaluations": [entry]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "error")


class ConfidenceFixConsistencyTest(unittest.TestCase):
    """confidence が confirmed でなければ fix_confident は真になれない。"""

    def test_confirmed_with_fix_confident_true_is_ok(self):
        raw = json.dumps({"evaluations": [_valid_entry(0, "confirmed", True)]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "ok")

    def test_inferred_with_fix_confident_false_is_ok(self):
        raw = json.dumps({"evaluations": [_valid_entry(0, "inferred", False)]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "ok")

    def test_inferred_with_fix_confident_true_is_rejected(self):
        raw = json.dumps({"evaluations": [_valid_entry(0, "inferred", True)]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "error")

    def test_unverified_with_fix_confident_true_is_rejected(self):
        raw = json.dumps({"evaluations": [_valid_entry(0, "unverified", True)]})
        result = parse_mod.interpret_evaluation(raw, findings_count=1)
        self.assertEqual(result["status"], "error")


class MainTest(unittest.TestCase):
    """main(): --response-file / --findings-count 引数処理・単一 JSON 出力。"""

    def test_cli_reads_response_file(self):
        body = json.dumps({"evaluations": [_drop_entry(0)]})
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(body)
            response_path = handle.name
        try:
            result = subprocess.run(
                [
                    "python3", str(_SCRIPT_PATH),
                    "--findings-count", "1",
                    "--response-file", response_path,
                ],
                capture_output=True, text=True,
            )
        finally:
            Path(response_path).unlink()

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")

    def test_cli_requires_response_file(self):
        result = subprocess.run(
            ["python3", str(_SCRIPT_PATH), "--findings-count", "1"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
