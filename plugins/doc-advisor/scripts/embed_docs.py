#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Embedding インデックス構築スクリプト (doc-advisor plugin)

文書メタデータを OpenAI Embedding API でベクトル化し、
{category}_index.json に保存する。差分更新・全体再構築・
staleness check の3モードに対応。

Usage:
    python3 embed_docs.py --category {specs|rules} [--full] [--check]

Options:
    --category  対象カテゴリ（必須）: specs または rules
    --full      全文書を再構築（省略時は差分更新）
    --check     インデックスの新鮮さを確認のみ（再構築なし）

Run from: プロジェクトルート
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from toc_utils import (
    ConfigNotReadyError,
    EMBEDDING_MODEL,
    calculate_file_hash,
    get_all_md_files,
    get_index_path,
    init_common_config,
    load_checksums,
    normalize_path,
    resolve_config_path,
    write_checksums_yaml,
)

# Embedding API バッチ上限
EMBEDDING_BATCH_SIZE = 100

# OpenAI Embedding API エンドポイント
OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"

# API エラー時のリトライ回数
API_RETRY_COUNT = 1

# レート制限（429）時の待機秒数
RATE_LIMIT_WAIT_SECONDS = 60


def log(msg):
    """進捗ログを stderr に出力する。stdout は JSON 出力専用。"""
    print(msg, file=sys.stderr)


def parse_args():
    """コマンドライン引数をパースして返す。"""
    parser = argparse.ArgumentParser(
        description="Embedding インデックスを構築・更新する"
    )
    parser.add_argument(
        "--category",
        required=True,
        choices=["rules", "specs"],
        help="対象カテゴリ: rules または specs",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="全文書を再構築（省略時は差分更新）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="インデックスの新鮮さを確認のみ（再構築なし）",
    )
    return parser.parse_args()


def load_index(index_path):
    """既存の インデックス JSON を読み込む。

    Args:
        index_path: インデックスファイルパス (Path)

    Returns:
        dict: インデックスデータ。存在しない場合は空 dict。

    Raises:
        ValueError: JSON パースエラー（破損ファイル）
    """
    index_path = Path(index_path)
    if not index_path.exists():
        return {}
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"インデックス JSON の読み込みに失敗しました: {index_path} — {e}") from e


def save_index(index, index_path):
    """インデックスデータを JSON ファイルに保存する。

    Args:
        index: 保存するインデックスデータ (dict)
        index_path: 保存先パス (Path)
    """
    index_path = Path(index_path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))


# text-embedding-3-small のトークン上限: 8,191
# 日本語は保守的に 1文字≒1トークンで見積もり、安全マージンを確保
EMBEDDING_MAX_CHARS = 7500


def read_file_content(file_path):
    """ファイル本文を読み込み、Embedding テキストとして返す。

    Args:
        file_path: ファイルの絶対パス (Path)

    Returns:
        str: ファイル本文
    """
    return file_path.read_text(encoding="utf-8")


def extract_title(content, fallback_name=""):
    """Markdown ファイルからタイトルを抽出する。

    以下の優先順で抽出する:
    1. YAML frontmatter の title フィールド
    2. 最初の # 見出し
    3. fallback_name（ファイル名など）

    Args:
        content: ファイル本文
        fallback_name: タイトルが見つからない場合のフォールバック

    Returns:
        str: 抽出されたタイトル
    """
    # YAML frontmatter からの抽出
    if content.startswith("---"):
        end_idx = content.find("---", 3)
        if end_idx != -1:
            frontmatter = content[3:end_idx]
            for line in frontmatter.split("\n"):
                stripped = line.strip()
                if stripped.startswith("title:"):
                    title = stripped[6:].strip().strip('"').strip("'")
                    if title:
                        return title

    # 最初の # 見出しからの抽出
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("##"):
            title = stripped[2:].strip()
            if title:
                return title

    return fallback_name


def truncate_to_token_limit(text, max_chars=EMBEDDING_MAX_CHARS):
    """テキストをトークン上限に合わせて切り詰める。

    text-embedding-3-small の上限（8,191 tokens）に対し、
    日本語テキストを保守的に 1文字≒1トークンで見積もる。

    Args:
        text: 入力テキスト
        max_chars: 最大文字数（デフォルト: EMBEDDING_MAX_CHARS）

    Returns:
        str: 切り詰められたテキスト（max_chars 以下の場合はそのまま）
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def call_embedding_api(texts, api_key):
    """OpenAI Embedding API をバッチ呼び出しする。

    Args:
        texts: Embedding するテキストリスト
        api_key: OpenAI API キー

    Returns:
        list[list[float]]: テキストに対応する Embedding ベクトルのリスト

    Raises:
        RuntimeError: API 呼び出し失敗（リトライ後も失敗）
    """
    payload = json.dumps({
        "model": EMBEDDING_MODEL,
        "input": texts,
    }).encode("utf-8")

    req = urllib.request.Request(
        OPENAI_EMBEDDINGS_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    last_error = None
    for attempt in range(API_RETRY_COUNT + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                # data は入力順にソート済みのはず。index でソートして安全に取得する
                embeddings = sorted(result["data"], key=lambda x: x["index"])
                if len(embeddings) != len(texts):
                    raise RuntimeError(
                        f"API 応答件数の不一致: 送信 {len(texts)} 件, 受信 {len(embeddings)} 件"
                    )
                return [e["embedding"] for e in embeddings]

        except urllib.error.HTTPError as e:
            if e.code == 429:
                # レート制限: 待機してリトライ
                if attempt < API_RETRY_COUNT:
                    log(f"  レート制限 (429)。{RATE_LIMIT_WAIT_SECONDS}秒待機してリトライします...")
                    time.sleep(RATE_LIMIT_WAIT_SECONDS)
                    last_error = e
                    continue
                last_error = e
            elif e.code == 401:
                raise RuntimeError(
                    f"API 認証エラー (401)。OPENAI_API_KEY が正しいか確認してください。"
                ) from e
            else:
                if attempt < API_RETRY_COUNT:
                    log(f"  API エラー ({e.code})。リトライします...")
                    last_error = e
                    continue
                last_error = e

        except urllib.error.URLError as e:
            if attempt < API_RETRY_COUNT:
                log(f"  ネットワークエラー。リトライします: {e}")
                last_error = e
                continue
            last_error = e

    raise RuntimeError(f"API 呼び出し失敗: {last_error}") from last_error


def get_source_file_path(md_file, root_dir, root_dir_name):
    """プロジェクト相対パスを取得する。

    Args:
        md_file: ファイルの絶対パス (Path)
        root_dir: ルートディレクトリ絶対パス (Path)
        root_dir_name: ルートディレクトリ名（プロジェクト相対）

    Returns:
        str: {root_dir_name}/{相対パス} 形式のプロジェクト相対パス
    """
    rel_path = normalize_path(md_file.relative_to(root_dir))
    return f"{root_dir_name}/{rel_path}"


def run_check_mode(category, common, index_path, checksums_file):
    """--check モード: インデックスの新鮮さを確認して JSON 出力する。

    Args:
        category: 'rules' または 'specs'
        common: init_common_config() の返り値
        index_path: インデックスファイルパス (Path)
        checksums_file: チェックサムファイルパス (Path)
    """
    if not index_path.exists():
        print(json.dumps({
            "status": "stale",
            "reason": "index_not_found",
            "message": f"インデックスが存在しません。embed_docs.py --category {category} を実行してください。",
        }))
        return

    # チェックサムと現在のファイルを比較
    old_checksums = load_checksums(checksums_file)
    if not old_checksums:
        print(json.dumps({
            "status": "stale",
            "reason": "checksums_not_found",
            "message": f"チェックサムファイルが存在しません。embed_docs.py --category {category} --full を実行してください。",
        }))
        return

    all_files, file_root_map = get_all_md_files(common)
    current_files = {}
    for f in all_files:
        root_dir, root_dir_name = file_root_map[f]
        current_files[get_source_file_path(f, root_dir, root_dir_name)] = f

    new_count = 0
    modified_count = 0
    for source_file, full_path in current_files.items():
        current_hash = calculate_file_hash(full_path)
        if current_hash is None:
            continue
        old_hash = old_checksums.get(source_file)
        if old_hash is None:
            new_count += 1
        elif current_hash != old_hash:
            modified_count += 1

    deleted_count = sum(1 for sf in old_checksums if sf not in current_files)
    total = new_count + modified_count + deleted_count

    if total > 0:
        parts = []
        if new_count:
            parts.append(f"{new_count} new")
        if modified_count:
            parts.append(f"{modified_count} modified")
        if deleted_count:
            parts.append(f"{deleted_count} deleted")
        print(json.dumps({
            "status": "stale",
            "reason": ", ".join(parts),
            "message": f"インデックスが古い状態です ({', '.join(parts)})。embed_docs.py --category {category} を実行してください。",
        }))
    else:
        print(json.dumps({
            "status": "fresh",
            "message": "インデックスは最新です。",
        }))


def build_index(category, common, index_path, checksums_file, full_mode, api_key):
    """インデックスを構築・更新する（差分または全体）。

    Args:
        category: 'rules' または 'specs'
        common: init_common_config() の返り値
        index_path: インデックスファイルパス (Path)
        checksums_file: チェックサムファイルパス (Path)
        full_mode: True の場合は全体再構築、False の場合は差分更新
        api_key: OpenAI API キー

    Returns:
        int: 終了コード（0=成功, 1=失敗）
    """
    project_root = common["project_root"]

    # 全対象ファイルを取得
    all_files, file_root_map = get_all_md_files(common)
    log(f"対象ファイル数: {len(all_files)}")

    # 現在のファイル一覧（プロジェクト相対パス → 絶対パス）
    current_files = {}
    for f in all_files:
        root_dir, root_dir_name = file_root_map[f]
        source_file = get_source_file_path(f, root_dir, root_dir_name)
        current_files[source_file] = f

    if full_mode:
        # 全体モード: 全ファイルを処理
        target_files = list(current_files.items())
        deleted_files = []
        existing_index = {"entries": {}}
        log(f"全体モード: {len(target_files)} ファイルを処理します")
    else:
        # 差分モード: 変更・新規ファイルのみ処理
        old_checksums = load_checksums(checksums_file)

        # 既存インデックスを読み込む（破損の場合は全体再構築に切り替え）
        try:
            existing_index = load_index(index_path)
        except ValueError as e:
            log(f"警告: {e} — 全体再構築にフォールバックします")
            existing_index = {"entries": {}}
            full_mode = True
            old_checksums = {}

        if not existing_index:
            existing_index = {"entries": {}}

        target_files = []
        for source_file, full_path in current_files.items():
            current_hash = calculate_file_hash(full_path)
            if current_hash is None:
                continue
            old_hash = old_checksums.get(source_file)
            if old_hash is None:
                log(f"  [新規] {source_file}")
                target_files.append((source_file, full_path))
            elif current_hash != old_hash:
                log(f"  [変更] {source_file}")
                target_files.append((source_file, full_path))

        # 削除ファイルの検出
        deleted_files = [sf for sf in old_checksums if sf not in current_files]
        for sf in deleted_files:
            log(f"  [削除] {sf}")

        if not target_files and not deleted_files:
            log("変更なし — インデックスは最新です")
            print(json.dumps({"status": "ok", "message": "インデックスは最新です。", "file_count": len(all_files)}))
            return 0

        log(f"差分モード: {len(target_files)} 件の変更, {len(deleted_files)} 件の削除")

    # 削除ファイルをインデックスから除去
    entries = existing_index.get("entries", {})
    for sf in deleted_files:
        entries.pop(sf, None)

    # Embedding テキストを生成（ファイル本文を直接使用）
    texts_to_embed = []
    paths_to_embed = []
    for source_file, full_path in target_files:
        text = read_file_content(full_path)
        title = extract_title(text, source_file)
        # 空ファイルの場合はファイルパスと title をフォールバックテキストとして使用
        if not text.strip():
            text = f"{title}\n{source_file}"
        text = truncate_to_token_limit(text)
        texts_to_embed.append(text)
        paths_to_embed.append((source_file, full_path, title))

    # バッチ処理で Embedding API を呼び出す
    success_count = 0
    failed_sources = []
    batch_failed = False

    for batch_start in range(0, len(texts_to_embed), EMBEDDING_BATCH_SIZE):
        batch_end = min(batch_start + EMBEDDING_BATCH_SIZE, len(texts_to_embed))
        batch_texts = texts_to_embed[batch_start:batch_end]
        batch_paths = paths_to_embed[batch_start:batch_end]

        log(f"  Embedding API: {batch_start + 1}〜{batch_end} 件目")

        try:
            embeddings = call_embedding_api(batch_texts, api_key)
        except RuntimeError as e:
            log(f"  エラー: バッチ {batch_start + 1}〜{batch_end} の処理に失敗しました: {e}")
            # 部分失敗: このバッチおよび残りバッチをスキップし、処理済み分を保存する
            for source_file, _, _ in batch_paths:
                failed_sources.append(source_file)
            # 残りバッチのファイルも failed_sources に追加（次回差分更新で再処理される）
            for remaining_start in range(batch_end, len(texts_to_embed), EMBEDDING_BATCH_SIZE):
                remaining_end = min(remaining_start + EMBEDDING_BATCH_SIZE, len(texts_to_embed))
                for source_file, _, _ in paths_to_embed[remaining_start:remaining_end]:
                    failed_sources.append(source_file)
            batch_failed = True
            break

        # 結果をインデックスに反映
        for i, (source_file, full_path, title) in enumerate(batch_paths):
            checksum = calculate_file_hash(full_path)
            entries[source_file] = {
                "title": title,
                "embedding": embeddings[i],
                "checksum": checksum or "",
            }
            success_count += 1

    # インデックスを保存（処理済み分のみ。部分失敗でも保存して冪等性を保証）
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index_data = {
        "metadata": {
            "category": category,
            "model": EMBEDDING_MODEL,
            "dimensions": len(next(iter(entries.values()))["embedding"]) if entries else 0,
            "generated_at": now,
            "file_count": len(entries),
        },
        "entries": entries,
    }
    save_index(index_data, index_path)
    log(f"インデックスを保存しました: {index_path} ({len(entries)} 件)")

    # チェックサムを更新（処理成功ファイルのみ）
    current_checksums = {}
    for source_file, full_path in current_files.items():
        # 失敗したファイルはチェックサムを更新しない（次回の差分で再処理される）
        if source_file in failed_sources:
            continue
        checksum = calculate_file_hash(full_path)
        if checksum is not None:
            current_checksums[source_file] = checksum

    checksums_file_path = Path(checksums_file)
    checksums_file_path.parent.mkdir(parents=True, exist_ok=True)
    write_checksums_yaml(
        current_checksums,
        checksums_file_path,
        header_comment=f"Embedding index checksums for {category}",
    )
    log(f"チェックサムを更新しました: {len(current_checksums)} 件")

    if batch_failed and failed_sources:
        log(f"警告: {len(failed_sources)} 件の処理に失敗しました。次回の差分更新で自動的に再処理されます。")
        print(json.dumps({
            "status": "partial",
            "message": f"{success_count} 件処理成功、{len(failed_sources)} 件失敗（次回差分更新で再処理されます）",
            "file_count": len(entries),
            "failed_count": len(failed_sources),
        }))
        return 1

    print(json.dumps({
        "status": "ok",
        "message": f"インデックスを構築しました。{success_count} 件処理、{len(deleted_files)} 件削除。",
        "file_count": len(entries),
    }))
    return 0


def main():
    """メインエントリポイント。"""
    args = parse_args()
    category = args.category

    # 設定を初期化
    try:
        common = init_common_config(category)
    except ConfigNotReadyError as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        return 1
    except (RuntimeError, FileNotFoundError) as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        return 1

    project_root = common["project_root"]
    config = common["config"]
    default_dir = project_root / category
    checksums_file = resolve_config_path(
        config.get("checksums_file", f".claude/doc-advisor/toc/{category}/.index_checksums.yaml"),
        default_dir,
        project_root,
    )
    index_path = get_index_path(category, project_root)

    # --check モード
    if args.check:
        run_check_mode(category, common, index_path, checksums_file)
        return 0

    # API キーの確認
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print(json.dumps({
            "status": "error",
            "error": (
                "OPENAI_API_KEY が設定されていません。"
                "export OPENAI_API_KEY='your-api-key' を実行してください。"
            ),
        }))
        return 1

    # インデックス構築（差分または全体）
    full_mode = args.full
    # インデックスが存在しない場合は自動的に全体モードに切り替え
    if not index_path.exists():
        if not full_mode:
            log(f"インデックスが存在しません。全体モードで構築します。")
        full_mode = True

    return build_index(category, common, index_path, checksums_file, full_mode, api_key)


if __name__ == "__main__":
    sys.exit(main())
