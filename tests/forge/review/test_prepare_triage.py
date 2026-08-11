#!/usr/bin/env python3
"""prepare_triage.py のテスト（段階的提示の仕分けファイルの用意）。

列挙と転記の取り違えを固定する。とくに次は手で書くと静かに壊れる。

- 提示順（重大度順）と、その順で振られる識別子の対応
- 位置未確定・位置欠落の表示
- 表を壊す文字（改行・パイプ）の畳み込み
- 振り分け（interactive 固定）と置き場の確定を SKILL 側へ戻していないこと

実行:
  python3 -m unittest tests.forge.review.test_prepare_triage -v
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "review" / "scripts" / "prepare_triage.py"
)

_spec = importlib.util.spec_from_file_location("forge_prepare_triage", _SCRIPT_PATH)
render_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_mod)


def _finding(severity, text="dummy", location=None):
    return {
        "severity": severity,
        "text": text,
        "location": location if location is not None else {"path": "a.py", "line": 1},
    }


class OrderingTest(unittest.TestCase):
    def test_findings_are_presented_in_severity_order(self):
        findings = [_finding("minor", "m"), _finding("critical", "c"), _finding("major", "j")]
        out = render_mod.render("rid", findings, [])
        self.assertLess(out.index("[01]"), out.index("[02]"))
        self.assertIn("[01] 🔴 critical", out)
        self.assertIn("[02] 🟡 major", out)
        self.assertIn("[03] 🟢 minor", out)

    def test_unknown_severity_goes_last(self):
        findings = [_finding("bogus", "b"), _finding("critical", "c")]
        out = render_mod.render("rid", findings, [])
        self.assertIn("[01] 🔴 critical", out)
        self.assertIn("[02] bogus", out)

    def test_ids_are_zero_padded_two_digits(self):
        findings = [_finding("major") for _ in range(3)]
        out = render_mod.render("rid", findings, [])
        for expected in ("[01]", "[02]", "[03]"):
            self.assertIn(expected, out)


class LocationTest(unittest.TestCase):
    def test_path_and_line(self):
        out = render_mod.render("rid", [_finding("major", location={"path": "x/y.md", "line": 42})], [])
        self.assertIn("x/y.md:42", out)

    def test_path_without_line(self):
        out = render_mod.render("rid", [_finding("major", location={"path": "x/y.md"})], [])
        self.assertIn("x/y.md", out)
        self.assertNotIn("x/y.md:None", out)

    def test_unknown_location_is_labeled(self):
        out = render_mod.render("rid", [_finding("major", location={"unknown": True})], [])
        self.assertIn("位置未確定", out)

    def test_missing_location_key_is_labeled(self):
        out = render_mod.render("rid", [{"severity": "major", "text": "t"}], [])
        self.assertIn("位置未確定", out)


class TableSafetyTest(unittest.TestCase):
    def test_newlines_are_collapsed_in_excluded_table(self):
        excluded = [_finding("minor", "1 行目\n2 行目", location={"unknown": True})]
        out = render_mod.render("rid", [], excluded)
        self.assertIn("1 行目 2 行目", out)

    def test_pipe_is_escaped_in_excluded_table(self):
        excluded = [_finding("minor", "a | b", location={"unknown": True})]
        out = render_mod.render("rid", [], excluded)
        self.assertIn("a \\| b", out)

    def test_finding_body_keeps_newlines_in_section(self):
        """節の本文は表ではないため、所見の改行を畳まない。"""
        out = render_mod.render("rid", [_finding("major", "1 行目\n2 行目")], [])
        self.assertIn("1 行目\n2 行目", out)

    def test_newlines_are_collapsed_in_agenda(self):
        out = render_mod.render("rid", [_finding("major", "1 行目\n2 行目")], [])
        self.assertIn("| 未着手 | 1 行目 2 行目 |", out)

    def test_pipe_is_escaped_in_agenda(self):
        out = render_mod.render("rid", [_finding("major", "a | b")], [])
        self.assertIn("| 未着手 | a \\| b |", out)


class AgendaTest(unittest.TestCase):
    """アジェンダ表は残件の一覧として機能しなければならない。"""

    def test_unsettled_rows_carry_the_finding_summary(self):
        """未決着の行を空にしない。ID と位置だけでは何の指摘か分からない。"""
        out = render_mod.render("rid", [_finding("major", "命名が規約と食い違う")], [])
        agenda = out.split("## [")[0]
        self.assertIn("命名が規約と食い違う", agenda)

    def test_agenda_column_is_result_or_issue(self):
        out = render_mod.render("rid", [], [])
        self.assertIn("| ID | 重大度 | 位置 | 状態 | 結果・課題 |", out)

    def test_long_summary_is_truncated(self):
        """所見本文をそのまま入れると表が読めなくなる。上限で切り詰める。"""
        long_text = "あ" * 300
        out = render_mod.render("rid", [_finding("major", long_text)], [])
        agenda = out.split("## [")[0]
        self.assertIn("あ" * render_mod.SUMMARY_CELL_LIMIT + "…", agenda)
        self.assertNotIn("あ" * (render_mod.SUMMARY_CELL_LIMIT + 1), agenda)

    def test_short_summary_is_not_truncated(self):
        out = render_mod.render("rid", [_finding("major", "短い所見")], [])
        self.assertNotIn("…", out.split("## [")[0])

    def test_full_text_remains_in_the_section(self):
        """切り詰めるのは表のセルだけ。全文は節に残る。"""
        long_text = "あ" * 300
        out = render_mod.render("rid", [_finding("major", long_text)], [])
        self.assertIn(long_text, out)


class SingleFileTest(unittest.TestCase):
    """ファイルは常に 1 つ。複数にすると「どれを開くのか」を解く仕組みが要る。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_filename_is_fixed_and_carries_no_identifier(self):
        result = render_mod.prepare("rid", [], 3, project_root=self.root)
        self.assertEqual(result["triage_path"], ".claude/.temp/review/triage.md")

    def test_rounds_share_one_file_and_the_latest_wins(self):
        """進行中のラウンドの作業ファイルであり、決着の保管庫ではない。"""
        render_mod.prepare("rid", [_finding("critical", "round1")], 1, project_root=self.root)
        render_mod.prepare("rid", [_finding("critical", "round2")], 2, project_root=self.root)
        entries = sorted((self.root / ".claude/.temp/review").iterdir())
        self.assertEqual([p.name for p in entries], ["triage.md"])
        written = entries[0].read_text(encoding="utf-8")
        self.assertIn("round2", written)
        self.assertNotIn("round1", written)

    def test_different_review_ids_share_one_file(self):
        render_mod.prepare("aaa", [], 1, project_root=self.root)
        render_mod.prepare("bbb", [], 1, project_root=self.root)
        entries = list((self.root / ".claude/.temp/review").iterdir())
        self.assertEqual([p.name for p in entries], ["triage.md"])

    def test_round_number_is_recorded_in_the_file(self):
        out = render_mod.render("rid", [], [], "agent-review", 4)
        self.assertIn("| ラウンド | 4 |", out)
        self.assertIn("(round 4)", out)


class StructureTest(unittest.TestCase):
    def test_empty_needs_decision_still_renders_agenda(self):
        out = render_mod.render("rid", [], [])
        self.assertIn("## アジェンダ", out)
        self.assertIn("判断が要る所見はありません", out)

    def test_excluded_section_is_omitted_when_empty(self):
        out = render_mod.render("rid", [_finding("major")], [])
        self.assertNotIn("## 対象外の所見", out)

    def test_excluded_section_states_human_confirmation_is_needed(self):
        out = render_mod.render("rid", [], [_finding("critical", location={"unknown": True})])
        self.assertIn("## 対象外の所見", out)
        self.assertIn("人間が直接内容を確認する必要がある", out)

    def test_counts_are_reported(self):
        out = render_mod.render(
            "rid",
            [_finding("major"), _finding("minor")],
            [_finding("critical", location={"unknown": True})],
        )
        self.assertIn("| 判断が要る所見 | 2 件 |", out)
        self.assertIn("| 対象外の所見 | 1 件 |", out)

    def test_backend_is_recorded(self):
        out = render_mod.render("rid", [], [], backend="agent-review")
        self.assertIn("agent-review", out)

    def test_backend_absent_is_marked(self):
        out = render_mod.render("rid", [], [])
        self.assertIn("（未記録）", out)


class PrepareTest(unittest.TestCase):
    """prepare(): 振り分け・組み立て・書き出しの連鎖。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_writes_file_under_fixed_location(self):
        """置き場もファイル名も引数にしない。SKILL がパスを組み立てる余地を残さないため。"""
        result = render_mod.prepare("rid", [_finding("major")], 1, project_root=self.root)
        self.assertEqual(result["triage_path"], ".claude/.temp/review/triage.md")
        self.assertTrue((self.root / ".claude/.temp/review/triage.md").exists())

    def test_creates_missing_directories(self):
        render_mod.prepare("rid", [], 1, project_root=self.root)
        self.assertTrue((self.root / ".claude/.temp/review").is_dir())

    def test_gating_is_interactive_and_not_delegated_to_caller(self):
        """位置が確定した所見は採否判断へ、未確定は対象外へ。呼び出し側は仕分けない。"""
        findings = [
            _finding("critical"),
            _finding("minor", location={"unknown": True}),
        ]
        result = render_mod.prepare("rid", findings, 1, project_root=self.root)
        self.assertEqual(result["needs_decision_count"], 1)
        self.assertEqual(result["excluded_count"], 1)

    def test_written_content_matches_render(self):
        findings = [_finding("critical", "c")]
        render_mod.prepare("rid", findings, 1, "agent-review", project_root=self.root)
        written = (self.root / ".claude/.temp/review/triage.md").read_text(encoding="utf-8")
        self.assertEqual(written, render_mod.render("rid", findings, [], "agent-review", 1))

    def test_absolute_path_is_returned(self):
        """利用者へ示すのは絶対パス。相対パスは cwd が違うと開けない。"""
        result = render_mod.prepare("rid", [], 1, project_root=self.root)
        self.assertTrue(Path(result["absolute_path"]).is_absolute())
        self.assertTrue(Path(result["absolute_path"]).exists())


class CliTest(unittest.TestCase):
    def _run(self, args, cwd):
        return subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), *args],
            capture_output=True, text=True, cwd=str(cwd),
        )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_cli_writes_file_and_reports_path_and_counts(self):
        findings = json.dumps([
            {"severity": "critical", "text": "t", "location": {"path": "a.py", "line": 3}},
            {"severity": "minor", "text": "u", "location": {"unknown": True}},
        ])
        proc = self._run(
            ["--review-id", "abc123", "--round", "1", "--findings-json", findings,
             "--backend", "agent-review"],
            cwd=self.root,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["triage_path"], ".claude/.temp/review/triage.md")
        self.assertEqual(payload["needs_decision_count"], 1)
        self.assertEqual(payload["excluded_count"], 1)
        written = (self.root / payload["triage_path"]).read_text(encoding="utf-8")
        self.assertIn("# レビュー所見の仕分け: abc123", written)
        self.assertIn("a.py:3", written)

    def test_cli_writes_under_project_root_regardless_of_cwd(self):
        """cwd がルート以外でも、指定したルートの直下へ書く。"""
        other = self.root / "sub"
        other.mkdir()
        proc = self._run(
            ["--review-id", "rid", "--round", "1", "--findings-json", "[]",
             "--project-root", str(self.root)],
            cwd=other,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.root / ".claude/.temp/review/triage.md").exists())
        self.assertFalse((other / ".claude").exists())

    def test_cli_rejects_empty_review_id(self):
        proc = self._run(
            ["--review-id", "  ", "--round", "1", "--findings-json", "[]"], cwd=self.root
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_cli_ignores_path_separators_in_review_id(self):
        """review_id はファイル名にならないため、置き場の外へは出ない。"""
        proc = self._run(
            ["--review-id", "../escape", "--round", "1", "--findings-json", "[]"],
            cwd=self.root,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.root / ".claude/.temp/review/triage.md").exists())

    def test_cli_requires_round(self):
        proc = self._run(["--review-id", "rid", "--findings-json", "[]"], cwd=self.root)
        self.assertNotEqual(proc.returncode, 0)

    def test_cli_rejects_non_positive_round(self):
        for bad in ("0", "-1"):
            with self.subTest(round=bad):
                proc = self._run(
                    ["--review-id", "rid", "--round", bad, "--findings-json", "[]"],
                    cwd=self.root,
                )
                self.assertNotEqual(proc.returncode, 0)

    def test_cli_has_no_request_context_args(self):
        """依頼の文脈は記録しない（再開時は今回の起動引数を使う）。"""
        proc = self._run(
            ["--review-id", "rid", "--round", "1", "--findings-json", "[]",
             "--pattern", "branch"],
            cwd=self.root,
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_cli_has_no_listing_mode(self):
        """置き場のファイルは 1 つなので、探す仕組みを持たない。"""
        proc = self._run(["--list"], cwd=self.root)
        self.assertNotEqual(proc.returncode, 0)

    def test_cli_does_not_accept_pre_gated_arrays(self):
        """仕分け済み配列を受け取る口を復活させない（AI に切り出しをさせない）。"""
        proc = self._run(
            ["--review-id", "rid", "--round", "1", "--needs-decision-json", "[]"],
            cwd=self.root,
        )
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
