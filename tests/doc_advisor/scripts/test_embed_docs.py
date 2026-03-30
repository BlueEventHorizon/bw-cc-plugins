#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""embed_docs.py のユニットテスト。

テスト対象:
- build_embedding_text() のテスト（API 呼び出しなし）
- get_index_path() のパス生成テスト
- インデックス JSON の読み書きラウンドトリップテスト
- call_embedding_api() の API モックテスト
- --check モードの stale/fresh 出力テスト
- CLI 統合テスト（subprocess 経由）
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# テスト対象モジュールの import
SCRIPTS_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'plugins', 'doc-advisor', 'scripts'
))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

EMBED_DOCS_SCRIPT = os.path.join(SCRIPTS_DIR, 'embed_docs.py')

import embed_docs
from embed_docs import (
    build_embedding_text,
    call_embedding_api,
    get_index_path,
    load_index,
    save_index,
)


# 固定テストベクトル（1536 次元）
FIXED_VECTOR = [1.0] + [0.0] * 1535
FIXED_VECTOR_2 = [0.0] + [1.0] + [0.0] * 1534


def _make_api_response(vectors):
    """OpenAI Embedding API のレスポンス JSON を生成する。

    Args:
        vectors: list[list[float]] — ベクトルのリスト

    Returns:
        bytes: JSON レスポンスバイト列
    """
    data = [{"index": i, "embedding": v} for i, v in enumerate(vectors)]
    return json.dumps({"data": data}).encode("utf-8")


# ===========================================================================
# build_embedding_text() テスト
# ===========================================================================

class TestBuildEmbeddingText(unittest.TestCase):
    """build_embedding_text() の単体テスト。"""

    def test_all_fields_present(self):
        """全フィールドが揃っている場合のテキスト生成"""
        metadata = {
            "title": "設計書タイトル",
            "purpose": "設計目的の説明",
            "keywords": ["セマンティック", "検索"],
            "applicable_tasks": ["設計", "レビュー"],
            "content_details": ["詳細1", "詳細2"],
        }
        result = build_embedding_text(metadata)
        self.assertIn("設計書タイトル", result)
        self.assertIn("設計目的の説明", result)
        self.assertIn("セマンティック 検索", result)
        self.assertIn("設計 レビュー", result)
        self.assertIn("詳細1\n詳細2", result)

    def test_fields_order(self):
        """フィールドが重要度順（title → purpose → keywords → applicable_tasks → content_details）に結合される"""
        metadata = {
            "title": "TITLE",
            "purpose": "PURPOSE",
            "keywords": ["KW1", "KW2"],
            "applicable_tasks": ["TASK1"],
            "content_details": ["DETAIL1"],
        }
        result = build_embedding_text(metadata)
        lines = result.split("\n")
        self.assertEqual(lines[0], "TITLE")
        self.assertEqual(lines[1], "PURPOSE")
        self.assertEqual(lines[2], "KW1 KW2")
        self.assertEqual(lines[3], "TASK1")
        self.assertEqual(lines[4], "DETAIL1")

    def test_missing_optional_fields(self):
        """title のみの場合、他のフィールドはスキップされる"""
        metadata = {"title": "タイトルのみ"}
        result = build_embedding_text(metadata)
        self.assertEqual(result, "タイトルのみ")

    def test_empty_metadata(self):
        """空メタデータの場合は空文字列を返す"""
        result = build_embedding_text({})
        self.assertEqual(result, "")

    def test_none_values_skipped(self):
        """None 値のフィールドはスキップされる"""
        metadata = {"title": "タイトル", "purpose": None, "keywords": None}
        result = build_embedding_text(metadata)
        self.assertEqual(result, "タイトル")

    def test_empty_list_fields_skipped(self):
        """空リストのフィールドはスキップされる"""
        metadata = {"title": "タイトル", "keywords": [], "applicable_tasks": []}
        result = build_embedding_text(metadata)
        self.assertEqual(result, "タイトル")

    def test_string_keywords(self):
        """keywords が文字列の場合もそのまま使用される"""
        metadata = {"title": "T", "keywords": "キーワード文字列"}
        result = build_embedding_text(metadata)
        self.assertIn("キーワード文字列", result)

    def test_string_content_details(self):
        """content_details が文字列の場合もそのまま使用される"""
        metadata = {"title": "T", "content_details": "詳細文字列"}
        result = build_embedding_text(metadata)
        self.assertIn("詳細文字列", result)


# ===========================================================================
# get_index_path() テスト
# ===========================================================================

class TestGetIndexPath(unittest.TestCase):
    """get_index_path() のパス生成テスト。"""

    def test_specs_path(self):
        """specs カテゴリのインデックスパス"""
        root = Path("/project")
        result = get_index_path("specs", root)
        expected = Path("/project/.claude/doc-advisor/toc/specs/specs_index.json")
        self.assertEqual(result, expected)

    def test_rules_path(self):
        """rules カテゴリのインデックスパス"""
        root = Path("/project")
        result = get_index_path("rules", root)
        expected = Path("/project/.claude/doc-advisor/toc/rules/rules_index.json")
        self.assertEqual(result, expected)


# ===========================================================================
# load_index / save_index ラウンドトリップテスト
# ===========================================================================

class TestLoadSaveIndex(unittest.TestCase):
    """インデックス JSON の読み書きラウンドトリップテスト。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_roundtrip(self):
        """保存したインデックスを正しく読み込めること"""
        index_path = Path(self.tmpdir) / "test_index.json"
        original = {
            "metadata": {
                "category": "specs",
                "model": "text-embedding-3-small",
                "dimensions": 1536,
                "generated_at": "2026-03-30T12:00:00Z",
                "file_count": 1,
            },
            "entries": {
                "docs/test.md": {
                    "title": "テスト文書",
                    "embedding": FIXED_VECTOR,
                    "checksum": "abc123",
                },
            },
        }
        save_index(original, index_path)
        loaded = load_index(index_path)

        self.assertEqual(loaded["metadata"]["category"], "specs")
        self.assertEqual(loaded["metadata"]["dimensions"], 1536)
        self.assertEqual(loaded["entries"]["docs/test.md"]["title"], "テスト文書")
        self.assertEqual(len(loaded["entries"]["docs/test.md"]["embedding"]), 1536)

    def test_load_nonexistent_returns_empty(self):
        """存在しないファイルの読み込みは空 dict を返す"""
        result = load_index(Path(self.tmpdir) / "nonexistent.json")
        self.assertEqual(result, {})

    def test_load_corrupted_raises_error(self):
        """破損 JSON はValueError を発生させる"""
        bad_path = Path(self.tmpdir) / "bad.json"
        bad_path.write_text("{invalid json", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_index(bad_path)

    def test_save_creates_parent_dirs(self):
        """save_index は親ディレクトリを自動作成する"""
        deep_path = Path(self.tmpdir) / "a" / "b" / "c" / "index.json"
        save_index({"entries": {}}, deep_path)
        self.assertTrue(deep_path.exists())

    def test_roundtrip_multiple_entries(self):
        """複数エントリのラウンドトリップ"""
        index_path = Path(self.tmpdir) / "multi.json"
        original = {
            "metadata": {"category": "rules", "file_count": 2},
            "entries": {
                "docs/a.md": {"title": "A", "embedding": FIXED_VECTOR, "checksum": "aaa"},
                "docs/b.md": {"title": "B", "embedding": FIXED_VECTOR_2, "checksum": "bbb"},
            },
        }
        save_index(original, index_path)
        loaded = load_index(index_path)
        self.assertEqual(len(loaded["entries"]), 2)
        self.assertEqual(loaded["entries"]["docs/a.md"]["embedding"][0], 1.0)
        self.assertEqual(loaded["entries"]["docs/b.md"]["embedding"][1], 1.0)


# ===========================================================================
# call_embedding_api() テスト（urllib.request.urlopen をモック）
# ===========================================================================

class TestCallEmbeddingApi(unittest.TestCase):
    """call_embedding_api() の API モックテスト。"""

    @patch("embed_docs.urllib.request.urlopen")
    def test_single_text(self, mock_urlopen):
        """単一テキストの Embedding 取得"""
        response_data = _make_api_response([FIXED_VECTOR])
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = call_embedding_api(["テストテキスト"], "fake-api-key")

        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]), 1536)
        self.assertEqual(result[0][0], 1.0)

    @patch("embed_docs.urllib.request.urlopen")
    def test_batch_texts(self, mock_urlopen):
        """バッチテキスト（複数テキスト）の Embedding 取得"""
        response_data = _make_api_response([FIXED_VECTOR, FIXED_VECTOR_2])
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = call_embedding_api(["テキスト1", "テキスト2"], "fake-api-key")

        self.assertEqual(len(result), 2)
        # index 順にソートされて返る
        self.assertEqual(result[0][0], 1.0)
        self.assertEqual(result[1][1], 1.0)

    @patch("embed_docs.urllib.request.urlopen")
    def test_api_auth_error_raises(self, mock_urlopen):
        """401 エラーで RuntimeError を発生させる"""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.openai.com/v1/embeddings",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )
        with self.assertRaises(RuntimeError) as ctx:
            call_embedding_api(["テスト"], "invalid-key")
        self.assertIn("認証エラー", str(ctx.exception))

    @patch("embed_docs.urllib.request.urlopen")
    def test_network_error_retries_then_raises(self, mock_urlopen):
        """ネットワークエラーでリトライ後に RuntimeError を発生させる"""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        with self.assertRaises(RuntimeError) as ctx:
            call_embedding_api(["テスト"], "fake-key")
        self.assertIn("API 呼び出し失敗", str(ctx.exception))
        # リトライ回数 + 初回 = API_RETRY_COUNT + 1 回呼ばれる
        self.assertEqual(mock_urlopen.call_count, embed_docs.API_RETRY_COUNT + 1)

    @patch("embed_docs.time.sleep")  # sleep をスキップ
    @patch("embed_docs.urllib.request.urlopen")
    def test_rate_limit_retries(self, mock_urlopen, mock_sleep):
        """429 レート制限でリトライする"""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.openai.com/v1/embeddings",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=None,
        )
        with self.assertRaises(RuntimeError):
            call_embedding_api(["テスト"], "fake-key")
        # リトライ回数 + 初回 = API_RETRY_COUNT + 1 回呼ばれる
        self.assertEqual(mock_urlopen.call_count, embed_docs.API_RETRY_COUNT + 1)
        # sleep が呼ばれている
        mock_sleep.assert_called_once()


# ===========================================================================
# --check モードのテスト（subprocess 経由）
# ===========================================================================

class TestRunCheckMode(unittest.TestCase):
    """--check モードの stale/fresh 出力テスト。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = self.tmpdir

        # .git ディレクトリ作成
        os.makedirs(os.path.join(self.project_root, '.git'))

        # .doc_structure.yaml 作成
        doc_structure = """\
# doc_structure_version: 3.0

rules:
  root_dirs:
    - rules/
  doc_types_map:
    rules/: rule
  patterns:
    target_glob: "**/*.md"
    exclude: []

specs:
  root_dirs:
    - specs/
  doc_types_map:
    specs/: spec
  patterns:
    target_glob: "**/*.md"
    exclude: []
"""
        with open(os.path.join(self.project_root, '.doc_structure.yaml'), 'w') as f:
            f.write(doc_structure)

        # ToC ディレクトリ作成
        self.toc_dir = os.path.join(
            self.project_root, '.claude', 'doc-advisor', 'toc', 'rules'
        )
        os.makedirs(self.toc_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_rule_file(self, rel_path, content='# Test Rule\n\nThis is a test rule.\n'):
        """rules/ 配下にテスト用 .md ファイルを作成"""
        full_path = os.path.join(self.project_root, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(content)
        return full_path

    def _run_embed_docs(self, *extra_args, category='rules'):
        """embed_docs.py を subprocess で実行"""
        cmd = [
            sys.executable, EMBED_DOCS_SCRIPT,
            '--category', category,
        ] + list(extra_args)
        env = os.environ.copy()
        env['CLAUDE_PROJECT_DIR'] = self.project_root
        # API キーを除去（--check モードでは不要）
        env.pop('OPENAI_API_KEY', None)
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=self.project_root, env=env
        )
        return result

    def test_check_no_index(self):
        """インデックスが存在しない場合は stale を返す"""
        self._create_rule_file('rules/test.md')
        result = self._run_embed_docs('--check')

        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        output = json.loads(result.stdout.strip())
        self.assertEqual(output["status"], "stale")
        self.assertEqual(output["reason"], "index_not_found")

    def test_check_no_checksums(self):
        """チェックサムファイルがない場合は stale を返す"""
        self._create_rule_file('rules/test.md')

        # インデックスだけ作成（チェックサムなし）
        index_path = os.path.join(self.toc_dir, 'rules_index.json')
        with open(index_path, 'w') as f:
            json.dump({"metadata": {}, "entries": {}}, f)

        result = self._run_embed_docs('--check')

        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        output = json.loads(result.stdout.strip())
        self.assertEqual(output["status"], "stale")
        self.assertEqual(output["reason"], "checksums_not_found")

    def test_check_fresh(self):
        """全ファイルのチェックサムが一致する場合は fresh を返す"""
        file_path = self._create_rule_file('rules/test.md')

        # インデックス作成
        index_path = os.path.join(self.toc_dir, 'rules_index.json')
        with open(index_path, 'w') as f:
            json.dump({"metadata": {}, "entries": {}}, f)

        # チェックサム作成（実際のハッシュ値を使用）
        import hashlib
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            sha256.update(f.read())
        file_hash = sha256.hexdigest()

        checksums_path = os.path.join(self.toc_dir, '.toc_checksums.yaml')
        with open(checksums_path, 'w') as f:
            f.write(f"checksums:\n  rules/test.md: {file_hash}\n")

        result = self._run_embed_docs('--check')

        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        output = json.loads(result.stdout.strip())
        self.assertEqual(output["status"], "fresh")

    def test_check_stale_new_file(self):
        """新しいファイルが追加された場合は stale を返す"""
        self._create_rule_file('rules/existing.md')
        self._create_rule_file('rules/new_file.md')

        # インデックス作成
        index_path = os.path.join(self.toc_dir, 'rules_index.json')
        with open(index_path, 'w') as f:
            json.dump({"metadata": {}, "entries": {}}, f)

        # チェックサムには existing.md のみ登録
        import hashlib
        sha256 = hashlib.sha256()
        existing_path = os.path.join(self.project_root, 'rules', 'existing.md')
        with open(existing_path, 'rb') as f:
            sha256.update(f.read())
        file_hash = sha256.hexdigest()

        checksums_path = os.path.join(self.toc_dir, '.toc_checksums.yaml')
        with open(checksums_path, 'w') as f:
            f.write(f"checksums:\n  rules/existing.md: {file_hash}\n")

        result = self._run_embed_docs('--check')

        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        output = json.loads(result.stdout.strip())
        self.assertEqual(output["status"], "stale")
        self.assertIn("1 new", output["reason"])

    def test_check_stale_modified_file(self):
        """ファイルが変更された場合は stale を返す"""
        self._create_rule_file('rules/test.md', content='# Original\n\nOriginal content.\n')

        # インデックス作成
        index_path = os.path.join(self.toc_dir, 'rules_index.json')
        with open(index_path, 'w') as f:
            json.dump({"metadata": {}, "entries": {}}, f)

        # 古いチェックサム（不一致なハッシュ）
        checksums_path = os.path.join(self.toc_dir, '.toc_checksums.yaml')
        with open(checksums_path, 'w') as f:
            f.write("checksums:\n  rules/test.md: old_hash_value\n")

        result = self._run_embed_docs('--check')

        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        output = json.loads(result.stdout.strip())
        self.assertEqual(output["status"], "stale")
        self.assertIn("1 modified", output["reason"])

    def test_check_stale_deleted_file(self):
        """ファイルが削除された場合は stale を返す"""
        # rules/ ディレクトリは作成するがファイルなし
        os.makedirs(os.path.join(self.project_root, 'rules'), exist_ok=True)

        # インデックス作成
        index_path = os.path.join(self.toc_dir, 'rules_index.json')
        with open(index_path, 'w') as f:
            json.dump({"metadata": {}, "entries": {}}, f)

        # 存在しないファイルのチェックサムを登録
        checksums_path = os.path.join(self.toc_dir, '.toc_checksums.yaml')
        with open(checksums_path, 'w') as f:
            f.write("checksums:\n  rules/deleted.md: some_hash\n")

        result = self._run_embed_docs('--check')

        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        output = json.loads(result.stdout.strip())
        self.assertEqual(output["status"], "stale")
        self.assertIn("1 deleted", output["reason"])


# ===========================================================================
# CLI 統合テスト（subprocess 経由）
# ===========================================================================

class TestEmbedDocsCli(unittest.TestCase):
    """embed_docs.py の CLI 統合テスト。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = self.tmpdir

        # .git ディレクトリ作成
        os.makedirs(os.path.join(self.project_root, '.git'))

        # .doc_structure.yaml 作成
        doc_structure = """\
# doc_structure_version: 3.0

rules:
  root_dirs:
    - rules/
  doc_types_map:
    rules/: rule
  patterns:
    target_glob: "**/*.md"
    exclude: []

specs:
  root_dirs:
    - specs/
  doc_types_map:
    specs/: spec
  patterns:
    target_glob: "**/*.md"
    exclude: []
"""
        with open(os.path.join(self.project_root, '.doc_structure.yaml'), 'w') as f:
            f.write(doc_structure)

        # rules/ ディレクトリ作成
        os.makedirs(os.path.join(self.project_root, 'rules'), exist_ok=True)

        # ToC ディレクトリ作成
        self.toc_dir = os.path.join(
            self.project_root, '.claude', 'doc-advisor', 'toc', 'rules'
        )
        os.makedirs(self.toc_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_rule_file(self, rel_path, content='# Test Rule\n\nThis is a test rule.\n'):
        """rules/ 配下にテスト用 .md ファイルを作成"""
        full_path = os.path.join(self.project_root, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(content)
        return full_path

    def _run_embed_docs(self, *extra_args, category='rules', env_override=None):
        """embed_docs.py を subprocess で実行"""
        cmd = [
            sys.executable, EMBED_DOCS_SCRIPT,
            '--category', category,
        ] + list(extra_args)
        env = os.environ.copy()
        env['CLAUDE_PROJECT_DIR'] = self.project_root
        if env_override:
            env.update(env_override)
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=self.project_root, env=env
        )
        return result

    def test_no_api_key_error(self):
        """OPENAI_API_KEY 未設定時にエラー JSON を出力する"""
        self._create_rule_file('rules/test.md')

        # API キーを除去
        env_override = {}
        env_clean = os.environ.copy()
        env_clean.pop('OPENAI_API_KEY', None)
        env_clean['CLAUDE_PROJECT_DIR'] = self.project_root

        cmd = [
            sys.executable, EMBED_DOCS_SCRIPT,
            '--category', 'rules',
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=self.project_root, env=env_clean
        )

        self.assertEqual(result.returncode, 1)
        output = json.loads(result.stdout.strip())
        self.assertEqual(output["status"], "error")
        self.assertIn("OPENAI_API_KEY", output["error"])

    def test_full_mode_with_mock_api(self):
        """--full モードで API をモックしてインデックスが生成されること（直接呼び出し）"""
        self._create_rule_file('rules/test.md')

        # ToC YAML を作成（load_metadata が参照するため）
        toc_path = os.path.join(self.toc_dir, 'rules_toc.yaml')
        with open(toc_path, 'w') as f:
            f.write('docs:\n  rules/test.md:\n    title: "Test Rule"\n    purpose: "テスト用"\n')

        # 直接モジュール関数を呼び出してテスト（API をモック）
        with patch("embed_docs.call_embedding_api") as mock_api:
            mock_api.return_value = [FIXED_VECTOR]

            # 環境変数を設定
            original_env = os.environ.get('CLAUDE_PROJECT_DIR')
            os.environ['CLAUDE_PROJECT_DIR'] = self.project_root

            try:
                from embed_docs import init_common_config, build_index
                from toc_utils import init_common_config as toc_init

                common = toc_init('rules')
                project_root = common['project_root']
                config = common['config']

                index_path = get_index_path('rules', project_root)

                from toc_utils import resolve_config_path
                default_dir = project_root / 'rules'
                checksums_file = resolve_config_path(
                    config.get('checksums_file', '.claude/doc-advisor/toc/rules/.toc_checksums.yaml'),
                    default_dir,
                    project_root,
                )

                exit_code = build_index('rules', common, index_path, checksums_file, True, 'fake-key')
            finally:
                if original_env is None:
                    os.environ.pop('CLAUDE_PROJECT_DIR', None)
                else:
                    os.environ['CLAUDE_PROJECT_DIR'] = original_env

        self.assertEqual(exit_code, 0)
        # インデックスが作成されたことを確認
        self.assertTrue(index_path.exists())
        with open(index_path, 'r') as f:
            index = json.load(f)
        self.assertEqual(index["metadata"]["category"], "rules")
        self.assertIn("rules/test.md", index["entries"])
        self.assertEqual(len(index["entries"]["rules/test.md"]["embedding"]), 1536)
        # API が呼ばれたことを確認
        mock_api.assert_called_once()

    def test_diff_mode_detects_changes(self):
        """差分モードで新規・変更・削除を検出してインデックスを更新すること"""
        self._create_rule_file('rules/existing.md', content='# Existing\n\nExisting content.\n')
        self._create_rule_file('rules/new_file.md', content='# New\n\nNew content.\n')

        # ToC YAML を作成
        toc_path = os.path.join(self.toc_dir, 'rules_toc.yaml')
        with open(toc_path, 'w') as f:
            f.write('docs:\n  rules/existing.md:\n    title: "Existing"\n  rules/new_file.md:\n    title: "New"\n  rules/deleted.md:\n    title: "Deleted"\n')

        # 既存インデックスを作成（existing.md と deleted.md がある状態）
        index_path = os.path.join(self.toc_dir, 'rules_index.json')
        existing_index = {
            "metadata": {"category": "rules", "model": "text-embedding-3-small", "dimensions": 1536, "file_count": 2},
            "entries": {
                "rules/existing.md": {"title": "Existing", "embedding": FIXED_VECTOR, "checksum": "old_hash"},
                "rules/deleted.md": {"title": "Deleted", "embedding": FIXED_VECTOR, "checksum": "deleted_hash"},
            },
        }
        with open(index_path, 'w') as f:
            json.dump(existing_index, f)

        # チェックサム（existing.md は古いハッシュ、deleted.md も登録）
        checksums_path = os.path.join(self.toc_dir, '.toc_checksums.yaml')
        with open(checksums_path, 'w') as f:
            f.write("checksums:\n  rules/existing.md: old_hash\n  rules/deleted.md: deleted_hash\n")

        with patch("embed_docs.call_embedding_api") as mock_api:
            mock_api.return_value = [FIXED_VECTOR, FIXED_VECTOR_2]

            original_env = os.environ.get('CLAUDE_PROJECT_DIR')
            os.environ['CLAUDE_PROJECT_DIR'] = self.project_root

            try:
                from toc_utils import init_common_config as toc_init, resolve_config_path
                common = toc_init('rules')
                project_root = common['project_root']
                config = common['config']
                idx_path = get_index_path('rules', project_root)
                default_dir = project_root / 'rules'
                checksums_file = resolve_config_path(
                    config.get('checksums_file', '.claude/doc-advisor/toc/rules/.toc_checksums.yaml'),
                    default_dir,
                    project_root,
                )

                exit_code = embed_docs.build_index('rules', common, idx_path, checksums_file, False, 'fake-key')
            finally:
                if original_env is None:
                    os.environ.pop('CLAUDE_PROJECT_DIR', None)
                else:
                    os.environ['CLAUDE_PROJECT_DIR'] = original_env

        self.assertEqual(exit_code, 0)
        with open(idx_path, 'r') as f:
            index = json.load(f)
        # deleted.md は削除されている
        self.assertNotIn("rules/deleted.md", index["entries"])
        # existing.md と new_file.md がある
        self.assertIn("rules/existing.md", index["entries"])
        self.assertIn("rules/new_file.md", index["entries"])
        # API が呼ばれた（2ファイル分）
        mock_api.assert_called_once()

    def test_config_not_ready_error(self):
        """doc_structure.yaml が未設定の場合にエラー JSON を返す"""
        # .doc_structure.yaml を削除し、デフォルト rules/ ディレクトリも削除
        os.remove(os.path.join(self.project_root, '.doc_structure.yaml'))
        rules_dir = os.path.join(self.project_root, 'rules')
        if os.path.exists(rules_dir):
            shutil.rmtree(rules_dir)

        env_clean = os.environ.copy()
        env_clean.pop('OPENAI_API_KEY', None)
        env_clean['CLAUDE_PROJECT_DIR'] = self.project_root

        cmd = [
            sys.executable, EMBED_DOCS_SCRIPT,
            '--category', 'rules', '--check',
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=self.project_root, env=env_clean
        )

        self.assertEqual(result.returncode, 1)
        output = json.loads(result.stdout.strip())
        self.assertEqual(output["status"], "error")


if __name__ == '__main__':
    unittest.main()
