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
from session.update_plan import read_plan, write_plan  # noqa: E402
from session.yaml_utils import atomic_write_text  # noqa: E402

# (title, location, perspective) で既存 finding と照合する際の正規化キー生成
def _finding_key(f):
    return (
        (f.get("title") or "").strip(),
        (f.get("location") or "").strip(),
        (f.get("perspective") or "").strip(),
    )


# merge 時に既存 item から保持するフィールド (evaluator / fixer / present-findings が
# 書き込む状態フィールド。再 extract で巻き戻してはならない)
_PRESERVED_FIELDS = (
    "status",
    "recommendation",
    "auto_fixable",
    "reason",
    "skip_reason",
    "files_modified",
    "fixed_at",
)

# merge 時に新 finding で上書きするフィールド (reviewer 由来の表示・分類情報)
_OVERRIDABLE_FIELDS = (
    "severity",
    "title",
    "priority",
    "perspective",
    "location",
    "body",
)


def _merge_plan_items(session_dir, new_findings):
    """既存 plan.yaml と new_findings を merge する。

    動作:
      - (title, location, perspective) で既存 item と照合
      - マッチした場合:
          * id は既存値で保持 (新 finding の incremental id は捨てる)
          * status / recommendation / auto_fixable / reason / skip_reason /
            files_modified / fixed_at は既存値を維持
          * severity / title / priority などの表示・分類フィールドは新 finding で上書き
      - 未マッチの新規 finding:
          * max(既存 id) + 1 から連番採番して append
      - 既存 item で new_findings に登場しないものはそのまま保持
        (--diff-only 後の append で過去 finding が消えないようにするため)

    Returns:
        merge 後の items list (id 昇順ソート済み)
    """
    try:
        existing_plan = read_plan(session_dir)
    except FileNotFoundError:
        existing_plan = {"items": []}

    existing_items = existing_plan.get("items") or []
    existing_by_key = {
        _finding_key(it): it
        for it in existing_items
        if isinstance(it, dict)
    }

    max_id = 0
    for it in existing_items:
        if isinstance(it, dict) and isinstance(it.get("id"), int):
            max_id = max(max_id, it["id"])

    used_existing_ids = set()
    merged_items = []
    next_new_id = max_id + 1

    for new_f in new_findings:
        key = _finding_key(new_f)
        if key in existing_by_key:
            existing = existing_by_key[key]
            used_existing_ids.add(existing.get("id"))
            merged = dict(existing)
            for field in _OVERRIDABLE_FIELDS:
                if field in new_f and new_f[field] not in (None, ""):
                    merged[field] = new_f[field]
            merged_items.append(merged)
            continue

        new_item = {k: v for k, v in new_f.items() if k != "id"}
        new_item["id"] = next_new_id
        next_new_id += 1
        merged_items.append(new_item)

    # 既存 item で new_findings に登場しなかったものを保持
    for it in existing_items:
        if not isinstance(it, dict):
            continue
        if it.get("id") not in used_existing_ids and _finding_key(it) not in {
            _finding_key(m) for m in merged_items
        }:
            merged_items.append(it)

    merged_items.sort(
        key=lambda x: x.get("id", 0) if isinstance(x.get("id"), int) else 0
    )
    return merged_items


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

        if not findings:
            print(
                f"Warning: {filename}: content is non-empty but no findings were "
                f"extracted (possible parse miss — check severity markers)",
                file=sys.stderr,
            )

        processed_files.append(filename)

        for f in findings:
            global_id += 1
            f["id"] = global_id
            if perspective:
                f["perspective"] = perspective
            all_findings.append(f)

    return all_findings, processed_files, failed_files


def run_session_dir_mode(session_dir, review_only=False):
    """session_dir モード: review_*.md を glob で収集し統合する。

    plan.yaml の生成は冪等な merge 動作 (修正 A):
      - 既存 plan.yaml がある場合: (title, location, perspective) で照合し、
        evaluator / fixer / present-findings が書いた状態フィールド
        (status / recommendation / auto_fixable / reason / skip_reason /
        files_modified / fixed_at) を保持したまま、reviewer 由来の表示・分類
        フィールドのみを更新する。新規 finding は max(id)+1 から連番採番する。
      - 既存 plan.yaml がない場合: 通常通り新規生成する。
    """
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
    plan_path = session_path / "plan.yaml"
    if not review_only:
        if plan_path.exists():
            merged_items = _merge_plan_items(session_dir, all_findings)
            write_plan(session_dir, {"items": merged_items})
        else:
            store.write_text("plan.yaml", generate_plan_yaml(all_findings))

    store.write_text("review.md", generate_review_md(all_findings))

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
