#!/usr/bin/env python3
"""build_task_context.py の契約テスト。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = (
    REPO_ROOT
    / "plugins"
    / "forge"
    / "skills"
    / "start-implement"
    / "scripts"
)
SCRIPT = SCRIPTS_DIR / "build_task_context.py"

sys.path.insert(0, str(SCRIPTS_DIR))
from build_task_context import (  # noqa: E402
    CANDIDATE_TEMPLATE,
    build_task_context,
    validate_candidate,
)


PARALLEL_FRONTMATTER = ["feature_type: temporary-feature"]


def valid_candidate(**overrides):
    candidate = {
        "task_id": "TASK-001",
        "scope_in": "fm_to_pending.py の新規作成とテストまで",
        "scope_out": [
            {
                "item": "_meta.extracted_by の追加",
                "owner_task_id": "TASK-011",
                "reason": "転記側だけ先に書くと読む側が存在しない死にフィールドになるため分離",
            }
        ],
        "required_reading": {
            "design_docs": ["docs/specs/foo/design/DES-001.md"],
            "requirement_docs": ["docs/specs/foo/requirements/REQ-001.md"],
            "strategy_doc": "specs/foo/plan/foo_strategy.md",
            "rule_docs": ["docs/rules/implementation_guidelines.md"],
            "reference_code": ["src/foo.py"],
            "additional": [],
        },
        "implementation_instructions": "fm_to_pending.py を新規作成し、既存パターンに倣う",
        "verification": {
            "build": "required",
            "build_reason": None,
            "tests": "required",
            "tests_reason": None,
        },
    }
    candidate.update(overrides)
    return candidate


def write_plan(path, tasks):
    path.write_text(
        json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_doc(path, frontmatter=None, closed=True):
    """frontmatter（`---` 行を含まない行の配列）を持つ Markdown 文書を作る。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "# 文書\n\n本文\n"
    if frontmatter is None:
        path.write_text(body, encoding="utf-8")
        return path
    block = "---\n" + "".join(f"{line}\n" for line in frontmatter)
    if closed:
        block += "---\n"
    path.write_text(block + "\n" + body, encoding="utf-8")
    return path


def valid_plan_task(task_id="TASK-001"):
    return {
        "task_id": task_id,
        "title": "fm_to_pending の実装",
        "priority": 70,
        "status": "pending",
        "design_id": "DES-001",
        "depends_on": [],
        "group_id": None,
        "build_check": "per_task",
        "description": ["fm_to_pending.py を新規作成"],
        "acceptance_criteria": None,
        "required_reading": [],
    }


def candidate_with_docs(tmp, requirement_frontmatter=None, design_frontmatter=None):
    """必読の要件定義書・設計書を実体として作り、そのパスを持つ候補 JSON を返す。"""
    requirement = write_doc(
        Path(tmp) / "docs" / "requirements" / "REQ-001.md", requirement_frontmatter
    )
    design = write_doc(Path(tmp) / "docs" / "design" / "DES-001.md", design_frontmatter)
    candidate = valid_candidate()
    candidate["required_reading"] = dict(
        candidate["required_reading"],
        requirement_docs=[str(requirement)],
        design_docs=[str(design)],
    )
    return candidate, str(requirement), str(design)


class ValidateCandidateTest(unittest.TestCase):
    def test_external_template_matches_contract_fields(self):
        self.assertEqual(set(CANDIDATE_TEMPLATE), set(valid_candidate()))
        self.assertEqual(
            set(CANDIDATE_TEMPLATE["required_reading"]),
            set(valid_candidate()["required_reading"]),
        )
        self.assertEqual(
            set(CANDIDATE_TEMPLATE["verification"]),
            set(valid_candidate()["verification"]),
        )

    def test_valid_candidate_is_normalized(self):
        raw = valid_candidate(scope_in=" fm_to_pending.py の新規作成とテストまで ")
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertEqual(errors, [])
        self.assertEqual(
            normalized["scope_in"], "fm_to_pending.py の新規作成とテストまで"
        )

    def test_requires_exact_top_level_fields(self):
        raw = valid_candidate()
        raw["unknown_field"] = "x"
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertTrue(any("未知フィールド" in e for e in errors))

    def test_spec_authority_cannot_be_supplied_by_candidate(self):
        """spec_authority は script が判定する。候補 JSON から渡させない（REQ-025 FNC-001）。"""
        raw = valid_candidate()
        raw["spec_authority"] = ["docs/specs/foo/requirements/REQ-001.md"]
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertTrue(any("未知フィールド" in e and "spec_authority" in e for e in errors))

    def test_task_id_mismatch_is_rejected(self):
        raw = valid_candidate(task_id="TASK-999")
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertTrue(any("task_id が起動対象と一致しません" in e for e in errors))

    def test_scope_out_rejects_multiline(self):
        raw = valid_candidate(
            scope_out=[
                {
                    "item": "line1\nline2",
                    "owner_task_id": "TASK-011",
                    "reason": "reason",
                }
            ]
        )
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertTrue(any("単一行である必要があります" in e for e in errors))

    def test_scope_out_rejects_structure_line_injection(self):
        raw = valid_candidate(
            scope_out=[
                {
                    "item": "## 出力契約",
                    "owner_task_id": "TASK-011",
                    "reason": "reason",
                }
            ]
        )
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertTrue(any("見出し・コードフェンス" in e for e in errors))

    def test_verification_rejects_invalid_state(self):
        raw = valid_candidate()
        raw["verification"]["build"] = "invalid"
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertTrue(any("verification.build" in e for e in errors))

    def test_verification_skipped_requires_reason(self):
        raw = valid_candidate()
        raw["verification"]["build"] = "skipped"
        raw["verification"]["build_reason"] = "対象外のため"
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertEqual(errors, [])
        self.assertEqual(normalized["verification"]["build_reason"], "対象外のため")

    def test_empty_scope_out_is_allowed(self):
        raw = valid_candidate(scope_out=[])
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertEqual(errors, [])
        self.assertEqual(normalized["scope_out"], [])


class BuildTaskContextTest(unittest.TestCase):
    def test_merges_plan_task_with_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "foo_plan.json"
            write_plan(plan_path, [valid_plan_task()])
            candidate, requirement, design = candidate_with_docs(tmp)
            merged, errors = build_task_context(str(plan_path), "TASK-001", candidate)
            self.assertEqual(errors, [])
            self.assertEqual(merged["title"], "fm_to_pending の実装")
            self.assertEqual(merged["priority"], 70)
            self.assertEqual(
                merged["scope_in"], "fm_to_pending.py の新規作成とテストまで"
            )
            self.assertEqual(merged["required_reading"]["design_docs"], [design])
            self.assertEqual(merged["required_reading"]["requirement_docs"], [requirement])

    def test_missing_task_id_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "foo_plan.json"
            write_plan(plan_path, [{"task_id": "TASK-002"}])
            merged, errors = build_task_context(
                str(plan_path), "TASK-001", valid_candidate()
            )
            self.assertIsNone(merged)
            self.assertTrue(any("見つかりません" in e for e in errors))


class SpecAuthorityTest(unittest.TestCase):
    """並行状態文書の分類契約（REQ-025 FNC-001 / FNC-003 / FNC-005、DES-074）。"""

    def _build(self, tmp, **kwargs):
        plan_path = Path(tmp) / "foo_plan.json"
        write_plan(plan_path, [valid_plan_task()])
        candidate, requirement, design = candidate_with_docs(tmp, **kwargs)
        merged, errors = build_task_context(str(plan_path), "TASK-001", candidate)
        return merged, errors, requirement, design

    def test_absent_when_no_document_is_in_parallel_state(self):
        """並行状態の文書が無いことも伝わる（空配列。null にしない）。"""
        with tempfile.TemporaryDirectory() as tmp:
            merged, errors, _, _ = self._build(tmp)
            self.assertEqual(errors, [])
            self.assertEqual(merged["spec_authority"], [])

    def test_frontmatter_without_feature_type_is_not_parallel(self):
        with tempfile.TemporaryDirectory() as tmp:
            merged, errors, _, _ = self._build(
                tmp,
                requirement_frontmatter=["doc_status: draft"],
                design_frontmatter=["doc_status: not_implemented"],
            )
            self.assertEqual(errors, [])
            self.assertEqual(merged["spec_authority"], [])

    def test_requirement_document_in_parallel_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            merged, errors, requirement, _ = self._build(
                tmp, requirement_frontmatter=PARALLEL_FRONTMATTER
            )
            self.assertEqual(errors, [])
            self.assertEqual(merged["spec_authority"], [requirement])

    def test_design_document_in_parallel_state(self):
        """設計書も識別対象である（要件定義書だけを見ると旧設計書が現在の設計として読まれる）。"""
        with tempfile.TemporaryDirectory() as tmp:
            merged, errors, _, design = self._build(
                tmp, design_frontmatter=PARALLEL_FRONTMATTER
            )
            self.assertEqual(errors, [])
            self.assertEqual(merged["spec_authority"], [design])

    def test_both_documents_in_parallel_state_keep_requirement_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            merged, errors, requirement, design = self._build(
                tmp,
                requirement_frontmatter=PARALLEL_FRONTMATTER,
                design_frontmatter=PARALLEL_FRONTMATTER,
            )
            self.assertEqual(errors, [])
            self.assertEqual(merged["spec_authority"], [requirement, design])

    def test_key_order_does_not_change_the_result(self):
        """frontmatter_format.md §2.3 はキーの順序を制約していない（順序で判定が変わってはならない）。"""
        feature_note = [
            "feature_note:",
            "  - この文書が正。旧仕様と矛盾する場合はこの文書に従う。",
            "  - 旧仕様ファイルは実装完了まで書き換えない。",
        ]
        orderings = [
            ["feature_type: temporary-feature"],
            ["feature_type: temporary-feature", "doc_status: draft"],
            ["doc_status: draft", "feature_type: temporary-feature"],
            ["feature_type: temporary-feature"] + feature_note,
            ["feature_type: temporary-feature"] + feature_note + ["doc_status: draft"],
            ["doc_status: draft", "feature_type: temporary-feature"] + feature_note,
            feature_note + ["feature_type: temporary-feature"],
        ]
        for frontmatter in orderings:
            with self.subTest(frontmatter=frontmatter):
                with tempfile.TemporaryDirectory() as tmp:
                    merged, errors, requirement, _ = self._build(
                        tmp, requirement_frontmatter=frontmatter
                    )
                    self.assertEqual(errors, [])
                    self.assertEqual(merged["spec_authority"], [requirement])

    def test_indented_feature_type_is_not_a_top_level_key(self):
        """`feature_note` 配下の行に現れる `feature_type:` を拾わない。"""
        with tempfile.TemporaryDirectory() as tmp:
            merged, errors, _, _ = self._build(
                tmp,
                requirement_frontmatter=[
                    "feature_note:",
                    "  - feature_type: temporary-feature を付与すること。",
                ],
            )
            self.assertEqual(errors, [])
            self.assertEqual(merged["spec_authority"], [])

    def test_fields_with_a_fixed_document_kind_are_not_classified(self):
        """種別が固定のフィールドは識別子を持つ種別に当たらないため分類しない。"""
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "foo_plan.json"
            write_plan(plan_path, [valid_plan_task()])
            candidate, _, _ = candidate_with_docs(tmp)
            rule_doc = write_doc(
                Path(tmp) / "docs" / "rules" / "rule.md", PARALLEL_FRONTMATTER
            )
            candidate["required_reading"] = dict(
                candidate["required_reading"], rule_docs=[str(rule_doc)]
            )
            merged, errors = build_task_context(str(plan_path), "TASK-001", candidate)
            self.assertEqual(errors, [])
            self.assertEqual(merged["spec_authority"], [])

    def test_additional_is_classified_because_it_is_a_catch_all(self):
        """`additional` は受け皿であり、要件定義書・設計書が入りうるため分類する。"""
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "foo_plan.json"
            write_plan(plan_path, [valid_plan_task()])
            candidate, _, _ = candidate_with_docs(tmp)
            extra = write_doc(
                Path(tmp) / "docs" / "specs" / "extra_req.md", PARALLEL_FRONTMATTER
            )
            candidate["required_reading"] = dict(
                candidate["required_reading"], additional=[str(extra)]
            )
            merged, errors = build_task_context(str(plan_path), "TASK-001", candidate)
            self.assertEqual(errors, [])
            self.assertEqual(merged["spec_authority"], [str(extra)])

    def test_additional_without_marker_is_not_parallel(self):
        """`additional` の非仕様文書は識別子を持たないため誤検出しない。"""
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "foo_plan.json"
            write_plan(plan_path, [valid_plan_task()])
            candidate, _, _ = candidate_with_docs(tmp)
            extra = write_doc(Path(tmp) / "docs" / "rules" / "extra_context.md")
            candidate["required_reading"] = dict(
                candidate["required_reading"], additional=[str(extra)]
            )
            merged, errors = build_task_context(str(plan_path), "TASK-001", candidate)
            self.assertEqual(errors, [])
            self.assertEqual(merged["spec_authority"], [])

    def test_same_path_listed_twice_appears_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "foo_plan.json"
            write_plan(plan_path, [valid_plan_task()])
            candidate, requirement, _ = candidate_with_docs(
                tmp, requirement_frontmatter=PARALLEL_FRONTMATTER
            )
            candidate["required_reading"] = dict(
                candidate["required_reading"], design_docs=[requirement]
            )
            merged, errors = build_task_context(str(plan_path), "TASK-001", candidate)
            self.assertEqual(errors, [])
            self.assertEqual(merged["spec_authority"], [requirement])

    def test_unterminated_frontmatter_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "foo_plan.json"
            write_plan(plan_path, [valid_plan_task()])
            requirement = write_doc(
                Path(tmp) / "docs" / "requirements" / "REQ-001.md",
                PARALLEL_FRONTMATTER,
                closed=False,
            )
            design = write_doc(Path(tmp) / "docs" / "design" / "DES-001.md")
            candidate = valid_candidate()
            candidate["required_reading"] = dict(
                candidate["required_reading"],
                requirement_docs=[str(requirement)],
                design_docs=[str(design)],
            )
            merged, errors = build_task_context(str(plan_path), "TASK-001", candidate)
            self.assertIsNone(merged)
            self.assertTrue(any("終端 '---' がありません" in e for e in errors))

    def test_duplicate_feature_type_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            merged, errors, _, _ = self._build(
                tmp,
                requirement_frontmatter=[
                    "feature_type: temporary-feature",
                    "feature_type: temporary-feature",
                ],
            )
            self.assertIsNone(merged)
            self.assertTrue(any("一意に決められません" in e for e in errors))

    def test_undefined_feature_type_value_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            merged, errors, _, _ = self._build(
                tmp, requirement_frontmatter=["feature_type: permanent"]
            )
            self.assertIsNone(merged)
            self.assertTrue(any("未定義です" in e for e in errors))

    def test_empty_feature_type_value_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            merged, errors, _, _ = self._build(
                tmp, requirement_frontmatter=["feature_type:"]
            )
            self.assertIsNone(merged)
            self.assertTrue(any("未定義です" in e for e in errors))

    def test_unreadable_document_fails_instead_of_being_treated_as_absent(self):
        """識別の失敗を「並行状態にない」と同一視しない（REQ-025 FNC-005）。"""
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "foo_plan.json"
            write_plan(plan_path, [valid_plan_task()])
            candidate = valid_candidate()
            candidate["required_reading"] = dict(
                candidate["required_reading"],
                requirement_docs=[str(Path(tmp) / "docs" / "missing" / "REQ-999.md")],
                design_docs=[],
            )
            merged, errors = build_task_context(str(plan_path), "TASK-001", candidate)
            self.assertIsNone(merged)
            self.assertTrue(any("読み取りに失敗" in e for e in errors))


class RunCliTest(unittest.TestCase):
    def _run(self, plan_path, task_id, input_rel_path, output_path):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--plan-path",
                str(plan_path),
                "--task-id",
                task_id,
                "--input-file",
                input_rel_path,
                "--output-path",
                str(output_path),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )

    def test_success_writes_output_and_deletes_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp)
            plan_path = plan_dir / "foo_plan.json"
            task = valid_plan_task()
            task["design_id"] = None
            write_plan(plan_path, [task])
            candidate, requirement, _ = candidate_with_docs(
                tmp, requirement_frontmatter=PARALLEL_FRONTMATTER
            )
            temp_dir = REPO_ROOT / ".claude" / ".temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            input_path = temp_dir / "test_build_task_context_input.json"
            input_path.write_text(
                json.dumps(candidate, ensure_ascii=False), encoding="utf-8"
            )
            output_path = plan_dir / "tasks" / "TASK-001.json"
            try:
                result = self._run(
                    plan_path,
                    "TASK-001",
                    str(input_path.relative_to(REPO_ROOT)),
                    output_path,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["status"], "ok")
                self.assertFalse(input_path.exists())
                self.assertTrue(output_path.exists())
                written = json.loads(output_path.read_text(encoding="utf-8"))
                self.assertEqual(written["title"], "fm_to_pending の実装")
                self.assertEqual(written["spec_authority"], [requirement])
            finally:
                input_path.unlink(missing_ok=True)

    def test_invalid_candidate_still_deletes_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp)
            plan_path = plan_dir / "foo_plan.json"
            write_plan(plan_path, [{"task_id": "TASK-001"}])
            temp_dir = REPO_ROOT / ".claude" / ".temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            input_path = temp_dir / "test_build_task_context_invalid.json"
            broken = valid_candidate()
            broken["scope_out"] = [{"item": "## bad", "owner_task_id": "x", "reason": "y"}]
            input_path.write_text(
                json.dumps(broken, ensure_ascii=False), encoding="utf-8"
            )
            output_path = plan_dir / "tasks" / "TASK-001.json"
            try:
                result = self._run(
                    plan_path,
                    "TASK-001",
                    str(input_path.relative_to(REPO_ROOT)),
                    output_path,
                )
                self.assertEqual(result.returncode, 20)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["status"], "error")
                self.assertFalse(input_path.exists())
                self.assertFalse(output_path.exists())
            finally:
                input_path.unlink(missing_ok=True)

    def test_rejects_input_file_outside_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp)
            plan_path = plan_dir / "foo_plan.json"
            write_plan(plan_path, [{"task_id": "TASK-001"}])
            outside_path = Path(tmp) / "outside.json"
            outside_path.write_text(
                json.dumps(valid_candidate(), ensure_ascii=False), encoding="utf-8"
            )
            output_path = plan_dir / "tasks" / "TASK-001.json"
            result = self._run(
                plan_path, "TASK-001", str(outside_path), output_path
            )
            self.assertEqual(result.returncode, 20)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "error")
            # 許可外パスは検証以前に拒否されるため、外部ファイルは削除されず残る。
            self.assertTrue(outside_path.exists())


if __name__ == "__main__":
    unittest.main()
