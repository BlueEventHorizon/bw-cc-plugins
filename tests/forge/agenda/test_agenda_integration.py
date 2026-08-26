#!/usr/bin/env python3
"""agenda 機構の統合テスト（DES-075 §9 の統合テスト対象、TASK-009 acceptance_criteria）。

start → record × N（背景・本質→決着への遷移を含む） → next/pending → finish の
一連の CLI 呼び出しが DES-075 §6.2 のシーケンスどおりに動作すること、各書き込み
操作直後に表示（agenda.html）が再生成され最新の agenda.json と一致することを検証する。

単体テスト（test_agenda_store.py）とは異なり、モックを使わず実際のファイル
書き込み・読み込みを通して検証する（統合テストの目的が「実際に繋がって
動くこと」の確認であるため）。ヘルパーは test_agenda_store.py のものを
import せず、本ファイル内で新規に用意する（テストファイル間の結合を避ける）。

実行:
  python3 -m unittest tests.forge.agenda.test_agenda_integration -v
"""

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

_AGENDA_DIR = (
    Path(__file__).resolve().parents[3] / "plugins" / "forge" / "scripts" / "agenda"
)


def _load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, _AGENDA_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


agenda_store = _load_module("agenda_store", "agenda_store.py")
agenda_render = _load_module("agenda_render", "agenda_render.py")


class AgendaIntegrationTest(unittest.TestCase):
    """start → record×N → next/pending → finish の一連の統合検証（DES-075 §6.2）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.agenda_dir = Path(self._tmp.name) / "20260825-agenda-integration"
        self.agenda_dir.mkdir()
        self.agenda_path = str(self.agenda_dir / "agenda.json")
        self._candidate_counter = 0

    # -- CLI 呼び出しヘルパー（本ファイル専用。他テストファイルと共有しない） --

    def _run(self, args_list):
        parser = agenda_store.build_parser()
        args = parser.parse_args(args_list)
        return agenda_store._HANDLERS[args.command](args)

    def _write_candidate(self, candidate: dict) -> str:
        self._candidate_counter += 1
        path = Path(self._tmp.name) / f"candidate-{self._candidate_counter}.json"
        path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def _start(self, candidate: dict):
        return self._run(
            ["start", "--path", self.agenda_path, "--input-file", self._write_candidate(candidate)]
        )

    def _record(self, item_id: str, patch: dict):
        return self._run(
            [
                "record",
                "--path", self.agenda_path,
                "--item-id", item_id,
                "--input-file", self._write_candidate(patch),
            ]
        )

    def _record_record(self):
        return agenda_store.load_agenda(self.agenda_path)

    # -- 表示（agenda.html）が最新の agenda.json と一致することの検証 --

    def _assert_render_matches_agenda(self):
        """実際に書き出された agenda.html が、実際に load_agenda() で読み込んだ
        最新の agenda.json のみから独立に再生成した内容と一致することを検証する
        （FNC-003: 提示と記録の一致）。agenda_state.js は新設計に存在しないため
        生成されないことも合わせて確認する。"""
        record = self._record_record()
        self.assertFalse((self.agenda_dir / "agenda_state.js").exists())

        html_path = self.agenda_dir / "agenda.html"
        self.assertTrue(html_path.exists())
        on_disk = html_path.read_text(encoding="utf-8")

        match = re.search(r"agenda_render\.py によって (.+?) に生成された", on_disk)
        self.assertIsNotNone(match, "生成物注記から generated_at を抽出できない")
        fresh = agenda_render.render_agenda_html(record, generated_at=match.group(1))
        self.assertEqual(on_disk, fresh)
        return record

    def test_start_to_record_to_decision_to_next_pending_to_finish(self):
        # --- start（consult Phase 2 相当。DES-075 §6・§6.2） ---
        start_result = self._start(
            {
                "structural_judgment": {"note": "同型の指摘は無い。個別の食い違いに留まる"},
                "config": {"item_fields": ["severity"], "severity_field": "severity"},
                "items": [
                    {"id": "01", "title": "項目1", "fields": {"severity": "major"}},
                    {
                        "id": "02",
                        "title": "項目2（外部指摘由来）",
                        "fields": {"severity": "critical"},
                        "verification": {"referenced": "", "action": "adopt", "reason": ""},
                    },
                ],
            }
        )
        self.assertEqual(start_result["status"], "ok")
        record = self._assert_render_matches_agenda()
        self.assertEqual(record["content_version"], 1)
        self.assertTrue(record["structural_judgment"]["recorded"])
        self.assertEqual(record["config"]["identity"], "20260825-agenda-integration")

        # --- record①（背景・本質。項目01） ---
        r1 = self._record("01", {"background": "背景1", "essence": "本質1"})
        self.assertEqual(r1["status"], "ok")
        record = self._assert_render_matches_agenda()
        self.assertEqual(record["content_version"], 2)
        item01 = next(i for i in record["items"] if i["id"] == "01")
        self.assertEqual(item01["last_changed_fields"], sorted(["background", "essence"]))

        # --- record②（決着。項目01。verification を持たないため background/essence のみで足りる） ---
        r2 = self._record(
            "01", {"decision": {"by": "human", "outcome": "adopt", "reason": "妥当と判断"}}
        )
        self.assertEqual(r2["status"], "ok")
        record = self._assert_render_matches_agenda()
        self.assertEqual(record["content_version"], 3)
        item01 = next(i for i in record["items"] if i["id"] == "01")
        self.assertEqual(item01["decision"]["outcome"], "adopt")

        # --- record①（背景・本質。項目02） ---
        r3 = self._record("02", {"background": "背景2", "essence": "本質2"})
        self.assertEqual(r3["status"], "ok")
        record = self._assert_render_matches_agenda()
        self.assertEqual(record["content_version"], 4)

        # --- next/pending（FNC-006）: 項目02のみ未対応 ---
        next_result = self._run(["next", "--path", self.agenda_path])
        self.assertEqual(next_result["status"], "ok")
        self.assertEqual(next_result["item_id"], "02")

        pending_result = self._run(["pending", "--path", self.agenda_path])
        self.assertEqual(pending_result["pending_item_ids"], ["02"])
        self.assertEqual(pending_result["remaining_count"], 1)

        # --- finish は残件があるため削除しない ---
        premature_finish = self._run(["finish", "--path", self.agenda_path])
        self.assertEqual(premature_finish["status"], "ok")
        self.assertFalse(premature_finish["deleted"])
        self.assertEqual(premature_finish["remaining_count"], 1)
        self.assertTrue(Path(self.agenda_path).exists())

        # --- record②（決着。項目02）を referenced 無しで試みると拒否される
        #     （FNC-011: 採用する場合も検証を要求する） ---
        rejected = self._record(
            "02", {"decision": {"by": "human", "outcome": "adopt", "reason": "妥当"}}
        )
        self.assertEqual(rejected["status"], "error")
        self.assertIn("verification.referenced", rejected["missing_fields"])
        record = self._record_record()
        self.assertEqual(record["content_version"], 4)  # 拒否は content_version を増やさない
        item02 = next(i for i in record["items"] if i["id"] == "02")
        self.assertIsNone(item02["decision"])  # 拒否された変更は永続化されない

        # --- verification.referenced を追記して再実行すると成功する ---
        self._record("02", {"verification": {"referenced": "path/to/file.py:10", "action": "adopt"}})
        r4 = self._record(
            "02", {"decision": {"by": "human", "outcome": "adopt", "reason": "妥当と判断2"}}
        )
        self.assertEqual(r4["status"], "ok")
        record = self._assert_render_matches_agenda()
        item02 = next(i for i in record["items"] if i["id"] == "02")
        self.assertEqual(item02["decision"]["outcome"], "adopt")

        # --- next / pending: 全項目決着済み ---
        next_result = self._run(["next", "--path", self.agenda_path])
        self.assertIsNone(next_result["item_id"])

        pending_result = self._run(["pending", "--path", self.agenda_path])
        self.assertEqual(pending_result["pending_item_ids"], [])
        self.assertEqual(pending_result["remaining_count"], 0)

        # --- finish: 全項目 decision 済みのため削除する ---
        finish_result = self._run(["finish", "--path", self.agenda_path])
        self.assertEqual(finish_result["status"], "ok")
        self.assertTrue(finish_result["deleted"])
        self.assertFalse(Path(self.agenda_path).exists())
        self.assertFalse((self.agenda_dir / "agenda.html").exists())

    def test_new_item_added_mid_session_requires_structural_judgment_note(self):
        # §5.1a: start 後に record で新規項目を追加する場合、集合全体への
        # 再判定（structural_judgment.note）を同一呼び出し内で伴わなければならない。
        self._start(
            {
                "structural_judgment": {"note": "初期判定"},
                "config": {"item_fields": [], "severity_field": None},
                "items": [{"id": "01", "title": "項目1"}],
            }
        )
        rejected = self._record("02", {"title": "追加項目"})
        self.assertEqual(rejected["status"], "error")
        self.assertIn("structural_judgment.note", rejected["missing_fields"])
        record = self._record_record()
        self.assertEqual(len(record["items"]), 1)  # 項目・判定ともに保存されない

        accepted = self._record(
            "02",
            {"title": "追加項目", "structural_judgment": {"note": "追加後もなお構造的な誤りは無い"}},
        )
        self.assertEqual(accepted["status"], "ok")
        record = self._assert_render_matches_agenda()
        self.assertEqual(len(record["items"]), 2)
        self.assertEqual(record["structural_judgment"]["note"], "追加後もなお構造的な誤りは無い")


if __name__ == "__main__":
    unittest.main()
