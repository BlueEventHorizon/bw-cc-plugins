#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
forge 同梱 ToC のコピーと checksums 生成を単一操作として実行する。

update-forge-toc skill の「同梱 ToC へのコピー」と「鮮度検証用 checksums の
再生成」を分離した 2 手順で運用すると、片方だけを実行してしまうヒューマン
エラーが起きる（checksums のみが再生成され、直前のソース文書変更が
未反映のまま rules_toc.yaml が stale で commit された事例がある）。
本スクリプトはこの 2 手順を単一のアトミックな操作に統合し、
片方だけの実行を構造的に防ぐ。

使用例:
    python3 finalize_toc.py \
      --doc-structure .claude/skills/update-forge-toc/forge_doc_structure.yaml \
      --toc-src .claude/.doc-advisor/toc/forge-rules-<hash>/toc.yaml \
      --toc-dest plugins/forge/toc/rules/rules_toc.yaml \
      --checksums-output plugins/forge/toc/rules/.toc_checksums.yaml
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from generate_toc_checksums import render_checksums, resolve_paths, sha256_of_file  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--doc-structure', required=True,
        help='rules 対象パスを解決する .doc_structure.yaml 互換ファイル',
    )
    parser.add_argument(
        '--project-root', default='.',
        help='プロジェクトルート（省略時はカレントディレクトリ）',
    )
    parser.add_argument(
        '--toc-src', required=True,
        help='doc-advisor index-docs が生成した toc.yaml のパス',
    )
    parser.add_argument(
        '--toc-dest', required=True,
        help='forge 同梱先の ToC パス（例: plugins/forge/toc/rules/rules_toc.yaml）',
    )
    parser.add_argument(
        '--checksums-output', required=True,
        help='鮮度検証用 checksums の出力先',
    )
    return parser.parse_args()


def main():
    args = parse_args()
    project_root = Path(args.project_root).resolve()

    toc_src = Path(args.toc_src)
    if not toc_src.is_absolute():
        toc_src = project_root / toc_src
    if not toc_src.is_file():
        print(json.dumps(
            {'status': 'error', 'message': f'toc-src が存在しません: {toc_src}'},
            ensure_ascii=False,
        ))
        return 1

    try:
        paths = resolve_paths(args.doc_structure, str(project_root))
    except RuntimeError as e:
        print(json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False))
        return 1

    checksums = {}
    for rel_path in paths:
        full_path = project_root / rel_path
        if not full_path.is_file():
            print(json.dumps(
                {'status': 'error', 'message': f'ファイルが存在しません: {rel_path}'},
                ensure_ascii=False,
            ))
            return 1
        checksums[rel_path] = sha256_of_file(full_path)

    # 1. ToC のコピー（旧 Step 3）
    toc_dest = project_root / args.toc_dest
    shutil.copyfile(toc_src, toc_dest)

    # 2. checksums の再生成（旧 Step 4）。コピー直後に同一スクリプト内で実行する
    #    ことで、コピー漏れのまま checksums だけが再生成される事態を構造的に防ぐ。
    checksums_content = render_checksums(paths, checksums)
    checksums_output = project_root / args.checksums_output
    checksums_output.write_text(checksums_content, encoding='utf-8')

    print(json.dumps({
        'status': 'ok',
        'toc_dest': args.toc_dest,
        'checksums_output': args.checksums_output,
        'file_count': len(paths),
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
