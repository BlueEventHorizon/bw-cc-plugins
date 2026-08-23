#!/usr/bin/env python3
"""agenda 機構の統合テスト（DES-075 §9 の統合テスト対象、TASK-004 acceptance_criteria）。

init → record-structural-judgment → update×N（決着への遷移を含む） → next/pending の
一連の CLI 呼び出しが意図通り成功すること、各書き込み操作直後に表示
（agenda.html/agenda_state.js）が再生成され最新の agenda.json と一致すること、
record-structural-judgment を個別項目の遷移より先に実行する順序制約（§6.2）が
守られていることを検証する。

単体テスト（test_agenda_store.py）とは異なり、モックを使わず実際のファイル
書き込み・読み込みを通して検証する（統合テストの目的が「実際に繋がって
動くこと」の確認であるため）。ヘルパー（`_run` 相当）は test_agenda_store.py の
ものを import せず、本ファイル内で新規に用意する（テストファイル間の結合を避ける）。

実行:
  python3 -m unittest tests.forge.agenda.test_agenda_integration -v
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "forge"
    / "scripts"
    / "agenda"
    / "agenda_store.py"
)
_SPEC = importlib.util.spec_from_file_location("agenda_store", _MODULE_PATH)
agenda_store = importlib.util.module_from_spec(_SPEC)
sys.modules["agenda_store"] = agenda_store
_SPEC.loader.exec_module(agenda_store)


class AgendaIntegrationTest(unittest.TestCase):
    """init → record-structural-judgment → update×N → next/pending の一連の統合検証。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.agenda_path = str(Path(self._tmp.name) / "agenda.json")

    # -- CLI 呼び出しヘルパー（本ファイル専用。他テストファイルと共有しない） --

    def _run(self, args_list):
        parser = agenda_store.build_parser()
        args = parser.parse_args(args_list)
        return agenda_store._HANDLERS[args.command](args)

    def _record(self):
        return agenda_store.load_agenda(self.agenda_path)

    def _read_state_js(self):
        agenda_dir = Path(self.agenda_path).parent
        text = (agenda_dir / "agenda_state.js").read_text(encoding="utf-8")
        prefix = "window.AGENDA_DATA = "
        self.assertTrue(text.startswith(prefix), text)
        json_str = text[len(prefix):].rstrip("\n")
        if json_str.endswith(";"):
            json_str = json_str[:-1]
        return json.loads(json_str)

    def _assert_render_matches_agenda(self):
        """実際に書き出された agenda.html/agenda_state.js が、実際に load_agenda() で
        読み込んだ最新の agenda.json と一致することを検証する（currentItemId/
        changedItemIds/contentVersion を実データで突合する）。"""
        record = self._record()
        agenda_dir = Path(self.agenda_path).parent
        self.assertTrue((agenda_dir / "agenda.html").exists())
        self.assertTrue((agenda_dir / "agenda_state.js").exists())

        state = self._read_state_js()
        self.assertEqual(state["currentItemId"], record["current_item_id"])
        self.assertEqual(state["contentVersion"], record["content_version"])
        expected_changed = sorted(
            item["id"]
            for item in record["items"]
            if isinstance(item, dict) and item.get("last_changed_fields")
        )
        self.assertEqual(sorted(state["changedItemIds"]), expected_changed)

        html_text = (agenda_dir / "agenda.html").read_text(encoding="utf-8")
        self.assertIn(
            f"window.__agendaLastVersion = {record['content_version']};", html_text
        )
        return record

    def test_init_to_record_structural_judgment_to_updates_to_next_pending(self):
        # --- init（consult Phase 2 相当。DES-075 §6） ---
        init_result = self._run(
            [
                "init",
                "--identity", "20260823-agenda-integration",
                "--status-vocabulary",
                json.dumps(["未着手", "進行中", "決着", "保留"], ensure_ascii=False),
                "--terminal-statuses", json.dumps(["決着"], ensure_ascii=False),
                "--active-statuses", json.dumps(["未着手", "進行中"], ensure_ascii=False),
                "--item-fields", json.dumps(["severity"], ensure_ascii=False),
                "--severity-field", "severity",
                "--path", self.agenda_path,
            ]
        )
        self.assertEqual(init_result["status"], "ok")
        record = self._assert_render_matches_agenda()
        self.assertEqual(record["content_version"], 1)
        self.assertFalse(record["structural_judgment"]["recorded"])

        # --- 順序制約（§6.2・FNC-012）: structural_judgment 未記録時は
        #     個別項目の遷移（update）が先に拒否されることを確認してから
        #     record-structural-judgment を実行する ---
        premature_update = self._run(
            [
                "update", "--path", self.agenda_path, "--item-id", "01",
                "--set", "title=項目1", "--set", "status=未着手",
            ]
        )
        self.assertEqual(premature_update["status"], "error")
        self.assertIn("structural_judgment.recorded", premature_update["missing_fields"])
        record_after_rejection = self._record()
        self.assertEqual(record_after_rejection["items"], [])
        self.assertEqual(record_after_rejection["content_version"], 1)

        # --- record-structural-judgment（FNC-012） ---
        rsj_result = self._run(
            [
                "record-structural-judgment", "--path", self.agenda_path,
                "--note", "同型の指摘は無い。個別の食い違いに留まる",
            ]
        )
        self.assertEqual(rsj_result["status"], "ok")
        record = self._assert_render_matches_agenda()
        self.assertEqual(record["content_version"], 2)
        self.assertTrue(record["structural_judgment"]["recorded"])

        # --- update ×N ---
        # 項目01を新規追加（未着手）
        update1 = self._run(
            [
                "update", "--path", self.agenda_path, "--item-id", "01",
                "--set", "title=項目1", "--set", "status=未着手",
                "--set", "fields.severity=high",
            ]
        )
        self.assertEqual(update1["status"], "ok")
        record = self._assert_render_matches_agenda()
        self.assertEqual(record["content_version"], 3)
        item01 = next(i for i in record["items"] if i["id"] == "01")
        self.assertEqual(
            sorted(item01["last_changed_fields"]), sorted(["title", "status", "fields"])
        )

        # 項目02を新規追加（進行中。外部指摘由来のため verification を持つ）
        update2 = self._run(
            [
                "update", "--path", self.agenda_path, "--item-id", "02",
                "--set", "title=項目2", "--set", "status=進行中",
                "--set", "verification.action=adopt",
            ]
        )
        self.assertEqual(update2["status"], "ok")
        record = self._assert_render_matches_agenda()
        self.assertEqual(record["content_version"], 4)

        # set-current で対話中の項目を示す（content_version は増えない。§3.2・§8.1）
        set_current_result = self._run(
            ["set-current", "--path", self.agenda_path, "--item-id", "01"]
        )
        self.assertEqual(set_current_result["status"], "ok")
        record = self._assert_render_matches_agenda()
        self.assertEqual(record["content_version"], 4)
        self.assertEqual(record["current_item_id"], "01")

        # 項目01を決着へ遷移（verification を持たない項目のため background/essence のみ必須）
        settle01 = self._run(
            [
                "update", "--path", self.agenda_path, "--item-id", "01",
                "--set", "status=決着",
                "--set", "background=背景の記述",
                "--set", "essence=本質の記述",
            ]
        )
        self.assertEqual(settle01["status"], "ok")
        record = self._assert_render_matches_agenda()
        self.assertEqual(record["content_version"], 5)
        item01 = next(i for i in record["items"] if i["id"] == "01")
        self.assertEqual(item01["status"], "決着")

        # 項目02を決着へ遷移させようとするが verification.referenced が空のため拒否される
        # （FNC-011: 採用する場合も検証を要求する）
        settle02_missing_ref = self._run(
            [
                "update", "--path", self.agenda_path, "--item-id", "02",
                "--set", "status=決着",
                "--set", "background=背景の記述2",
                "--set", "essence=本質の記述2",
            ]
        )
        self.assertEqual(settle02_missing_ref["status"], "error")
        self.assertIn("verification.referenced", settle02_missing_ref["missing_fields"])
        record = self._record()
        item02 = next(i for i in record["items"] if i["id"] == "02")
        self.assertEqual(item02["status"], "進行中")  # 拒否された変更は永続化されない
        self.assertEqual(record["content_version"], 5)  # 拒否は content_version を増やさない

        # referenced を追記して再実行すると成功する
        settle02 = self._run(
            [
                "update", "--path", self.agenda_path, "--item-id", "02",
                "--set", "status=決着",
                "--set", "background=背景の記述2",
                "--set", "essence=本質の記述2",
                "--set", "verification.action=adopt",
                "--set", "verification.referenced=path/to/file.py:10",
            ]
        )
        self.assertEqual(settle02["status"], "ok")
        record = self._assert_render_matches_agenda()
        self.assertEqual(record["content_version"], 6)
        item02 = next(i for i in record["items"] if i["id"] == "02")
        self.assertEqual(item02["status"], "決着")

        # --- next / pending（FNC-006） ---
        next_result = self._run(["next", "--path", self.agenda_path])
        self.assertEqual(next_result["status"], "ok")
        self.assertIsNone(next_result["next_item_id"])  # 全項目が決着済み

        pending_result = self._run(["pending", "--path", self.agenda_path])
        self.assertEqual(pending_result["status"], "ok")
        self.assertEqual(pending_result["pending_item_ids"], [])
        self.assertEqual(pending_result["remaining_count"], 0)


if __name__ == "__main__":
    unittest.main()
