"""onboarding_block.py のテスト。

転記範囲はマーカーで宣言され、見出し名には依存しない（見出し依存だと節の改名やタグ追加で
転記範囲が黙って変わる）。抽出・ハッシュ・差し込みが決定論的で冪等であることを検証する。
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = REPO_ROOT / "plugins" / "forge" / "skills" / "onboarding" / "scripts" / "onboarding_block.py"

_spec = importlib.util.spec_from_file_location("onboarding_block", _SCRIPT_PATH)
ob = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ob)


SAMPLE_SKILL = """---
name: onboarding
description: |
  ダミー
allowed-tools: Read, Bash
---

# onboarding

マーカーより前は転記されない。

<!-- FORGE_ONBOARDING_COPY_START -->

## forge 必読文書 [MANDATORY]

- `${CLAUDE_PLUGIN_ROOT}/docs/foo.md` — フー

### forge 内蔵文書

- `${CLAUDE_PLUGIN_ROOT}/docs/bar.md` — バー

## プロジェクト文書

- ルールの参照には `query-db-rules` SKILL を使う

## 重要規約 [MANDATORY]

- **Hoge しない**

<!-- FORGE_ONBOARDING_COPY_END -->

## 実行フロー

ここは転記対象ではない。
"""


def _write_skill(tmp: Path, text: str = SAMPLE_SKILL) -> Path:
    p = tmp / "SKILL.md"
    p.write_text(text, encoding="utf-8")
    return p


class TestExtract(unittest.TestCase):
    def test_extracts_marked_region_verbatim(self):
        region = ob.extract_copy_region(SAMPLE_SKILL)
        self.assertTrue(region.startswith("## forge 必読文書 [MANDATORY]"))
        self.assertTrue(region.rstrip().endswith("- **Hoge しない**"))
        self.assertIn("### forge 内蔵文書", region)
        # プレースホルダを解決しない
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/docs/bar.md", region)

    def test_excludes_everything_outside_markers(self):
        region = ob.extract_copy_region(SAMPLE_SKILL)
        self.assertNotIn("実行フロー", region)
        self.assertNotIn("ここは転記対象ではない", region)
        self.assertNotIn("マーカーより前は転記されない", region)
        self.assertNotIn("FORGE_ONBOARDING_COPY", region)

    def test_does_not_depend_on_heading_names(self):
        """囲みの内側は見出しを自由に改名・追加できる。"""
        text = SAMPLE_SKILL.replace("## forge 必読文書 [MANDATORY]", "## 全然違う名前").replace(
            "- **Hoge しない**", "- **Hoge しない**\n\n## 追加した節\n\n- 追加"
        )
        region = ob.extract_copy_region(text)
        self.assertIn("## 全然違う名前", region)
        self.assertIn("## 追加した節", region)

    def test_raises_when_markers_missing(self):
        with self.assertRaises(ob.BlockError):
            ob.extract_copy_region("# x\n\n## 必読文書\n\n本文\n")

    def test_raises_when_markers_unpaired(self):
        with self.assertRaises(ob.BlockError):
            ob.extract_copy_region(f"# x\n\n{ob.COPY_START}\n\n本文\n")

    def test_raises_when_markers_reversed(self):
        with self.assertRaises(ob.BlockError):
            ob.extract_copy_region(f"# x\n\n{ob.COPY_END}\n\n本文\n\n{ob.COPY_START}\n")

    def test_raises_when_region_is_empty(self):
        with self.assertRaises(ob.BlockError):
            ob.extract_copy_region(f"# x\n\n{ob.COPY_START}\n\n\n{ob.COPY_END}\n")


class TestBodyIsVerbatim(unittest.TestCase):
    def test_body_does_not_rewrite_headings(self):
        """script は書き換えない。接頭辞は転記元が持つ。"""
        body = ob.render_body(ob.extract_copy_region(SAMPLE_SKILL))
        self.assertIn("## forge 必読文書 [MANDATORY]", body)
        self.assertNotIn("## forge forge", body)

    def test_body_keeps_unprefixed_heading_as_is(self):
        text = SAMPLE_SKILL.replace("## forge 必読文書 [MANDATORY]", "## 素の見出し")
        body = ob.render_body(ob.extract_copy_region(text))
        self.assertIn("## 素の見出し", body)


class TestHash(unittest.TestCase):
    def test_hash_is_stable(self):
        body = ob.render_body(ob.extract_copy_region(SAMPLE_SKILL))
        self.assertEqual(ob.compute_hash(body), ob.compute_hash(body))

    def test_hash_changes_when_source_changes(self):
        a = ob.render_body(ob.extract_copy_region(SAMPLE_SKILL))
        b = ob.render_body(ob.extract_copy_region(SAMPLE_SKILL.replace("Hoge しない", "Fuga しない")))
        self.assertNotEqual(ob.compute_hash(a), ob.compute_hash(b))


class TestEvaluate(unittest.TestCase):
    def setUp(self):
        self.body = ob.render_body(ob.extract_copy_region(SAMPLE_SKILL))
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


class TestHashScope(unittest.TestCase):
    """ハッシュは転記範囲（+ chrome）だけに依存する。"""

    def test_hash_ignores_changes_outside_copy_markers(self):
        outside = SAMPLE_SKILL.replace("## 実行フロー", "## 実行フロー（書き換えた）")
        self.assertNotEqual(outside, SAMPLE_SKILL)
        a = ob.compute_hash(ob.render_body(ob.extract_copy_region(SAMPLE_SKILL)))
        b = ob.compute_hash(ob.render_body(ob.extract_copy_region(outside)))
        self.assertEqual(a, b)

    def test_hash_reflects_changes_inside_copy_markers(self):
        inside = SAMPLE_SKILL.replace("- **Hoge しない**", "- **Fuga しない**")
        a = ob.compute_hash(ob.render_body(ob.extract_copy_region(SAMPLE_SKILL)))
        b = ob.compute_hash(ob.render_body(ob.extract_copy_region(inside)))
        self.assertNotEqual(a, b)


class TestSplice(unittest.TestCase):
    def setUp(self):
        self.block = ob.render_block(ob.render_body(ob.extract_copy_region(SAMPLE_SKILL)))

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
        self.assertIn("プロジェクト文書", out)


class TestCli(unittest.TestCase):
    def _run(self, tmp: Path, *args: str):
        skill = _write_skill(tmp)
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), "--skill-md", str(skill), *args],
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

    def test_write_creates_file_when_missing(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            target = tmp / "CLAUDE.md"
            proc, out = self._run(tmp, "--write", "--target", str(target))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(out["action"], "created")
            text = target.read_text(encoding="utf-8")
            self.assertIn("FORGE_ONBOARDING_START", text)
            self.assertIn("## 重要規約 [MANDATORY]", text)

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
            # 転記元を変更してから再実行すると stale と判定され更新される
            changed = SAMPLE_SKILL.replace("Hoge しない", "Fuga しない")
            skill = _write_skill(tmp, changed)
            proc = subprocess.run(
                [sys.executable, str(_SCRIPT_PATH), "--skill-md", str(skill), "--write", "--target", str(target)],
                capture_output=True,
                text=True,
            )
            out = json.loads(proc.stdout)
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


class TestRealSkillMd(unittest.TestCase):
    """配布物の実体が転記可能な状態であることを検証する。"""

    def setUp(self):
        self.text = ob.SKILL_MD.read_text(encoding="utf-8")

    def test_real_skill_md_has_paired_copy_markers(self):
        self.assertEqual(self.text.count(ob.COPY_START), 1)
        self.assertEqual(self.text.count(ob.COPY_END), 1)

    def test_real_copy_region_is_not_empty_and_excludes_flow(self):
        region = ob.extract_copy_region(self.text)
        self.assertTrue(region.strip())
        self.assertNotIn("## 実行フロー", region)

    def test_real_copy_region_headings_are_forge_prefixed(self):
        """転記先での見出し重複を防ぐ規約。script は接頭辞を付けないので、ここで強制する。"""
        region = ob.extract_copy_region(self.text)
        h2 = [ln for ln in region.splitlines() if ln.startswith("## ")]
        self.assertTrue(h2, "転記範囲に ## 見出しが無い")
        for line in h2:
            self.assertTrue(
                line.startswith("## forge "),
                f"転記範囲の ## 見出しは 'forge ' で始めること: {line!r}",
            )

    def test_real_copy_region_has_no_nested_destination_markers(self):
        """転記先マーカーが混入するとブロック検出が壊れる。"""
        region = ob.extract_copy_region(self.text)
        self.assertNotIn("FORGE_ONBOARDING_START", region)
        self.assertNotIn(ob.MARKER_END, region)


if __name__ == "__main__":
    unittest.main()
