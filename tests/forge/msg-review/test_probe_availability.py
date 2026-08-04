"""probe_availability.py の単体テスト（可用性検査の集約、DES-045 §3.5.2 / ADR-068）。

3 つの判定スクリプトの呼び出しを差し替え、集約の契約を固定する。とくに次の 2 点は
設計上の境界であり、テストで固定しないと将来の変更で静かに破れる。

- **不足を軸ごとに個別に返す**: 「使えません」への畳み込みが起きないこと
- **画面を読み取らない**: `capture-pane` / `read-screen` を呼ばないこと。軸 peer が
  実プロセスを直接確認する以上、画面からの推測は前提の判定材料を追加しない
  （ADR-068 §2.1 / §2.2）
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "msg-review" / "scripts" / "probe_availability.py"
)

_spec = importlib.util.spec_from_file_location("msg_review_probe_availability", _SCRIPT_PATH)
probe_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe_mod)

_PROJECT_ROOT = "/tmp/project"

#: 初期化が完了し、3 軸すべてが成立している応答
_OK_RESPONSES = {
    "ensure_codex_hook.py": {
        "gitignore": {"status": "already_present"},
        "symlink": {"status": "unchanged"},
        "hooks_json": {"status": "unchanged"},
    },
    "check_cmux_available.py": {"status": "available", "path": "/opt/bin/cmux"},
    "find_codex_pane.py": {"status": "found", "workspace": "W", "surface": "S"},
    "check_setup.py": {"status": "ok", "checks": [], "warnings": []},
}


class _Recorder:
    """`run_json` の差し替え。呼ばれたコマンド列を記録し、指定の応答を返す。"""

    def __init__(self, responses=None, errors=None):
        self.responses = dict(_OK_RESPONSES)
        if responses:
            self.responses.update(responses)
        self.errors = errors or {}
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        script = Path(args[1]).name
        if script in self.errors:
            return None, self.errors[script]
        return self.responses[script], None

    @property
    def scripts(self):
        return [Path(call[1]).name for call in self.calls]

    @property
    def flat_args(self):
        return [token for call in self.calls for token in call]


def _axes(result):
    return [entry["axis"] for entry in result["missing"]]


class AllAxesSatisfiedTest(unittest.TestCase):
    def test_available_with_empty_missing(self):
        result = probe_mod.probe(_PROJECT_ROOT, run_json=_Recorder())
        self.assertTrue(result["available"])
        self.assertEqual(result["missing"], [])

    def test_all_three_axes_are_evaluated_after_initialization(self):
        recorder = _Recorder()
        probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        self.assertEqual(
            sorted(recorder.scripts),
            [
                "check_cmux_available.py",
                "check_setup.py",
                "ensure_codex_hook.py",
                "find_codex_pane.py",
            ],
        )

    def test_project_root_is_passed_to_the_axes_that_need_it(self):
        recorder = _Recorder()
        probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        for call in recorder.calls:
            script = Path(call[1]).name
            if script == "find_codex_pane.py":
                self.assertIn(_PROJECT_ROOT, call)
            elif script == "check_setup.py":
                self.assertIn("--project-root", call)
                self.assertIn(_PROJECT_ROOT, call)


class MissingIsReportedPerAxisTest(unittest.TestCase):
    """不足を軸ごとに個別に返す（「使えません」に畳み込まない）。"""

    def test_only_wake_missing(self):
        recorder = _Recorder(
            {"check_cmux_available.py": {"status": "unavailable", "reason": "見つかりません"}}
        )
        result = probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        self.assertFalse(result["available"])
        self.assertEqual(_axes(result), [probe_mod.AXIS_WAKE])

    def test_only_peer_missing(self):
        recorder = _Recorder({"find_codex_pane.py": {"status": "not_found"}})
        result = probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        self.assertFalse(result["available"])
        self.assertEqual(_axes(result), [probe_mod.AXIS_PEER])

    def test_only_setup_missing(self):
        recorder = _Recorder(
            {
                "check_setup.py": {
                    "status": "error",
                    "checks": [{"name": "db_path_resolution", "ok": False, "detail": "解決不能"}],
                    "warnings": [],
                }
            }
        )
        result = probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        self.assertFalse(result["available"])
        self.assertEqual(_axes(result), [probe_mod.AXIS_SETUP])
        self.assertIn("db_path_resolution", result["missing"][0]["detail"])

    def test_wake_and_peer_missing_are_listed_separately(self):
        recorder = _Recorder(
            {
                "check_cmux_available.py": {"status": "unavailable", "reason": "見つかりません"},
                "find_codex_pane.py": {"status": "not_found"},
            }
        )
        result = probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        self.assertEqual(_axes(result), [probe_mod.AXIS_WAKE, probe_mod.AXIS_PEER])

    def test_every_missing_entry_carries_detail_and_remedy(self):
        recorder = _Recorder(
            {
                "check_cmux_available.py": {"status": "unavailable", "reason": "見つかりません"},
                "find_codex_pane.py": {"status": "ambiguous"},
                "check_setup.py": {"status": "error", "checks": [], "warnings": []},
            }
        )
        result = probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        self.assertEqual(len(result["missing"]), 3)
        for entry in result["missing"]:
            self.assertTrue(entry["detail"])
            self.assertTrue(entry["remedy"])


class PeerStatusIsDistinguishedTest(unittest.TestCase):
    """find_codex_pane の 4 状態を区別する。

    `error` は「判定できなかった」であり「常駐していない」ではない。両者を同じ
    文面で返すと、利用者は Codex を起動すべきなのか cmux を直すべきなのかを
    判断できない。
    """

    def test_found_is_satisfied(self):
        result = probe_mod.probe(_PROJECT_ROOT, run_json=_Recorder())
        self.assertNotIn(probe_mod.AXIS_PEER, _axes(result))

    def test_not_found_reports_absence(self):
        recorder = _Recorder({"find_codex_pane.py": {"status": "not_found"}})
        entry = probe_mod.probe(_PROJECT_ROOT, run_json=recorder)["missing"][0]
        self.assertIn("見つかりません", entry["detail"])

    def test_ambiguous_reports_multiple_candidates(self):
        recorder = _Recorder({"find_codex_pane.py": {"status": "ambiguous"}})
        entry = probe_mod.probe(_PROJECT_ROOT, run_json=recorder)["missing"][0]
        self.assertIn("複数", entry["detail"])

    def test_error_reports_undeterminable_not_absence(self):
        recorder = _Recorder(
            {"find_codex_pane.py": {"status": "error", "reason": "問い合わせ失敗"}}
        )
        entry = probe_mod.probe(_PROJECT_ROOT, run_json=recorder)["missing"][0]
        self.assertIn("判定できませんでした", entry["detail"])
        self.assertIn("問い合わせ失敗", entry["detail"])

    def test_unknown_status_is_not_treated_as_absence(self):
        """将来 find_codex_pane が status を追加しても「不在」と断定しない。"""
        recorder = _Recorder({"find_codex_pane.py": {"status": "brand_new_state"}})
        entry = probe_mod.probe(_PROJECT_ROOT, run_json=recorder)["missing"][0]
        self.assertIn("判定できませんでした", entry["detail"])


class ScriptFailureBecomesMissingTest(unittest.TestCase):
    """判定スクリプト自体の失敗も、その軸の不足として返す（検査結果として返す）。"""

    def test_each_axis_failure_is_reported(self):
        for script, axis in (
            ("check_cmux_available.py", probe_mod.AXIS_WAKE),
            ("find_codex_pane.py", probe_mod.AXIS_PEER),
            ("check_setup.py", probe_mod.AXIS_SETUP),
        ):
            with self.subTest(script=script):
                recorder = _Recorder(errors={script: "非ゼロ終了しました"})
                result = probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
                self.assertFalse(result["available"])
                self.assertIn(axis, _axes(result))


class AvailableAndMissingAgreeTest(unittest.TestCase):
    """`available` と `missing` の空・非空が食い違う出力を作らない。"""

    def test_agreement_across_all_combinations(self):
        unavailable = {"status": "unavailable", "reason": "見つかりません"}
        not_found = {"status": "not_found"}
        setup_error = {"status": "error", "checks": [], "warnings": []}
        for wake_bad in (False, True):
            for peer_bad in (False, True):
                for setup_bad in (False, True):
                    with self.subTest(wake=wake_bad, peer=peer_bad, setup=setup_bad):
                        responses = {}
                        if wake_bad:
                            responses["check_cmux_available.py"] = unavailable
                        if peer_bad:
                            responses["find_codex_pane.py"] = not_found
                        if setup_bad:
                            responses["check_setup.py"] = setup_error
                        result = probe_mod.probe(
                            _PROJECT_ROOT, run_json=_Recorder(responses)
                        )
                        self.assertEqual(result["available"], not result["missing"])


class NoScreenReadingTest(unittest.TestCase):
    """画面の読み取りを一切行わない（ADR-068 §2.1）。"""

    def test_does_not_invoke_capture_pane_or_read_screen(self):
        recorder = _Recorder()
        probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        joined = " ".join(recorder.flat_args)
        self.assertNotIn("capture-pane", joined)
        self.assertNotIn("read-screen", joined)

    def test_does_not_invoke_a_liveness_style_script(self):
        """画面推測の判定スクリプトを呼ばない（廃止済み設計の再導入を防ぐ）。"""
        recorder = _Recorder()
        probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        for script in recorder.scripts:
            self.assertNotIn("liveness", script)


class NoSendOrWakeTest(unittest.TestCase):
    """依頼送信・起床のいずれも行わない（副作用を持たない）。"""

    def test_does_not_invoke_send_or_wake_scripts(self):
        recorder = _Recorder()
        probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        joined = " ".join(recorder.flat_args)
        for forbidden in ("send.py", "send_and_await_reply.py", "wake_codex.sh", "send-key"):
            self.assertNotIn(forbidden, joined)


class WarningsArePassedThroughTest(unittest.TestCase):
    def test_setup_warnings_are_returned_unchanged(self):
        recorder = _Recorder(
            {"check_setup.py": {"status": "ok", "checks": [], "warnings": ["注意 A", "注意 B"]}}
        )
        result = probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        self.assertEqual(result["warnings"], ["注意 A", "注意 B"])

    def test_warnings_alone_do_not_make_it_unavailable(self):
        recorder = _Recorder(
            {"check_setup.py": {"status": "ok", "checks": [], "warnings": ["注意"]}}
        )
        result = probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        self.assertTrue(result["available"])

    def test_non_list_warnings_are_normalized_to_empty(self):
        recorder = _Recorder(
            {"check_setup.py": {"status": "ok", "checks": [], "warnings": None}}
        )
        result = probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        self.assertEqual(result["warnings"], [])


class InitializeBeforeCheckingTest(unittest.TestCase):
    """初期化（イニシャルセットアップ）を判定より前に実行する [MANDATORY]。

    Codex 側フック登録と非追跡 symlink `.codex/msg-sys/scripts` は、新規クローン・
    新規 worktree では必ず不在である（壊れているのではなく、まだ作られていない）。
    検査を初期化より前に置くと、初期化すれば使える環境を「使えない」と判定し、
    初期化する唯一の経路が封じられる（実際にこの順序で `/forge:review` が新規環境で
    恒久的に fail closed した）。順序は静かに壊れるためテストで固定する。
    """

    def test_initialization_runs_before_every_axis(self):
        recorder = _Recorder()
        probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        self.assertEqual(recorder.scripts[0], "ensure_codex_hook.py")

    def test_initialization_receives_project_root_and_plugin_dir(self):
        recorder = _Recorder()
        probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        init_call = recorder.calls[0]
        self.assertIn("--project-root", init_call)
        self.assertIn(_PROJECT_ROOT, init_call)
        self.assertIn("--plugin-msg-sys-dir", init_call)
        self.assertIn(str(probe_mod._MSG_SYS_DIR), init_call)

    def test_setup_axis_checks_the_full_precondition_set(self):
        """検査項目を契機ごとに作り分けない（前提検査へ除外フラグを渡さない）。"""
        recorder = _Recorder()
        probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        setup_call = next(
            call for call in recorder.calls if Path(call[1]).name == "check_setup.py"
        )
        self.assertNotIn("--skip-codex-hook", setup_call)

    def test_initialization_conflict_is_added_to_the_setup_shortfall(self):
        """初期化を完了できなかった理由を検査結果に添える（失敗を隠さない）。"""
        recorder = _Recorder(
            {
                "ensure_codex_hook.py": {
                    "symlink": {"status": "conflict", "path": "/proj/.codex/msg-sys/scripts"},
                    "hooks_json": {"status": "skipped_due_to_symlink_conflict"},
                },
                "check_setup.py": {
                    "status": "error",
                    "checks": [
                        {"name": "codex_hooks_registration", "ok": False, "detail": "..."}
                    ],
                    "warnings": [],
                },
            }
        )
        entry = next(
            e
            for e in probe_mod.probe(_PROJECT_ROOT, run_json=recorder)["missing"]
            if e["axis"] == probe_mod.AXIS_SETUP
        )
        self.assertIn("人間由来の実体", entry["detail"])
        self.assertIn("手動で解消", entry["remedy"])

    def test_initialization_reason_survives_when_check_setup_is_unrunnable(self):
        """前提検査が実行不能な経路でも初期化の失敗理由を落とさないこと [MANDATORY]。

        以前は `check_setup.py` が `status: error` を返す経路にのみ理由を添えており、
        `check_setup.py` 自体が実行不能・タイムアウト・JSON 不正だった経路では
        `init_note` を捨てていた。初期化が conflict で失敗しかつ前提検査も実行できない
        組み合わせでは、返る不足が「設定を判定できませんでした」だけになり、初期化に
        失敗した事実が利用者へ届かなかった（実レビューで指摘）。
        """
        recorder = _Recorder(
            {
                "ensure_codex_hook.py": {
                    "symlink": {"status": "conflict", "path": "/proj/.codex/msg-sys/scripts"},
                    "hooks_json": {"status": "skipped_due_to_symlink_conflict"},
                }
            },
            errors={"check_setup.py": "check_setup.py の実行に失敗しました: OSError"},
        )
        entry = next(
            e
            for e in probe_mod.probe(_PROJECT_ROOT, run_json=recorder)["missing"]
            if e["axis"] == probe_mod.AXIS_SETUP
        )
        # 前提検査を判定できなかった事実と、初期化に失敗した事実の両方が残る
        self.assertIn("判定できませんでした", entry["detail"])
        self.assertIn("人間由来の実体", entry["detail"])
        # 軸固有の対処を捨てず、初期化の対処を併記する
        self.assertIn("forge プラグインの導入状態", entry["remedy"])
        self.assertIn("手動で解消", entry["remedy"])

    def test_shortfall_assembly_has_a_single_definition_point(self):
        """不足の組み立てが 1 箇所（`_setup_shortfall`）に閉じていること。

        経路ごとに書き分けると、片方だけ理由を落とす形が再発する。
        """
        without = probe_mod._setup_shortfall("詳細", "対処", None)
        self.assertEqual(without, {"axis": probe_mod.AXIS_SETUP, "detail": "詳細", "remedy": "対処"})
        with_note = probe_mod._setup_shortfall("詳細", "対処", "初期化できませんでした")
        self.assertIn("初期化できませんでした", with_note["detail"])
        self.assertIn("初期化できませんでした", with_note["remedy"])
        self.assertTrue(with_note["remedy"].startswith("対処"))

    def test_initialization_failure_alone_is_not_a_shortfall(self):
        """初期化の結果そのものを不足として数えない（実際の状態は前提検査が判定する）。"""
        recorder = _Recorder(
            errors={"ensure_codex_hook.py": "実行に失敗しました: OSError"}
        )
        result = probe_mod.probe(_PROJECT_ROOT, run_json=recorder)
        # check_setup が ok を返す限り、初期化の実行失敗だけでは利用不可にしない
        self.assertTrue(result["available"])


class ExitCodeIsNotUsedForJudgmentTest(unittest.TestCase):
    """判定は JSON の `status` で行い、exit code では分岐しない [MANDATORY]。

    `find_codex_pane.py` は `found` 以外で exit 1 を返す（`wake_codex.sh` が注入対象の
    確定を exit code で判定するため、そちらの契約は変えられない）。exit code で先に
    切ると `not_found` / `ambiguous` が「判定できなかった」へ畳み込まれ、常駐していない
    だけの利用者に「cmux の動作を確認してください」という誤った対処を示す状態になる。

    差し替え不可の `_run_json`（本番の subprocess 境界）を実際に呼んで固定する。
    軸ごとの応答を差し替えるテストではこの不一致を検出できないため。
    """

    def _fake_script(self, tmpdir, payload, exit_code):
        script = Path(tmpdir) / "find_codex_pane.py"
        script.write_text(
            "import json, sys\n"
            f"print(json.dumps({payload!r}))\n"
            f"sys.exit({exit_code})\n",
            encoding="utf-8",
        )
        return script

    def test_json_on_stdout_is_used_even_when_exit_code_is_nonzero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = self._fake_script(tmpdir, {"status": "not_found"}, 1)
            payload, error = probe_mod._run_json([sys.executable, str(script)])
        self.assertIsNone(error)
        self.assertEqual(payload, {"status": "not_found"})

    def test_nonzero_exit_without_json_is_reported_as_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "find_codex_pane.py"
            script.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
            payload, error = probe_mod._run_json([sys.executable, str(script)])
        self.assertIsNone(payload)
        self.assertIn("find_codex_pane.py", error)

    def test_not_found_reaches_the_residency_remedy_through_the_real_boundary(self):
        """exit 1 の `not_found` が「常駐していない」の remedy に到達すること。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            script = self._fake_script(tmpdir, {"status": "not_found"}, 1)
            with mock.patch.object(probe_mod, "FIND_PANE_SCRIPT", script):
                result = probe_mod.probe(_PROJECT_ROOT, run_json=probe_mod._run_json)
        peer = next(e for e in result["missing"] if e["axis"] == probe_mod.AXIS_PEER)
        self.assertIn("常駐 Codex セッションが", peer["detail"])
        self.assertIn("常駐起動", peer["remedy"])
        self.assertNotIn("判定できませんでした", peer["detail"])


class ScriptPathsExistTest(unittest.TestCase):
    """参照する判定スクリプトが実在すること（相対解決の誤りを検出する）。"""

    def test_all_referenced_scripts_exist(self):
        for path in (
            probe_mod.CHECK_CMUX_SCRIPT,
            probe_mod.FIND_PANE_SCRIPT,
            probe_mod.CHECK_SETUP_SCRIPT,
        ):
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), f"{path} が存在しません")


if __name__ == "__main__":
    unittest.main()
