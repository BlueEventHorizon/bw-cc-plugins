"""check_baseline_violations.py のテスト。

修正 E: dprint pre-existing 違反を session 初期化時にスナップショットし、
fixer の構文検証から「pre-existing 立証責任」を解放する。
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPO_ROOT
    / "plugins"
    / "forge"
    / "scripts"
    / "session"
    / "check_baseline_violations.py"
)


def _run(session_dir):
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(session_dir)],
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestCheckBaselineViolations(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_refs(self, target_files):
        lines = ["target_files:"]
        for f in target_files:
            lines.append(f"  - {f}")
        (self.session_dir / "refs.yaml").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    def test_session_dir_not_found(self):
        r = _run(self.session_dir / "missing")
        self.assertNotEqual(r.returncode, 0)
        # stderr に error JSON が出る
        try:
            data = json.loads(r.stdout) if r.stdout.strip() else {}
        except json.JSONDecodeError:
            data = {}
        self.assertTrue(
            data.get("status") == "error"
            or "error" in r.stderr.lower()
            or "error" in r.stdout.lower()
        )

    def test_refs_missing_returns_empty_baseline(self):
        """refs.yaml がなければ checked=0 の空 baseline を書き出す。"""
        r = _run(self.session_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["checked"], 0)
        baseline_path = self.session_dir / "baseline_violations.json"
        self.assertTrue(baseline_path.exists())
        baseline = json.loads(baseline_path.read_text())
        self.assertEqual(baseline["files"], {})

    def test_empty_target_files_writes_empty_baseline(self):
        self._write_refs([])
        r = _run(self.session_dir)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["checked"], 0)
        self.assertEqual(data["pre_existing_count"], 0)

    def test_dprint_unavailable_writes_empty_baseline(self):
        """dprint 不在環境では全ファイル has_violations=false (fail-safe)。"""
        # 適当な target_files を refs.yaml に書く
        self._write_refs(["fake-file-a.md", "fake-file-b.md"])

        # shutil.which が None を返すよう module をモック化して再実行は難しいので、
        # PATH を空にして subprocess を実行する
        env_path = ""
        r = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), str(self.session_dir)],
            capture_output=True,
            text=True,
            timeout=30,
            env={"PATH": env_path},
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        # dprint 不在: checked は 0 (pre-existing 判定は実施されない)
        self.assertEqual(data["checked"], 0)

        baseline = json.loads(
            (self.session_dir / "baseline_violations.json").read_text()
        )
        self.assertIsNone(baseline["tool"])
        # target_files は entries として保持される
        self.assertIn("fake-file-a.md", baseline["files"])
        self.assertFalse(baseline["files"]["fake-file-a.md"]["has_violations"])

    def test_violation_classification_by_exit_code(self):
        """exit code 20 のみ has_violations=true、それ以外は false (検査対象外含む)。

        dprint コマンドは includes パターンや環境設定に依存して exit code を
        変える (0/14/20 など)。スクリプトは「公式の violation exit code = 20」
        だけを違反扱いし、他は安全側 (違反なし) に倒すこと。

        subprocess.run を直接 mock して exit code 別の挙動を検証する。
        """
        # 実 dprint の振る舞いに依存せずスクリプトロジックを直接検証するため、
        # check_baseline_violations モジュールをスクリプトとしてではなく import で
        # ロードして _check_file の挙動だけテストする。
        script_dir = SCRIPT_PATH.parent
        sys.path.insert(0, str(script_dir.parent))
        try:
            from session import check_baseline_violations as cbv
        finally:
            sys.path.pop(0)

        with mock.patch.object(cbv.subprocess, "run") as mock_run:
            # exit 20 → has_violations=true
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=20, stdout="", stderr=""
            )
            result = cbv._check_file("any.md")
            self.assertTrue(result["has_violations"])
            self.assertEqual(result["exit_code"], 20)

            # exit 0 → has_violations=false
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            result = cbv._check_file("any.md")
            self.assertFalse(result["has_violations"])
            self.assertEqual(result["exit_code"], 0)

            # exit 14 (no files found) → has_violations=false (検査対象外)
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=14, stdout="", stderr=""
            )
            result = cbv._check_file("any.md")
            self.assertFalse(result["has_violations"])
            self.assertEqual(result["exit_code"], 14)


if __name__ == "__main__":
    unittest.main()
