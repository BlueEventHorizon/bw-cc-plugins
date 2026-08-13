#!/usr/bin/env python3
"""update_triage.py のテスト（段階的提示の仕分けファイルの作成・更新）。

このファイルが守っているのは、実運用で実際に起きた 2 つの失敗である。

- **作り直しで決着が消えた**: 作成専用のスクリプトが既存を上書きしていたため、
  ラウンド途中で所見の集合が変わるたびにファイルが作り直され、書き込んだ決着が
  黙って消えた。入口を 1 つにし、更新は既存を読み戻して行う
- **再実行で増える**: 消える経路を塞ぐと、今度は同じ所見が二重に足される。追加は
  位置 + 本文の同一性で冪等にする

実行:
  python3 -m unittest tests.forge.review.test_update_triage -v
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "review" / "scripts" / "update_triage.py"
)

_spec = importlib.util.spec_from_file_location("forge_update_triage", _SCRIPT_PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _finding(severity="major", text="dummy", summary="要約", location=None, **extra):
    finding = {
        "severity": severity,
        "text": text,
        "summary": summary,
        "location": location if location is not None else {"path": "a.py", "line": 1},
    }
    finding.update(extra)
    return finding


def _meta(review_id="rid"):
    return {"review_id": review_id}


class AddTest(unittest.TestCase):
    def test_ids_are_assigned_in_severity_order(self):
        entries, added, _ = mod.add([], [
            _finding("minor", "m"), _finding("critical", "c"), _finding("major", "j"),
        ])
        self.assertEqual([e["id"] for e in entries], ["01", "02", "03"])
        self.assertEqual([e["text"] for e in entries], ["c", "j", "m"])

    def test_ids_are_zero_padded(self):
        entries, _, _ = mod.add([], [_finding(text=str(i)) for i in range(3)])
        self.assertEqual([e["id"] for e in entries], ["01", "02", "03"])

    def test_added_findings_continue_after_the_largest_id(self):
        """既存の識別子は動かさない。会話で指した番号が別物を指さないため。"""
        entries, _, _ = mod.add([], [_finding(text="a"), _finding(text="b")])
        entries, added, _ = mod.add(entries, [_finding(text="c")])
        self.assertEqual([e["id"] for e in entries], ["01", "02", "03"])
        self.assertEqual([e["id"] for e in added], ["03"])
        self.assertEqual(entries[0]["text"], "a")

    def test_adding_the_same_finding_twice_is_a_no_op(self):
        """再実行で増えない（消える経路を塞いだ代わりに増えるのでは意味がない）。"""
        entries, _, _ = mod.add([], [_finding(text="a")])
        entries, added, skipped = mod.add(entries, [_finding(text="a", summary="別の要約")])
        self.assertEqual(added, [])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(len(entries), 1)

    def test_same_text_at_a_different_location_is_a_different_finding(self):
        entries, _, _ = mod.add([], [_finding(text="a", location={"path": "x.py", "line": 1})])
        entries, added, _ = mod.add(entries, [
            _finding(text="a", location={"path": "y.py", "line": 1}),
        ])
        self.assertEqual(len(added), 1)
        self.assertEqual(len(entries), 2)

    def test_identity_ignores_whitespace_differences(self):
        entries, _, _ = mod.add([], [_finding(text="1 行目\n2 行目")])
        _, added, _ = mod.add(entries, [_finding(text="1 行目 2 行目")])
        self.assertEqual(added, [])

    def test_identity_survives_a_round_trip_through_the_file(self):
        """読み戻したエントリと入力の所見を突き合わせられること。

        保存済みは位置が文字列、入力は辞書である。片方しか扱えないと突合が常に
        外れ、再実行のたびに増える。
        """
        entries, _, _ = mod.add([], [_finding(text="a")])
        _, reloaded = mod.parse(mod.render(_meta(), entries))
        _, added, skipped = mod.add(reloaded, [_finding(text="a")])
        self.assertEqual(added, [])
        self.assertEqual(len(skipped), 1)


class InitialStateTest(unittest.TestCase):
    """生成時点で決まっているものは決着済みとして出す（後から書き換えない）。"""

    def test_unlocated_finding_is_out_of_scope(self):
        entries, _, _ = mod.add([], [_finding(location={"unknown": True})])
        self.assertEqual(entries[0]["state"], "対象外")

    def test_missing_location_key_is_out_of_scope(self):
        entries, _, _ = mod.add([], [{"severity": "major", "text": "t", "summary": "s"}])
        self.assertEqual(entries[0]["state"], "対象外")

    def test_dropped_finding_is_withdrawn_not_out_of_scope(self):
        """`取り下げ`（指摘が誤り）と `対象外`（最初から範囲外）は別の状態である。"""
        entries, _, _ = mod.add([], [_finding(drop_reason="該当しない")])
        self.assertEqual(entries[0]["state"], "取り下げ")

    def test_ordinary_finding_is_pending(self):
        entries, _, _ = mod.add([], [_finding()])
        self.assertEqual(entries[0]["state"], "未着手")

    def test_drop_reason_is_recorded_as_the_resolution(self):
        entries, _, _ = mod.add([], [_finding(drop_reason="criteria に規定なし")])
        self.assertEqual(entries[0]["fields"]["決着"], "criteria に規定なし")

    def test_missing_drop_reason_is_marked_not_silently_blank(self):
        entries, _, _ = mod.add([], [_finding(drop_reason="   ")])
        self.assertEqual(entries[0]["state"], "未着手")

    def test_out_of_scope_resolution_states_human_confirmation_is_needed(self):
        entries, _, _ = mod.add([], [_finding(location={"unknown": True})])
        self.assertIn("人間が直接内容を確認する必要がある", entries[0]["fields"]["決着"])


class MarkTest(unittest.TestCase):
    """`✅` と `☑️` は対象の違う 2 つの確信を 1 列の順序尺度で示す。

    - `☑️` — レビュアーの**指摘**が正しいと確信している
    - `✅` — 加えて、その**修正**を責任を持って実行できる
    """

    def test_auto_fix_mark_needs_both(self):
        self.assertEqual(mod._mark({"confidence": "confirmed", "fix_confident": True}), "✅")

    def test_confirmed_alone_is_checkmark(self):
        """「指摘は正しいが直し方に確信が無い」を表せること。"""
        self.assertEqual(mod._mark({"confidence": "confirmed"}), "☑️")

    def test_fix_confidence_without_confirmed_falls_to_blank(self):
        """矛盾した入力は低い側へ倒す（高い側へ倒すと確信の無い修正が通る）。"""
        self.assertEqual(mod._mark({"confidence": "inferred", "fix_confident": True}), "")

    def test_missing_confidence_falls_to_blank(self):
        self.assertEqual(mod._mark({}), "")

    def test_unknown_confidence_value_falls_to_blank(self):
        self.assertEqual(mod._mark({"confidence": "very-sure"}), "")

    def test_both_judgements_are_written_as_settled_values(self):
        """手順 1 で確定済みの判断を空欄で出さない（二度決めさせない）。"""
        entries, _, _ = mod.add([], [_finding(confidence="confirmed", fix_confident=True)])
        self.assertEqual(entries[0]["fields"]["指摘は正しいか"], "☑️ 確信あり")
        self.assertEqual(entries[0]["fields"]["修正を任せられるか"], "✅ 責任を持って実行できる")

    def test_lack_of_confidence_is_stated_explicitly(self):
        entries, _, _ = mod.add([], [_finding(confidence="unverified")])
        self.assertEqual(entries[0]["fields"]["指摘は正しいか"], "確信なし")
        self.assertEqual(entries[0]["fields"]["修正を任せられるか"], "直し方に確信が無い")

    def test_confidence_is_written_with_three_distinct_values(self):
        """**3 値を潰さない [MANDATORY]**。

        `inferred`（根拠はあるが未確認）と `unverified`（記憶・推測のみ）を同じ表記にすると、
        ファイルを読んだ人が両者を区別できない。記号は `修正の可否` の軸とは別の軸である。
        """
        written = {}
        for value in ("confirmed", "inferred", "unverified"):
            entries, _, _ = mod.add([], [_finding(confidence=value)])
            written[value] = entries[0]["fields"]["指摘は正しいか"]
        self.assertEqual(len(set(written.values())), 3, written)
        self.assertTrue(written["confirmed"].startswith(mod.CONFIRMED_MARK))
        self.assertTrue(written["inferred"].startswith(mod.INFERRED_MARK))
        self.assertFalse(written["unverified"].startswith(mod.INFERRED_MARK))

    def test_inferred_does_not_raise_the_agenda_mark(self):
        """`🤔` は確信度の軸であり、`☑️` / `✅` の軸を動かさない。"""
        entries, _, _ = mod.add([], [_finding(confidence="inferred", fix_confident=True)])
        self.assertEqual(mod._mark(entries[0]), "")

    def test_unknown_confidence_is_written_as_the_lowest_value(self):
        entries, _, _ = mod.add([], [_finding(confidence="very-sure")])
        self.assertEqual(entries[0]["fields"]["指摘は正しいか"], "確信なし")


class SummaryTest(unittest.TestCase):
    """アジェンダ表のセルは AI が書く。機械的に切り詰めない。"""

    def test_summary_is_written_verbatim(self):
        entries, _, _ = mod.add([], [_finding(summary="命名が規約と食い違う")])
        self.assertEqual(entries[0]["result"], "命名が規約と食い違う")

    def test_long_summary_is_not_truncated(self):
        """切り詰めは文の途中で切るため、課題の所在ではなく背景の断片が残る。"""
        long_summary = "あ" * 200
        entries, _, _ = mod.add([], [_finding(summary=long_summary)])
        self.assertEqual(entries[0]["result"], long_summary)

    def test_missing_summary_is_an_error_not_a_dump_of_the_finding(self):
        """本文を表へ流し込まない（表が読めなくなる）。黙って切らず、書かせる。"""
        with self.assertRaises(ValueError):
            mod.add([], [{"severity": "major", "text": "本文",
                          "location": {"path": "a.py", "line": 1}}])

    def test_settled_entries_do_not_need_a_summary(self):
        """取り下げ・対象外は決着済みであり、結果欄に理由が入る。"""
        entries, _, _ = mod.add([], [
            {"severity": "major", "text": "t", "location": {"path": "a.py", "line": 1},
             "drop_reason": "該当しない"},
        ])
        self.assertEqual(entries[0]["result"], "該当しない")

    def test_table_breaking_characters_are_collapsed(self):
        entries, _, _ = mod.add([], [_finding(summary="1 行目\n2 行目 | 続き")])
        self.assertEqual(entries[0]["result"], "1 行目 2 行目 \\| 続き")

    def test_finding_body_keeps_newlines_in_the_section(self):
        """節の本文は表ではないため、所見の改行を畳まない。"""
        out = mod.render(_meta(), mod.add([], [_finding(text="1 行目\n2 行目")])[0])
        self.assertIn("1 行目\n2 行目", out)


def _settled(**overrides) -> dict:
    """決着に必要な欄を埋めた fields。個別に欠かす検証は overrides で行う。"""
    fields = {
        "背景": "背景を書いた",
        "本質": "本質を書いた",
        "対応": "対応を書いた",
        "推奨": "採用する。理由",
        "決着": "利用者が採用",
    }
    fields.update(overrides)
    return {k: v for k, v in fields.items() if v is not None}


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.entries, _, _ = mod.add([], [_finding(text="a"), _finding(text="b")])

    def test_state_and_result_are_updated(self):
        mod.update(self.entries, "01", state="決着", result="採用した", fields=_settled())
        self.assertEqual(self.entries[0]["state"], "決着")
        self.assertEqual(self.entries[0]["result"], "採用した")

    def test_fields_are_updated(self):
        mod.update(self.entries, "01", fields={"決着": "利用者が採用"})
        self.assertEqual(self.entries[0]["fields"]["決着"], "利用者が採用")

    def test_other_entries_are_untouched(self):
        before = dict(self.entries[1])
        mod.update(self.entries, "01", state="決着", fields=_settled())
        self.assertEqual(self.entries[1], before)

    def test_unknown_id_is_an_error(self):
        """打ち間違いを静かに無視すると、書いたつもりの決着がどこにも残らない。"""
        with self.assertRaises(KeyError):
            mod.update(self.entries, "99", state="決着")

    def test_unknown_state_is_an_error(self):
        with self.assertRaises(ValueError):
            mod.update(self.entries, "01", state="かたづいた")

    def test_unknown_field_is_an_error(self):
        with self.assertRaises(ValueError):
            mod.update(self.entries, "01", fields={"感想": "よかった"})

    def test_settling_requires_the_fields_that_the_presentation_produced(self):
        """`決着` だけ書いて済ませられない [MANDATORY]。

        背景・本質・対応・推奨が空のまま決着すると、提示で述べた内容が会話にしか残らない。
        しかもファイルは決着済みに見えるため、失われたことに気付く手がかりも消える。
        規約だけに頼らず構造で止める（`review_id` の照合と同じ理由）。
        """
        for missing in ("背景", "本質", "対応", "推奨", "決着"):
            with self.subTest(missing=missing):
                entries, _, _ = mod.add([], [_finding(text="a")])
                with self.assertRaises(ValueError) as ctx:
                    mod.update(
                        entries, "01", state="決着",
                        fields=_settled(**{missing: None}),
                    )
                self.assertIn(missing, str(ctx.exception))
                # 止まったなら状態も欄も変わっていないこと
                self.assertEqual(entries[0]["state"], "未着手")
                self.assertEqual(entries[0]["fields"]["決着"], mod.FIELD_PLACEHOLDER["決着"])

    def test_placeholder_text_does_not_count_as_written(self):
        """初期値のまま渡すのは書いていないのと同じである。"""
        with self.assertRaises(ValueError):
            mod.update(
                self.entries, "01", state="決着",
                fields=_settled(背景=mod.FIELD_PLACEHOLDER["背景"]),
            )

    def test_settling_check_does_not_apply_to_other_states(self):
        """`取り下げ` / `対象外` は生成時点の決着であり、提示を経ていない。"""
        for state in ("未着手", "進行中", "保留", "取り下げ", "対象外"):
            with self.subTest(state=state):
                entries, _, _ = mod.add([], [_finding(text=f"x{state}")])
                mod.update(entries, "01", state=state)
                self.assertEqual(entries[0]["state"], state)

    def test_withdrawn_entry_can_be_restored_for_presentation(self):
        """取り下げの差し戻し。節は既にあるため全文も決着欄も失われていない。"""
        entries, _, _ = mod.add([], [_finding(drop_reason="該当しない")])
        mod.update(entries, "01", state="未着手", result="差し戻し")
        self.assertEqual(entries[0]["state"], "未着手")
        self.assertEqual(entries[0]["text"], "dummy")


class RoundTripTest(unittest.TestCase):
    """更新は読み戻して行うため、生成した書式を必ず読み戻せること。"""

    def test_entries_survive_render_and_parse(self):
        entries, _, _ = mod.add([], [
            _finding("critical", "本文 A\n2 行目", summary="A"),
            _finding("minor", "本文 B", summary="B", location={"unknown": True}),
            _finding("major", "本文 C", summary="C", drop_reason="該当しない"),
            _finding("major", "本文 D", summary="D", confidence="confirmed", fix_confident=True),
            _finding("major", "本文 E", summary="E", confidence="inferred"),
        ])
        meta, reloaded = mod.parse(mod.render(_meta("abc"), entries))
        self.assertEqual(meta, _meta("abc"))
        self.assertEqual(len(reloaded), len(entries))
        for original, restored in zip(entries, reloaded):
            for key in ("id", "severity", "location", "text", "state", "result", "fields"):
                self.assertEqual(restored[key], original[key], key)
            self.assertEqual(mod._mark(restored), mod._mark(original))
            # **2 つの判断が往復で保たれること**。`inferred` を `unverified` へ畳まない。
            self.assertEqual(restored["confidence"], original["confidence"], original["id"])
            self.assertEqual(
                restored["fix_confident"], original["fix_confident"], original["id"]
            )

    def test_updates_survive_a_round_trip(self):
        entries, _, _ = mod.add([], [_finding(text="a")])
        mod.update(entries, "01", state="決着", result="採用", fields=_settled())
        _, reloaded = mod.parse(mod.render(_meta(), entries))
        self.assertEqual(reloaded[0]["state"], "決着")
        self.assertEqual(reloaded[0]["fields"]["決着"], "利用者が採用")

    def test_empty_file_still_renders_an_agenda(self):
        out = mod.render(_meta(), [])
        self.assertIn("## アジェンダ", out)
        self.assertIn("所見はありません", out)

    def test_file_carries_only_the_review_id_as_metadata(self):
        """件数はアジェンダと CLI 出力に出る。同じ値を 2 か所に置かない。"""
        out = mod.render(_meta("abc"), mod.add([], [_finding()])[0])
        self.assertTrue(out.startswith("# レビュー所見の仕分け: abc\n"))
        self.assertNotIn("| 項目 | 値 |", out)
        self.assertNotIn("バックエンド", out)
        self.assertNotIn("round", out)

    def test_section_without_an_agenda_row_is_an_error(self):
        """壊れたファイルを黙って読み進めない（読めた分だけ残ると静かに消える）。"""
        text = mod.render(_meta(), mod.add([], [_finding()])[0])
        broken = text.replace("| 01 | ", "| 09 | ", 1)
        with self.assertRaises(ValueError):
            mod.parse(broken)


class CliTest(unittest.TestCase):
    def _run(self, args, cwd=None):
        return subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), *args],
            capture_output=True, text=True, cwd=str(cwd or self.root),
        )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _settled_args(self):
        return [a for name, value in _settled().items() for a in ("--field", f"{name}={value}")]

    def _add(self, findings, extra=()):
        return self._run([
            "--project-root", str(self.root), "--add-json",
            json.dumps(findings, ensure_ascii=False), *extra,
        ])

    def test_creates_the_file_at_a_fixed_location(self):
        proc = self._add([_finding()], ["--review-id", "abc"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["triage_path"], ".claude/.temp/review/triage.md")
        self.assertTrue(payload["created"])
        self.assertTrue((self.root / payload["triage_path"]).exists())

    def test_absolute_path_is_returned(self):
        """相対パスは cwd が異なると開けない。利用者へ示すのは絶対パスである。"""
        proc = self._add([_finding()], ["--review-id", "abc"])
        self.assertTrue(Path(json.loads(proc.stdout)["absolute_path"]).is_absolute())

    def test_writes_under_project_root_regardless_of_cwd(self):
        other = self.root / "sub"
        other.mkdir()
        proc = self._run([
            "--project-root", str(self.root), "--review-id", "abc",
            "--add-json", json.dumps([_finding()], ensure_ascii=False),
        ], cwd=other)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.root / ".claude/.temp/review/triage.md").exists())
        self.assertFalse((other / ".claude").exists())

    def test_creation_requires_a_review_id(self):
        self.assertNotEqual(self._add([_finding()]).returncode, 0)
        self.assertNotEqual(self._add([_finding()], ["--review-id", "  "]).returncode, 0)

    def test_has_no_round_argument(self):
        """ラウンドは往復回数であり、所見の扱いを何も決めない。"""
        proc = self._add([_finding()], ["--review-id", "abc", "--round", "1"])
        self.assertNotEqual(proc.returncode, 0)

    def test_adding_again_does_not_grow_the_file(self):
        self._add([_finding()], ["--review-id", "abc"])
        proc = self._add([_finding()])
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["added_ids"], [])
        self.assertEqual(payload["skipped_count"], 1)
        self.assertEqual(payload["total_count"], 1)

    def test_update_reports_counts(self):
        self._add([
            _finding(text="a", confidence="confirmed", fix_confident=True),
            _finding(text="b"),
        ], ["--review-id", "abc"])
        proc = self._run([
            "--project-root", str(self.root), "--id", "01", "--state", "決着",
            "--result", "採用", *self._settled_args(),
        ])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["open_count"], 1)
        self.assertEqual(payload["auto_fixable_count"], 1)
        written = (self.root / payload["triage_path"]).read_text(encoding="utf-8")
        self.assertIn("利用者が採用", written)

    def test_settling_without_the_presentation_fields_leaves_the_file_alone(self):
        """止まったときファイルが書き換わらないこと。

        半端に決着だけ立って残ると、次に読んだ人には決着済みに見える。
        """
        self._add([_finding(text="a")], ["--review-id", "abc"])
        path = self.root / ".claude/.temp/review/triage.md"
        before = path.read_text(encoding="utf-8")
        proc = self._run([
            "--project-root", str(self.root), "--id", "01", "--state", "決着",
            "--field", "決着=利用者が採用",
        ])
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        for name in ("背景", "本質", "対応", "推奨"):
            self.assertIn(name, proc.stderr)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_errors_are_reported_as_a_line_not_a_traceback(self):
        self._add([_finding()], ["--review-id", "abc"])
        proc = self._run(["--project-root", str(self.root), "--id", "99", "--state", "決着"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("99", proc.stderr)

    def test_requires_an_operation(self):
        proc = self._run(["--project-root", str(self.root), "--review-id", "abc", "--round", "1"])
        self.assertNotEqual(proc.returncode, 0)

    def test_findings_from_another_review_are_refused(self):
        """前のセッションの残りへ追記しない。

        ファイル名は固定でどのレビューのものかを持たないため、照合しなければ
        旧所見と新所見が同じ表に並び、`review_id` だけが黙って置き換わる。
        """
        self._add([_finding(text="前回")], ["--review-id", "OLD"])
        proc = self._add([_finding(text="今回")], ["--review-id", "NEW"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("OLD", proc.stderr)
        self.assertIn("NEW", proc.stderr)
        written = (self.root / ".claude/.temp/review/triage.md").read_text(encoding="utf-8")
        self.assertIn("前回", written)
        self.assertNotIn("今回", written)

    def test_the_same_review_may_continue(self):
        self._add([_finding(text="a")], ["--review-id", "SAME"])
        proc = self._add([_finding(text="b")], ["--review-id", "SAME"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["total_count"], 2)

    def test_updates_without_a_review_id_are_not_blocked(self):
        """決着の書き込みは識別子を伴わない（照合する材料が無い）。"""
        self._add([_finding()], ["--review-id", "SAME"])
        proc = self._run([
            "--project-root", str(self.root), "--id", "01", "--state", "決着",
            *self._settled_args(),
        ])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_output_carries_the_agenda_ready_to_display(self):
        """更新後の表をそのまま返す。AI が手で書き起こすと食い違う。

        実際に、決着させていない所見をコンソールだけ `進行中` と書いた事故が起きた。
        """
        self._add([_finding(text="a", summary="A の所在")], ["--review-id", "abc"])
        proc = self._run([
            "--project-root", str(self.root), "--id", "01",
            "--state", "決着", "--result", "採用した", *self._settled_args(),
        ])
        agenda = json.loads(proc.stdout)["agenda"]
        self.assertIn("| ID | 判定 | 重大度 | 状態 | 結果・課題 |", agenda)
        self.assertNotIn("a.py", agenda)
        self.assertIn("| 01 |", agenda)
        self.assertIn("決着", agenda)
        self.assertIn("採用した", agenda)
        written = (self.root / ".claude/.temp/review/triage.md").read_text(encoding="utf-8")
        self.assertIn(agenda, written)

    def test_a_title_from_an_older_format_is_refused(self):
        """書式変更をまたいだファイルを黙って読み進めない。

        見出しの残りを丸ごと `review_id` として取り込むと、余分な語が入ったまま
        再生成で固定される（旧見出しの `(round N)` を取り込んだ実例がある）。
        """
        self._add([_finding()], ["--review-id", "abc"])
        path = self.root / ".claude/.temp/review/triage.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "# レビュー所見の仕分け: abc", "# レビュー所見の仕分け: abc (round 1)"
            ),
            encoding="utf-8",
        )
        proc = self._run(["--project-root", str(self.root), "--id", "01", "--state", "決着"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("空白", proc.stderr)

    def test_has_no_regeneration_mode(self):
        """作り直す経路を持たない（決着が消えた原因そのもの）。"""
        for flag in ("--findings-json", "--force", "--overwrite"):
            with self.subTest(flag=flag):
                proc = self._run([
                    "--project-root", str(self.root), flag, "[]",
                    "--review-id", "abc", "--round", "1",
                ])
                self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
