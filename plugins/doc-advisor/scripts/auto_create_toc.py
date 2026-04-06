#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto-create-toc メインスクリプト（doc-advisor プラグイン）

セッション終了時に ToC を自動更新する。
Markdown ファイルからスクリプトのみでメタデータを抽出し、
validate_toc.py の検査を通過するエントリを生成する。

TASK-002: MetadataExtractor クラスとヘルパー関数の実装。
main() やコアロジック（detect_changed_files, update_toc 等）は TASK-003 で実装する。
"""

import re
from pathlib import Path

from create_pending_yaml import determine_doc_type


# doc_type → 汎用タスクのマッピング
_APPLICABLE_TASKS_MAP = {
    'rule': ['ルール確認'],
    'requirement': ['仕様確認'],
    'design': ['設計確認'],
    'plan': ['計画確認'],
    'api': ['API確認'],
    'reference': ['参考資料確認'],
    'spec': ['仕様確認'],
}

# 概要セクションとして認識する見出しテキスト（正規化後、小文字で完全一致）
_OVERVIEW_KEYWORDS = {'概要', 'overview'}

# メタデータセクションとして認識する見出しテキスト（正規化後、小文字で完全一致）
_METADATA_KEYWORDS = {'メタデータ', 'metadata'}

# 除外セクション（headings に含めない）として認識する見出しテキスト（正規化後、小文字で完全一致）
_EXCLUDED_SECTION_KEYWORDS = {'メタデータ', 'metadata', '改定履歴', '変更履歴'}


def _normalize_heading_text(text):
    """見出しテキストから番号プレフィックスを除去する。

    例: "1. 概要" → "概要", "2 アーキテクチャ概要" → "アーキテクチャ概要"
    """
    return re.sub(r'^\d+\.?\s*', '', text).strip()


def _parse_frontmatter(content):
    """ファイル先頭の frontmatter をパースして辞書を返す。

    YAML パーサーを使わず、`key: value` 形式の行を正規表現で抽出する。
    frontmatter がない場合は空辞書を返す。

    Args:
        content: ファイル全体の文字列

    Returns:
        tuple: (frontmatter辞書, frontmatter以降の本文)
    """
    lines = content.split('\n')
    fm_dict = {}
    body_start = 0

    # 先頭の空行をスキップ
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    if idx >= len(lines) or lines[idx].strip() != '---':
        # frontmatter なし
        return fm_dict, content

    # frontmatter 開始
    idx += 1
    fm_start = idx
    while idx < len(lines):
        if lines[idx].strip() == '---':
            body_start = idx + 1
            break
        idx += 1
    else:
        # 閉じ `---` がない場合は frontmatter なしとして扱う
        return {}, content

    # frontmatter の key: value をパース
    fm_lines = lines[fm_start:idx]
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        # key: value 形式の行を抽出
        match = re.match(r'^(\w[\w\-]*)\s*:\s*(.*)$', line)
        if match:
            key = match.group(1).strip()
            value = match.group(2).strip()
            # クォートの除去
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            # マルチライン指示子（|, >, |-, >-）の場合は後続インデント行を連結
            if value in ('|', '>', '|-', '>-'):
                multiline_parts = []
                j = i + 1
                while j < len(fm_lines):
                    next_line = fm_lines[j]
                    # 2スペース以上のインデントがある行を連結対象とする
                    if re.match(r'^  +\S', next_line):
                        multiline_parts.append(next_line.strip())
                        j += 1
                    else:
                        break
                value = ' '.join(multiline_parts)
                i = j
                fm_dict[key] = value
                continue
            fm_dict[key] = value
        i += 1

    body = '\n'.join(lines[body_start:])
    return fm_dict, body


def _parse_metadata_table(lines):
    """Markdown テーブルからキーバリューを抽出する。

    `| key | value |` 形式のテーブル行を辞書化する。
    ヘッダー行とセパレータ行（`| --- | --- |`）はスキップする。

    Args:
        lines: テーブル行のリスト

    Returns:
        dict: テーブルから抽出したキーバリュー辞書
    """
    result = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith('|'):
            continue
        # セパレータ行をスキップ
        if re.match(r'^\|[\s\-:]+\|[\s\-:]+\|$', stripped):
            continue
        cells = [c.strip() for c in stripped.split('|')]
        # 先頭・末尾の空セルを除去
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            key = cells[0].strip()
            value = cells[1].strip()
            if key and not re.match(r'^-+$', key):
                result[key] = value
    return result


def _extract_keywords(title, headings, metadata_table, max_keywords=10):
    """title・headings・metadata_table からキーワードを抽出する。

    重複除去、最大 max_keywords 語。
    0 件の場合はファイル名から 1 語を生成する（呼び出し元で保証）。

    Args:
        title: ドキュメントタイトル
        headings: 見出しテキストのリスト
        metadata_table: メタデータテーブルの辞書
        max_keywords: 最大キーワード数

    Returns:
        list[str]: キーワードリスト
    """
    words = []

    # title の単語
    if title:
        words.extend(_split_to_words(title))

    # headings の単語
    for h in headings:
        words.extend(_split_to_words(h))

    # metadata_table から特定のキーの値を抽出
    for key in ('関連要件', '関連設計', '要件ID', '設計ID'):
        value = metadata_table.get(key, '')
        if value:
            # REQ-005, DES-009 等の ID をキーワード化
            ids = re.findall(r'[A-Z]+-\d+', value)
            words.extend(ids)

    # 重複除去（順序保持）
    seen = set()
    unique = []
    for w in words:
        w_lower = w.lower()
        if w_lower not in seen and len(w) > 1:
            seen.add(w_lower)
            unique.append(w)

    return unique[:max_keywords]


def _split_to_words(text):
    """テキストを単語に分割する。

    日本語テキストはそのまま、英数字テキストはスペース・記号で分割。
    短すぎる単語（1文字以下）は除外。

    Args:
        text: 分割対象のテキスト

    Returns:
        list[str]: 単語リスト
    """
    if not text:
        return []
    # 記号・スペースで分割
    tokens = re.split(r'[\s\-_/():,.\[\]{}|「」（）、。・]+', text)
    # 空文字列と1文字以下の英数字を除外（日本語1文字は許容）
    result = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        # 純粋な英数字で1文字以下のものは除外
        if re.match(r'^[a-zA-Z0-9]$', t):
            continue
        result.append(t)
    return result


def _filename_to_title(filepath):
    """ファイル名からタイトルを生成する。

    スネークケース・ケバブケースをタイトルケースに変換する。
    拡張子は除去する。

    Args:
        filepath: ファイルパス（Path または str）

    Returns:
        str: 生成されたタイトル
    """
    stem = Path(filepath).stem
    # スネークケース・ケバブケースをスペース区切りに変換
    title = re.sub(r'[-_]', ' ', stem)
    # 各単語の先頭を大文字にする
    title = title.title()
    return title


def resolve_doc_type(filepath, doc_types_map, category=None):
    """ファイルパスから doc_type を決定する。

    doc_types_map の最長一致 → determine_doc_type() フォールバック。

    入力は相対パスを前提とする。絶対パスが渡された場合は
    先頭の `/` を除去して相対パスとして扱う。

    Args:
        filepath: ファイルの相対パス（プロジェクトルートからの相対パス）
        doc_types_map: パス→doc_type のマッピング辞書
        category: カテゴリ名（フォールバック用）

    Returns:
        str: doc_type 文字列
    """
    filepath_str = str(filepath)
    # 絶対パスの場合は先頭の `/` を除去して相対パスとして正規化
    if filepath_str.startswith('/'):
        filepath_str = filepath_str.lstrip('/')

    if doc_types_map:
        # 最長一致でマッチするパスを探す
        best_match = ''
        best_type = ''
        for path_prefix, doc_type in doc_types_map.items():
            normalized_prefix = path_prefix.rstrip('/')
            if filepath_str.startswith(normalized_prefix + '/') or filepath_str == normalized_prefix:
                if len(normalized_prefix) > len(best_match):
                    best_match = normalized_prefix
                    best_type = doc_type
        if best_type:
            return best_type

    # フォールバック: root_dir_name から推定
    # filepath の先頭ディレクトリを root_dir_name として使用
    parts = filepath_str.replace('\\', '/').split('/')
    root_dir_name = parts[0] if parts else ''

    return determine_doc_type(root_dir_name, doc_types_map=doc_types_map, category=category)


class MetadataExtractor:
    """Markdown ファイルからメタデータを抽出するクラス。

    設計書 DES-009 §5.2 のアルゴリズムに従い、以下のメタデータを抽出する:
    - title: H1 見出し（なければファイル名から生成）
    - purpose: frontmatter description/purpose → 概要セクション → first_para
    - doc_type: doc_types_map の最長一致 → determine_doc_type() フォールバック
    - content_details: H2/H3 見出しから最大10件
    - keywords: title・headings・metadata_table から抽出
    - applicable_tasks: doc_type ベースの汎用タスク

    全フィールドの非空保証を行い、validate_toc.py の検査を通過するエントリを生成する。
    """

    def __init__(self, file_path, doc_types_map, category):
        """初期化。ファイルを読み込み、frontmatter・本文・見出しをパースする。

        Args:
            file_path: 対象ファイルのパス（プロジェクトルートからの相対パス文字列）
            doc_types_map: パス→doc_type のマッピング辞書
            category: カテゴリ名（'rules' または 'specs'）
        """
        self.file_path = file_path
        self.doc_types_map = doc_types_map
        self.category = category

        self._title = None
        self._frontmatter = {}
        self._body = ''
        self._headings = []
        self._metadata_table = {}
        self._overview_text = ''
        self._first_para = ''
        self.parse_error = False

        self._parse()

    def _parse(self):
        """ファイルを読み込み、構造をパースする。"""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except (IOError, OSError, PermissionError, UnicodeDecodeError):
            self.parse_error = True
            return

        if not content.strip():
            return

        # frontmatter パース
        self._frontmatter, self._body = _parse_frontmatter(content)

        # 本文から構造を解析
        self._parse_body()

    def _parse_body(self):
        """本文を1パスで走査し、H1・H2/H3・セクション情報を構築する。

        設計書 §5.2 ステップ 3-4 に対応:
        - title: 最初の H1 見出し
        - metadata_table: 「メタデータ」セクションのテーブル
        - overview_text: 概要セクションの本文（最大2行）
        - headings: H2/H3 見出しテキスト（メタデータ・改定履歴除外）
        - first_para: H1 直後の最初の段落テキスト
        """
        lines = self._body.split('\n')

        current_section = None  # 現在のセクション種別 ('overview', 'metadata', 'excluded', 'normal', None)
        overview_lines = []
        metadata_table_lines = []
        first_para_lines = []
        found_h1 = False
        in_h1_section = False  # H1 直後のセクション（first_para 抽出用）

        for line in lines:
            stripped = line.strip()

            # H1 見出しの検出
            h1_match = re.match(r'^#\s+(.+)$', stripped)
            if h1_match:
                if not found_h1:
                    self._title = h1_match.group(1).strip()
                    found_h1 = True
                    in_h1_section = True
                    current_section = None
                continue

            # H2/H3 見出しの検出
            h23_match = re.match(r'^(#{2,3})\s+(.+)$', stripped)
            if h23_match:
                heading_level = len(h23_match.group(1))
                heading_text = h23_match.group(2).strip()
                normalized = _normalize_heading_text(heading_text)
                normalized_lower = normalized.lower()

                in_h1_section = False

                # セクション種別の判定
                if normalized_lower in _OVERVIEW_KEYWORDS:
                    current_section = 'overview'
                elif normalized_lower in _METADATA_KEYWORDS:
                    current_section = 'metadata'
                elif normalized_lower in _EXCLUDED_SECTION_KEYWORDS:
                    current_section = 'excluded'
                else:
                    current_section = 'normal'
                    # headings に追加（除外セクション以外）
                    self._headings.append(normalized)
                continue

            # H4以上の見出し（セクション区切りとしては無視するが、内容収集は続行）
            if re.match(r'^#{4,}\s+', stripped):
                continue

            # 空行の処理
            if not stripped:
                # first_para の区切り
                if in_h1_section and first_para_lines:
                    in_h1_section = False
                continue

            # セクション内容の収集
            if current_section == 'overview':
                if len(overview_lines) < 2 and not stripped.startswith('|'):
                    overview_lines.append(stripped)
            elif current_section == 'metadata':
                if stripped.startswith('|'):
                    metadata_table_lines.append(stripped)

            # first_para の収集（H1 直後の最初の段落、見出しやテーブルは除外）
            if in_h1_section and not stripped.startswith('#') and not stripped.startswith('|'):
                first_para_lines.append(stripped)

        # 解析結果の構築
        self._overview_text = ' '.join(overview_lines).strip()
        self._metadata_table = _parse_metadata_table(metadata_table_lines)
        self._first_para = ' '.join(first_para_lines).strip()

    def extract_title(self):
        """タイトルを抽出する。

        H1 見出しがあればそれを使用、なければファイル名から生成する。

        Returns:
            str: タイトル文字列（非空保証）
        """
        if self._title:
            return self._title
        return _filename_to_title(self.file_path)

    def extract_purpose(self):
        """purpose を抽出する。

        優先順:
        1. frontmatter の description フィールド
        2. frontmatter の purpose フィールド
        3. 概要セクションのテキスト
        4. first_para

        Returns:
            str: purpose 文字列（非空保証）
        """
        # frontmatter の description
        desc = self._frontmatter.get('description', '').strip()
        if desc:
            return desc

        # frontmatter の purpose
        purpose = self._frontmatter.get('purpose', '').strip()
        if purpose:
            return purpose

        # 概要セクション
        if self._overview_text:
            return self._overview_text

        # first_para
        if self._first_para:
            return self._first_para

        # フォールバック: タイトルから生成
        title = self.extract_title()
        return f"{title}に関するドキュメント"

    def extract_content_details(self, max_items=10):
        """content_details を抽出する。

        H2/H3 見出しから最大10件。0件の場合は first_para から1項目生成。

        Args:
            max_items: 最大項目数

        Returns:
            list[str]: content_details リスト（非空保証）
        """
        if self._headings:
            return self._headings[:max_items]

        # フォールバック: first_para から 1 項目
        if self._first_para:
            # 長すぎる場合は先頭100文字で切る
            text = self._first_para[:100]
            if len(self._first_para) > 100:
                text += '...'
            return [text]

        # 最終フォールバック: タイトルから生成
        title = self.extract_title()
        return [f"{title}の内容"]

    def extract_doc_type(self):
        """doc_type を決定する。

        doc_types_map の最長一致 → determine_doc_type() フォールバック。

        Returns:
            str: doc_type 文字列（非空保証）
        """
        return resolve_doc_type(
            self.file_path,
            doc_types_map=self.doc_types_map,
            category=self.category,
        )

    def extract_keywords(self, max_keywords=10):
        """キーワードを抽出する。

        title・headings・metadata_table から抽出。0件の場合はタイトルから生成。

        Args:
            max_keywords: 最大キーワード数

        Returns:
            list[str]: キーワードリスト（非空保証）
        """
        keywords = _extract_keywords(
            self.extract_title(),
            self._headings,
            self._metadata_table,
            max_keywords=max_keywords,
        )

        if keywords:
            return keywords

        # フォールバック: タイトルの単語分割
        title_words = _split_to_words(self.extract_title())
        if title_words:
            return title_words[:max_keywords]

        # 最終フォールバック: ファイル名から 1 語
        stem = Path(self.file_path).stem
        return [stem]

    def extract_applicable_tasks(self):
        """applicable_tasks を生成する。

        doc_type ベースの汎用タスクを 1 件以上生成。

        Returns:
            list[str]: applicable_tasks リスト（非空保証）
        """
        doc_type = self.extract_doc_type()

        tasks = _APPLICABLE_TASKS_MAP.get(doc_type, [])
        if tasks:
            return list(tasks)  # コピーを返す

        # フォールバック: doc_type + "関連" で1項目
        return [f"{doc_type}関連"]

    def extract_metadata(self):
        """全メタデータフィールドを辞書として返す。

        validate_toc.py が要求する必須フィールドを全て含み、
        全フィールドが非空であることを保証する。

        ファイル読み込みに失敗した場合（parse_error が True）は None を返す。
        呼び出し元でスキップ判定に使用する。

        Returns:
            dict | None: メタデータ辞書。読み込み失敗時は None
        """
        if self.parse_error:
            return None
        return {
            'title': self.extract_title(),
            'purpose': self.extract_purpose(),
            'doc_type': self.extract_doc_type(),
            'content_details': self.extract_content_details(),
            'keywords': self.extract_keywords(),
            'applicable_tasks': self.extract_applicable_tasks(),
        }
