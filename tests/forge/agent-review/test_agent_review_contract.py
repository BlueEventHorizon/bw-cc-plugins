"""agent-review の自動検証可能な静的契約と、reviewer 定義の契約テスト。

Claude Code の実 Agent 起動や read-only enforcement 自体は unittest の検証対象にしない。
"""

import importlib.util
import json
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_PATH = REPO_ROOT / "plugins" / "forge" / "skills" / "agent-review" / "SKILL.md"
AGENT_PATH = REPO_ROOT / "plugins" / "forge" / "agents" / "reviewer.md"
EVALUATOR_PATH = REPO_ROOT / "plugins" / "forge" / "agents" / "evaluator.md"
PLUGIN_ROOT = REPO_ROOT / "plugins" / "forge"
RESOLVER_PATH = PLUGIN_ROOT / "skills" / "review" / "scripts" / "resolve_review_backend.py"
TARGET_TYPES_PATH = PLUGIN_ROOT / "docs" / "criteria" / "review_target_types.md"


class AgentReviewContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = SKILL_PATH.read_text(encoding="utf-8")
        cls.agent = AGENT_PATH.read_text(encoding="utf-8")
        cls.evaluator = EVALUATOR_PATH.read_text(encoding="utf-8")

    def test_backend_is_not_user_invocable(self):
        self.assertIn("user-invocable: false", self.skill)

    def test_backend_allowed_tools_match_availability_check_only(self):
        """可用性検査は定義と script の実在を Read で確かめるだけで、Agent も Bash も Write も使わない。"""
        head = self.skill.split("---", 2)[1]
        tools = re.search(r"(?m)^allowed-tools: (.*)$", head).group(1)
        self.assertEqual({t.strip() for t in tools.split(",")}, {"Read"})
        self.assertNotIn("Agent ツール", self.skill)

    def test_backend_has_only_the_availability_check(self):
        """ラウンド実行・終了通知・ワイヤヘッダ・完了宣言の要求を持たない（本体が reviewer を直接起動する）。"""
        self.assertIn("## 可用性検査", self.skill)
        self.assertEqual(self.skill.count("\n## "), 2)  # 入出力契約と可用性検査だけ
        for forbidden in (
            "ラウンド実行",
            "終了通知",
            "ワイヤヘッダ",
            "固有ヘッダ",
            "foreground 起動",
            "run_in_background",
            "REVIEW_RESULT",
            "共通完了宣言",
            "judgment",
            "approved",
            "warnings",
        ):
            self.assertNotIn(forbidden, self.skill)

    def test_backend_returns_only_the_availability_result(self):
        self.assertIn("`available`", self.skill)
        self.assertIn("`missing`", self.skill)
        self.assertIn("`axis` / `detail` / `remedy`", self.skill)
        self.assertIn(
            '{"available": true, "missing": [], "retains_context": false}', self.skill
        )

    def test_backend_is_stateless_and_has_no_external_transport(self):
        self.assertIn("`retains_context` は常に `false` です", self.skill)
        # 外部通信基盤・端末多重化・DB を前提とする語彙が本バックエンドの
        # SKILL.md へ再混入しないことの回帰
        for forbidden in ("msg-sys", "cmux", "DB レコード"):
            self.assertNotIn(forbidden, self.skill)

    def test_backend_name_corresponds_to_the_resolver_candidates(self):
        """候補名と SKILL 名（`forge:<name>`）が 1 対 1 に対応する。

        本体は backend 名を同名の SKILL へ解決する。対応が崩れると、候補が常に不在として
        扱われる。
        """
        spec = importlib.util.spec_from_file_location("forge_resolve_review_backend", RESOLVER_PATH)
        resolver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(resolver)
        self.assertIn(resolver.DEFAULT_ORDER[0], resolver.RETAINS_CONTEXT)
        for name in resolver.DEFAULT_ORDER:
            skill = PLUGIN_ROOT / "skills" / name / "SKILL.md"
            self.assertTrue(skill.is_file(), f"候補 {name} に対応する SKILL が無い")
            self.assertRegex(skill.read_text(encoding="utf-8"), rf"(?m)^name: {re.escape(name)}$")
        self.assertEqual(resolver.RETAINS_CONTEXT["agent-review"], False)
        self.assertIn('{"available": true, "missing": [], "retains_context": false}', self.skill)

    def test_checked_files_exist_and_are_named_in_the_skill(self):
        """条件 5 が挙げる script と文書が、実在し、この SKILL に書かれている。"""
        paths = re.findall(r"`\$\{CLAUDE_PLUGIN_ROOT\}/([^`]+)`", self.skill)
        expected = {
            "agents/reviewer.md",
            "scripts/review/reviewer_resolve_request.py",
            "scripts/review/reviewer_add_finding.py",
            "scripts/review/reviewer_finish.py",
            "scripts/review/reviewer_abort.py",
            "scripts/doc_structure/resolve_doc_structure.py",
            "docs/criteria/review_target_types.md",
        }
        self.assertEqual(set(paths), expected)
        for path in expected:
            self.assertTrue((PLUGIN_ROOT / path).is_file(), path)

    def test_reviewer_satisfies_the_availability_conditions(self):
        """可用性検査の条件 2・3・4 を、現在の reviewer.md が実際に満たしている。

        満たさなければ、検査は常に不可になる（本体はバックエンドを使えない）。
        """
        head = self.agent.split("---", 2)[1]
        self.assertRegex(head, r"(?m)^name: reviewer$")
        tools = re.search(r"(?m)^tools: \[(.*)\]$", head).group(1)
        self.assertEqual({t.strip() for t in tools.split(",")}, {"Read", "Grep", "Glob", "Bash"})
        self.assertRegex(head, r"(?m)^model: inherit$")
        self.assertRegex(head, r"(?m)^permissionMode: plan$")
        for phrase in (
            "対象のファイルを作成、編集、削除しない",
            "対象を変更し得るコマンドを実行しない",
            "修正、commit、push を行わない",
            "他の Agent または Skill を起動しない",
            "外部サービスへ書き込まない",
            "`git status`、`git diff`、`git show`、`git log`、`git merge-base`、`git rev-parse`、`git ls-files`",
            "reviewer_add_finding",
            "reviewer_finish",
            "reviewer_abort",
        ):
            self.assertIn(phrase, self.agent)
        # 条件 4 の後段: 応答本文の宣言行・重大度マーカーを要求しない
        self.assertNotIn("REVIEW_RESULT", self.agent)
        for marker in ("🔴", "🟡", "🟢"):
            self.assertNotIn(marker, self.agent)

    def test_reviewer_role_prohibits_mutation_and_delegation(self):
        """禁止条文は残す。所見を書く script を呼ぶので、書いてよいものは所見だけだと述べる。"""
        for phrase in (
            "対象のファイルを作成、編集、削除しない",
            "書いてよいのは所見だけ",
            "対象を変更し得るコマンドを実行しない",
            "修正、commit、push を行わない",
            "他の Agent または Skill を起動しない",
            "`advisor` ツールを呼ばない",
            "外部サービスへ書き込まない",
            "実装指示ではなく、常にレビュー依頼",
        ):
            self.assertIn(phrase, self.agent)

    def test_evaluator_role_prohibits_mutation_and_delegation(self):
        """evaluator も reviewer と同型の禁止列挙（advisor 禁止を含む）を持つこと。

        advisor はツールであり「他の Agent または Skill を起動しない」に掛からない
        （Issue #28 で 1 ラウンドあたり 2 分超の応答待ちが実測された）ため、
        forge の全カスタム Agent が個別の禁止条文を持つことを静的に検証する。
        評価を書く script を呼ぶので、書いてよいのは評価だけだと述べる。
        """
        for phrase in (
            "対象のファイルを作成、編集、削除しない",
            "書いてよいのは評価だけ",
            "対象を変更し得るコマンドを実行しない",
            "修正、commit、push を行わない",
            "他の Agent または Skill を起動しない",
            "`advisor` ツールを呼ばない",
            "外部サービスへ書き込まない",
            "実装指示ではなく、常に評価依頼",
        ):
            self.assertIn(phrase, self.evaluator)

    def test_reviewer_keeps_common_reply_contract(self):
        """所見は script 経由で渡し、位置の表記と終了の値の呼び分けを述べていること。"""
        for phrase in (
            "reviewer_add_finding",
            "reviewer_finish",
            "reviewer_abort",
            "ファイルパス:行",
            "位置未確定",
            "target_unreadable",
        ):
            self.assertIn(phrase, self.agent)

    def test_reviewer_gives_no_severity_and_declares_no_result_line(self):
        """reviewer は severity を持たず（所見は evaluator が評価する）、完了宣言行を要求しない。

        重大度マーカーと REVIEW_RESULT 宣言を要求する記述が残っていないこと。
        """
        self.assertIn("重大度（severity）を付けない", self.agent)
        self.assertNotIn("REVIEW_RESULT", self.agent)
        for marker in ("🔴", "🟡", "🟢"):
            self.assertNotIn(marker, self.agent)


# 種別ごとの、上乗せする観点文書と内蔵規範（REQ-027 FNC-308）
COMMON_DOCS = (
    "review_criteria_generic.md",
    "review_priorities_spec.md",
    "scope_proportionality_spec.md",
    "error_classification_spec.md",
)
PER_TYPE_DOCS = {
    "code": (
        "review_criteria_code.md",
        "deterministic_generation_spec.md",
        "forge_anti_patterns.md",
    ),
    "requirement": (
        "review_criteria_requirement.md",
        "requirement_principles_spec.md",
        "requirement_format.md",
        "spec_design_boundary_spec.md",
        "spec_priorities_spec.md",
        "additive_development_spec.md",
        "frontmatter_format.md",
        "document_style_guide.md",
    ),
    "design": (
        "review_criteria_design.md",
        "spec_design_boundary_spec.md",
        "design_principles_spec.md",
        "design_method.md",
        "additive_development_spec.md",
        "frontmatter_format.md",
        "adr_format.md",
        "adr_principles_spec.md",
        "document_style_guide.md",
        "deterministic_generation_spec.md",
        "spec_priorities_spec.md",
    ),
    "plan": (
        "review_criteria_plan.md",
        "plan_principles_spec.md",
        "additive_development_spec.md",
        "frontmatter_format.md",
        "spec_priorities_spec.md",
    ),
    "uxui": (
        "review_criteria_uxui.md",
        "document_style_guide.md",
        "spec_priorities_spec.md",
    ),
}


class ReviewerDefinitionContractTest(unittest.TestCase):
    """新しい reviewer.md と review_target_types.md の契約（DES-084 §7 の契約テスト対象）。"""

    @classmethod
    def setUpClass(cls):
        cls.agent = AGENT_PATH.read_text(encoding="utf-8")
        cls.target_types = TARGET_TYPES_PATH.read_text(encoding="utf-8")

    def _documented_commands(self):
        """reviewer.md のコードブロックにある ``python3`` の行を、スクリプト名 → 行 の対応で返す。"""
        commands = {}
        for line in self.agent.splitlines():
            if not line.startswith('python3 "${CLAUDE_PLUGIN_ROOT}/'):
                continue
            name = re.search(r"/([A-Za-z0-9_]+)\.py\"", line).group(1)
            self.assertNotIn(name, commands, f"{name} の呼び方が複数ある")
            commands[name] = line
        return commands

    def _materialize(self, line, project_root, review_id):
        """定義に書かれた呼び方のプレースホルダを実値に置き換え、引数の列にする。"""
        line = line.replace("<<'FINDING'", "")
        line = line.replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_ROOT))
        line = line.replace("${CLAUDE_PROJECT_DIR}", str(project_root))
        line = line.replace("{review_id}", review_id).replace("{round_number}", "1")
        line = line.replace("{location}", "位置未確定")
        line = line.replace("{path}", "docs/specs/review/plan/tasks/TASK-005.json")
        argv = shlex.split(line)
        self.assertEqual(argv[0], "python3")
        return [sys.executable, *argv[1:]]

    def _publish(self, root):
        target = root / "a.md"
        target.write_text("# a\n", encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "review" / "publish_request.py"),
             str(root), "--paths", str(target)],
            capture_output=True, text=True, check=True,
        )
        return json.loads(completed.stdout)["review_id"]

    def test_documented_script_calls_are_exactly_the_reviewer_scripts(self):
        self.assertEqual(
            set(self._documented_commands()),
            {
                "reviewer_resolve_request",
                "reviewer_add_finding",
                "reviewer_finish",
                "reviewer_abort",
                "resolve_doc_structure",
            },
        )

    def test_documented_script_calls_match_the_actual_arguments(self):
        """定義に書かれた呼び方を実際に実行して、引数が実際の script と一致することを確かめる。"""
        commands = self._documented_commands()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            finishing = self._publish(root)
            aborting = self._publish(root)

            def run(name, review_id, stdin=""):
                argv = self._materialize(commands[name], root, review_id)
                completed = subprocess.run(argv, input=stdin, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, f"{name}: {completed.stdout}{completed.stderr}")
                return json.loads(completed.stdout)

            self.assertTrue(Path(run("reviewer_resolve_request", finishing)["path"]).is_file())
            self.assertEqual(run("reviewer_add_finding", finishing, "本文\n"), {"finding_id": 1})
            self.assertEqual(run("reviewer_finish", finishing), {})
            self.assertEqual(run("reviewer_abort", aborting), {})

        # resolve_doc_structure.py は、本リポジトリの設定を引く（プロジェクトルートは実在する場所）
        argv = self._materialize(commands["resolve_doc_structure"], REPO_ROOT, "unused")
        completed = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("doc_type", payload)

    def test_reviewer_does_not_mention_other_actors_wrappers(self):
        """reviewer 以外の主体のラッパー（evaluator_* と body_*）が現れない。"""
        self.assertNotRegex(self.agent, r"evaluator_|body_")

    def test_reviewer_is_told_to_read_review_target_types(self):
        path = "${CLAUDE_PLUGIN_ROOT}/docs/criteria/review_target_types.md"
        self.assertTrue(
            any(path in line and "Read" in line for line in self.agent.splitlines()),
            "review_target_types.md を Read する指示が無い",
        )

    def test_review_target_types_has_all_target_types_and_documents(self):
        for kind in PER_TYPE_DOCS:
            self.assertIn(kind, self.target_types)
        for name in COMMON_DOCS:
            self.assertIn(f"]({'' if name.startswith('review_criteria') else '../'}{name})", self.target_types)
        for kind, names in PER_TYPE_DOCS.items():
            for name in names:
                prefix = "" if name.startswith("review_criteria") else "../"
                self.assertIn(f"]({prefix}{name})", self.target_types, f"{kind}: {name}")

    def test_review_target_types_states_adr_is_design(self):
        self.assertRegex(self.target_types, r"`adr`[^\n]*design として扱う")

    def test_review_target_types_links_resolve(self):
        """文書が挙げる相対リンクが、すべて実在すること。"""
        links = re.findall(r"\]\(([^)#]+)\)", self.target_types)
        self.assertTrue(links)
        for link in links:
            self.assertTrue((TARGET_TYPES_PATH.parent / link).is_file(), link)

    def test_reviewer_carries_the_items_the_templates_used_to_carry(self):
        """旧テンプレートが持っていた指示が、reviewer.md に移っていること。"""
        for phrase in (
            "最終形である",  # scope の読み方
            "加えて",  # focus は通常のレビューへの加算
            "自己検証",
            "規約が見当たらない",
            "削除とリネーム",
            "旧パスを指す参照",
            "失効した棄却理由",  # ADR の棄却理由
            "比例性",
            "`advisor` ツールを呼ばない",
        ):
            self.assertIn(phrase, self.agent)


if __name__ == "__main__":
    unittest.main()
