"""evaluator.md の契約テスト（DES-083 §7 の契約テスト対象）。

定義が持つ script の呼び方が、ラッパー（evaluator_*）と resolve_doc_structure.py の実際の引数と
一致すること、他の主体のラッパーが現れないこと、REQ-026 FNC-208 の項目・FNC-201 の 5 つの
メタ観点・disposition の 5 値・reason の書き方を持つこと、旧い形の記述が残っていないことを確かめる。
Claude Code の実 Agent 起動は unittest の検証対象にしない。
"""

import json
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "forge"
SCRIPT_DIR = PLUGIN_ROOT / "scripts" / "review"
EVALUATOR_PATH = PLUGIN_ROOT / "agents" / "evaluator.md"


class EvaluatorDefinitionContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = EVALUATOR_PATH.read_text(encoding="utf-8")

    def _documented_commands(self):
        """evaluator.md のコードブロックにある ``python3`` の行を、スクリプト名 → 行 の対応で返す。"""
        commands = {}
        for line in self.text.splitlines():
            if not line.startswith('python3 "${CLAUDE_PLUGIN_ROOT}/'):
                continue
            name = re.search(r"/([A-Za-z0-9_]+)\.py\"", line).group(1)
            self.assertNotIn(name, commands, f"{name} の呼び方が複数ある")
            commands[name] = line
        return commands

    def _materialize(self, line, project_root, review_id):
        """定義に書かれた呼び方のプレースホルダを実値に置き換え、引数の列にする。"""
        line = line.replace("<<'REASON'", "")
        line = line.replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_ROOT))
        line = line.replace("${CLAUDE_PROJECT_DIR}", str(project_root))
        line = line.replace("{review_id}", review_id).replace("{round_number}", "1")
        for placeholder, value in (
            ("{disposition}", "valid"),
            ("{severity}", "major"),
            ("{finding_id}", "1"),
            ("{confidence}", "confirmed"),
            ("{fix_confident}", "true"),
            ("{path}", "docs/specs/review/plan/tasks/TASK-005.json"),
        ):
            line = line.replace(placeholder, value)
        argv = shlex.split(line)
        self.assertEqual(argv[0], "python3")
        return [sys.executable, *argv[1:]]

    def _run_documented(self, commands, name, root, review_id, stdin=""):
        argv = self._materialize(commands[name], root, review_id)
        completed = subprocess.run(argv, input=stdin, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, f"{name}: {completed.stdout}{completed.stderr}")
        return json.loads(completed.stdout)

    def _publish_with_finding(self, root):
        target = root / "a.md"
        target.write_text("# a\n", encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "publish_request.py"), str(root), "--paths", str(target)],
            capture_output=True, text=True, check=True,
        )
        review_id = json.loads(completed.stdout)["review_id"]
        for script, extra, stdin in (
            ("reviewer_add_finding.py", ["--location", f"{target}:1"], "所見\n"),
            ("reviewer_finish.py", [], ""),
        ):
            subprocess.run(
                [sys.executable, str(SCRIPT_DIR / script), str(root), review_id, "1", *extra],
                input=stdin, capture_output=True, text=True, check=True,
            )
        return review_id

    # --- script の呼び方 ---

    def test_documented_script_calls_are_exactly_the_evaluator_scripts(self):
        self.assertEqual(
            set(self._documented_commands()),
            {
                "evaluator_resolve_inputs",
                "evaluator_add_evaluation",
                "evaluator_finish",
                "resolve_doc_structure",
            },
        )

    def test_documented_script_calls_match_the_actual_arguments(self):
        """定義に書かれた呼び方を実際に実行して、引数が実際の script と一致することを確かめる。"""
        commands = self._documented_commands()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            review_id = self._publish_with_finding(root)
            inputs = self._run_documented(commands, "evaluator_resolve_inputs", root, review_id)
            self.assertTrue(Path(inputs["request"]).is_file())
            self.assertTrue(Path(inputs["findings"]).is_file())
            self.assertEqual(
                self._run_documented(commands, "evaluator_add_evaluation", root, review_id, "根拠\n"), {}
            )
            self.assertEqual(self._run_documented(commands, "evaluator_finish", root, review_id), {})

        argv = self._materialize(commands["resolve_doc_structure"], REPO_ROOT, "unused")
        completed = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("doc_type", payload)

    def test_every_documented_option_exists_in_the_wrapper(self):
        """本文が挙げる ``--xxx`` が、ラッパーの実際の引数に存在すること（--new / --location を含む）。"""
        helps = ""
        for name in ("evaluator_resolve_inputs", "evaluator_add_evaluation", "evaluator_finish"):
            helps += subprocess.run(
                [sys.executable, str(SCRIPT_DIR / f"{name}.py"), "--help"],
                capture_output=True, text=True, check=True,
            ).stdout
        helps += subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "doc_structure" / "resolve_doc_structure.py"), "--help"],
            capture_output=True, text=True, check=True,
        ).stdout
        wrapper_section = self.text.split("## 入力の各項目の扱い")[0]
        documented = set(re.findall(r"`?(--[a-z][a-z-]*)", wrapper_section))
        self.assertIn("--new", documented)
        self.assertIn("--location", documented)
        for option in documented:
            self.assertIn(option, helps, f"{option} がラッパーに存在しない")

    def test_first_argument_is_the_project_dir_and_doc_structure_gets_project_root(self):
        commands = self._documented_commands()
        for name in ("evaluator_resolve_inputs", "evaluator_add_evaluation", "evaluator_finish"):
            self.assertRegex(commands[name], r'\.py" "\$\{CLAUDE_PROJECT_DIR\}" ', name)
        self.assertIn('--project-root "${CLAUDE_PROJECT_DIR}"', commands["resolve_doc_structure"])

    def test_does_not_mention_other_actors_wrappers(self):
        """他の主体のラッパー（reviewer_* と body_*）が現れない。"""
        self.assertNotRegex(self.text, r"reviewer_|body_")

    # --- 読む文書 ---

    def test_is_told_to_read_review_target_types(self):
        path = "${CLAUDE_PLUGIN_ROOT}/docs/criteria/review_target_types.md"
        self.assertTrue(
            any(path in line and "Read" in line for line in self.text.splitlines()),
            "review_target_types.md を Read する指示が無い",
        )

    # --- REQ-026 FNC-208 の項目 ---

    def test_has_every_item_of_fnc_208(self):
        for heading in (
            "## script の呼び方",
            "## 入力の各項目の扱い",
            "## 所見を起点に読む",
            "## target 種別ごとに読む文書",
            "## メタ観点",
            "## 評価として何を述べるか",
        ):
            self.assertIn(heading, self.text)
        self.assertRegex(self.text, r"`disposition` を判定する")
        self.assertIn("severity と確信度", self.text)

    def test_has_the_five_meta_perspectives(self):
        for phrase in (
            "本質を疑う",
            "対象の情報を疑う",
            "既存の決定の当否を外から判定しない",
            "まず最も強い解釈を試す",
            "逆から検証する",
        ):
            self.assertIn(phrase, self.text)
        self.assertIn("作り出さない", self.text)

    def test_has_the_five_dispositions(self):
        for value in ("invalid", "misunderstanding", "out_of_scope", "flawed_premise", "valid"):
            self.assertIn(f"`{value}`", self.text)

    def test_unreadable_location_and_unknown_location_are_distinguished(self):
        # 指す箇所が読めない所見だけを退ける材料にし、位置未確定の所見はそれを理由に退けない
        self.assertIn("`ファイルパス:行` で指された箇所が読めないとき", self.text)
        self.assertIn("`位置未確定` の所見は、指す箇所が元から無いだけで、箇所が読めないのではない", self.text)

    def test_explains_every_key_of_targets_and_that_diff_is_not_an_empty_diff(self):
        for key in ("`paths`", "`base_branch`", "`diff`"):
            self.assertIn(key, self.text)
        self.assertIn("差分が空であることを意味しない", self.text)

    def test_has_how_to_write_reason_for_each_scene(self):
        for scene in (
            "所見のとおり成立する",
            "所見を書き直す",
            "複数の所見を束ねる",
            "1 つの所見を複数の評価に分ける",
            "退ける",
        ):
            self.assertIn(scene, self.text)
        self.assertIn("確定させた問題を先に書き", self.text)

    def test_has_confidence_new_finding_and_finishing(self):
        for phrase in (
            "`confirmed`",
            "`inferred`",
            "`unverified`",
            "`fix_confident`",
            "`--new`",
            "`--location`",
            "すべての判断を確定させてから書き出す",
            "引かれていない",
            "書けない異常終了",
        ):
            self.assertIn(phrase, self.text)

    def test_carries_the_items_the_templates_used_to_carry(self):
        """戦略書「移し替え」のうち evaluator 側へ寄る項目。"""
        for phrase in (
            "重大度カタログの特定手順",  # severity の特定手順
            "失効した棄却理由",  # ADR の棄却理由の確認
            "ADR-NNN §N",
            "比例性チェックの適用条件",
            "`advisor` ツールを呼ばない",
            "最終形である",  # scope の読み方
            "`focus`",
        ):
            self.assertIn(phrase, self.text)

    # --- 旧い形の記述が残っていない ---

    def test_no_old_form_remains(self):
        """所見配列を依頼に載せる旧い形と、最終応答の JSON を返す旧い形。"""
        for phrase in (
            "所見の配列",
            "`index`",
            '"index"',
            "最終応答は、JSONオブジェクト",
            "最終応答の1文字目",
            "応答形式",
            "対応表",
        ):
            self.assertNotIn(phrase, self.text)
        self.assertNotRegex(self.text, r'"evaluations"\s*:')

    def test_frontmatter_is_kept(self):
        head = self.text.split("---")[1]
        self.assertRegex(head, r"(?m)^tools: \[Read, Grep, Glob, Bash\]$")
        self.assertRegex(head, r"(?m)^model: inherit$")
        self.assertRegex(head, r"(?m)^permissionMode: plan$")


if __name__ == "__main__":
    unittest.main()
