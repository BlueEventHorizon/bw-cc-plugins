#!/usr/bin/env python3
"""agenda 機構の統合テスト（DES-080 §7「統合」）。

結合 script（`combine_findings_and_evaluations.py`。無変更で import する）の出力を
`agenda_wrapper.py start` の標準入力へつなぎ、構造判断 → 項目ごとの値（背景・本質・
決着の 3 値）→ 新規項目の追加 → `finish` までを通す。単体テストと異なりモックを
使わず、実際の git リポジトリ・ファイル書き込み・読み込みを通す（統合テストの目的が
「実際に繋がって動くこと」の確認であるため）。

固定すること:

1. 結合 script を変更せずにその出力が `start` へ渡り、保存された記録から現行と同じ欄
   （問題・重大度バッジ）を持つ提示が生成されること（DES-080 §2.1・§4.1・§4.3）
2. 各 `record` 直後の `agenda.html` が記録から生成したものと一致すること
   （agenda:REQ-021 FNC-003）
3. 未決着が残る途中の `finish` は削除せず、全決着後の `finish` で記録に属するもの
   （`agenda.json` / `agenda.html` / `agenda_state.js`）がすべて消えること（REQ-022 FNC-006）
4. `decision` が 2 値の項目は store の残件に数えられ render も未決着表示、3 値そろいで
   両者とも決着になること（DES-080 §2.6・§4.4）。記録側と提示側は別々に決着を判定して
   おり、両者の一致点はここだけである

ヘルパーは他のテストファイルから import せず本ファイル内で用意する
（テストファイル間の結合を避ける）。

実行:
  python3 -m unittest tests.forge.agenda.test_agenda_integration -v
"""

import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AGENDA_DIR = _REPO_ROOT / "plugins" / "forge" / "scripts" / "agenda"
_COMBINE_PATH = (
    _REPO_ROOT
    / "plugins"
    / "forge"
    / "skills"
    / "review"
    / "scripts"
    / "combine_findings_and_evaluations.py"
)


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


agenda_store = _load_module("agenda_store", _AGENDA_DIR / "agenda_store.py")
agenda_render = _load_module("agenda_render", _AGENDA_DIR / "agenda_render.py")
agenda_wrapper = _load_module("agenda_wrapper", _AGENDA_DIR / "agenda_wrapper.py")
# 結合 script は無変更のまま import する（DES-080 §2.1・§6）。
combine = _load_module("combine_findings_and_evaluations", _COMBINE_PATH)

# reviewer 応答（parse_findings.py が生成する実体）と evaluator 判定
# （parse_evaluation.py が検証済み）に相当する入力。所見本文は `text`、重大度は
# `severity` という名前で来る（forge:DES-066 §3.10a）。
_FINDINGS = [
    {"text": "所見1の本文", "file": "a.py", "line": 10},
    {"text": "所見2の本文", "file": "b.py", "line": 20},
]
_EVALUATIONS = [
    {"index": 0, "disposition": "fix", "severity": "major", "confidence": "high"},
    {"index": 1, "disposition": "fix", "severity": "critical", "confidence": "medium"},
]


class AgendaIntegrationTestCase(unittest.TestCase):
    """一時 git リポジトリの中から wrapper を呼ぶ（置き場は絶対パスで解決される）。"""

    def setUp(self):
        if shutil.which("git") is None:
            self.skipTest("git が無い環境のため置き場の解決を検証できない")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, capture_output=True)
        self._orig_cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, str(self._orig_cwd))
        self.agenda_dir = self.repo / ".claude" / ".temp" / "review"
        self.agenda_path = self.agenda_dir / "agenda.json"

    # -- wrapper 呼び出しヘルパー（本ファイル専用） --

    def _run(self, argv, stdin_text=""):
        args = agenda_wrapper.build_parser().parse_args(argv)
        return agenda_wrapper.run(args, io.StringIO(stdin_text))

    def _combined_stdin(self, findings=None, evaluations=None) -> str:
        """結合 script の標準出力に相当する JSON 文字列を作る（script は無変更）。"""
        result = combine.combine_findings_and_evaluations(
            findings if findings is not None else _FINDINGS,
            evaluations if evaluations is not None else _EVALUATIONS,
        )
        self.assertEqual(result["status"], "ok")
        return json.dumps(result, ensure_ascii=False)

    def _start(self, findings=None, evaluations=None):
        return self._run(
            ["--origin", "review", "start"], self._combined_stdin(findings, evaluations)
        )

    def _record_structural(self, note="同型の指摘は無い。個別の食い違いに留まる"):
        return self._run(["--origin", "review", "record", "--structural"], note)

    def _record_new(self, note="追加後もなお構造的な誤りは無い"):
        return self._run(["--origin", "review", "record", "--new"], note)

    def _record_value(self, item_id, field, body):
        return self._run(
            ["--origin", "review", "record", "--item-id", item_id, "--field", field], body
        )

    def _settle(self, item_id, *, outcome="adopt", reason="妥当と判断"):
        """背景・本質・決着の 3 値を 1 つずつ加え、各書き込み後に提示の一致を確認する。"""
        for field, body in (
            ("background", f"背景 {item_id}"),
            ("essence", f"本質 {item_id}"),
            ("decision.by", "human"),
            ("decision.outcome", outcome),
            ("decision.reason", reason),
        ):
            self.assertEqual(self._record_value(item_id, field, body)["status"], "ok")
            self._assert_render_matches_record()

    def _load_record(self):
        return agenda_store.load_agenda(self.agenda_path)

    def _html(self):
        return (self.agenda_dir / "agenda.html").read_text(encoding="utf-8")

    def _pending_ids(self):
        return self._run(["--origin", "review", "pending"])["pending_item_ids"]

    # -- 提示（agenda.html）と記録（agenda.json）の一致 --

    def _assert_render_matches_record(self):
        """書き出された `agenda.html` が、読み直した `agenda.json` だけから独立に
        再生成した内容と一致することを確認する（agenda:REQ-021 FNC-003）。
        `agenda_state.js`（自動追従用の世代番号。DES-077 §4.2）も合わせて確認する。"""
        record = self._load_record()
        state_js = (self.agenda_dir / "agenda_state.js").read_text(encoding="utf-8")
        self.assertEqual(
            state_js, agenda_render.render_agenda_state_js(record.get("content_version"))
        )

        on_disk = self._html()
        match = re.search(r"agenda_render\.py によって (.+?) に生成された", on_disk)
        self.assertIsNotNone(match, "生成物注記から generated_at を抽出できない")
        self.assertEqual(
            on_disk, agenda_render.render_agenda_html(record, generated_at=match.group(1))
        )
        return record


class CombinedOutputToPresentationTest(AgendaIntegrationTestCase):
    """結合 script の出力が start へ渡り、現行と同じ欄を持つ提示になること。"""

    def test_combined_output_is_saved_and_presented_with_current_fields(self):
        self.assertEqual(self._start()["status"], "ok")
        record = self._assert_render_matches_record()

        # 作り替えずに渡された値がそのまま保存されている（REQ-022 FNC-002）
        self.assertEqual([item["id"] for item in record["items"]], ["01", "02"])
        self.assertEqual(record["items"][0]["text"], "所見1の本文")
        self.assertEqual(record["items"][0]["severity"], "major")
        self.assertEqual(record["items"][0]["file"], "a.py")

        # 現行と同じ欄が出ている: 問題（wrapper が text を problem にも置く。§4.3）と
        # 重大度バッジ（項目直下の severity を config.severity_field で引く。§4.1）
        html = self._html()
        self.assertIn("<dt>問題</dt><dd>所見1の本文</dd>", html)
        self.assertIn("<dt>問題</dt><dd>所見2の本文</dd>", html)
        self.assertIn('<span class="severity-badge" data-severity="major">major</span>', html)
        self.assertIn(
            '<span class="severity-badge" data-severity="critical">critical</span>', html
        )


class FullSequenceTest(AgendaIntegrationTestCase):
    """start → 構造判断 → 項目ごとの値 → 新規項目 → finish の一連の流れ。"""

    def test_sequence_from_combined_output_to_finish(self):
        self._start()
        self.assertEqual(self._record_structural()["status"], "ok")
        self._assert_render_matches_record()

        self._settle("01")

        # 未決着（項目02・新規項目）が残る途中の finish は削除しない
        self.assertEqual(self._pending_ids(), ["02"])
        premature = self._run(["--origin", "review", "finish"])
        self.assertFalse(premature["deleted"])
        self.assertEqual(premature["remaining_count"], 1)
        self.assertTrue(self.agenda_path.is_file())

        self._settle("02", reason="重大なため対応する")

        # 新規項目は応答の id で以後の値を加える（DES-080 §2.6・§3）
        new_result = self._record_new()
        self.assertEqual(new_result["status"], "ok")
        new_id = new_result["id"]
        self.assertEqual(new_id, "03")
        self._assert_render_matches_record()

        mid_finish = self._run(["--origin", "review", "finish"])
        self.assertFalse(mid_finish["deleted"])
        self.assertEqual(mid_finish["pending_item_ids"], [new_id])

        self._settle(new_id, outcome="drop", reason="議論の結果として見送る")
        self.assertEqual(self._pending_ids(), [])

        # 全決着後の finish で、記録に属するものがすべて消える（REQ-022 FNC-006）
        finish = self._run(["--origin", "review", "finish"])
        self.assertTrue(finish["deleted"])
        self.assertFalse(self.agenda_path.exists())
        self.assertFalse((self.agenda_dir / "agenda.html").exists())
        self.assertFalse((self.agenda_dir / "agenda_state.js").exists())


class SettlementBoundaryTest(AgendaIntegrationTestCase):
    """決着判定の境界で store の残件と render の表示が一致すること（DES-080 §4.4）。

    記録側（`agenda_schema.is_settled`）と表示側（`agenda_render._is_settled`）は
    別々に判定しており、両者の一致を固定する点はここだけである。
    """

    def setUp(self):
        super().setUp()
        self._start()
        self._record_structural()
        for field, body in (("background", "背景"), ("essence", "本質")):
            self._record_value("01", field, body)

    def test_two_of_three_decision_values_are_unsettled_in_store_and_render(self):
        self._record_value("01", "decision.by", "human")
        self._record_value("01", "decision.outcome", "adopt")
        self._assert_render_matches_record()

        # 記録側: 残件に数えられ、finish は削除しない
        self.assertIn("01", self._pending_ids())
        self.assertFalse(self._run(["--origin", "review", "finish"])["deleted"])

        # 提示側: 決着として出さない（進行中・決着欄は未定）
        html = self._html()
        self.assertIn('<span class="status-pill" data-status="進行中">進行中</span>', html)
        self.assertIn('<span class="undecided">(未定)</span>', html)

    def test_three_decision_values_are_settled_in_store_and_render(self):
        for field, body in (
            ("decision.by", "human"),
            ("decision.outcome", "adopt"),
            ("decision.reason", "妥当と判断"),
        ):
            self._record_value("01", field, body)
        self._assert_render_matches_record()

        # 記録側: 残件から外れる
        self.assertNotIn("01", self._pending_ids())

        # 提示側: 決着として出す
        html = self._html()
        self.assertIn('<span class="status-pill" data-status="adopt">adopt</span>', html)
        self.assertIn("<dd>adopt（妥当と判断）</dd>", html)


if __name__ == "__main__":
    unittest.main()
