#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc-db index を検索する。"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List

import build_index
import hybrid_score
import lexical_search
import llm_rerank
from _utils import calculate_file_hash, load_checksums
from embedding_api import EMBEDDING_MODEL, call_embedding_api_single


def parse_args():
    parser = argparse.ArgumentParser(description="Search doc-db index")
    parser.add_argument("--category", required=True, choices=["rules", "specs"])
    parser.add_argument("--query", required=True)
    parser.add_argument("--mode", default="hybrid", choices=["emb", "lex", "hybrid", "rerank"])
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--doc-type", default="")
    return parser.parse_args()


def _error(message: str, hint: str = "-", exit_code: int = 2):
    sys.stderr.write(json.dumps({"error": message, "hint": hint}) + "\n")
    raise SystemExit(exit_code)


def load_index(index_path: Path) -> Dict:
    if not index_path.exists():
        _error("index_not_found", "run build_index first")
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _error("index_corrupted", "run build_index --full")
    return {}


def _load_index_or_rebuild(
    project_root: Path,
    category: str,
    doc_type: str,
    require_full: bool = False,
) -> Dict:
    index_path = build_index.get_index_path(project_root, category, doc_type)
    if not index_path.exists():
        rc = build_index.run_build(project_root, category, full=require_full, doc_type=doc_type)
        if rc != 0:
            _error("index_not_found", "run build_index first")
    return load_index(index_path)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _resolve_doc_types(category: str, doc_type: str) -> List[str]:
    if category != "specs":
        return [""]
    if doc_type:
        return [x.strip() for x in doc_type.split(",") if x.strip()]
    return ["requirement", "design"]


def _is_stale(project_root: Path, category: str, index: Dict, doc_type: str) -> bool:
    checksums_path = build_index.get_checksums_path(
        build_index.get_index_path(project_root, category, doc_type)
    )
    saved = load_checksums(checksums_path)
    index_generated_at = index.get("metadata", {}).get("generated_at", "")
    checksum_generated_at = build_index._read_checksums_generated_at(checksums_path)
    if checksum_generated_at and index_generated_at and checksum_generated_at != index_generated_at:
        _error("generated_at_mismatch", "run build_index --full")

    for rel, digest in saved.items():
        if calculate_file_hash(project_root / rel) != digest:
            return True
    current_files = set(build_index.resolve_target_files(project_root, category, doc_type))
    if current_files != set(saved.keys()):
        return True
    return False


def _ensure_fresh(project_root: Path, category: str, index: Dict, doc_type: str):
    if _is_stale(project_root, category, index, doc_type):
        rc = build_index.run_build(project_root, category, full=False, doc_type=doc_type)
        if rc != 0:
            _error("auto_rebuild_failed", "run build_index manually")


def _make_results(entries: List[Dict], ids: List[str], score_key: str) -> List[Dict]:
    mapping = {f"{e['path']}#{e['chunk_id']}": e for e in entries}
    out = []
    for row in ids:
        entry = mapping[row["chunk_id"]]
        out.append(
            {
                "path": entry["path"],
                "heading_path": entry["heading_path"],
                "body": entry["body"],
                "score": row["score"],
                "breakdown": {
                    "emb": row.get("emb_score", 0.0),
                    "lex": row.get("lex_score", 0.0),
                },
            }
        )
    return out


def search(project_root: Path, category: str, query: str, mode: str, top_n: int, doc_type: str = ""):
    if not query.strip():
        _error("query must not be empty", "provide non-empty --query")
    if top_n < 1:
        _error("top_n must be >= 1", "set --top-n 1..100")

    doc_types = _resolve_doc_types(category, doc_type)
    indexes = []
    for one_type in doc_types:
        index = _load_index_or_rebuild(project_root, category, one_type)
        if index.get("metadata", {}).get("model") not in ("", EMBEDDING_MODEL):
            _error("model_mismatch", "run build_index --full")
        _ensure_fresh(project_root, category, index, one_type)
        indexes.append(_load_index_or_rebuild(project_root, category, one_type))

    entries_map = {}
    for index in indexes:
        entries_map.update(index.get("entries", {}))
    entries = list(entries_map.values())

    fallback_used = False
    rerank_error = None
    rerank_api_calls = 0
    rerank_token_usage = 0

    if mode == "lex":
        lex = lexical_search.score_chunks(query, entries)
        results = [
            {
                "path": x["path"],
                "heading_path": x["heading_path"],
                "body": x["body"],
                "score": x["lex_score"],
                "breakdown": {"emb": 0.0, "lex": x["lex_score"]},
            }
            for x in lex[:top_n]
        ]
    else:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            _error("OPENAI_API_KEY not set", "export OPENAI_API_KEY=...")
        qvec = call_embedding_api_single(query, api_key)
        emb = []
        for key, entry in entries_map.items():
            emb_score = cosine_similarity(qvec, entry.get("embedding", []))
            emb.append({"chunk_id": key, "emb_score": emb_score, "score": emb_score})

        if mode == "emb":
            emb.sort(key=lambda x: (-x["emb_score"], x["chunk_id"]))
            ids = emb[:top_n]
            results = _make_results(entries, ids, "emb_score")
        else:
            lex = lexical_search.score_chunks(query, entries)
            lex_for_fuse = [
                {
                    "chunk_id": f"{x['path']}#{x['chunk_id']}",
                    "lex_score": x["lex_score"],
                }
                for x in lex
            ]
            fused = hybrid_score.combine_scores(emb, lex_for_fuse, method="rrf")
            emb_map = {row["chunk_id"]: row["emb_score"] for row in emb}
            lex_map = {row["chunk_id"]: row["lex_score"] for row in lex_for_fuse}
            ids = []
            for row in fused[: max(top_n, llm_rerank.MAX_CANDIDATES)]:
                row["emb_score"] = emb_map.get(row["chunk_id"], 0.0)
                row["lex_score"] = lex_map.get(row["chunk_id"], 0.0)
                ids.append(row)
            base_results = _make_results(entries, ids, "score")
            if mode == "hybrid":
                results = base_results[:top_n]
            else:
                candidates = []
                for row in ids:
                    # Build explicit candidate payload so rerank has stable ids and breakdown.
                    entry = entries_map.get(row["chunk_id"])
                    if entry is None:
                        continue
                    candidates.append(
                        {
                            "chunk_id": row["chunk_id"],
                            "path": entry["path"],
                            "heading_path": entry["heading_path"],
                            "body": entry["body"],
                            "score": row["score"],
                            "emb_score": row["emb_score"],
                            "lex_score": row["lex_score"],
                        }
                    )
                reranked, rerank_meta = llm_rerank.rerank(query, candidates, api_key)
                fallback_used = rerank_meta["fallback_used"]
                rerank_error = rerank_meta["rerank_error"]
                rerank_api_calls = rerank_meta["api_calls"]
                rerank_token_usage = rerank_meta["token_usage"]
                results = [
                    {
                        "path": c["path"],
                        "heading_path": c["heading_path"],
                        "body": c["body"],
                        "score": c.get("rerank_score", c["score"]),
                        "breakdown": {
                            "emb": c["emb_score"],
                            "lex": c["lex_score"],
                            "rerank": c.get("rerank_score", c["score"]),
                        },
                    }
                    for c in reranked[:top_n]
                ]

    output = {
        "results": results,
        "fallback_used": fallback_used,
        "rerank_error": rerank_error,
        "api_calls": {
            "embedding": 1 if mode in ("emb", "hybrid", "rerank") else 0,
            "rerank": rerank_api_calls,
        },
        "token_usage": {"embedding": 0, "rerank": rerank_token_usage},
        "build_state": "incomplete"
        if any(i.get("metadata", {}).get("build_state") == "incomplete" for i in indexes)
        else "complete",
        "incomplete_count": sum(len(i.get("metadata", {}).get("failed_chunks", [])) for i in indexes),
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


def main():
    args = parse_args()
    return search(
        Path.cwd().resolve(),
        args.category,
        args.query,
        args.mode,
        args.top_n,
        doc_type=args.doc_type,
    )


if __name__ == "__main__":
    raise SystemExit(main())
