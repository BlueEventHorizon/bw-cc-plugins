"""resolve_review_backend.py の単体テスト（DES-066 §2.1 / §2.2）。

固定する契約:

- **明示指定と候補順を `mode` で区別する**: `explicit` は可用性検査が不可なら
  fail closed、`order` は次候補へ進む。この区別を失うと、利用者・プロジェクトが
  選んだ実行主体が満たせないときに黙って別の主体で走る（ADR-060 が禁じた挙動）
- **設定不正で既定値へ落ちない**: 読めない設定を無視して既定で動くと、意図した
  実行主体と異なる側で静かにレビューが走る
- **可用性検査を行わない**: 判定は各バックエンドの責務であり、本 CLI は順序だけを扱う
"""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "review" / "scripts" / "resolve_review_backend.py"
)

_spec = importlib.util.spec_from_file_location("forge_resolve_review_backend", _SCRIPT_PATH)
resolve_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resolve_mod)

_PROJECT_ROOT = "/tmp/project"


class _FakeSettings:
    """`forge_settings` の差し替え。section の返り値または送出例外を指定する。"""

    SettingsError = resolve_mod.forge_settings.SettingsError

    def __init__(self, section_value=None, raises=None):
        self._section = section_value if section_value is not None else {}
        self._raises = raises
        self.calls = []

    def section(self, project_root, name):
        self.calls.append((project_root, name))
        if self._raises is not None:
            raise self._raises
        return self._section


class NoSettingTest(unittest.TestCase):
    def test_default_order_when_nothing_specified(self):
        code, payload = resolve_mod.run(_PROJECT_ROOT, settings=_FakeSettings())
        self.assertEqual(code, resolve_mod.EXIT_SUCCESS)
        self.assertEqual(payload["mode"], resolve_mod.MODE_ORDER)
        self.assertEqual(payload["order"], list(resolve_mod.DEFAULT_ORDER))
        self.assertEqual(payload["source"], resolve_mod.SOURCE_DEFAULT)

    def test_default_order_is_not_empty(self):
        """候補が 1 つも無ければ、どの実行主体も試せない。"""
        self.assertTrue(resolve_mod.DEFAULT_ORDER)

    def test_reads_the_review_section(self):
        settings = _FakeSettings()
        resolve_mod.run(_PROJECT_ROOT, settings=settings)
        self.assertEqual(settings.calls, [(_PROJECT_ROOT, resolve_mod.SETTINGS_SECTION)])


class ArgumentTakesPrecedenceTest(unittest.TestCase):
    def test_backend_argument_is_explicit(self):
        code, payload = resolve_mod.run(
            _PROJECT_ROOT, backend_argument="codex-appserver", settings=_FakeSettings()
        )
        self.assertEqual(code, resolve_mod.EXIT_SUCCESS)
        self.assertEqual(payload["mode"], resolve_mod.MODE_EXPLICIT)
        self.assertEqual(payload["order"], ["codex-appserver"])
        self.assertEqual(payload["source"], resolve_mod.SOURCE_ARGUMENT)

    def test_argument_beats_setting(self):
        settings = _FakeSettings({"backend": "from-setting"})
        _, payload = resolve_mod.run(
            _PROJECT_ROOT, backend_argument="from-argument", settings=settings
        )
        self.assertEqual(payload["order"], ["from-argument"])

    def test_argument_is_honored_even_when_settings_are_broken(self):
        """今まさに与えられた指定を、無関係な設定不正で妨げない。"""
        settings = _FakeSettings(raises=resolve_mod.forge_settings.SettingsError("壊れています"))
        code, payload = resolve_mod.run(
            _PROJECT_ROOT, backend_argument="msg-review", settings=settings
        )
        self.assertEqual(code, resolve_mod.EXIT_SUCCESS)
        self.assertEqual(payload["order"], ["msg-review"])
        self.assertEqual(settings.calls, [])

    def test_argument_is_trimmed(self):
        _, payload = resolve_mod.run(
            _PROJECT_ROOT, backend_argument="  msg-review  ", settings=_FakeSettings()
        )
        self.assertEqual(payload["order"], ["msg-review"])

    def test_blank_argument_is_an_error(self):
        code, payload = resolve_mod.run(
            _PROJECT_ROOT, backend_argument="   ", settings=_FakeSettings()
        )
        self.assertEqual(code, resolve_mod.EXIT_OPERATION_ERROR)
        self.assertIsNone(payload["order"])


class SettingBackendTest(unittest.TestCase):
    def test_setting_backend_is_explicit(self):
        settings = _FakeSettings({"backend": "msg-review"})
        code, payload = resolve_mod.run(_PROJECT_ROOT, settings=settings)
        self.assertEqual(code, resolve_mod.EXIT_SUCCESS)
        self.assertEqual(payload["mode"], resolve_mod.MODE_EXPLICIT)
        self.assertEqual(payload["order"], ["msg-review"])
        self.assertEqual(payload["source"], resolve_mod.SOURCE_SETTING)


class SettingsMayNotDefineTheOrderTest(unittest.TestCase):
    """設定ファイルに候補順を書くキーを置かない（復活防止）。

    `.forge.yaml` は既定の挙動を 1 点だけ矯正する手段であり、無くても全機能が
    既定で動く（DES-061 §2.1）。候補順は選択ではなく解決アルゴリズムの定義であり、
    設定へ出すと順序を決めた理由が設計書に残ったまま結果だけが外部化される。
    """

    def test_only_backend_is_allowed(self):
        self.assertEqual(resolve_mod._ALLOWED_KEYS, (resolve_mod.SETTINGS_BACKEND_KEY,))

    def test_backend_order_is_rejected_as_unknown_key(self):
        """かつて存在した `backend_order` を書いても、未知キーとして拒否される。"""
        settings = _FakeSettings({"backend_order": ["a", "b"]})
        code, payload = resolve_mod.run(_PROJECT_ROOT, settings=settings)
        self.assertEqual(code, resolve_mod.EXIT_OPERATION_ERROR)
        self.assertEqual(payload["reason_code"], resolve_mod.REASON_SETTINGS_INVALID)
        self.assertIn("backend_order", payload["message"])
        self.assertIsNone(payload["order"])

    def test_backend_order_alongside_backend_is_also_rejected(self):
        """`backend` が正しく書かれていても、未知キーの同居は許さない。

        許してしまうと、効いていない設定が書かれたまま残り、利用者は順序を
        指定できたつもりになる。
        """
        settings = _FakeSettings({"backend": "chosen", "backend_order": ["a", "b"]})
        code, _ = resolve_mod.run(_PROJECT_ROOT, settings=settings)
        self.assertEqual(code, resolve_mod.EXIT_OPERATION_ERROR)

    def test_module_has_no_order_key_constant(self):
        """順序を読むキーの定数自体を持たない。"""
        self.assertFalse(hasattr(resolve_mod, "SETTINGS_ORDER_KEY"))


class SettingsInvalidTest(unittest.TestCase):
    """不正な設定で既定値へ落ちない（推測で実行主体を選ばない）。"""

    def _assert_invalid(self, section_value=None, raises=None):
        settings = _FakeSettings(section_value, raises=raises)
        code, payload = resolve_mod.run(_PROJECT_ROOT, settings=settings)
        self.assertEqual(code, resolve_mod.EXIT_OPERATION_ERROR)
        self.assertEqual(payload["reason_code"], resolve_mod.REASON_SETTINGS_INVALID)
        self.assertIsNone(payload["mode"])
        self.assertIsNone(payload["order"])
        self.assertIsNone(payload["source"])
        self.assertTrue(payload["message"])
        return payload

    def test_unparseable_settings(self):
        self._assert_invalid(raises=resolve_mod.forge_settings.SettingsError("3 行目付近"))

    def test_unknown_key(self):
        payload = self._assert_invalid({"backned": "msg-review"})
        # 綴り誤りを発見できるようキー名は載せる（値は載せない）
        self.assertIn("backned", payload["message"])

    def test_backend_is_not_a_string(self):
        self._assert_invalid({"backend": ["msg-review"]})

    def test_backend_is_blank(self):
        self._assert_invalid({"backend": "   "})

    def test_message_does_not_leak_setting_values(self):
        payload = self._assert_invalid({"backend": "   "})
        self.assertNotIn("   ", payload["message"].replace(" ", "_"))


class NoAvailabilityProbeTest(unittest.TestCase):
    """本 CLI は可用性検査を行わない（判定は各バックエンドの責務）。"""

    def test_does_not_spawn_any_process(self):
        with mock.patch.object(subprocess, "run") as run_mock:
            resolve_mod.run(_PROJECT_ROOT, settings=_FakeSettings())
            resolve_mod.run(
                _PROJECT_ROOT, backend_argument="msg-review", settings=_FakeSettings()
            )
        run_mock.assert_not_called()

    def test_module_does_not_import_subprocess(self):
        self.assertFalse(hasattr(resolve_mod, "subprocess"))


class CliTest(unittest.TestCase):
    def test_cli_exit_code_and_json(self):
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), "--project-root", "/tmp/nonexistent-forge-root"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, resolve_mod.EXIT_SUCCESS)
        self.assertIn(resolve_mod.MODE_ORDER, proc.stdout)

    def test_cli_accepts_backend_argument(self):
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), "--backend", "msg-review"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, resolve_mod.EXIT_SUCCESS)
        self.assertIn(resolve_mod.MODE_EXPLICIT, proc.stdout)


if __name__ == "__main__":
    unittest.main()
