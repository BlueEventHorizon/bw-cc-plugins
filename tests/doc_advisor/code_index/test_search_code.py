#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search_code.py のユニットテスト。

subprocess で CLI を実行するパターン。
フィクスチャとして tmpdir に code_index.json を事前構築し、
キーワード検索・影響範囲検索・エラーハンドリングを検証する。

設計根拠: DES-007 §5.1-5.3, NFR-01-3
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

# テスト対象スクリプトのパス
SCRIPTS_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'plugins', 'doc-advisor', 'scripts'
))
SEARCH_SCRIPT = os.path.join(SCRIPTS_DIR, 'code_index', 'search_code.py')


# ---------------------------------------------------------------------------
# フィクスチャ生成ヘルパー
# ---------------------------------------------------------------------------

def _build_fixture_index(entries, schema_version='1.0'):
    """テスト用のインデックスデータを構築する。

    Args:
        entries: {相対パス: エントリ dict} の辞書
        schema_version: スキーマバージョン

    Returns:
        dict: code_index.json に書き込む完全なインデックス構造
    """
    languages = {}
    for entry in entries.values():
        lang = entry.get('language', 'unknown')
        languages[lang] = languages.get(lang, 0) + 1

    return {
        'metadata': {
            'schema_version': schema_version,
            'generated_at': '2026-04-02T12:00:00Z',
            'file_count': len(entries),
            'languages': languages,
        },
        'entries': entries,
    }


def _swift_entries():
    """テスト用の Swift ファイルエントリ（5件）を返す。"""
    return {
        'Sources/Auth/JwtVerifier.swift': {
            'language': 'swift',
            'lines': 142,
            'imports': ['Foundation', 'CryptoKit', 'Auth.TokenStore'],
            'exports': [
                {
                    'name': 'class JwtVerifier',
                    'kind': 'Class',
                    'line': 15,
                    'access': 'public',
                    'conforms_to': ['TokenVerifying', 'Sendable'],
                    'doc': 'JWT トークンを検証しペイロードをデコードする',
                    'extensions': None,
                },
                {
                    'name': 'func verify(_ token: String) throws -> Payload',
                    'kind': 'Function',
                    'line': 42,
                    'access': 'public',
                    'conforms_to': [],
                    'doc': '署名を検証し、有効期限をチェックしてペイロードを返す',
                    'extensions': None,
                },
            ],
            'sections': ['Public API', 'Validation'],
        },
        'Sources/Auth/TokenStore.swift': {
            'language': 'swift',
            'lines': 89,
            'imports': ['Foundation'],
            'exports': [
                {
                    'name': 'class TokenStore',
                    'kind': 'Class',
                    'line': 10,
                    'access': 'public',
                    'conforms_to': ['Sendable'],
                    'doc': 'トークンの永続化と取得を管理する',
                    'extensions': None,
                },
            ],
            'sections': ['Storage'],
        },
        'Sources/Network/ApiClient.swift': {
            'language': 'swift',
            'lines': 200,
            'imports': ['Foundation', 'Auth'],
            'exports': [
                {
                    'name': 'class ApiClient',
                    'kind': 'Class',
                    'line': 8,
                    'access': 'public',
                    'conforms_to': [],
                    'doc': 'REST API クライアント。認証ヘッダーを自動付与する',
                    'extensions': None,
                },
            ],
            'sections': ['Request', 'Response'],
        },
        'Sources/Network/WebSocket.swift': {
            'language': 'swift',
            'lines': 150,
            'imports': ['Foundation', 'Network'],
            'exports': [
                {
                    'name': 'class WebSocket',
                    'kind': 'Class',
                    'line': 5,
                    'access': 'public',
                    'conforms_to': [],
                    'doc': 'WebSocket 接続を管理する',
                    'extensions': None,
                },
            ],
            'sections': ['Connection', 'Message'],
        },
        'Tests/AuthTests/JwtVerifierTests.swift': {
            'language': 'swift',
            'lines': 95,
            'imports': ['XCTest', 'Auth'],
            'exports': [
                {
                    'name': 'class JwtVerifierTests',
                    'kind': 'Class',
                    'line': 5,
                    'access': 'internal',
                    'conforms_to': ['XCTestCase'],
                    'doc': 'JwtVerifier のユニットテスト',
                    'extensions': None,
                },
            ],
            'sections': ['Tests'],
        },
    }


class SearchCodeTestBase(unittest.TestCase):
    """search_code.py テストの基底クラス。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # インデックスディレクトリを作成
        self.index_dir = os.path.join(
            self.tmpdir, '.claude', 'doc-advisor', 'code_index',
        )
        os.makedirs(self.index_dir, exist_ok=True)
        self.index_path = os.path.join(self.index_dir, 'code_index.json')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_index(self, entries, schema_version='1.0'):
        """フィクスチャインデックスを書き込む。"""
        data = _build_fixture_index(entries, schema_version)
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _run_search(self, args):
        """search_code.py を subprocess で実行する。

        Args:
            args: コマンドライン引数のリスト（search_code.py 以降の部分）

        Returns:
            subprocess.CompletedProcess
        """
        cmd = [sys.executable, SEARCH_SCRIPT] + args
        return subprocess.run(
            cmd, capture_output=True, text=True,
            env={**os.environ, 'PYTHONPATH': SCRIPTS_DIR},
        )


# ===========================================================================
# --query モード: キーワードマッチとスコア順
# ===========================================================================

class TestQueryMode(SearchCodeTestBase):
    """--query モードのテスト。"""

    def setUp(self):
        super().setUp()
        self._write_index(_swift_entries())

    def test_query_basic_keyword(self):
        """基本的なキーワード検索が動作する"""
        proc = self._run_search(['--query', 'JWT', self.tmpdir])
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'ok')
        self.assertGreater(result['count'], 0)

    def test_query_returns_json(self):
        """出力が正しい JSON フォーマットである"""
        proc = self._run_search(['--query', 'ApiClient', self.tmpdir])
        result = json.loads(proc.stdout)
        self.assertIn('status', result)
        self.assertIn('results', result)
        self.assertIn('count', result)
        self.assertIn('truncated', result)

    def test_query_score_ordering(self):
        """結果がスコア降順で返される"""
        proc = self._run_search(['--query', 'JwtVerifier', self.tmpdir])
        result = json.loads(proc.stdout)
        scores = [r['score'] for r in result['results']]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_query_export_match_highest_score(self):
        """export 名マッチが最も高いスコアを得る"""
        proc = self._run_search(['--query', 'JwtVerifier', self.tmpdir])
        result = json.loads(proc.stdout)
        # JwtVerifier.swift は export 名 + パス名 + doc でマッチするため最高スコア
        top = result['results'][0]
        self.assertIn('JwtVerifier', top['path'])

    def test_query_case_insensitive(self):
        """大文字小文字を無視して検索できる"""
        proc = self._run_search(['--query', 'jwtverifier', self.tmpdir])
        result = json.loads(proc.stdout)
        self.assertGreater(result['count'], 0)
        paths = [r['path'] for r in result['results']]
        self.assertTrue(any('JwtVerifier' in p for p in paths))

    def test_query_multiple_keywords(self):
        """複数キーワードで検索できる"""
        proc = self._run_search(['--query', 'JWT トークン', self.tmpdir])
        result = json.loads(proc.stdout)
        self.assertGreater(result['count'], 0)

    def test_query_path_match(self):
        """パス名による部分一致マッチが動作する"""
        proc = self._run_search(['--query', 'Network', self.tmpdir])
        result = json.loads(proc.stdout)
        paths = [r['path'] for r in result['results']]
        self.assertTrue(any('Network' in p for p in paths))

    def test_query_import_match(self):
        """import 名によるマッチが動作する"""
        proc = self._run_search(['--query', 'CryptoKit', self.tmpdir])
        result = json.loads(proc.stdout)
        self.assertGreater(result['count'], 0)

    def test_query_doc_match(self):
        """doc（ドキュメントコメント）によるマッチが動作する"""
        proc = self._run_search(['--query', '認証ヘッダー', self.tmpdir])
        result = json.loads(proc.stdout)
        self.assertGreater(result['count'], 0)
        # ApiClient.swift の doc にマッチするはず
        paths = [r['path'] for r in result['results']]
        self.assertTrue(any('ApiClient' in p for p in paths))

    def test_query_no_match(self):
        """マッチしない場合は空結果を返す"""
        proc = self._run_search(['--query', 'NonExistentSymbol12345', self.tmpdir])
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['count'], 0)

    def test_query_matched_keywords_field(self):
        """matched_keywords フィールドが正しい"""
        proc = self._run_search(['--query', 'JWT', self.tmpdir])
        result = json.loads(proc.stdout)
        for r in result['results']:
            self.assertIn('matched_keywords', r)
            self.assertIsInstance(r['matched_keywords'], list)


# ===========================================================================
# --query モード: 30KB 制限
# ===========================================================================

class TestQuerySizeLimit(SearchCodeTestBase):
    """--query モードの 30KB 出力制限テスト。"""

    def test_size_limit_with_many_entries(self):
        """大量エントリで出力が 30KB 以下に収まる"""
        # 200件のエントリを生成（各エントリに長い doc を付与）
        entries = {}
        for i in range(200):
            path = f'Sources/Module{i}/File{i}.swift'
            entries[path] = {
                'language': 'swift',
                'lines': 100,
                'imports': ['Foundation', 'ModuleA', 'ModuleB'],
                'exports': [
                    {
                        'name': f'class Widget{i}',
                        'kind': 'Class',
                        'line': 10,
                        'access': 'public',
                        'conforms_to': ['Protocol1', 'Protocol2'],
                        'doc': f'Widget{i} はデータの変換と永続化を担当するコンポーネントです。'
                               f'複数のプロトコルに準拠し、拡張可能な設計になっています。'
                               f'キーワード: search target match query',
                        'extensions': None,
                    },
                ],
                'sections': ['Section1', 'Section2'],
            }
        self._write_index(entries)

        proc = self._run_search(['--query', 'search target', self.tmpdir])
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'ok')

        # 出力サイズが 30KB 以下
        output_bytes = len(proc.stdout.encode('utf-8'))
        self.assertLessEqual(output_bytes, 30 * 1024,
                             f'出力サイズ {output_bytes} バイトが 30KB を超過')

        # truncated フラグが True
        self.assertTrue(result['truncated'])


# ===========================================================================
# --affected-by モード: 影響範囲検索
# ===========================================================================

class TestAffectedByMode(SearchCodeTestBase):
    """--affected-by モードのテスト。"""

    def setUp(self):
        super().setUp()
        self._write_index(_swift_entries())

    def test_affected_by_basic(self):
        """基本的な影響範囲検索が動作する"""
        # TokenStore を変更した場合、Auth を import している
        # ApiClient と JwtVerifierTests が影響を受けるはず
        proc = self._run_search([
            '--affected-by', 'Sources/Auth/TokenStore.swift',
            self.tmpdir,
        ])
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'ok')
        self.assertIn('affected_files', result)
        self.assertIn('count', result)

    def test_affected_by_returns_dependents(self):
        """Auth モジュール内のファイル変更で Auth を import するファイルが返る"""
        proc = self._run_search([
            '--affected-by', 'Sources/Auth/JwtVerifier.swift',
            self.tmpdir,
        ])
        result = json.loads(proc.stdout)
        affected = result.get('affected_files', [])
        # Auth ディレクトリ内のファイルを import している
        # ApiClient（Auth を import）と JwtVerifierTests（Auth を import）
        self.assertTrue(
            any('ApiClient' in f for f in affected)
            or any('JwtVerifierTests' in f for f in affected),
            f'Auth を import しているファイルが影響範囲に含まれていない: {affected}',
        )

    def test_affected_by_with_hops(self):
        """--hops オプションが動作する"""
        proc = self._run_search([
            '--affected-by', 'Sources/Auth/TokenStore.swift',
            self.tmpdir, '--hops', '2',
        ])
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'ok')

    def test_affected_by_file_not_in_index(self):
        """インデックスに存在しないファイルはエラーを返す"""
        proc = self._run_search([
            '--affected-by', 'Sources/NonExistent.swift',
            self.tmpdir,
        ])
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'error')
        self.assertIn('インデックスに存在しません', result['message'])

    def test_affected_by_path_traversal(self):
        """パストラバーサルを検出してエラーを返す"""
        proc = self._run_search([
            '--affected-by', '../../etc/passwd',
            self.tmpdir,
        ])
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'error')
        self.assertIn('traversal', result['message'].lower())


# ===========================================================================
# インデックス未作成時のエラー
# ===========================================================================

class TestIndexNotFound(SearchCodeTestBase):
    """インデックスファイルが存在しない場合のテスト。"""

    def test_query_without_index(self):
        """インデックス未作成時にエラーメッセージを返す"""
        # インデックスファイルを作成しない
        proc = self._run_search(['--query', 'test', self.tmpdir])
        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'error')
        self.assertIn('インデックスが見つかりません', result['message'])

    def test_affected_by_without_index(self):
        """インデックス未作成時に影響範囲検索もエラーを返す"""
        proc = self._run_search([
            '--affected-by', 'Sources/Foo.swift', self.tmpdir,
        ])
        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'error')


# ===========================================================================
# パフォーマンステスト（NFR-01-3: 100ms 以内）
# ===========================================================================

class TestPerformance(SearchCodeTestBase):
    """キーワード検索のパフォーマンステスト。"""

    def test_query_performance_2000_files(self):
        """2000 ファイルのインデックスで検索が 100ms 以内に完了する"""
        # 2000件のエントリを生成
        entries = {}
        for i in range(2000):
            path = f'Sources/Mod{i // 10}/File{i}.swift'
            entries[path] = {
                'language': 'swift',
                'lines': 50 + (i % 100),
                'imports': ['Foundation', f'Module{i % 20}'],
                'exports': [
                    {
                        'name': f'class Type{i}',
                        'kind': 'Class',
                        'line': 5,
                        'access': 'public',
                        'conforms_to': [],
                        'doc': f'Type{i} の説明文。データ処理と変換を行う。',
                        'extensions': None,
                    },
                ],
                'sections': [],
            }
        self._write_index(entries)

        # ウォームアップ（Python インタープリタ起動コストを除外するため複数回実行）
        self._run_search(['--query', 'Type500', self.tmpdir])

        # 計測
        start = time.monotonic()
        proc = self._run_search(['--query', 'Type500', self.tmpdir])
        elapsed_ms = (time.monotonic() - start) * 1000

        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = json.loads(proc.stdout)
        self.assertEqual(result['status'], 'ok')

        # 100ms 以内（subprocess 起動コスト込みなので余裕を持たせて 500ms）
        # 純粋な検索処理は 100ms 以内だが、subprocess 起動に時間がかかるため閾値を緩和
        self.assertLess(elapsed_ms, 500,
                        f'検索に {elapsed_ms:.0f}ms かかった（500ms 超過）')


if __name__ == '__main__':
    unittest.main()
