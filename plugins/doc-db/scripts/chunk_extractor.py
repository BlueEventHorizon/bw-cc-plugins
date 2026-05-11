#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown を見出し境界で chunk 分割する。"""

from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Tuple

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
MAX_CHUNK_CHARS = 8192


def _split_large_chunk(body: str, start: int, end: int, max_chars: int) -> List[Tuple[str, int, int]]:
    if len(body) <= max_chars:
        return [(body, start, end)]

    segments: List[Tuple[str, int, int]] = []
    rel = 0
    while rel < len(body):
        next_rel = min(rel + max_chars, len(body))
        if next_rel < len(body):
            window = body[rel:next_rel]
            split_at = window.rfind("\n\n")
            if split_at > 0:
                next_rel = rel + split_at + 2
        piece = body[rel:next_rel]
        if piece.strip():
            seg_start = start + rel
            seg_end = start + next_rel
            segments.append((piece, seg_start, seg_end))
        rel = next_rel

    if not segments:
        return [(body[:max_chars], start, min(start + max_chars, end))]
    return segments


def _build_chunk_id(path: str, heading_path: List[str], seen: Dict[str, int]) -> str:
    base = hashlib.sha256(f"{path}|{' > '.join(heading_path)}".encode("utf-8")).hexdigest()[:8]
    count = seen.get(base, 0) + 1
    seen[base] = count
    if count == 1:
        return base
    return f"{base}-{count}"


def extract_chunks(
    path: str,
    markdown_text: str,
    max_chunk_chars: int = MAX_CHUNK_CHARS,
    min_chunk_level: int = 6,
) -> List[Dict]:
    """Markdown を見出し境界でチャンク分割する。

    min_chunk_level: このレベル以下の見出しのみチャンク境界とする（デフォルト 6 = 全レベル）。
    例えば min_chunk_level=1 にすると h1 のみが境界となり、h2 以下は親チャンクに含まれる。
    """
    matches = list(HEADING_RE.finditer(markdown_text))
    chunks: List[Dict] = []
    seen_ids: Dict[str, int] = {}

    if not matches:
        body = markdown_text
        for segment, start, end in _split_large_chunk(body, 0, len(markdown_text), max_chunk_chars):
            heading_path: List[str] = []
            chunks.append(
                {
                    "path": path,
                    "heading_path": heading_path,
                    "body": segment,
                    "char_range": [start, end],
                    "chunk_id": _build_chunk_id(path, heading_path, seen_ids),
                }
            )
        return chunks

    # min_chunk_level 以下の見出しのみをチャンク境界とする
    boundary_matches = [m for m in matches if len(m.group(1)) <= min_chunk_level]
    if not boundary_matches:
        boundary_matches = matches

    heading_stack: List[str] = []
    for idx, match in enumerate(boundary_matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        content_start = match.start()
        content_end = boundary_matches[idx + 1].start() if idx + 1 < len(boundary_matches) else len(markdown_text)
        section_text = markdown_text[content_start:content_end]

        heading_stack = heading_stack[: level - 1]
        heading_stack.append(title)
        heading_path = list(heading_stack)

        for segment, seg_start, seg_end in _split_large_chunk(
            section_text, content_start, content_end, max_chunk_chars
        ):
            chunks.append(
                {
                    "path": path,
                    "heading_path": heading_path,
                    "body": segment,
                    "char_range": [seg_start, seg_end],
                    "chunk_id": _build_chunk_id(path, heading_path, seen_ids),
                }
            )

    return chunks
