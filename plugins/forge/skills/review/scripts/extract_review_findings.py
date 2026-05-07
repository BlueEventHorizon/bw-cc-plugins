#!/usr/bin/env python3
"""review_*.md から指摘事項を抽出し plan.yaml / review.md を生成する。"""

import glob
import json
import sys
from pathlib import Path

# plugins/forge/skills/review/scripts/ → plugins/forge/scripts/
_FORGE_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
_FORGE_SCRIPTS_STR = str(_FORGE_SCRIPTS)
if _FORGE_SCRIPTS_STR in sys.path:
    sys.path.remove(_FORGE_SCRIPTS_STR)
sys.path.insert(0, _FORGE_SCRIPTS_STR)

_loaded_review = sys.modules.get("review")
if _loaded_review:
    loaded_path = str(getattr(_loaded_review, "__file__", ""))
    if not loaded_path.startswith(_FORGE_SCRIPTS_STR):
        del sys.modules["review"]

from review.findings_parser import (  # noqa: E402
    extract_findings,
    extract_perspective_from_filename,
)
from review.findings_renderer import (  # noqa: E402
    generate_plan_yaml,
    generate_review_md,
    summarize,
)
from session.store import SessionStore  # noqa: E402
from session.yaml_utils import atomic_write_text  # noqa: E402


def _emit_error(error):
    print(json.dumps({"status": "error", "error": error}, ensure_ascii=False, indent=2),
          file=sys.stderr)


def _collect_review_files(session_path):
    """review_*.md を収集する。.raw.md は evaluator backup なので除外する。"""
    return sorted(
        f for f in glob.glob(str(session_path / "review_*.md"))
        if not Path(f).name.endswith(".raw.md")
    )


def _extract_all_findings(review_files):
    all_findings = []
    global_id = 0
    processed_files = []
    failed_files = []

    for review_file in review_files:
        review_path = Path(review_file)
        filename = review_path.name
        perspective = extract_perspective_from_filename(filename)

        try:
            content = review_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"Warning: {filename}: {e}", file=sys.stderr)
            failed_files.append(filename)
            continue

        findings = extract_findings(content)
        if not findings and not content.strip():
            failed_files.append(filename)
            continue

        processed_files.append(filename)

        for f in findings:
            global_id += 1
            f["id"] = global_id
            if perspective:
                f["perspective"] = perspective
            all_findings.append(f)

    return all_findings, processed_files, failed_files


def run_session_dir_mode(session_dir, review_only=False):
    """session_dir モード: review_*.md を glob で収集し統合する。"""
    session_path = Path(session_dir)
    if not session_path.is_dir():
        _emit_error(f"Directory not found: {session_dir}")
        return 1

    review_files = _collect_review_files(session_path)
    if not review_files:
        _emit_error(f"No review_*.md files found in: {session_dir}")
        return 1

    all_findings, processed_files, failed_files = _extract_all_findings(review_files)
    if not all_findings and not processed_files:
        _emit_error("All review files failed or contained no findings")
        return 1

    store = SessionStore(session_path)
    if not review_only:
        store.write_text("plan.yaml", generate_plan_yaml(all_findings), meta=None)

    review_meta = None
    if not review_only:
        review_meta = {
            "phase": "review_extracted",
            "phase_status": "completed",
            "active_artifact": "review.md",
        }
    store.write_text("review.md", generate_review_md(all_findings), meta=review_meta)

    result = summarize(all_findings)
    result["status"] = "ok"
    result["files_processed"] = len(processed_files)
    result["files_failed"] = len(failed_files)
    result["review_only"] = review_only
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_legacy_mode(review_md_path, output_path):
    """旧モード（後方互換）: 単一ファイルを処理する。"""
    try:
        content = Path(review_md_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        _emit_error(f"File not found: {review_md_path}")
        return 1

    findings = extract_findings(content)
    plan_path = Path(output_path)
    atomic_write_text(plan_path, generate_plan_yaml(findings))

    result = summarize(findings)
    result["status"] = "ok"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main():
    args = sys.argv[1:]
    review_only = False
    if "--review-only" in args:
        review_only = True
        args = [a for a in args if a != "--review-only"]

    if len(args) == 1:
        sys.exit(run_session_dir_mode(args[0], review_only=review_only))
    if len(args) == 2 and not review_only:
        sys.exit(run_legacy_mode(args[0], args[1]))

    print("Usage:", file=sys.stderr)
    print("  extract_review_findings.py <session_dir>", file=sys.stderr)
    print("  extract_review_findings.py <session_dir> --review-only", file=sys.stderr)
    print("  extract_review_findings.py <review_md_path> <output_plan_yaml>", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
