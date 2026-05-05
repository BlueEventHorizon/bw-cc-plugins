"""write_interpretation のテスト。"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[4] / "plugins" / "forge" / "scripts"),
)

from session.write_interpretation import write_interpretation
from session.yaml_utils import read_yaml

SCRIPT = str(
    Path(__file__).resolve().parents[4]
    / "plugins" / "forge" / "scripts" / "session" / "write_interpretation.py"
)


class _FsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.session_dir = self.tmpdir / "review-test"
        self.session_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_review(self, perspective, content):
        path = self.session_dir / f"review_{perspective}.md"
        path.write_text(content, encoding="utf-8")
        return path


class TestWriteInterpretation(_FsTestCase):
    def test_first_call_creates_backup(self):
        """初回呼び出しで .raw.md が作成される。"""
        self._write_review("logic", "# reviewer 原文\n指摘1\n")

        result = write_interpretation(
            str(self.session_dir), "logic", "# evaluator 評価\n整形後\n"
        )

        self.assertTrue(result["backup_created"])
        target = self.session_dir / "review_logic.md"
        backup = self.session_dir / "review_logic.raw.md"
        self.assertTrue(backup.exists())
        self.assertEqual(target.read_text(encoding="utf-8"),
                         "# evaluator 評価\n整形後\n")
        self.assertEqual(backup.read_text(encoding="utf-8"),
                         "# reviewer 原文\n指摘1\n")

    def test_second_call_preserves_backup(self):
        """2回目呼び出しで .raw.md が保護される(初回バックアップが維持)。"""
        self._write_review("logic", "# reviewer 原文\n")

        write_interpretation(
            str(self.session_dir), "logic", "# 初回整形\n"
        )
        result2 = write_interpretation(
            str(self.session_dir), "logic", "# 2回目整形\n"
        )

        self.assertFalse(result2["backup_created"])
        target = self.session_dir / "review_logic.md"
        backup = self.session_dir / "review_logic.raw.md"
        self.assertEqual(target.read_text(encoding="utf-8"), "# 2回目整形\n")
        # 初回のバックアップ内容が維持されている
        self.assertEqual(backup.read_text(encoding="utf-8"), "# reviewer 原文\n")

    def test_idempotent_same_content(self):
        """同一内容での連続呼び出しは結果不変。"""
        self._write_review("logic", "# reviewer 原文\n")

        write_interpretation(str(self.session_dir), "logic", "# 整形\n")
        write_interpretation(str(self.session_dir), "logic", "# 整形\n")
        write_interpretation(str(self.session_dir), "logic", "# 整形\n")

        target = self.session_dir / "review_logic.md"
        backup = self.session_dir / "review_logic.raw.md"
        self.assertEqual(target.read_text(encoding="utf-8"), "# 整形\n")
        self.assertEqual(backup.read_text(encoding="utf-8"), "# reviewer 原文\n")

    def test_missing_target_raises(self):
        """review_{perspective}.md が存在しない場合はエラー。"""
        with self.assertRaises(FileNotFoundError):
            write_interpretation(
                str(self.session_dir), "unknown", "# 整形\n"
            )

    def test_empty_content_raises(self):
        """空内容はエラー。"""
        self._write_review("logic", "# reviewer 原文\n")
        with self.assertRaises(ValueError):
            write_interpretation(str(self.session_dir), "logic", "")

    def test_no_tmp_files_left_after_write(self):
        """アトミック書き込みの tmp ファイルが session_dir に残らない。"""
        self._write_review("logic", "# reviewer 原文\n")
        write_interpretation(str(self.session_dir), "logic", "# 整形\n")
        write_interpretation(str(self.session_dir), "logic", "# 再整形\n")

        # .tmp で終わるファイルがない(tempfile.mkstemp の suffix 回収確認)
        tmp_files = list(self.session_dir.glob("*.tmp"))
        self.assertEqual(tmp_files, [])
        # .review_logic.md.* のような隠しファイルも残らない
        hidden_files = list(self.session_dir.glob(".*.tmp"))
        self.assertEqual(hidden_files, [])

    def test_updates_session_meta(self):
        """review_{perspective}.md 書き換え後に active_artifact を更新する。"""
        (self.session_dir / "session.yaml").write_text(
            "status: active\nskill: review\n", encoding="utf-8"
        )
        self._write_review("logic", "# reviewer 原文\n")

        write_interpretation(str(self.session_dir), "logic", "# 整形\n")

        session = read_yaml(str(self.session_dir / "session.yaml"))
        self.assertEqual(session["active_artifact"], "review_logic.md")

    def test_atomic_rename_does_not_corrupt_on_partial(self):
        """書き込みに失敗しても target は直前の内容のまま維持される。

        store の tmp エラーパスを検証: 書き込み中に例外が
        発生した場合、target は書き換わらず tmp は掃除される。
        """
        from session.store import _atomic_write_text

        target = self.session_dir / "test_atomic.md"
        target.write_text("original", encoding="utf-8")

        # disk full 相当をシミュレート: content 引数に非 str を渡して TypeError
        with self.assertRaises((TypeError, AttributeError)):
            _atomic_write_text(target, 12345)  # 非文字列 → 書き込み時に失敗

        # target は元のまま
        self.assertEqual(target.read_text(encoding="utf-8"), "original")
        # tmp ファイルが残らない
        tmp_files = list(self.session_dir.glob(".test_atomic.md.*"))
        self.assertEqual(tmp_files, [])


class TestWriteInterpretationCli(_FsTestCase):
    def test_cli_first_call(self):
        (self.session_dir / "review_logic.md").write_text(
            "# reviewer 原文\n", encoding="utf-8"
        )

        result = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir),
             "--perspective", "logic"],
            input="# 整形\n",
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "ok")
        self.assertTrue(output["backup_created"])
        self.assertTrue((self.session_dir / "review_logic.raw.md").exists())
        self.assertEqual(
            (self.session_dir / "review_logic.md").read_text(encoding="utf-8"),
            "# 整形\n",
        )

    def test_cli_second_call_preserves_backup(self):
        (self.session_dir / "review_logic.md").write_text(
            "# reviewer 原文\n", encoding="utf-8"
        )

        subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir),
             "--perspective", "logic"],
            input="# 初回\n",
            capture_output=True, text=True,
        )
        result = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir),
             "--perspective", "logic"],
            input="# 2回目\n",
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        output = json.loads(result.stdout)
        self.assertFalse(output["backup_created"])
        # .raw.md は初回バックアップのまま
        self.assertEqual(
            (self.session_dir / "review_logic.raw.md").read_text(encoding="utf-8"),
            "# reviewer 原文\n",
        )
        self.assertEqual(
            (self.session_dir / "review_logic.md").read_text(encoding="utf-8"),
            "# 2回目\n",
        )

    def test_cli_missing_target(self):
        """review_{perspective}.md がない場合は非ゼロ終了。"""
        result = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir),
             "--perspective", "missing"],
            input="# 整形\n",
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)

    def test_cli_empty_stdin(self):
        """空 stdin は非ゼロ終了。"""
        (self.session_dir / "review_logic.md").write_text(
            "# reviewer 原文\n", encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir),
             "--perspective", "logic"],
            input="",
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
