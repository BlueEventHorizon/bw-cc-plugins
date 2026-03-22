#!/usr/bin/env python3
"""
session_manager.py のテスト

セッションディレクトリの作成・検索・削除をテストする。
標準ライブラリのみ使用。

実行:
  python3 -m unittest tests.forge.scripts.test_session_manager -v
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# テスト対象モジュールへのパスを追加
sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / 'plugins' / 'forge' / 'scripts'))

from session_manager import (
    COMMON_FIELDS,
    TEMP_BASE,
    cmd_cleanup,
    cmd_find,
    cmd_init,
    generate_session_name,
    parse_extra_args,
    validate_temp_path,
)
from session.yaml_utils import (
    now_iso,
    read_yaml,
    write_flat_yaml,
    yaml_scalar,
)


class _FsTestCase(unittest.TestCase):
    """ファイルシステムを使うテストの基底クラス"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        # TEMP_BASE をテスト用に差し替えるため、ワーキングディレクトリを変更
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmpdir)
        # .claude/.temp/ を作成
        (self.tmpdir / ".claude" / ".temp").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_file(self, rel_path, content=''):
        p = self.tmpdir / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8')
        return p


# =========================================================================
# 1. YAML ユーティリティ
# =========================================================================

class TestYamlValue(unittest.TestCase):
    """yaml_scalar のテスト（yaml_utils に委譲）"""

    def test_string_no_special(self):
        self.assertEqual(yaml_scalar("hello"), "hello")

    def test_string_with_colon(self):
        self.assertEqual(yaml_scalar("key: value"), '"key: value"')

    def test_string_with_space(self):
        self.assertEqual(yaml_scalar("hello world"), '"hello world"')

    def test_integer(self):
        self.assertEqual(yaml_scalar(42), "42")

    def test_bool_true(self):
        self.assertEqual(yaml_scalar(True), "true")

    def test_bool_false(self):
        self.assertEqual(yaml_scalar(False), "false")

    def test_empty_string(self):
        self.assertEqual(yaml_scalar(""), '""')

    def test_string_with_quotes(self):
        result = yaml_scalar('say "hello"')
        self.assertIn('\\"', result)


class TestWriteReadYaml(_FsTestCase):
    """write_flat_yaml / read_yaml の往復テスト"""

    def test_roundtrip_basic(self):
        path = self.tmpdir / "test.yaml"
        data = {"skill": "review", "status": "in_progress", "auto_count": 3}
        write_flat_yaml(path, data, field_order=COMMON_FIELDS)
        result = read_yaml(path)
        self.assertEqual(result["skill"], "review")
        self.assertEqual(result["status"], "in_progress")
        self.assertEqual(result["auto_count"], 3)

    def test_field_order(self):
        """共通フィールドが先に出力されるか"""
        path = self.tmpdir / "test.yaml"
        data = {
            "feature": "login",
            "skill": "start-design",
            "status": "in_progress",
            "started_at": "2026-03-13T10:00:00Z",
            "last_updated": "2026-03-13T10:00:00Z",
            "resume_policy": "none",
        }
        write_flat_yaml(path, data, field_order=COMMON_FIELDS)
        content = path.read_text(encoding="utf-8")
        lines = [l for l in content.strip().split("\n") if l]
        # 最初の行は skill
        self.assertTrue(lines[0].startswith("skill:"))
        # feature は共通フィールドの後
        skill_idx = next(i for i, l in enumerate(lines) if l.startswith("skill:"))
        feature_idx = next(i for i, l in enumerate(lines) if l.startswith("feature:"))
        self.assertGreater(feature_idx, skill_idx)

    def test_quoted_values_roundtrip(self):
        """スペース・特殊文字を含む値の往復"""
        path = self.tmpdir / "test.yaml"
        data = {"output_dir": "specs/login/design", "skill": "start-design"}
        write_flat_yaml(path, data, field_order=COMMON_FIELDS)
        result = read_yaml(path)
        self.assertEqual(result["output_dir"], "specs/login/design")

    def test_comments_ignored(self):
        """コメント行はスキップされる"""
        path = self.tmpdir / "test.yaml"
        path.write_text("# コメント\nskill: review\n# もう一つ\nstatus: in_progress\n",
                        encoding="utf-8")
        result = read_yaml(path)
        self.assertEqual(result["skill"], "review")
        self.assertEqual(result["status"], "in_progress")
        self.assertEqual(len(result), 2)

    def test_integer_roundtrip(self):
        """整数値が正しく往復する"""
        path = self.tmpdir / "test.yaml"
        write_flat_yaml(path, {"auto_count": 0, "skill": "review"}, field_order=COMMON_FIELDS)
        result = read_yaml(path)
        self.assertEqual(result["auto_count"], 0)
        self.assertIsInstance(result["auto_count"], int)


# =========================================================================
# 2. ヘルパー
# =========================================================================

class TestHelpers(unittest.TestCase):
    """ヘルパー関数のテスト"""

    def test_now_iso_format(self):
        ts = now_iso()
        # ISO 8601 + Z 表記
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_generate_session_name_format(self):
        name = generate_session_name("start-design")
        # {skill_name}-{6 hex chars}
        self.assertRegex(name, r"^start-design-[0-9a-f]{6}$")

    def test_generate_session_name_various_skills(self):
        """各スキル名がディレクトリ名に含まれること"""
        for skill in ["review", "start-plan", "start-implement"]:
            name = generate_session_name(skill)
            self.assertTrue(name.startswith(f"{skill}-"))

    def test_generate_session_name_unique(self):
        """連続生成で重複しないこと"""
        names = {generate_session_name("start-design") for _ in range(10)}
        self.assertEqual(len(names), 10)

    def test_parse_extra_args(self):
        remaining = ["--feature", "login", "--mode", "new", "--output-dir", "specs/login"]
        result = parse_extra_args(remaining)
        self.assertEqual(result["feature"], "login")
        self.assertEqual(result["mode"], "new")
        # ハイフンはアンダースコアに変換
        self.assertEqual(result["output_dir"], "specs/login")

    def test_parse_extra_args_integer(self):
        remaining = ["--auto-count", "3"]
        result = parse_extra_args(remaining)
        self.assertEqual(result["auto_count"], 3)
        self.assertIsInstance(result["auto_count"], int)


class TestValidateTempPath(_FsTestCase):
    """validate_temp_path のテスト"""

    def test_valid_path(self):
        path = os.path.join(TEMP_BASE, "start-design-a3f7b2")
        os.makedirs(path, exist_ok=True)
        self.assertTrue(validate_temp_path(path))

    def test_traversal_rejected(self):
        self.assertFalse(validate_temp_path("../../etc/passwd"))

    def test_outside_temp_rejected(self):
        self.assertFalse(validate_temp_path("/tmp/something"))


# =========================================================================
# 3. cmd_init
# =========================================================================

class TestCmdInit(_FsTestCase):
    """cmd_init のテスト"""

    def _make_args(self, skill):
        """argparse の Namespace を模擬する"""
        class Args:
            pass
        a = Args()
        a.skill = skill
        return a

    def test_creates_directory_and_refs(self):
        result = cmd_init(self._make_args("start-design"), [])
        session_dir = result["session_dir"]
        self.assertTrue(os.path.isdir(session_dir))
        self.assertTrue(os.path.isdir(os.path.join(session_dir, "refs")))

    def test_creates_session_yaml(self):
        result = cmd_init(self._make_args("start-design"), [])
        yaml_path = os.path.join(result["session_dir"], "session.yaml")
        self.assertTrue(os.path.isfile(yaml_path))
        data = read_yaml(yaml_path)
        self.assertEqual(data["skill"], "start-design")
        self.assertEqual(data["status"], "in_progress")

    def test_auto_timestamps(self):
        result = cmd_init(self._make_args("start-design"), [])
        data = read_yaml(os.path.join(result["session_dir"], "session.yaml"))
        self.assertRegex(str(data["started_at"]),
                         r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
        self.assertEqual(data["started_at"], data["last_updated"])

    def test_resume_policy_review(self):
        """review は resume_policy: resume"""
        result = cmd_init(self._make_args("review"), [])
        data = read_yaml(os.path.join(result["session_dir"], "session.yaml"))
        self.assertEqual(data["resume_policy"], "resume")

    def test_resume_policy_create(self):
        """create-* は resume_policy: none"""
        result = cmd_init(self._make_args("start-design"), [])
        data = read_yaml(os.path.join(result["session_dir"], "session.yaml"))
        self.assertEqual(data["resume_policy"], "none")

    def test_resume_policy_explicit(self):
        """--resume-policy で明示指定すると上書きされる"""
        result = cmd_init(
            self._make_args("start-design"),
            ["--resume-policy", "resume"],
        )
        data = read_yaml(os.path.join(result["session_dir"], "session.yaml"))
        self.assertEqual(data["resume_policy"], "resume")

    def test_extra_fields(self):
        """任意の --key value がsession.yaml に含まれる"""
        result = cmd_init(
            self._make_args("start-design"),
            ["--feature", "login", "--mode", "new", "--output-dir", "specs/login"],
        )
        data = read_yaml(os.path.join(result["session_dir"], "session.yaml"))
        self.assertEqual(data["feature"], "login")
        self.assertEqual(data["mode"], "new")
        self.assertEqual(data["output_dir"], "specs/login")

    def test_json_output_structure(self):
        result = cmd_init(self._make_args("start-design"), [])
        self.assertEqual(result["status"], "created")
        self.assertIn("session_dir", result)
        self.assertTrue(result["session_dir"].startswith(TEMP_BASE))

    def test_hyphen_to_underscore(self):
        """--output-dir → output_dir に変換"""
        result = cmd_init(
            self._make_args("start-design"),
            ["--output-dir", "specs/login/design"],
        )
        data = read_yaml(os.path.join(result["session_dir"], "session.yaml"))
        self.assertIn("output_dir", data)
        self.assertNotIn("output-dir", data)


# =========================================================================
# 4. cmd_find
# =========================================================================

class TestCmdFind(_FsTestCase):
    """cmd_find のテスト"""

    def _make_args(self, skill):
        class Args:
            pass
        a = Args()
        a.skill = skill
        return a

    def _create_session(self, skill, name=None):
        """テスト用セッションを手動作成する"""
        if name is None:
            name = f"{skill}-aaaaaa"
        session_dir = os.path.join(TEMP_BASE, name)
        os.makedirs(session_dir, exist_ok=True)
        write_flat_yaml(
            os.path.join(session_dir, "session.yaml"),
            {"skill": skill, "started_at": "2026-03-13T18:00:00Z",
             "last_updated": "2026-03-13T18:00:00Z",
             "status": "in_progress", "resume_policy": "none"},
            field_order=COMMON_FIELDS,
        )
        return session_dir

    def test_find_matching(self):
        self._create_session("start-design")
        result = cmd_find(self._make_args("start-design"))
        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["sessions"]), 1)
        self.assertEqual(result["sessions"][0]["skill"], "start-design")

    def test_find_no_match(self):
        self._create_session("start-design")
        result = cmd_find(self._make_args("review"))
        self.assertEqual(result["status"], "none")

    def test_find_multiple(self):
        self._create_session("start-design", "start-design-aaaaaa")
        self._create_session("start-design", "start-design-bbbbbb")
        result = cmd_find(self._make_args("start-design"))
        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["sessions"]), 2)

    def test_find_ignores_other_skills(self):
        self._create_session("start-design", "start-design-aaaaaa")
        self._create_session("start-plan", "start-plan-bbbbbb")
        result = cmd_find(self._make_args("start-design"))
        self.assertEqual(len(result["sessions"]), 1)


# =========================================================================
# 5. cmd_cleanup
# =========================================================================

class TestCmdCleanup(_FsTestCase):
    """cmd_cleanup のテスト"""

    def _make_args(self, session_dir):
        class Args:
            pass
        a = Args()
        a.session_dir = session_dir
        return a

    def test_deletes_directory(self):
        session_dir = os.path.join(TEMP_BASE, "start-design-aaaaaa")
        os.makedirs(session_dir, exist_ok=True)
        result = cmd_cleanup(self._make_args(session_dir))
        self.assertEqual(result["status"], "deleted")
        self.assertFalse(os.path.exists(session_dir))

    def test_rejects_unsafe_path(self):
        result = cmd_cleanup(self._make_args("/tmp/dangerous"))
        self.assertEqual(result["status"], "error")

    def test_nonexistent_path(self):
        result = cmd_cleanup(self._make_args(
            os.path.join(TEMP_BASE, "nonexistent")))
        self.assertEqual(result["status"], "error")

    def test_traversal_rejected(self):
        result = cmd_cleanup(self._make_args(
            os.path.join(TEMP_BASE, "..", "..", "etc")))
        self.assertEqual(result["status"], "error")


# =========================================================================
# 6. CLI 統合テスト
# =========================================================================

class TestCLI(_FsTestCase):
    """subprocess で CLI を呼び出すテスト"""

    SCRIPT = str(Path(__file__).resolve().parents[3]
                 / "plugins" / "forge" / "scripts" / "session_manager.py")

    def _run(self, *cli_args):
        result = subprocess.run(
            [sys.executable, self.SCRIPT] + list(cli_args),
            capture_output=True, text=True, cwd=self.tmpdir,
        )
        return result

    def test_init_cli(self):
        r = self._run("init", "--skill", "start-design", "--feature", "login")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["status"], "created")
        # ディレクトリが実際に作成されている
        self.assertTrue(os.path.isdir(
            os.path.join(self.tmpdir, data["session_dir"])))

    def test_find_cli_none(self):
        r = self._run("find", "--skill", "start-design")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["status"], "none")

    def test_init_find_cleanup_cycle(self):
        """init → find → cleanup の往復テスト"""
        # init
        r = self._run("init", "--skill", "start-plan", "--feature", "test")
        self.assertEqual(r.returncode, 0)
        init_data = json.loads(r.stdout)
        session_dir = init_data["session_dir"]

        # find
        r = self._run("find", "--skill", "start-plan")
        self.assertEqual(r.returncode, 0)
        find_data = json.loads(r.stdout)
        self.assertEqual(find_data["status"], "found")
        self.assertEqual(len(find_data["sessions"]), 1)

        # cleanup
        r = self._run("cleanup", session_dir)
        self.assertEqual(r.returncode, 0)
        cleanup_data = json.loads(r.stdout)
        self.assertEqual(cleanup_data["status"], "deleted")

        # find で消えている
        r = self._run("find", "--skill", "start-plan")
        find_data = json.loads(r.stdout)
        self.assertEqual(find_data["status"], "none")

    def test_no_command_shows_help(self):
        r = self._run()
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
