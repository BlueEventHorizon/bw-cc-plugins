#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc-db の chunk 単位 index を構築する。"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import chunk_extractor
from _utils import calculate_file_hash, load_checksums
from doc_structure import (
    invert_doc_types_map,
    load_doc_structure,
    resolve_files,
    resolve_files_by_doc_type,
)
from embedding_api import EMBEDDING_MODEL, call_embedding_api

SCHEMA_VERSION = "1.0"
CHECKSUMS_SUFFIX = ".checksums.yaml"


def parse_args():
    parser = argparse.ArgumentParser(description="Build doc-db index")
    parser.add_argument("--category", required=True, choices=["rules", "specs"])
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--doc-type", default="")
    return parser.parse_args()


def get_index_path(project_root: Path, category: str, doc_type: str = "") -> Path:
    if category == "specs":
        suffix = f"{doc_type}_index.json" if doc_type else "specs_index.json"
        return project_root / f".claude/doc-db/index/specs/{suffix}"
    return project_root / ".claude/doc-db/index/rules/rules_index.json"


def get_checksums_path(index_path: Path) -> Path:
    return index_path.with_suffix(index_path.suffix + CHECKSUMS_SUFFIX)


def _read_checksums_generated_at(checksums_path: Path) -> str:
    if not checksums_path.exists():
        return ""
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("generated_at:"):
            return line.split(":", 1)[1].strip()
    return ""


def load_index(index_path: Path) -> Dict:
    if not index_path.exists():
        return {"metadata": {}, "entries": {}}
    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _render_checksums_content(checksums: Dict[str, str], generated_at: str) -> str:
    lines = [
        "# doc-db checksums",
        "# Auto-generated - do not edit",
        f"generated_at: {generated_at}",
        f"file_count: {len(checksums)}",
        "checksums:",
    ]
    for rel_path, hash_value in sorted(checksums.items()):
        lines.append(f"  {rel_path}: {hash_value}")
    return "\n".join(lines) + "\n"


def save_index_and_checksums_two_phase(
    index: Dict,
    index_path: Path,
    checksums: Dict[str, str],
    checksums_path: Path,
    generated_at: str,
):
    index_path.parent.mkdir(parents=True, exist_ok=True)
    checksums_path.parent.mkdir(parents=True, exist_ok=True)
    index_tmp = None
    checksums_tmp = None
    old_index_bytes = index_path.read_bytes() if index_path.exists() else None
    old_checksums_bytes = checksums_path.read_bytes() if checksums_path.exists() else None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=index_path.parent,
            delete=False,
            suffix=".tmp",
        ) as tf_index:
            index_tmp = Path(tf_index.name)
            json.dump(index, tf_index, ensure_ascii=False, separators=(",", ":"))
            tf_index.flush()
            os.fsync(tf_index.fileno())
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=checksums_path.parent,
            delete=False,
            suffix=".tmp",
        ) as tf_checksums:
            checksums_tmp = Path(tf_checksums.name)
            tf_checksums.write(_render_checksums_content(checksums, generated_at))
            tf_checksums.flush()
            os.fsync(tf_checksums.fileno())
        os.replace(index_tmp, index_path)
        try:
            os.replace(checksums_tmp, checksums_path)
        except Exception:
            if old_index_bytes is not None:
                index_path.write_bytes(old_index_bytes)
            else:
                index_path.unlink(missing_ok=True)
            if old_checksums_bytes is not None:
                checksums_path.write_bytes(old_checksums_bytes)
            else:
                checksums_path.unlink(missing_ok=True)
            raise
    except Exception:
        if index_tmp and index_tmp.exists():
            index_tmp.unlink(missing_ok=True)
        if checksums_tmp and checksums_tmp.exists():
            checksums_tmp.unlink(missing_ok=True)
        raise


def resolve_target_files(project_root: Path, category: str, doc_type: str) -> List[str]:
    config, _ = load_doc_structure(str(project_root))
    if doc_type:
        files = []
        for t in [x.strip() for x in doc_type.split(",") if x.strip()]:
            files.extend(resolve_files_by_doc_type(config, category, t, str(project_root)))
        return sorted(set(files))
    return resolve_files(config, category, str(project_root))


def resolve_specs_doc_types(project_root: Path) -> List[str]:
    config, _ = load_doc_structure(str(project_root))
    specs = config.get("specs", {})
    doc_types_map = specs.get("doc_types_map", {})
    return sorted(invert_doc_types_map(doc_types_map).keys())


def _validate_existing_schema(existing: Dict, full: bool):
    schema = existing.get("metadata", {}).get("schema_version")
    if schema and schema != SCHEMA_VERSION and not full:
        raise RuntimeError("schema mismatch: run with --full")


def _embed_chunks(chunk_records: List[Dict], api_key: str):
    texts = [c["body"] if c["body"].strip() else c["path"] for c in chunk_records]
    vectors = call_embedding_api(texts, api_key)
    for i, vector in enumerate(vectors):
        chunk_records[i]["embedding"] = vector
    return chunk_records


def _run_build_one(project_root: Path, category: str, full: bool = False, doc_type: str = "") -> int:
    index_path = get_index_path(project_root, category, doc_type)
    checksums_path = get_checksums_path(index_path)
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print(json.dumps({"status": "error", "error": "OPENAI_API_KEY is required"}))
        return 1

    existing = load_index(index_path)
    try:
        _validate_existing_schema(existing, full)
    except RuntimeError as e:
        print(json.dumps({"status": "error", "error": str(e), "hint": "use --full"}))
        return 2

    targets = resolve_target_files(project_root, category, doc_type)
    current_checksums = {p: calculate_file_hash(project_root / p) for p in targets}
    old_checksums = {} if full else load_checksums(checksums_path)

    changed = [p for p in targets if old_checksums.get(p) != current_checksums.get(p)]
    deleted = [p for p in old_checksums if p not in current_checksums]
    if not changed and not deleted and existing.get("entries"):
        print(json.dumps({"status": "ok", "message": "up-to-date"}))
        return 0

    entries = {} if full else dict(existing.get("entries", {}))
    for key, val in list(entries.items()):
        if val.get("path") in deleted:
            entries.pop(key, None)
    for key, val in list(entries.items()):
        if val.get("path") in changed:
            entries.pop(key, None)

    failed_chunks: List[Dict] = []
    to_embed: List[Dict] = []
    for rel_path in changed:
        abs_path = project_root / rel_path
        text = abs_path.read_text(encoding="utf-8")
        chunks = chunk_extractor.extract_chunks(rel_path, text)
        for c in chunks:
            to_embed.append(c)

    if to_embed:
        try:
            _embed_chunks(to_embed, api_key)
        except Exception as e:  # noqa: BLE001
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for c in to_embed:
                failed_chunks.append(
                    {
                        "chunk_id": c["chunk_id"],
                        "path": c["path"],
                        "error_type": "other",
                        "message": str(e),
                        "attempts": 1,
                        "last_failed_at": now,
                    }
                )
            to_embed = []

    for c in to_embed:
        key = f"{c['path']}#{c['chunk_id']}"
        entries[key] = {
            "path": c["path"],
            "chunk_id": c["chunk_id"],
            "heading_path": c["heading_path"],
            "body": c["body"],
            "char_range": c["char_range"],
            "embedding": c["embedding"],
            "checksum": current_checksums.get(c["path"], ""),
        }

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dims = 0
    if entries:
        dims = len(next(iter(entries.values())).get("embedding", []))
    index = {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "category": category,
            "doc_type": doc_type or None,
            "model": EMBEDDING_MODEL,
            "dimensions": dims,
            "generated_at": now,
            "chunk_count": len(entries),
            "file_count": len({v["path"] for v in entries.values()}),
            "build_state": "incomplete" if failed_chunks else "complete",
            "failed_chunks": failed_chunks,
        },
        "entries": entries,
    }
    save_index_and_checksums_two_phase(index, index_path, current_checksums, checksums_path, now)
    print(
        json.dumps(
            {
                "status": "ok",
                "index": str(index_path.relative_to(project_root)),
                "build_state": index["metadata"]["build_state"],
                "failed_count": len(failed_chunks),
            }
        )
    )
    return 0


def run_build(project_root: Path, category: str, full: bool = False, doc_type: str = "") -> int:
    if category == "specs":
        if doc_type:
            doc_types = [x.strip() for x in doc_type.split(",") if x.strip()]
        else:
            doc_types = resolve_specs_doc_types(project_root)
        for one_type in doc_types:
            rc = _run_build_one(project_root, category, full=full, doc_type=one_type)
            if rc != 0:
                return rc
        return 0
    return _run_build_one(project_root, category, full=full, doc_type=doc_type)


def _run_check_one(project_root: Path, category: str, doc_type: str = ""):
    index_path = get_index_path(project_root, category, doc_type)
    checksums_path = get_checksums_path(index_path)
    if not index_path.exists():
        print(json.dumps({"status": "stale", "reason": "index_not_found"}))
        return 0
    index = load_index(index_path)
    files = resolve_target_files(project_root, category, doc_type)
    disk = {p: calculate_file_hash(project_root / p) for p in files}
    saved = load_checksums(checksums_path)
    if disk != saved:
        print(json.dumps({"status": "stale", "reason": "checksum_mismatch"}))
        return 0
    checksum_generated_at = _read_checksums_generated_at(checksums_path)
    if checksum_generated_at and checksum_generated_at != index.get("metadata", {}).get("generated_at"):
        print(json.dumps({"status": "stale", "reason": "generated_at_mismatch"}))
        return 0
    print(json.dumps({"status": "fresh"}))
    return 0


def run_check(project_root: Path, category: str):
    if category == "specs":
        doc_types = resolve_specs_doc_types(project_root)
        for one_type in doc_types:
            _run_check_one(project_root, category, one_type)
        return 0
    return _run_check_one(project_root, category)


def main():
    args = parse_args()
    project_root = Path.cwd().resolve()
    if args.check:
        return run_check(project_root, args.category)
    return run_build(project_root, args.category, full=args.full, doc_type=args.doc_type)


if __name__ == "__main__":
    raise SystemExit(main())
