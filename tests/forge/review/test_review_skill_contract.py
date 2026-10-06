"""review 本体（SKILL.md）の契約テスト（DES-084 §7・DES-083 §7 の契約テスト対象）。

本体の定義が、(1) `disposition` などの値にそのまま従わず内容を吟味してから修正・ドロップ・終端を決める
指示を持つこと、(2) 位置引数（種別）を廃止してエラー終了する旨を持ち、引数解釈結果の定型出力に位置引数が
無いこと、(3) 旧い script の呼び出しが（`--secrets` の節を除き）残っていないこと、(4) 新しい script の
呼び方が実際の引数と一致すること、(5) 終端のすべての経路が 1 つの出口を通って `delete_review.py` を
呼ぶことを確かめる。Claude Code の実 Agent 起動は unittest の検証対象にしない。

置き場: `plugins/forge/skills/review/` のテストは `tests/forge/review/` に置く規約（テストディレクトリ名は
スキルディレクトリ名と一致させる）に従う。reviewer.md / evaluator.md の契約テスト（`tests/forge/agent-review/`）は
Agent の定義を対象にしており、本テストは review スキルの定義を対象にする。
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
SKILL_PATH = PLUGIN_ROOT / "skills" / "review" / "SKILL.md"
SCRIPT_DIR = PLUGIN_ROOT / "scripts" / "review"

# 削除済みの旧い受け渡しの script。本体の SKILL.md が名前を挙げていてはならない（`--secrets` の節を除く。
# その節は Issue #62 の範囲として変更しない）
OLD_SCRIPTS = (
    "build_review_request.py",
    "parse_findings.py",
    "parse_evaluation.py",
    "combine_findings_and_evaluations.py",
)

# 本体が本書の仕組みで呼ぶ script（`${CLAUDE_PLUGIN_ROOT}` 起点のもの）
EXPECTED_PLUGIN_ROOT_SCRIPTS = {
    "resolve_review_backend",
    "publish_request",
    "body_resolve_findings",
    "body_resolve_evaluations",
    "count_actionable",
    "advance_round",
    "delete_review",
}

POSITIONAL_KINDS = ("code", "design", "requirement", "plan", "uxui")


def _between(text, start, end=None):
    """``start`` を含む行から、``end`` を含む行の手前までを返す。"""
    begin = text.index(start)
    if end is None:
        return text[begin:]
    return text[begin : text.index(end, begin)]


def _strip_secrets_sections(text):
    """`--secrets` の節（独立起動の説明・Step 2.3・Step 6 の例外）を取り除く。"""
    stripped = text.replace(_between(text, "**`--secrets`（独立起動）**", "引数解釈は AI が"), "")
    stripped = stripped.replace(_between(stripped, "#### 2.3 ", "### Step 3:"), "")
    stripped = stripped.replace(_between(stripped, "**`--secrets` の例外", "`--secrets` 以外では"), "")
    return stripped


class ReviewSkillContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SKILL_PATH.read_text(encoding="utf-8")
        cls.without_secrets = _strip_secrets_sections(cls.text)
        cls.step7 = _between(cls.text, "### Step 7: ", "### Step 7.5:")
        cls.step8 = _between(cls.text, "### Step 8: ", "## エラーフロー一覧")

    # --- 吟味（DES-083 §7 の契約テスト） ---

    def test_does_not_follow_values_as_is_but_examines_the_content(self):
        for phrase in (
            "`disposition`・`confidence`・`fix_confident` などの値にそのまま従って、修正・ドロップ・終端を決めない",
            "自分で理解し、調査し、考える",
            "吟味",
            "script は行き先を決めない",
        ):
            self.assertIn(phrase, self.step7)

    def test_flawed_premise_is_always_presented(self):
        self.assertRegex(
            self.step7,
            r"`flawed_premise` は、`confidence` / `fix_confident` の値に関わらず自動修正の対象にしない。常に提示する",
        )

    def test_terminal_judgement_uses_count_as_material_not_as_the_decision(self):
        self.assertIn("材料であって、判断そのものではない", self.step7)
        self.assertIn("本体が単独で打ち切らない", self.step7)

    def test_unfixable_open_findings_are_confirmed_with_the_user_before_ending(self):
        """対応できるものが無い（ドロップ・位置未確定のみ）ときも、本体が単独で終えない（REQ-029 FNC-318）。"""
        start = self.step7.index("**対応できるものが無い**")
        bullet = self.step7[start:self.step7.index("- **残りが軽微**", start)]
        self.assertIn("AskUserQuestion", bullet)
        self.assertIn("本体が単独で打ち切らない", bullet)
        self.assertIn("終えると決まれば Step 8", bullet)

    # --- 位置引数の廃止（DES-084 §7・戦略書 決定事項 4） ---

    def test_positional_kind_is_abolished_with_an_error_exit(self):
        self.assertIn("位置引数（種別）は廃止した", self.text)
        self.assertIn("廃止を明示してエラー終了する", self.text)
        self.assertIn("受け付けて無視しない", self.text)
        # 受け付けて無視する互換を作らない（エラー終了だけ）
        self.assertIn("依頼を公開せずエラー終了", _between(self.text, "## エラーフロー一覧"))

    def test_no_positional_kind_in_syntax_hint_or_axis_table(self):
        head = self.text.split("---", 2)[1]
        hint = re.search(r"(?m)^argument-hint: (.*)$", head).group(1)
        for kind in POSITIONAL_KINDS:
            self.assertNotIn(kind, hint)
        syntax = _between(self.text, "## コマンド構文", "**位置引数（種別）は廃止した**")
        self.assertNotIn("<種別>", syntax)
        self.assertNotRegex(syntax, r"\|\s*種別")

    def test_argument_interpretation_output_has_no_positional_kind(self):
        block = _between(self.text, "### 引数解釈結果の定型出力", "## 依頼モード")
        for kind in POSITIONAL_KINDS:
            self.assertNotRegex(block, rf"\b{kind}\b")
        self.assertNotIn("種別", block)
        self.assertNotIn("パターン", block)

    def test_no_pattern_or_template_selection_remains(self):
        self.assertNotIn("パターン", self.without_secrets)
        self.assertNotIn("_review_request_template", self.without_secrets)
        self.assertNotIn("templates/", self.without_secrets)

    # --- 削除済みの旧 script への言及が残らないこと ---

    def test_old_scripts_are_not_mentioned_except_in_secrets_sections(self):
        for name in OLD_SCRIPTS:
            self.assertNotIn(name, self.without_secrets)
        # 結合した配列を渡す前提（`index` で所見と評価を 1 対 1 に結合する形）も残らない
        self.assertNotIn("`combined`", self.without_secrets)

    def test_no_backend_round_delegation_remains(self):
        for phrase in ("バックエンドへラウンドの実行を委譲", "終了通知モード", "ラウンド実行"):
            self.assertNotIn(phrase, self.without_secrets)

    # --- Agent の起動 ---

    def test_launches_reviewer_and_evaluator_with_the_two_values_only(self):
        self.assertIn("`forge:reviewer`", self.text)
        self.assertIn("`forge:evaluator`", self.text)
        self.assertEqual(self.text.count("**prompt に渡すのは `review_id` と `round_number` だけ**"), 2)

    def test_allowed_tools_keep_agent_and_skill(self):
        head = self.text.split("---", 2)[1]
        tools = re.search(r"(?m)^allowed-tools: (.*)$", head).group(1)
        names = {t.strip() for t in tools.split(",")}
        self.assertLessEqual({"Agent", "Skill", "Read", "Write", "Bash", "AskUserQuestion"}, names)

    def test_retains_context_comes_from_the_backend_resolution_script(self):
        step15 = _between(self.text, "### Step 1.5:", "### Step 2:")
        self.assertIn("`retains_context`（候補名から真偽値への対応）", step15)
        self.assertIn("`true` が得られたら、依頼を公開せず", step15)

    # --- 終端 ---

    def test_all_terminal_routes_go_through_one_exit_that_deletes(self):
        for route in ("approved", "halted_with_open_findings", "failure", "interrupted"):
            self.assertIn(f"`{route}`", self.step8)
        self.assertIn("レビューを終える経路はすべてこの Step を通す", self.step8)
        self.assertEqual(self.text.count("scripts/review/delete_review.py"), 1)
        self.assertIn("scripts/review/delete_review.py", self.step8)
        self.assertIn("報告を出力してから、保持物を削除する", self.step8)

    def test_next_round_is_only_reached_from_step_7_and_does_not_rebuild_the_request(self):
        self.assertEqual(self.text.count("scripts/review/advance_round.py"), 1)
        self.assertIn("scripts/review/advance_round.py", self.step7)
        self.assertIn("**依頼は変えない**", self.step7)
        self.assertIn("次のラウンド番号が 5 以上になる場合", self.step7)

    # --- script の呼び方 ---

    def _documented_commands(self):
        """``${CLAUDE_PLUGIN_ROOT}`` 起点の ``python3`` の呼び方を、script 名 → 1 行 の対応で返す。"""
        commands = {}
        lines = self.text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('python3 "${CLAUDE_PLUGIN_ROOT}/'):
                joined = line
                while joined.endswith("\\"):
                    i += 1
                    joined = joined[:-1].rstrip() + " " + lines[i].strip()
                name = re.search(r"/([A-Za-z0-9_]+)\.py\"", joined).group(1)
                self.assertNotIn(name, commands, f"{name} の呼び方が複数ある")
                commands[name] = joined
            i += 1
        return commands

    def _materialize(self, line, project_root, review_id, round_number, extra):
        line = re.sub(r"\[--backend <name>\]\s*", "", line)
        line = line.replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_ROOT))
        line = line.replace("${CLAUDE_PROJECT_DIR}", str(project_root))
        line = line.replace("{review_id}", review_id).replace("{round_number}", str(round_number))
        for placeholder, value in extra.items():
            line = line.replace(placeholder, value)
        argv = shlex.split(line)
        self.assertEqual(argv[0], "python3")
        return [sys.executable, *argv[1:]]

    def test_documented_plugin_root_scripts_are_exactly_the_expected_ones(self):
        self.assertEqual(set(self._documented_commands()), EXPECTED_PLUGIN_ROOT_SCRIPTS)

    def test_documented_script_calls_match_the_actual_arguments(self):
        """定義に書かれた呼び方を実際に実行して、引数が実際の script と一致することを確かめる。"""
        commands = self._documented_commands()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "a.md"
            target.write_text("# a\n", encoding="utf-8")
            reference = root / "rule.md"
            reference.write_text("# rule\n", encoding="utf-8")
            focus = root / "focus.txt"
            focus.write_text("重点観点\n複数行\n", encoding="utf-8")
            scope = root / "scope.txt"
            scope.write_text("到達目標\n", encoding="utf-8")

            def run(name, review_id="unused", round_number=1, extra=None, expect=0):
                argv = self._materialize(commands[name], root, review_id, round_number, extra or {})
                completed = subprocess.run(argv, capture_output=True, text=True)
                self.assertEqual(completed.returncode, expect, f"{name}: {completed.stdout}{completed.stderr}")
                return json.loads(completed.stdout)

            backend = run("resolve_review_backend")
            self.assertEqual(backend["status"], "success")
            self.assertEqual(set(backend["retains_context"]), set(backend["order"]))

            published = run(
                "publish_request",
                extra={
                    "{target_path}": str(target),
                    "{base_branch}": "main",
                    "{reference_path}": str(reference),
                    "{focus_file}": str(focus),
                    "{scope_file}": str(scope),
                },
            )
            review_id = published["review_id"]
            self.assertEqual(published["round_number"], 1)
            # 受け渡しファイルは成功時に script が削除する
            self.assertFalse(focus.exists())
            self.assertFalse(scope.exists())

            # 所見・評価が正常に書き終えられていない間は、読み出しが失敗して errors を返す
            for name in ("body_resolve_findings", "body_resolve_evaluations"):
                self.assertIn("errors", run(name, review_id, expect=1))

            def call(script, *args, stdin=""):
                completed = subprocess.run(
                    [sys.executable, str(SCRIPT_DIR / script), str(root), review_id, "1", *args],
                    input=stdin, capture_output=True, text=True, check=True,
                )
                return json.loads(completed.stdout)

            call("reviewer_add_finding.py", "--location", f"{target}:1", stdin="所見\n")
            call("reviewer_finish.py")
            call(
                "evaluator_add_evaluation.py", "--disposition", "valid", "--severity", "major",
                "--findings", "1", "--confidence", "confirmed", "--fix-confident", "true", stdin="根拠\n",
            )
            call("evaluator_finish.py")

            for name in ("body_resolve_findings", "body_resolve_evaluations"):
                self.assertTrue(Path(run(name, review_id)["path"]).is_file())
            self.assertEqual(run("count_actionable", review_id), {"actionable": 1})
            self.assertEqual(run("advance_round", review_id), {"round_number": 2})
            self.assertTrue((root / ".temp" / "review" / review_id / "2").is_dir())
            self.assertEqual(run("delete_review", review_id), {})
            self.assertFalse((root / ".temp" / "review" / review_id).exists())

    def test_publish_request_documents_every_option_it_has(self):
        """本文が挙げる ``--xxx`` が publish_request.py の実際の引数に存在し、逆も欠けていない。"""
        helps = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "publish_request.py"), "--help"],
            capture_output=True, text=True, check=True,
        ).stdout
        step4 = _between(self.text, "### Step 4:", "### Step 5:")
        for option in ("--paths", "--base-branch", "--diff", "--references", "--focus-file", "--scope-file"):
            self.assertIn(option, helps)
            self.assertIn(f"`{option}", step4)

    def test_split_by_location_call_matches_the_actual_arguments(self):
        """位置の振り分けは script に任せ、所見の結果のパスを渡す（JSON を引数へ埋め込まない）。"""
        step7 = self.step7
        match = re.search(
            r'(?m)^\s*(python3 "\$\{CLAUDE_SKILL_DIR\}/scripts/split_by_location\.py" .*)$', step7
        )
        self.assertIsNotNone(match, "split_by_location.py の呼び方が Step 7 に無い")
        self.assertNotIn("--findings-json", self.text)
        with tempfile.TemporaryDirectory() as tmp:
            findings = Path(tmp) / "review_result.json"
            findings.write_text(
                json.dumps(
                    {
                        "findings": [
                            {"finding_id": 1, "location": ["/abs/a.md:1"], "body": "x"},
                            {"finding_id": 2, "location": ["位置未確定"], "body": "y"},
                        ],
                        "exit": "0",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            line = match.group(1).replace(
                "${CLAUDE_SKILL_DIR}", str(PLUGIN_ROOT / "skills" / "review")
            ).replace("{findings_path}", str(findings))
            argv = shlex.split(line)
            completed = subprocess.run(
                [sys.executable, *argv[1:]], capture_output=True, text=True
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual([f["finding_id"] for f in payload["located"]], [1])
        self.assertEqual([f["finding_id"] for f in payload["unlocated"]], [2])

    # --- 旧い形の記述が残っていない ---

    def test_focus_and_scope_are_not_limited_by_the_old_request_builder(self):
        for phrase in ("単一行に要約して渡す", "プロトコル注入", "構造行拒否", "見出し行・コードフェンス行・共通契約行"):
            self.assertNotIn(phrase, self.text)


if __name__ == "__main__":
    unittest.main()
