"""onboarding_block.py のテスト。

転記元は copy_block.md 専用ファイルで、その全文が転記範囲である（SKILL.md に置くと、
SKILL.md が全文コンテキストへ注入されるため転記済みのときに必ず二重読みになる）。
抽出・ハッシュ・差し込みが決定論的で冪等であること、および status から承認文言・次の
行動が一意に決まることを検証する。
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_SKILL_DIR = REPO_ROOT / "plugins" / "forge" / "skills" / "onboarding"
_SCRIPT_PATH = _SKILL_DIR / "scripts" / "onboarding_block.py"

_spec = importlib.util.spec_from_file_location("onboarding_block", _SCRIPT_PATH)
ob = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ob)


SAMPLE_SOURCE = """## forge 必読文書 [MANDATORY]

- `${CLAUDE_PLUGIN_ROOT}/docs/foo.md` — フー

### forge 内蔵文書

- `${CLAUDE_PLUGIN_ROOT}/docs/bar.md` — バー

## forge プロジェクト文書

- ルールの参照には `query-db-rules` SKILL を使う

## forge 重要規約 [MANDATORY]

- **Hoge しない**
"""


def _write_source(tmp: Path, text: str = SAMPLE_SOURCE) -> Path:
    p = tmp / "copy_block.md"
    p.write_text(text, encoding="utf-8")
    return p


class TestReadRegion(unittest.TestCase):
    def test_returns_whole_file_verbatim(self):
        region = ob.read_region(SAMPLE_SOURCE)
        self.assertTrue(region.startswith("## forge 必読文書 [MANDATORY]"))
        self.assertTrue(region.rstrip().endswith("- **Hoge しない**"))
        self.assertIn("### forge 内蔵文書", region)
        # プレースホルダを解決しない
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/docs/bar.md", region)

    def test_strips_only_surrounding_newlines(self):
        self.assertEqual(ob.read_region("\n\n本文\n\n"), "本文")

    def test_raises_when_source_is_empty(self):
        with self.assertRaises(ob.BlockError):
            ob.read_region("")

    def test_raises_when_source_is_whitespace_only(self):
        with self.assertRaises(ob.BlockError):
            ob.read_region("\n  \n\t\n")


class TestBodyIsVerbatim(unittest.TestCase):
    def test_body_does_not_rewrite_headings(self):
        """script は書き換えない。接頭辞は転記元が持つ。"""
        body = ob.render_body(ob.read_region(SAMPLE_SOURCE))
        self.assertIn("## forge 必読文書 [MANDATORY]", body)
        self.assertNotIn("## forge forge", body)

    def test_body_keeps_unprefixed_heading_as_is(self):
        text = SAMPLE_SOURCE.replace("## forge 必読文書 [MANDATORY]", "## 素の見出し")
        body = ob.render_body(ob.read_region(text))
        self.assertIn("## 素の見出し", body)


class TestHash(unittest.TestCase):
    def test_hash_is_stable(self):
        body = ob.render_body(ob.read_region(SAMPLE_SOURCE))
        self.assertEqual(ob.compute_hash(body), ob.compute_hash(body))

    def test_hash_changes_when_source_changes(self):
        a = ob.render_body(ob.read_region(SAMPLE_SOURCE))
        b = ob.render_body(ob.read_region(SAMPLE_SOURCE.replace("Hoge しない", "Fuga しない")))
        self.assertNotEqual(ob.compute_hash(a), ob.compute_hash(b))


class TestEvaluate(unittest.TestCase):
    def setUp(self):
        self.body = ob.render_body(ob.read_region(SAMPLE_SOURCE))
        self.digest = ob.compute_hash(self.body)
        self.block = ob.render_block(self.body)

    def test_absent_when_no_marker(self):
        self.assertEqual(ob.evaluate("# CLAUDE.md\n\n本文\n", self.block), "absent")

    def test_fresh_when_block_matches(self):
        self.assertEqual(ob.evaluate(f"# x\n\n{self.block}\n", self.block), "fresh")

    def test_stale_when_recorded_hash_differs(self):
        stale = self.block.replace(f"hash={self.digest}", "hash=deadbeef1234")
        self.assertEqual(ob.evaluate(f"# x\n\n{stale}\n", self.block), "stale")

    def test_stale_when_block_body_is_tampered_but_hash_left_intact(self):
        """記録されたハッシュだけを見ると見逃す、最も起こりやすいドリフト。"""
        tampered = self.block.replace("- **Hoge しない**", "- **Hoge してよい**")
        self.assertIn("hash=" + self.digest, tampered)
        self.assertEqual(ob.evaluate(f"# x\n\n{tampered}\n", self.block), "stale")

    def test_stale_when_a_line_is_deleted_from_block(self):
        tampered = self.block.replace("- **Hoge しない**\n", "")
        self.assertEqual(ob.evaluate(f"# x\n\n{tampered}\n", self.block), "stale")

    def test_fresh_is_unaffected_by_content_outside_the_block(self):
        host = f"# x\n\n## ホスト節\n\n本文\n\n{self.block}\n\n## 後ろの節\n\n本文\n"
        self.assertEqual(ob.evaluate(host, self.block), "fresh")

    def test_raises_when_markers_unpaired(self):
        broken = "# x\n\n<!-- FORGE_ONBOARDING_START hash=abc123 -->\n\n本文\n"
        with self.assertRaises(ob.BlockError):
            ob.evaluate(broken, self.block)

    def test_raises_when_markers_reversed(self):
        broken = f"# x\n\n{ob.MARKER_END}\n\n<!-- FORGE_ONBOARDING_START hash=abc123 -->\n"
        with self.assertRaises(ob.BlockError):
            ob.evaluate(broken, self.block)


class TestProposal(unittest.TestCase):
    """承認の提示は status から一意に決まる（AI に表を解釈させない）。"""

    def test_fresh_needs_no_approval(self):
        self.assertIsNone(ob.proposal_for("fresh", True))
        self.assertIsNone(ob.proposal_for("fresh", False))

    def test_mode_distinguishes_three_cases(self):
        self.assertEqual(ob.mode_for("absent", True), "append")
        self.assertEqual(ob.mode_for("absent", False), "create")
        self.assertEqual(ob.mode_for("stale", True), "update")

    def test_each_mode_has_distinct_wording(self):
        asks = {ob.proposal_for(s, e)["ask"] for s, e in (("absent", True), ("absent", False), ("stale", True))}
        self.assertEqual(len(asks), 3, "3 つの型で問いが重複している")

    def test_notice_is_quoted_and_names_the_plugin(self):
        """一行だけの問いでは唐突な書き込み要求に見えるため、引用符号と名乗りを持たせる。"""
        for status, exists in (("absent", True), ("absent", False), ("stale", True)):
            notice = ob.proposal_for(status, exists)["notice"]
            lines = notice.splitlines()
            self.assertTrue(lines, "notice が空である")
            for line in lines:
                self.assertTrue(line.startswith("> "), f"引用符号が無い行がある: {line!r}")
            self.assertIn(ob.PLUGIN_LABEL, notice)
            self.assertIn(ob.MARKETPLACE_NAME, notice)

    def test_notice_avoids_markdown_hazards(self):
        """`=` の罫線は直前の行を setext 見出しに化けさせる。GFM アラートは色が付かず雑音になる。"""
        for status, exists in (("absent", True), ("absent", False), ("stale", True)):
            notice = ob.proposal_for(status, exists)["notice"]
            self.assertNotIn("===", notice)
            self.assertNotIn("[!", notice)

    def test_notice_states_the_benefit_when_proposing_a_new_block(self):
        """「なんだこれは」に答えるのは、内部事情ではなく利用者の利得である。"""
        for status, exists in (("absent", True), ("absent", False)):
            self.assertIn(ob.BENEFIT, ob.proposal_for(status, exists)["notice"])

    def test_options_offer_accept_and_decline(self):
        for status, exists in (("absent", True), ("absent", False), ("stale", True)):
            options = ob.proposal_for(status, exists)["options"]
            self.assertEqual(len(options), 2)
            for opt in options:
                self.assertTrue(opt["label"])
                self.assertTrue(opt["description"])

    def test_wording_hides_internal_details(self):
        """ハッシュ・マーカー名・引数を提示に出さない。"""
        for status, exists in (("absent", True), ("absent", False), ("stale", True)):
            p = ob.proposal_for(status, exists)
            texts = [p["ask"], p["notice"]] + [o["description"] for o in p["options"]]
            for text in texts:
                for leak in ("hash", "FORGE_ONBOARDING", "--write", "copy_block"):
                    self.assertNotIn(leak, text)


class TestUnsubstitutedPlaceholder(unittest.TestCase):
    """置換されなかったプレースホルダを、黙って別の場所へ書く経路にしない。"""

    def test_detects_unsubstituted(self):
        self.assertTrue(ob.unsubstituted_placeholder("${CLAUDE_PROJECT_DIR}/CLAUDE.md"))

    def test_accepts_real_paths(self):
        self.assertFalse(ob.unsubstituted_placeholder("/tmp/foo/CLAUDE.md"))
        self.assertFalse(ob.unsubstituted_placeholder("CLAUDE.md"))


class TestSplice(unittest.TestCase):
    def setUp(self):
        self.block = ob.render_block(ob.render_body(ob.read_region(SAMPLE_SOURCE)))

    def test_appends_when_absent_and_keeps_existing_content(self):
        out = ob.splice("# CLAUDE.md\n\n## 既存節\n\n本文\n", self.block)
        self.assertIn("## 既存節", out)
        self.assertIn("本文", out)
        self.assertTrue(out.rstrip().endswith(ob.MARKER_END))

    def test_replaces_only_the_block_region(self):
        old = ob.render_block("> 古い chrome\n\n## forge 必読文書 [MANDATORY]\n\n- 古い")
        original = f"# CLAUDE.md\n\n前の本文\n\n{old}\n\n後の本文\n"
        out = ob.splice(original, self.block)
        self.assertIn("前の本文", out)
        self.assertIn("後の本文", out)
        self.assertNotIn("古い chrome", out)
        self.assertIn("forge プロジェクト文書", out)


class TestCli(unittest.TestCase):
    def _run(self, tmp: Path, *args: str, text: str = SAMPLE_SOURCE):
        source = _write_source(tmp, text)
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), "--source", str(source), *args],
            capture_output=True,
            text=True,
        )
        return proc, json.loads(proc.stdout) if proc.stdout.strip() else {}

    def test_check_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            target = tmp / "CLAUDE.md"
            proc, out = self._run(tmp, "--check", "--target", str(target))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(out["status"], "absent")
            self.assertFalse(out["target_exists"])
            self.assertFalse(target.exists())

    def test_check_emits_proposal_and_runnable_command_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            target = tmp / "CLAUDE.md"
            _, out = self._run(tmp, "--check", "--target", str(target))
            expected = ob.proposal_for("absent", False)
            self.assertEqual(out["ask"], expected["ask"])
            self.assertEqual(out["notice"], expected["notice"])
            self.assertEqual(out["options"], expected["options"])
            self.assertIn("--write", out["on_approve"])
            self.assertIn(str(target), out["on_approve"])

    def test_check_emits_no_ask_when_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            target = tmp / "CLAUDE.md"
            self._run(tmp, "--write", "--target", str(target))
            _, out = self._run(tmp, "--check", "--target", str(target))
            self.assertEqual(out["status"], "fresh")
            self.assertEqual(out["action"], "none")
            for key in ("ask", "notice", "options", "on_approve"):
                self.assertNotIn(key, out)

    def test_check_returns_block_body_when_proposing(self):
        """転記はそれを実行したセッションには効かないため、規範本文を返す。"""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            target = tmp / "CLAUDE.md"
            _, out = self._run(tmp, "--check", "--target", str(target))
            self.assertEqual(out["action"], "propose")
            self.assertIn("- **Hoge しない**", out["block_body"])
            self.assertIn("## forge 必読文書 [MANDATORY]", out["block_body"])
            # chrome（ブロックの定型注記）は規範ではないので載せない
            self.assertNotIn("手で編集しない", out["block_body"])

    def test_check_omits_block_body_when_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            target = tmp / "CLAUDE.md"
            self._run(tmp, "--write", "--target", str(target))
            _, out = self._run(tmp, "--check", "--target", str(target))
            self.assertNotIn("block_body", out)

    def test_write_self_verifies(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            target = tmp / "CLAUDE.md"
            _, out = self._run(tmp, "--write", "--target", str(target))
            self.assertEqual(out["written_status"], "fresh")

    def test_unsubstituted_target_aborts_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            proc, out = self._run(tmp, "--write", "--target", "${CLAUDE_PROJECT_DIR}/CLAUDE.md")
            self.assertEqual(proc.returncode, 3)
            self.assertIn("error", out)
            self.assertFalse(any(tmp.glob("**/CLAUDE.md")))

    def test_check_emits_stale_ask(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            target = tmp / "CLAUDE.md"
            self._run(tmp, "--write", "--target", str(target))
            changed = SAMPLE_SOURCE.replace("Hoge しない", "Fuga しない")
            _, out = self._run(tmp, "--check", "--target", str(target), text=changed)
            self.assertEqual(out["status"], "stale")
            self.assertEqual(out["ask"], ob.proposal_for("stale", True)["ask"])
            self.assertIn("更新", out["notice"])

    def test_write_creates_file_when_missing(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            target = tmp / "CLAUDE.md"
            proc, out = self._run(tmp, "--write", "--target", str(target))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(out["action"], "created")
            self.assertIn("--check", out["verify"])
            text = target.read_text(encoding="utf-8")
            self.assertIn("FORGE_ONBOARDING_START", text)
            self.assertIn("## forge 重要規約 [MANDATORY]", text)

    def test_write_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            target = tmp / "CLAUDE.md"
            target.write_text("# CLAUDE.md\n\n## 既存\n\n本文\n", encoding="utf-8")
            self._run(tmp, "--write", "--target", str(target))
            first = target.read_text(encoding="utf-8")
            proc, out = self._run(tmp, "--write", "--target", str(target))
            self.assertEqual(out["status"], "fresh")
            self.assertEqual(out["action"], "none")
            self.assertEqual(first, target.read_text(encoding="utf-8"))

    def test_write_updates_when_source_changed(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            target = tmp / "CLAUDE.md"
            self._run(tmp, "--write", "--target", str(target))
            changed = SAMPLE_SOURCE.replace("Hoge しない", "Fuga しない")
            _, out = self._run(tmp, "--write", "--target", str(target), text=changed)
            self.assertEqual(out["status"], "stale")
            self.assertEqual(out["action"], "updated")
            text = target.read_text(encoding="utf-8")
            self.assertIn("Fuga しない", text)
            self.assertNotIn("Hoge しない", text)

    def test_broken_markers_abort_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            target = tmp / "CLAUDE.md"
            broken = "# CLAUDE.md\n\n<!-- FORGE_ONBOARDING_START hash=abc123 -->\n\n本文\n"
            target.write_text(broken, encoding="utf-8")
            proc, out = self._run(tmp, "--write", "--target", str(target))
            self.assertEqual(proc.returncode, 3)
            self.assertIn("error", out)
            self.assertEqual(target.read_text(encoding="utf-8"), broken)

    def test_missing_source_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            proc = subprocess.run(
                [sys.executable, str(_SCRIPT_PATH), "--source", str(tmp / "nope.md"), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("error", json.loads(proc.stdout))


class TestRealCopyBlock(unittest.TestCase):
    """配布物の実体が転記可能な状態であることを検証する。"""

    def setUp(self):
        self.region = ob.read_region(ob.SOURCE.read_text(encoding="utf-8"))

    def test_source_file_is_the_dedicated_copy_block(self):
        self.assertEqual(ob.SOURCE.name, "copy_block.md")
        self.assertTrue(ob.SOURCE.is_file())

    def test_real_copy_region_is_not_empty(self):
        self.assertTrue(self.region.strip())

    def test_real_copy_region_headings_are_forge_prefixed(self):
        """転記先での見出し重複を防ぐ規約。script は接頭辞を付けないので、ここで強制する。"""
        h2 = [ln for ln in self.region.splitlines() if ln.startswith("## ")]
        self.assertTrue(h2, "転記範囲に ## 見出しが無い")
        for line in h2:
            self.assertTrue(
                line.startswith("## forge "),
                f"転記範囲の ## 見出しは 'forge ' で始めること: {line!r}",
            )

    def test_real_copy_region_has_no_destination_markers(self):
        """転記先マーカーが混入するとブロック検出が壊れる。"""
        self.assertNotIn("FORGE_ONBOARDING_START", self.region)
        self.assertNotIn(ob.MARKER_END, self.region)

    def test_skill_md_does_not_duplicate_the_copy_block(self):
        """SKILL.md は起動時に全文注入される。転記範囲を持たせると必ず二重読みになる。"""
        skill = (_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        for line in self.region.splitlines():
            body = line.strip()
            if len(body) < 20:
                continue
            self.assertNotIn(body, skill, f"転記範囲の記述が SKILL.md に複製されている: {body[:40]!r}")


if __name__ == "__main__":
    unittest.main()
