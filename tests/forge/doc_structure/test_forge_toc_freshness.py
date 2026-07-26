#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge 同梱 ToC の鮮度契約テスト（Issue #158 / #174）。

`plugins/forge/toc/rules/rules_toc.yaml` は doc-advisor 管理 ToC のコピー配布物であり、
`update-forge-toc` skill（`.claude/skills/update-forge-toc/`）の実行を忘れると
ソース文書（`plugins/forge/docs/`, `plugins/forge/skills/*/docs/`）を更新しても
黙って stale になる。以下を検証し、更新忘れを CI / ローカルテストで検出する:

1. `.bak` ファイルが残存していないこと
2. `.toc_checksums.yaml`（内容 hash、mtime 非依存）が現在のソース文書と一致すること
3. `rules_toc.yaml` の索引パス集合が、解決された全ソース文書パス集合と完全一致すること
   （不足だけでなく、doc_structure から外れた余剰エントリの残存も検出する）
4. doc-advisor がインストールされている場合、`prepare_toc.py --dry-run` で
   ToC 本体（検索インデックスの中身）自体が現在のソース文書から再生成不要な
   状態（pending 差分 0 件）であること。checksums 一致（上記 2）だけでは
   「checksums のみ再生成され rules_toc.yaml 本体は stale なまま」という
   Issue #174 の実害を検出できないため、本テストが権威的な鮮度判定を行う
   （doc-advisor 未インストール環境ではスキップ）

実行:
    python3 -m unittest tests.forge.doc_structure.test_forge_toc_freshness -v
"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_STRUCTURE_SCRIPTS = REPO_ROOT / 'plugins' / 'forge' / 'scripts' / 'doc_structure'
GENERATE_SCRIPT = REPO_ROOT / 'plugins' / 'forge' / 'scripts' / 'doc_structure' / 'generate_toc_checksums.py'
DOC_STRUCTURE_PATH = '.claude/skills/update-forge-toc/forge_doc_structure.yaml'
TOC_DIR = REPO_ROOT / 'plugins' / 'forge' / 'toc'
RULES_TOC_PATH = TOC_DIR / 'rules' / 'rules_toc.yaml'
CHECKSUMS_PATH = TOC_DIR / 'rules' / '.toc_checksums.yaml'
TOC_KEY = 'forge-rules'

DOC_KEY_PATTERN = re.compile(r'^  (\S.*\.md):$', re.MULTILINE)


def _find_doc_advisor_prepare_toc():
    """インストール済み doc-advisor プラグインの prepare_toc.py を探す。

    見つからない場合は None を返す（doc-advisor 未インストール環境向けの
    グレースフルスキップ判定に使う）。
    """
    cache_root = Path.home() / '.claude' / 'plugins' / 'cache' / 'DocAdvisor' / 'doc-advisor'
    if not cache_root.is_dir():
        return None
    candidates = sorted(cache_root.glob('*/scripts/prepare_toc.py'))
    return candidates[-1] if candidates else None


def resolve_rules_paths():
    result = subprocess.run(
        [sys.executable, str(DOC_STRUCTURE_SCRIPTS / 'resolve_doc_structure.py'),
         '--type', 'rules', '--doc-structure', DOC_STRUCTURE_PATH],
        capture_output=True, text=True, cwd=REPO_ROOT, check=True,
    )
    data = json.loads(result.stdout)
    assert data['status'] == 'ok', data
    return sorted(data['rules'])


class TestForgeTocFreshness(unittest.TestCase):

    def test_no_bak_files_in_forge_toc(self):
        bak_files = sorted(str(p.relative_to(REPO_ROOT)) for p in TOC_DIR.rglob('*.bak'))
        self.assertEqual(
            bak_files, [],
            f"forge 同梱 ToC ディレクトリに .bak ファイルが残存しています: {bak_files}\n"
            "git 履歴から復元可能なため削除してください。",
        )

    def test_toc_checksums_match_current_docs(self):
        result = subprocess.run(
            [sys.executable, str(GENERATE_SCRIPT), '--doc-structure', DOC_STRUCTURE_PATH],
            capture_output=True, text=True, cwd=REPO_ROOT, check=True,
        )
        fresh_content = result.stdout
        committed_content = CHECKSUMS_PATH.read_text(encoding='utf-8')

        self.assertEqual(
            fresh_content, committed_content,
            "plugins/forge/toc/rules/.toc_checksums.yaml が現在のソース文書と一致しません"
            "（stale）。plugins/forge/docs/ または plugins/forge/skills/*/docs/ の更新後は"
            "update-forge-toc skill を実行して rules_toc.yaml と checksums を同時に再生成してください。",
        )

    def test_rules_toc_indexed_paths_match_resolved_paths_exactly(self):
        resolved = set(resolve_rules_paths())
        toc_text = RULES_TOC_PATH.read_text(encoding='utf-8')
        indexed = set(DOC_KEY_PATTERN.findall(toc_text))

        missing = sorted(resolved - indexed)
        surplus = sorted(indexed - resolved)

        self.assertEqual(
            (missing, surplus), ([], []),
            f"rules_toc.yaml の索引パス集合が解決済みソース文書パス集合と一致しません。\n"
            f"不足（索引に無い文書）: {missing}\n"
            f"余剰（doc_structure から外れた stale な索引エントリ）: {surplus}\n"
            "update-forge-toc skill を実行して再生成してください。",
        )

    def test_toc_body_matches_current_docs_via_doc_advisor_dry_run(self):
        prepare_toc = _find_doc_advisor_prepare_toc()
        if prepare_toc is None:
            raise unittest.SkipTest(
                'doc-advisor プラグイン（外部 marketplace BlueEventHorizon/DocAdvisor）が'
                '未インストールのためスキップします。checksums 一致（他テスト）だけでは'
                'ToC 本体の stale 化を検出できないため、可能な環境では本テストが権威的な'
                '判定を行います。'
            )

        paths = resolve_rules_paths()
        result = subprocess.run(
            [
                sys.executable, str(prepare_toc),
                '--key', TOC_KEY,
                '--paths-json', json.dumps(paths, ensure_ascii=False),
                '--dry-run',
            ],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload.get('status'), 'ok', payload)

        counts = payload.get('counts', {})
        self.assertEqual(
            (counts.get('added'), counts.get('updated')), (0, 0),
            f"doc-advisor の prepare_toc.py --dry-run が pending 差分を検出しました: {counts}\n"
            "rules_toc.yaml（ToC 本体）がソース文書の最新内容から再生成されていません"
            "（checksums のみ再生成された stale 化の可能性）。"
            "update-forge-toc skill を実行して再生成してください。",
        )

    def test_rules_toc_paths_all_exist_on_disk(self):
        toc_text = RULES_TOC_PATH.read_text(encoding='utf-8')
        indexed_paths = DOC_KEY_PATTERN.findall(toc_text)
        self.assertGreater(len(indexed_paths), 0, "rules_toc.yaml から索引パスを抽出できませんでした")

        missing = [p for p in indexed_paths if not (REPO_ROOT / p).is_file()]
        self.assertEqual(
            missing, [],
            f"rules_toc.yaml に索引があるが実在しないファイルがあります: {missing}",
        )


if __name__ == '__main__':
    unittest.main()
