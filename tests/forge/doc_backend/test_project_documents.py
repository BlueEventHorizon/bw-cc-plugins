#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""project_documents.py のユニットテスト。

検証項目は worktree 共通 key、branch series、detached fallback、対象文書、exclude。

外部コマンドは `run_command()` の 1 境界へ差し替えて注入する。git は実行せず、
実リポジトリの branch / worktree 構成にも依存しない。fixture はすべて本ファイル内の
定数文字列で持つ。

実行:
  python3 -m unittest tests.forge.doc_backend.test_project_documents -v
"""

import ast
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "doc_backend" / "project_documents.py"
)

_spec = importlib.util.spec_from_file_location(
    "doc_backend_project_documents", _SCRIPT_PATH
)
project_documents = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(project_documents)


# --- fixture ------------------------------------------------------------------

#: 同一 repo の 2 つの worktree。basename は異なるが git common dir は共通
MAIN_WORKTREE = "/repo/sample-project"
LINKED_WORKTREE = "/repo/sample-project-worktrees/feature-x"

#: `git rev-parse --git-common-dir` の出力（linked worktree では絶対パスで返る）
GIT_COMMON_DIR_ABSOLUTE = "/repo/sample-project/.git\n"

#: 本体 worktree では相対パス（`.git`）で返る
GIT_COMMON_DIR_RELATIVE = ".git\n"

#: `git rev-parse --abbrev-ref HEAD` の出力
BRANCH_OUTPUT = "feature/doc-db\n"
BRANCH_OUTPUT_MAIN = "main\n"
DETACHED_OUTPUT = "HEAD\n"

#: git が repo 外で返すエラー出力
NOT_A_REPO_STDERR = "fatal: not a git repository (or any of the parent directories): .git\n"

#: resolver（`resolve_doc_structure.py --type rules`）の成功応答
RESOLVER_RULES_OK = json.dumps({
    "status": "ok",
    "project_root": MAIN_WORKTREE,
    "rules": ["docs/rules/alpha.md", "docs/rules/beta.md"],
})

#: resolver の成功応答（0 件）
RESOLVER_RULES_EMPTY = json.dumps({
    "status": "ok",
    "project_root": MAIN_WORKTREE,
    "rules": [],
})

#: resolver の成功応答（specs）
RESOLVER_SPECS_OK = json.dumps({
    "status": "ok",
    "project_root": MAIN_WORKTREE,
    "specs": ["docs/specs/foo/design/DES-001_foo.md"],
})

#: resolver の設定エラー応答（stdout へ出る経路）
RESOLVER_CONFIG_ERROR = json.dumps({
    "status": "error",
    "message": ".doc_structure.yaml に root_dirs が定義されていません。 パス解決ができません",
    "suggestion": "setup-doc-structure を実行して .doc_structure.yaml を再生成してください",
})

#: resolver のファイル不在応答
RESOLVER_NOT_FOUND = json.dumps({
    "status": "error",
    "message": ".doc_structure.yaml が見つかりません: /repo/sample-project/.doc_structure.yaml",
})

#: JSON として解析できない resolver 出力
RESOLVER_TRACEBACK = "Traceback (most recent call last):\n  File \"resolve_doc_structure.py\"\n"

#: category の一覧を含まない resolver 応答
RESOLVER_MISSING_CATEGORY = json.dumps({"status": "ok", "project_root": MAIN_WORKTREE})

#: hermetic な resolver 実行に使う .doc_structure.yaml（exclude の実効を確かめる）
DOC_STRUCTURE_YAML = """# doc_structure_version: 3.0

rules:
  root_dirs:
    - docs/rules/
  patterns:
    target_glob: "**/*.md"
    exclude: []

specs:
  root_dirs:
    - "docs/specs/**/design/"
    - "docs/specs/**/plan/"
  patterns:
    target_glob: "**/*.md"
    exclude: [plan]
"""

MARKDOWN_BODY = "# fixture\n"


# --- 注入用 runner ------------------------------------------------------------


class _RecordingRunner:
    """`run_command()` と同じ signature で canned な結果を返す差し替え境界。

    コマンドの先頭要素（`git`）と `rev-parse` の対象で応答を切り分ける。
    resolver 呼び出しは script 名で判定する。
    """

    def __init__(self, common_dir=GIT_COMMON_DIR_ABSOLUTE, branch=BRANCH_OUTPUT, resolver=None):
        self._common_dir = common_dir
        self._branch = branch
        self._resolver = resolver
        self.calls = []

    def __call__(self, args, cwd, timeout):
        args = list(args)
        self.calls.append({"args": args, "cwd": Path(cwd), "timeout": timeout})
        if args[0] == "git" and "--git-common-dir" in args:
            return self._reply(self._common_dir)
        if args[0] == "git" and "--abbrev-ref" in args:
            return self._reply(self._branch)
        if any("resolve_doc_structure.py" in arg for arg in args):
            if self._resolver is None:
                raise AssertionError("resolver 応答が注入されていません")
            return self._reply(self._resolver)
        raise AssertionError(f"想定外のコマンド: {args}")

    @staticmethod
    def _reply(canned):
        """canned は文字列（stdout, exit 0）または `(returncode, stdout, stderr)`。"""
        if isinstance(canned, tuple):
            return canned
        return 0, canned, ""


def _resolver_runner(resolver_output, **kwargs):
    return _RecordingRunner(resolver=resolver_output, **kwargs)


class WorktreeCommonKeyTest(unittest.TestCase):
    """KEY が worktree 間で分裂しないこと。"""

    def test_project_name_comes_from_git_common_dir_parent(self):
        runner = _RecordingRunner()
        name = project_documents.detect_project_name(Path(LINKED_WORKTREE), runner=runner)
        self.assertEqual(name, "sample-project")

    def test_project_name_ignores_worktree_basename(self):
        runner = _RecordingRunner()
        name = project_documents.detect_project_name(Path(LINKED_WORKTREE), runner=runner)
        self.assertNotEqual(name, Path(LINKED_WORKTREE).name)

    def test_same_key_from_main_and_linked_worktree(self):
        main = project_documents.resolve(
            "rules", Path(MAIN_WORKTREE), runner=_resolver_runner(RESOLVER_RULES_OK)
        )
        linked = project_documents.resolve(
            "rules", Path(LINKED_WORKTREE), runner=_resolver_runner(RESOLVER_RULES_OK)
        )
        self.assertEqual(main.key, linked.key)
        self.assertEqual(main.key, "sample-project-rules")

    def test_relative_common_dir_is_resolved_against_project_root(self):
        runner = _RecordingRunner(common_dir=GIT_COMMON_DIR_RELATIVE)
        name = project_documents.detect_project_name(Path(MAIN_WORKTREE), runner=runner)
        self.assertEqual(name, "sample-project")

    def test_project_name_falls_back_to_root_name_when_not_a_repo(self):
        runner = _RecordingRunner(common_dir=(128, "", NOT_A_REPO_STDERR))
        name = project_documents.detect_project_name(Path("/tmp/plain-dir"), runner=runner)
        self.assertEqual(name, "plain-dir")

    def test_project_name_falls_back_when_output_is_empty(self):
        runner = _RecordingRunner(common_dir=(0, "\n", ""))
        name = project_documents.detect_project_name(Path("/tmp/plain-dir"), runner=runner)
        self.assertEqual(name, "plain-dir")

    def test_project_name_falls_back_when_command_unavailable(self):
        runner = _RecordingRunner(
            common_dir=(project_documents.COMMAND_UNAVAILABLE_RETURNCODE, "", "git が見つかりません")
        )
        name = project_documents.detect_project_name(Path("/tmp/plain-dir"), runner=runner)
        self.assertEqual(name, "plain-dir")

    def test_git_command_uses_project_root_as_cwd_and_bounded_timeout(self):
        runner = _RecordingRunner()
        project_documents.detect_project_name(Path(LINKED_WORKTREE), runner=runner)
        call = runner.calls[0]
        self.assertEqual(call["args"], ["git", "rev-parse", "--git-common-dir"])
        self.assertEqual(call["cwd"], Path(LINKED_WORKTREE))
        self.assertEqual(call["timeout"], project_documents.GIT_TIMEOUT_SECONDS)

    def test_key_format_is_project_name_dash_category(self):
        self.assertEqual(project_documents.build_key("sample-project", "specs"), "sample-project-specs")


class RelativeProjectRootTest(unittest.TestCase):
    """相対 project root でも KEY と local_path の契約を満たすこと。

    `Path(".")` のような相対 root を渡されたとき、正規化しないと `.name` が空文字列に
    なり、git 非管理環境の KEY が `-{category}` へ落ちる。cwd を移動して実測する。
    """

    def setUp(self):
        self._original_cwd = Path.cwd()
        self._tempdir = tempfile.TemporaryDirectory()
        # macOS の /var・/tmp は symlink であり、resolve() 後の絶対パスと素朴な連結が
        # 一致しないため、期待値側も resolve() 済みの実体パスで持つ。
        self.project_root = Path(self._tempdir.name).resolve() / "plain-project"
        (self.project_root / "docs" / "rules").mkdir(parents=True)
        os.chdir(self.project_root)

    def tearDown(self):
        os.chdir(self._original_cwd)
        self._tempdir.cleanup()

    def test_project_name_is_not_empty_for_relative_root_outside_git(self):
        runner = _RecordingRunner(common_dir=(128, "", NOT_A_REPO_STDERR))
        name = project_documents.detect_project_name(Path("."), runner=runner)
        self.assertEqual(name, "plain-project")

    def test_key_does_not_start_with_a_dash_for_relative_root_outside_git(self):
        resolved = project_documents.resolve(
            "rules",
            Path("."),
            runner=_resolver_runner(
                RESOLVER_RULES_OK,
                common_dir=(128, "", NOT_A_REPO_STDERR),
                branch=(128, "", NOT_A_REPO_STDERR),
            ),
        )
        self.assertEqual(resolved.key, "plain-project-rules")
        self.assertFalse(resolved.key.startswith("-"))

    def test_entries_local_path_is_absolute_for_relative_root(self):
        resolved = project_documents.resolve(
            "rules", Path("."), runner=_resolver_runner(RESOLVER_RULES_OK)
        )
        for entry in resolved.entries:
            with self.subTest(path=entry["path"]):
                self.assertTrue(Path(entry["local_path"]).is_absolute())
        self.assertEqual(
            [entry["local_path"] for entry in resolved.entries],
            [
                str(self.project_root / "docs/rules/alpha.md"),
                str(self.project_root / "docs/rules/beta.md"),
            ],
        )

    def test_to_dict_project_root_is_absolute_for_relative_root(self):
        resolved = project_documents.resolve(
            "rules", Path("."), runner=_resolver_runner(RESOLVER_RULES_OK)
        )
        self.assertEqual(resolved.to_dict()["project_root"], str(self.project_root))


class BranchSeriesTest(unittest.TestCase):
    """series が現在の branch であること（読み書きで同一）。"""

    def test_series_is_current_branch(self):
        runner = _RecordingRunner()
        self.assertEqual(
            project_documents.detect_series(Path(MAIN_WORKTREE), runner=runner), "feature/doc-db"
        )

    def test_series_keeps_slash_in_branch_name(self):
        runner = _RecordingRunner(branch="release/1.2.x\n")
        self.assertEqual(
            project_documents.detect_series(Path(MAIN_WORKTREE), runner=runner), "release/1.2.x"
        )

    def test_series_command_is_abbrev_ref_head(self):
        runner = _RecordingRunner()
        project_documents.detect_series(Path(MAIN_WORKTREE), runner=runner)
        self.assertEqual(
            runner.calls[0]["args"], ["git", "rev-parse", "--abbrev-ref", "HEAD"]
        )

    def test_resolve_uses_branch_as_series(self):
        resolved = project_documents.resolve(
            "specs", Path(MAIN_WORKTREE), runner=_resolver_runner(RESOLVER_SPECS_OK)
        )
        self.assertEqual(resolved.series, "feature/doc-db")


class DetachedAndFailureFallbackTest(unittest.TestCase):
    """series 取得不能・detached HEAD の扱いが規定どおりであること。"""

    def _series(self, branch):
        return project_documents.detect_series(
            Path(MAIN_WORKTREE), runner=_RecordingRunner(branch=branch)
        )

    def test_detached_head_falls_back_to_main(self):
        self.assertEqual(self._series(DETACHED_OUTPUT), project_documents.DEFAULT_SERIES)
        self.assertEqual(self._series(DETACHED_OUTPUT), "main")

    def test_non_zero_exit_falls_back_to_main(self):
        self.assertEqual(self._series((128, "", NOT_A_REPO_STDERR)), "main")

    def test_empty_output_falls_back_to_main(self):
        self.assertEqual(self._series((0, "\n", "")), "main")

    def test_command_unavailable_falls_back_to_main(self):
        self.assertEqual(
            self._series((project_documents.COMMAND_UNAVAILABLE_RETURNCODE, "", "git 不在")),
            "main",
        )

    def test_detached_head_does_not_create_a_head_series(self):
        resolved = project_documents.resolve(
            "rules",
            Path(MAIN_WORKTREE),
            runner=_resolver_runner(RESOLVER_RULES_OK, branch=DETACHED_OUTPUT),
        )
        self.assertNotEqual(resolved.series, "HEAD")
        self.assertEqual(resolved.series, "main")


class RunCommandBoundaryTest(unittest.TestCase):
    """外部コマンド境界そのものの検証（subprocess.run を差し替える）。"""

    def test_returns_returncode_stdout_stderr(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="out", stderr="err")
        with mock.patch.object(project_documents.subprocess, "run", return_value=completed):
            self.assertEqual(
                project_documents.run_command(["git", "status"], Path("/tmp"), 5),
                (0, "out", "err"),
            )

    def test_os_error_is_reported_as_unavailable(self):
        with mock.patch.object(
            project_documents.subprocess, "run", side_effect=OSError("No such file")
        ):
            returncode, stdout, stderr = project_documents.run_command(
                ["git", "status"], Path("/tmp"), 5
            )
        self.assertEqual(returncode, project_documents.COMMAND_UNAVAILABLE_RETURNCODE)
        self.assertEqual(stdout, "")
        self.assertIn("No such file", stderr)

    def test_timeout_is_reported_as_unavailable(self):
        with mock.patch.object(
            project_documents.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5),
        ):
            returncode, _, stderr = project_documents.run_command(
                ["git", "status"], Path("/tmp"), 5
            )
        self.assertEqual(returncode, project_documents.COMMAND_UNAVAILABLE_RETURNCODE)
        self.assertIn("5", stderr)

    def test_git_detection_uses_the_real_boundary_by_default(self):
        """既定の runner が `run_command` であること（差し替えは任意引数）。"""
        with mock.patch.object(
            project_documents.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=GIT_COMMON_DIR_ABSOLUTE, stderr=""
            ),
        ):
            self.assertEqual(
                project_documents.detect_project_name(Path(LINKED_WORKTREE)), "sample-project"
            )


class ResolverDelegationTest(unittest.TestCase):
    """対象文書の解決を既存 resolver の CLI へ委譲していること。"""

    def test_resolver_command_shape(self):
        runner = _resolver_runner(RESOLVER_RULES_OK)
        project_documents.resolve_paths("rules", Path(MAIN_WORKTREE), runner=runner)
        args = runner.calls[-1]["args"]
        self.assertTrue(args[1].endswith("resolve_doc_structure.py"), args[1])
        self.assertEqual(args[2:], ["--type", "rules", "--project-root", MAIN_WORKTREE])
        self.assertEqual(runner.calls[-1]["timeout"], project_documents.RESOLVER_TIMEOUT_SECONDS)

    def test_resolver_script_path_points_at_doc_structure_resolver(self):
        self.assertTrue(project_documents.RESOLVER_SCRIPT.is_file())
        self.assertEqual(project_documents.RESOLVER_SCRIPT.name, "resolve_doc_structure.py")

    def test_paths_are_returned_in_resolver_order(self):
        paths = project_documents.resolve_paths(
            "rules", Path(MAIN_WORKTREE), runner=_resolver_runner(RESOLVER_RULES_OK)
        )
        self.assertEqual(paths, ["docs/rules/alpha.md", "docs/rules/beta.md"])

    def test_specs_category_reads_specs_list(self):
        paths = project_documents.resolve_paths(
            "specs", Path(MAIN_WORKTREE), runner=_resolver_runner(RESOLVER_SPECS_OK)
        )
        self.assertEqual(paths, ["docs/specs/foo/design/DES-001_foo.md"])

    def test_no_yaml_parsing_is_reimplemented(self):
        """`.doc_structure.yaml` を自前で解釈していないこと（二重実装の防止）。"""
        tree = ast.parse(_SCRIPT_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for forbidden in ("glob", "fnmatch", "yaml", "os"):
            self.assertNotIn(
                forbidden, imported, f"resolver の責務を再実装している: {forbidden}"
            )

        defined = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }
        for forbidden in ("parse_config", "expand_globs", "collect_md_files", "is_excluded"):
            self.assertNotIn(
                forbidden, defined, f"resolver の責務を再実装している: {forbidden}"
            )

    def test_unknown_category_is_rejected(self):
        with self.assertRaises(project_documents.ProjectDocumentsError):
            project_documents.resolve_paths(
                "readme", Path(MAIN_WORKTREE), runner=_resolver_runner(RESOLVER_RULES_OK)
            )

    def test_config_error_becomes_project_documents_error(self):
        runner = _resolver_runner((1, RESOLVER_CONFIG_ERROR, ""))
        with self.assertRaises(project_documents.ProjectDocumentsError) as ctx:
            project_documents.resolve_paths("rules", Path(MAIN_WORKTREE), runner=runner)
        self.assertIn("root_dirs", str(ctx.exception))
        self.assertIn("setup-doc-structure", str(ctx.exception))

    def test_missing_config_file_becomes_project_documents_error(self):
        runner = _resolver_runner((1, RESOLVER_NOT_FOUND, ""))
        with self.assertRaises(project_documents.ProjectDocumentsError) as ctx:
            project_documents.resolve_paths("rules", Path(MAIN_WORKTREE), runner=runner)
        self.assertIn(".doc_structure.yaml", str(ctx.exception))

    def test_error_on_stderr_is_also_detected(self):
        """resolver は経路により JSON を stderr へ出す。どちらでも失敗として扱う。"""
        runner = _resolver_runner((1, "", RESOLVER_CONFIG_ERROR))
        with self.assertRaises(project_documents.ProjectDocumentsError):
            project_documents.resolve_paths("rules", Path(MAIN_WORKTREE), runner=runner)

    def test_unparsable_output_becomes_project_documents_error(self):
        runner = _resolver_runner((1, "", RESOLVER_TRACEBACK))
        with self.assertRaises(project_documents.ProjectDocumentsError) as ctx:
            project_documents.resolve_paths("rules", Path(MAIN_WORKTREE), runner=runner)
        self.assertIn("Traceback", str(ctx.exception))

    def test_missing_category_list_becomes_project_documents_error(self):
        runner = _resolver_runner(RESOLVER_MISSING_CATEGORY)
        with self.assertRaises(project_documents.ProjectDocumentsError) as ctx:
            project_documents.resolve_paths("rules", Path(MAIN_WORKTREE), runner=runner)
        self.assertIn("rules", str(ctx.exception))


class DocumentCountTest(unittest.TestCase):
    """対象文書数を呼び出し側が取得できること（0 件先行判定に使う）。"""

    def test_count_and_is_empty_for_non_empty_result(self):
        resolved = project_documents.resolve(
            "rules", Path(MAIN_WORKTREE), runner=_resolver_runner(RESOLVER_RULES_OK)
        )
        self.assertEqual(resolved.count, 2)
        self.assertFalse(resolved.is_empty)

    def test_zero_documents_is_success_not_error(self):
        resolved = project_documents.resolve(
            "rules", Path(MAIN_WORKTREE), runner=_resolver_runner(RESOLVER_RULES_EMPTY)
        )
        self.assertEqual(resolved.count, 0)
        self.assertTrue(resolved.is_empty)
        self.assertEqual(resolved.paths, ())

    def test_zero_and_non_zero_are_distinguishable_by_caller(self):
        empty = project_documents.resolve(
            "rules", Path(MAIN_WORKTREE), runner=_resolver_runner(RESOLVER_RULES_EMPTY)
        )
        filled = project_documents.resolve(
            "rules", Path(MAIN_WORKTREE), runner=_resolver_runner(RESOLVER_RULES_OK)
        )
        self.assertNotEqual(empty.count, filled.count)
        self.assertNotEqual(empty.is_empty, filled.is_empty)

    def test_entries_carry_path_and_absolute_local_path(self):
        resolved = project_documents.resolve(
            "rules", Path(MAIN_WORKTREE), runner=_resolver_runner(RESOLVER_RULES_OK)
        )
        self.assertEqual(
            resolved.entries,
            [
                {
                    "path": "docs/rules/alpha.md",
                    "local_path": f"{MAIN_WORKTREE}/docs/rules/alpha.md",
                },
                {
                    "path": "docs/rules/beta.md",
                    "local_path": f"{MAIN_WORKTREE}/docs/rules/beta.md",
                },
            ],
        )

    def test_entries_are_empty_for_zero_documents(self):
        resolved = project_documents.resolve(
            "rules", Path(MAIN_WORKTREE), runner=_resolver_runner(RESOLVER_RULES_EMPTY)
        )
        self.assertEqual(resolved.entries, [])

    def test_to_dict_exposes_key_series_and_count(self):
        resolved = project_documents.resolve(
            "specs", Path(MAIN_WORKTREE), runner=_resolver_runner(RESOLVER_SPECS_OK)
        )
        self.assertEqual(
            resolved.to_dict(),
            {
                "project_root": MAIN_WORKTREE,
                "category": "specs",
                "project_name": "sample-project",
                "key": "sample-project-specs",
                "series": "feature/doc-db",
                "count": 1,
                "paths": ["docs/specs/foo/design/DES-001_foo.md"],
            },
        )

    def test_resolve_rejects_unknown_category_before_running_git(self):
        runner = _resolver_runner(RESOLVER_RULES_OK)
        with self.assertRaises(project_documents.ProjectDocumentsError):
            project_documents.resolve("readme", Path(MAIN_WORKTREE), runner=runner)
        self.assertEqual(runner.calls, [])


class ExcludeDelegationTest(unittest.TestCase):
    """exclude が実効すること（resolver の CLI を temp プロジェクトに対して実行）。

    ここだけは resolver を実際に起動する。委譲先が exclude を適用することを、
    注入では確認できないためである。対象は tempdir に組み立てた project root と
    本ファイル内の `.doc_structure.yaml` fixture のみで、本リポジトリの設定・
    branch・worktree 構成には依存しない（git は注入した runner で置き換える）。
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        (self.root / ".doc_structure.yaml").write_text(DOC_STRUCTURE_YAML, encoding="utf-8")
        for rel in (
            "docs/rules/alpha.md",
            "docs/rules/nested/beta.md",
            "docs/specs/foo/design/DES-001_foo.md",
            "docs/specs/foo/plan/foo_plan.md",
        ):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(MARKDOWN_BODY, encoding="utf-8")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_rules_are_collected_recursively(self):
        paths = project_documents.resolve_paths("rules", self.root)
        self.assertEqual(sorted(paths), ["docs/rules/alpha.md", "docs/rules/nested/beta.md"])

    def test_excluded_directory_is_omitted(self):
        paths = project_documents.resolve_paths("specs", self.root)
        self.assertEqual(paths, ["docs/specs/foo/design/DES-001_foo.md"])
        self.assertNotIn("docs/specs/foo/plan/foo_plan.md", paths)

    def test_missing_config_raises_project_documents_error(self):
        (self.root / ".doc_structure.yaml").unlink()
        with self.assertRaises(project_documents.ProjectDocumentsError):
            project_documents.resolve_paths("rules", self.root)

    def test_resolve_combines_injected_git_with_real_resolver(self):
        resolved = project_documents.resolve(
            "specs", self.root, runner=_HybridRunner(self.root)
        )
        self.assertEqual(resolved.key, "sample-project-specs")
        self.assertEqual(resolved.series, "feature/doc-db")
        self.assertEqual(resolved.count, 1)


class _HybridRunner:
    """git だけを注入し、resolver は実際に実行する runner。"""

    def __init__(self, project_root):
        self._project_root = Path(project_root)

    def __call__(self, args, cwd, timeout):
        args = list(args)
        if args[0] == "git" and "--git-common-dir" in args:
            return 0, GIT_COMMON_DIR_ABSOLUTE, ""
        if args[0] == "git" and "--abbrev-ref" in args:
            return 0, BRANCH_OUTPUT, ""
        return project_documents.run_command(args, cwd, timeout)


if __name__ == "__main__":
    unittest.main()
