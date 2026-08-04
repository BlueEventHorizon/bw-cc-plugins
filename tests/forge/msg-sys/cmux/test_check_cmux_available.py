"""check_cmux_available.py の単体テスト（可用性検査の軸 A、DES-045 §3.5.2）。

判定は PATH 探索のみで行い、cmux を一度も起動しない（副作用を持たない）。
本テストはその性質を `subprocess` の不使用として固定する——将来「健全性まで
確かめる」意図で `cmux --version` 等を呼ぶ変更が入ると、可用性検査が候補ごとに
外部プロセスを起動する高価な検査になり、forge:ADR-067 §2.1 が課した性質を破る。
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[4]
    / "plugins" / "forge" / "scripts" / "msg-sys" / "cmux" / "check_cmux_available.py"
)

_spec = importlib.util.spec_from_file_location("msg_sys_check_cmux_available", _SCRIPT_PATH)
check_cmux_available_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_cmux_available_mod)


class CheckCmuxAvailableTest(unittest.TestCase):
    def test_available_when_command_found(self):
        result = check_cmux_available_mod.check_cmux_available(
            which=lambda name: "/opt/bin/cmux"
        )
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["path"], "/opt/bin/cmux")

    def test_unavailable_when_command_missing(self):
        result = check_cmux_available_mod.check_cmux_available(which=lambda name: None)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("cmux", result["reason"])

    def test_unavailable_when_which_returns_empty_string(self):
        """空文字列も「見つからない」として扱う（真偽判定に委ねる）。"""
        result = check_cmux_available_mod.check_cmux_available(which=lambda name: "")
        self.assertEqual(result["status"], "unavailable")

    def test_looks_up_the_cmux_command_name(self):
        seen = []
        check_cmux_available_mod.check_cmux_available(
            which=lambda name: seen.append(name) or "/opt/bin/cmux"
        )
        self.assertEqual(seen, [check_cmux_available_mod.CMUX_COMMAND])


class NoSideEffectTest(unittest.TestCase):
    """判定が読み取りのみであること（forge:ADR-067 §2.1）。"""

    def test_does_not_spawn_any_process(self):
        with mock.patch.object(subprocess, "run") as run_mock, \
                mock.patch.object(subprocess, "Popen") as popen_mock:
            check_cmux_available_mod.check_cmux_available(which=lambda name: "/opt/bin/cmux")
            check_cmux_available_mod.check_cmux_available(which=lambda name: None)
        run_mock.assert_not_called()
        popen_mock.assert_not_called()

    def test_module_does_not_import_subprocess(self):
        """モジュール自身が subprocess を持ち込んでいないこと。

        `check_cmux_available` の実装が将来 cmux を起動する形へ変わると、まず
        subprocess の import が現れる。import の不在を固定することで、上記の
        呼び出しテストをすり抜ける経路（別モジュール経由の起動等）も含めて
        「起動しない」を保てる。
        """
        self.assertFalse(hasattr(check_cmux_available_mod, "subprocess"))


class CliTest(unittest.TestCase):
    def test_cli_exits_zero_and_reports_unavailable_when_not_on_path(self):
        """可用性の有無は異常ではないため、利用不可でも終了コードは 0。

        PATH から cmux を除いた環境で実行する（実行環境に cmux が導入されて
        いるかどうかに依存しないテストにする）。
        """
        with tempfile.TemporaryDirectory() as empty_dir:
            proc = subprocess.run(
                [sys.executable, str(_SCRIPT_PATH)],
                capture_output=True,
                text=True,
                env={"PATH": empty_dir},
            )
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
