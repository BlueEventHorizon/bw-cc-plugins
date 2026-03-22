#!/usr/bin/env python3
"""skill_monitor の単体テスト。

YamlReader（設計書 5.5 節）と SkillMonitorServer / RequestHandler
（設計書 5.1〜5.2 節）のテストを含む。
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection

# プラグインスクリプトへのパスを追加
SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "plugins", "forge", "scripts"
)
sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))

from skill_monitor import YamlReader, SkillMonitorServer, RequestHandler


class TestYamlReaderReadYamlFile(unittest.TestCase):
    """YamlReader.read_yaml_file() のテスト。"""

    def setUp(self):
        self.reader = YamlReader()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write(self, filename, content):
        """テスト用ファイルを作成する。"""
        filepath = os.path.join(self.tmpdir, filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath

    # ------------------------------------------------------------------
    # パターン1: フラット key-value（session.yaml）
    # ------------------------------------------------------------------

    def test_flat_session_yaml(self):
        """フラット key-value（session.yaml 形式）を正しくパースする。"""
        filepath = self._write("session.yaml", """\
skill: review
started_at: "2026-03-09T18:30:00Z"
last_updated: "2026-03-09T18:30:00Z"
status: in_progress
resume_policy: resume
review_type: code
engine: codex
auto_count: 0
current_cycle: 0
""")
        result = self.reader.read_yaml_file(filepath)
        self.assertIsNotNone(result)
        self.assertEqual(result["skill"], "review")
        self.assertEqual(result["status"], "in_progress")
        self.assertEqual(result["review_type"], "code")
        self.assertEqual(result["engine"], "codex")
        self.assertEqual(result["auto_count"], 0)
        self.assertEqual(result["current_cycle"], 0)

    def test_flat_start_design_session_yaml(self):
        """start-design の session.yaml をパースする。"""
        filepath = self._write("session.yaml", """\
skill: start-design
feature: login
mode: new
started_at: "2026-03-12T10:00:00Z"
last_updated: "2026-03-12T10:05:00Z"
status: in_progress
resume_policy: none
output_dir: "specs/login/design"
""")
        result = self.reader.read_yaml_file(filepath)
        self.assertIsNotNone(result)
        self.assertEqual(result["skill"], "start-design")
        self.assertEqual(result["feature"], "login")
        self.assertEqual(result["mode"], "new")
        self.assertEqual(result["output_dir"], "specs/login/design")

    # ------------------------------------------------------------------
    # パターン2: リスト付き構造（plan.yaml, evaluation.yaml）
    # ------------------------------------------------------------------

    def test_plan_yaml_items_list(self):
        """plan.yaml の items リストを正しくパースする。"""
        filepath = self._write("plan.yaml", """\
items:
  - id: 1
    severity: critical
    title: "help と review のコマンド仕様不一致"
    status: fixed
    fixed_at: "2026-03-09T18:35:00Z"
    files_modified:
      - plugins/forge/skills/help/SKILL.md
  - id: 2
    severity: major
    title: "設計意図が不明瞭な処理"
    status: needs_review
""")
        result = self.reader.read_yaml_file(filepath)
        self.assertIsNotNone(result)
        self.assertIn("items", result)
        items = result["items"]
        self.assertEqual(len(items), 2)

        # 1件目
        self.assertEqual(items[0]["id"], 1)
        self.assertEqual(items[0]["severity"], "critical")
        self.assertEqual(items[0]["title"], "help と review のコマンド仕様不一致")
        self.assertEqual(items[0]["status"], "fixed")
        self.assertEqual(items[0]["fixed_at"], "2026-03-09T18:35:00Z")
        self.assertIsInstance(items[0]["files_modified"], list)
        self.assertEqual(len(items[0]["files_modified"]), 1)
        self.assertEqual(
            items[0]["files_modified"][0],
            "plugins/forge/skills/help/SKILL.md",
        )

        # 2件目
        self.assertEqual(items[1]["id"], 2)
        self.assertEqual(items[1]["severity"], "major")
        self.assertEqual(items[1]["status"], "needs_review")

    def test_evaluation_yaml(self):
        """evaluation.yaml の items リストを正しくパースする。"""
        filepath = self._write("evaluation.yaml", """\
cycle: 1
items:
  - id: 1
    severity: critical
    title: "help と review のコマンド仕様不一致"
    recommendation: fix
    auto_fixable: false
    reason: "明確な仕様不一致、副作用なし"
  - id: 2
    severity: major
    title: "設計意図が不明瞭な処理"
    recommendation: needs_review
    reason: "意図的な設計の可能性があり、確認が必要"
""")
        result = self.reader.read_yaml_file(filepath)
        self.assertIsNotNone(result)
        self.assertEqual(result["cycle"], 1)
        self.assertIn("items", result)
        items = result["items"]
        self.assertEqual(len(items), 2)

        self.assertEqual(items[0]["id"], 1)
        self.assertEqual(items[0]["recommendation"], "fix")
        self.assertEqual(items[0]["auto_fixable"], False)

        self.assertEqual(items[1]["id"], 2)
        self.assertEqual(items[1]["recommendation"], "needs_review")

    def test_plan_yaml_with_inline_array(self):
        """plan.yaml の files_modified がインライン配列の場合。"""
        filepath = self._write("plan.yaml", """\
items:
  - id: 1
    severity: critical
    title: "テスト指摘"
    status: fixed
    fixed_at: "2026-03-09T18:35:00Z"
    files_modified: []
    skip_reason: ""
""")
        result = self.reader.read_yaml_file(filepath)
        items = result["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["files_modified"], [])
        self.assertEqual(items[0]["skip_reason"], "")

    # ------------------------------------------------------------------
    # パターン3: ネストオブジェクト付きリスト（refs.yaml）
    # ------------------------------------------------------------------

    def test_refs_yaml_nested_objects(self):
        """refs.yaml のネストオブジェクト付きリストを正しくパースする。"""
        filepath = self._write("refs.yaml", """\
target_files:
  - plugins/forge/skills/review/SKILL.md
  - plugins/forge/skills/reviewer/SKILL.md
reference_docs:
  - path: docs/rules/skill_authoring_notes.md
  - path: plugins/forge/docs/review_criteria_spec.md
perspectives:
  - name: correctness
    criteria_path: plugins/forge/docs/review_criteria_spec.md
    section: "正確性 (Logic)"
    output_path: review_correctness.md
related_code:
  - path: plugins/forge/skills/reviewer/SKILL.md
    reason: "同種 AI 専用スキルの frontmatter 参考"
    lines: "1-30"
  - path: plugins/forge/skills/evaluator/SKILL.md
    reason: "同種 AI 専用スキルの frontmatter 参考"
""")
        result = self.reader.read_yaml_file(filepath)
        self.assertIsNotNone(result)

        # target_files: 文字列リスト
        self.assertIn("target_files", result)
        self.assertEqual(len(result["target_files"]), 2)
        self.assertEqual(
            result["target_files"][0],
            "plugins/forge/skills/review/SKILL.md",
        )

        # reference_docs: オブジェクトリスト（path のみ）
        self.assertIn("reference_docs", result)
        self.assertEqual(len(result["reference_docs"]), 2)
        self.assertEqual(
            result["reference_docs"][0]["path"],
            "docs/rules/skill_authoring_notes.md",
        )

        # perspectives: オブジェクトリスト
        self.assertIn("perspectives", result)
        self.assertEqual(len(result["perspectives"]), 1)
        self.assertEqual(result["perspectives"][0]["name"], "correctness")
        self.assertEqual(
            result["perspectives"][0]["criteria_path"],
            "plugins/forge/docs/review_criteria_spec.md",
        )
        self.assertEqual(
            result["perspectives"][0]["section"], "正確性 (Logic)"
        )
        self.assertEqual(
            result["perspectives"][0]["output_path"], "review_correctness.md"
        )

        # related_code: オブジェクトリスト（複数フィールド）
        self.assertIn("related_code", result)
        self.assertEqual(len(result["related_code"]), 2)
        self.assertEqual(
            result["related_code"][0]["path"],
            "plugins/forge/skills/reviewer/SKILL.md",
        )
        self.assertEqual(result["related_code"][0]["lines"], "1-30")
        self.assertEqual(
            result["related_code"][1]["path"],
            "plugins/forge/skills/evaluator/SKILL.md",
        )

    def test_refs_dir_specs_yaml(self):
        """refs/specs.yaml（共通スキーマ）を正しくパースする。"""
        filepath = self._write("specs.yaml", """\
source: query-specs
query: "login feature design"
documents:
  - path: specs/requirements/app_overview.md
    reason: "アプリ全体の要件定義"
  - path: specs/design/login_screen_design.md
    reason: "ログイン画面の設計仕様"
    lines: "10-50"
""")
        result = self.reader.read_yaml_file(filepath)
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "query-specs")
        self.assertEqual(result["query"], "login feature design")
        self.assertIn("documents", result)
        docs = result["documents"]
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0]["path"], "specs/requirements/app_overview.md")
        self.assertEqual(docs[0]["reason"], "アプリ全体の要件定義")
        self.assertEqual(docs[1]["lines"], "10-50")

    # ------------------------------------------------------------------
    # 存在しないファイル
    # ------------------------------------------------------------------

    def test_nonexistent_file_returns_none(self):
        """存在しないファイルに対して None を返す。"""
        filepath = os.path.join(self.tmpdir, "nonexistent.yaml")
        result = self.reader.read_yaml_file(filepath)
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # 空ファイル
    # ------------------------------------------------------------------

    def test_empty_file_returns_empty_dict(self):
        """空ファイルに対して空 dict を返す。"""
        filepath = self._write("empty.yaml", "")
        result = self.reader.read_yaml_file(filepath)
        self.assertEqual(result, {})

    def test_comment_only_file_returns_empty_dict(self):
        """コメントのみのファイルに対して空 dict を返す。"""
        filepath = self._write("comments.yaml", """\
# コメントのみ
# もう一行
""")
        result = self.reader.read_yaml_file(filepath)
        self.assertEqual(result, {})


class TestYamlReaderReadMarkdownFile(unittest.TestCase):
    """YamlReader.read_markdown_file() のテスト。"""

    def setUp(self):
        self.reader = YamlReader()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_read_review_md(self):
        """review.md を文字列としてそのまま読み込む。"""
        content = """\
### 🔴致命的問題

1. **[問題名]**: 具体的な説明
   - 箇所: ファイル名:42

### 🟡品質問題

1. **[品質問題]**: 説明

### サマリー

- 🔴致命的: 1件
- 🟡品質: 1件
"""
        filepath = os.path.join(self.tmpdir, "review.md")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        result = self.reader.read_markdown_file(filepath)
        self.assertEqual(result, content)

    def test_nonexistent_markdown_returns_none(self):
        """存在しない Markdown ファイルに対して None を返す。"""
        filepath = os.path.join(self.tmpdir, "nonexistent.md")
        result = self.reader.read_markdown_file(filepath)
        self.assertIsNone(result)


class TestYamlReaderReadSessionDir(unittest.TestCase):
    """YamlReader.read_session_dir() のテスト。"""

    def setUp(self):
        self.reader = YamlReader()
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = os.path.join(self.tmpdir, "review-abc123")
        os.makedirs(os.path.join(self.session_dir, "refs"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write(self, relative_path, content):
        """セッションディレクトリ内にファイルを作成する。"""
        filepath = os.path.join(self.session_dir, relative_path)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath

    def test_full_session_dir(self):
        """全ファイルが存在するセッションディレクトリを正しく読み込む。"""
        # セッション直下のファイル
        self._write("session.yaml", """\
skill: review
started_at: "2026-03-09T18:30:00Z"
last_updated: "2026-03-09T18:30:00Z"
status: in_progress
review_type: code
engine: claude
""")
        self._write("plan.yaml", """\
items:
  - id: 1
    severity: critical
    title: "問題1"
    status: pending
""")
        self._write("review.md", "## レビュー結果\n\nテスト")
        self._write("refs.yaml", """\
target_files:
  - test.py
perspectives:
  - name: correctness
    criteria_path: review/docs/review_criteria_code.md
    section: "正確性 (Logic)"
    output_path: review_correctness.md
reference_docs:
  - path: doc1.md
""")

        # refs/ ディレクトリ
        self._write("refs/specs.yaml", """\
source: query-specs
query: "test"
documents:
  - path: spec1.md
    reason: "テスト仕様"
""")

        result = self.reader.read_session_dir(self.session_dir)

        # 構造確認
        self.assertEqual(result["session_dir"], self.session_dir)

        # files
        self.assertTrue(result["files"]["session.yaml"]["exists"])
        self.assertEqual(
            result["files"]["session.yaml"]["content"]["skill"], "review"
        )

        self.assertTrue(result["files"]["plan.yaml"]["exists"])
        self.assertEqual(len(result["files"]["plan.yaml"]["content"]["items"]), 1)

        self.assertTrue(result["files"]["review.md"]["exists"])
        self.assertIn("レビュー結果", result["files"]["review.md"]["content"])

        # refs
        self.assertTrue(result["refs"]["specs.yaml"]["exists"])
        self.assertFalse(result["refs"]["rules.yaml"]["exists"])
        self.assertFalse(result["refs"]["code.yaml"]["exists"])

        # refs_yaml
        self.assertTrue(result["refs_yaml"]["exists"])
        self.assertIn("target_files", result["refs_yaml"]["content"])

    def test_empty_session_dir(self):
        """ファイルが存在しないセッションディレクトリを正しく処理する。"""
        result = self.reader.read_session_dir(self.session_dir)

        # 全ファイルが exists: false
        for filename in YamlReader.SESSION_FILES:
            self.assertFalse(result["files"][filename]["exists"])
            self.assertIsNone(result["files"][filename]["content"])

        for filename in YamlReader.REFS_FILES:
            self.assertFalse(result["refs"][filename]["exists"])
            self.assertIsNone(result["refs"][filename]["content"])

        self.assertFalse(result["refs_yaml"]["exists"])
        self.assertIsNone(result["refs_yaml"]["content"])

    def test_partial_session_dir(self):
        """一部のファイルのみ存在するセッションディレクトリ。"""
        self._write("session.yaml", """\
skill: review
status: in_progress
""")

        result = self.reader.read_session_dir(self.session_dir)

        # session.yaml は exists: true
        self.assertTrue(result["files"]["session.yaml"]["exists"])
        self.assertEqual(
            result["files"]["session.yaml"]["content"]["skill"], "review"
        )

        # 他は exists: false
        self.assertFalse(result["files"]["plan.yaml"]["exists"])
        self.assertFalse(result["files"]["review.md"]["exists"])


class TestYamlReaderEdgeCases(unittest.TestCase):
    """エッジケースのテスト。"""

    def setUp(self):
        self.reader = YamlReader()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write(self, filename, content):
        filepath = os.path.join(self.tmpdir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath

    def test_boolean_values(self):
        """真偽値を正しくパースする。"""
        filepath = self._write("test.yaml", """\
items:
  - id: 1
    auto_fixable: true
  - id: 2
    auto_fixable: false
""")
        result = self.reader.read_yaml_file(filepath)
        self.assertIs(result["items"][0]["auto_fixable"], True)
        self.assertIs(result["items"][1]["auto_fixable"], False)

    def test_japanese_values(self):
        """日本語を含む値を正しくパースする。"""
        filepath = self._write("test.yaml", """\
items:
  - id: 1
    title: "日本語のタイトル"
    reason: "理由の説明"
""")
        result = self.reader.read_yaml_file(filepath)
        self.assertEqual(result["items"][0]["title"], "日本語のタイトル")
        self.assertEqual(result["items"][0]["reason"], "理由の説明")

    def test_mixed_flat_and_list(self):
        """フラット値とリストが混在する YAML。"""
        filepath = self._write("test.yaml", """\
cycle: 1
status: in_progress
items:
  - id: 1
    severity: critical
    title: "テスト"
""")
        result = self.reader.read_yaml_file(filepath)
        self.assertEqual(result["cycle"], 1)
        self.assertEqual(result["status"], "in_progress")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["id"], 1)

    def test_string_list(self):
        """文字列のみのリストをパースする。"""
        filepath = self._write("test.yaml", """\
target_files:
  - path/to/file1.py
  - path/to/file2.py
  - path/to/file3.py
""")
        result = self.reader.read_yaml_file(filepath)
        self.assertEqual(len(result["target_files"]), 3)
        self.assertEqual(result["target_files"][0], "path/to/file1.py")
        self.assertEqual(result["target_files"][2], "path/to/file3.py")

    def test_nested_string_list(self):
        """オブジェクト内のネストされた文字列リスト。"""
        filepath = self._write("test.yaml", """\
items:
  - id: 1
    title: "テスト"
    files_modified:
      - file1.py
      - file2.py
""")
        result = self.reader.read_yaml_file(filepath)
        item = result["items"][0]
        self.assertIsInstance(item["files_modified"], list)
        self.assertEqual(len(item["files_modified"]), 2)
        self.assertEqual(item["files_modified"][0], "file1.py")


# ======================================================================
# SSE サーバーのテスト（設計書 5.1〜5.2 節）
# ======================================================================

def _find_free_port():
    """空きポートを取得する。"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestSkillMonitorServerEndpoints(unittest.TestCase):
    """API エンドポイントのテスト。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = os.path.join(self.tmpdir, "review-test123")
        os.makedirs(os.path.join(self.session_dir, "refs"))

        # session.yaml を作成
        with open(
            os.path.join(self.session_dir, "session.yaml"), "w", encoding="utf-8"
        ) as f:
            f.write("skill: review\nstatus: in_progress\n")

        self.port = _find_free_port()
        self.server = SkillMonitorServer(self.session_dir, port=self.port)
        self.server_thread = threading.Thread(target=self.server.start, daemon=True)
        self.server_thread.start()
        # サーバー起動を待つ
        time.sleep(0.3)

    def tearDown(self):
        self.server.stop()
        self.server_thread.join(timeout=5)
        shutil.rmtree(self.tmpdir)

    def _get(self, path):
        """GET リクエストを送信する。"""
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp, body

    def _post(self, path, data):
        """POST リクエストを送信する。"""
        body = json.dumps(data).encode("utf-8")
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(
            "POST", path, body=body,
            headers={"Content-Type": "application/json"}
        )
        resp = conn.getresponse()
        resp_body = resp.read()
        conn.close()
        return resp, resp_body

    def test_get_index_coming_soon(self):
        """GET / — index.html が存在しない場合「Coming soon」を返す。"""
        resp, body = self._get("/")
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.getheader("Content-Type"))
        self.assertEqual(body, b"Coming soon")

    def test_get_session(self):
        """GET /session — セッション全体を JSON で返す。"""
        resp, body = self._get("/session")
        self.assertEqual(resp.status, 200)
        self.assertIn("application/json", resp.getheader("Content-Type"))
        data = json.loads(body)
        self.assertEqual(data["session_dir"], self.session_dir)
        self.assertTrue(data["files"]["session.yaml"]["exists"])
        self.assertEqual(
            data["files"]["session.yaml"]["content"]["skill"], "review"
        )

    def test_get_history_empty(self):
        """GET /history — 初期状態では空配列を返す。"""
        resp, body = self._get("/history")
        self.assertEqual(resp.status, 200)
        data = json.loads(body)
        self.assertEqual(data, [])

    def test_post_notify_updates_history(self):
        """POST /notify — 履歴に追記される。"""
        resp, body = self._post("/notify", {"file": "plan.yaml"})
        self.assertEqual(resp.status, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], "ok")

        # /history で確認
        resp2, body2 = self._get("/history")
        history = json.loads(body2)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["file"], "plan.yaml")
        self.assertEqual(history[0]["event"], "update")
        self.assertIn("timestamp", history[0])

    def test_post_notify_multiple(self):
        """POST /notify — 複数の通知が履歴に蓄積される。"""
        self._post("/notify", {"file": "plan.yaml"})
        self._post("/notify", {"file": "session.yaml"})
        self._post("/notify", {"file": "review.md"})

        resp, body = self._get("/history")
        history = json.loads(body)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["file"], "plan.yaml")
        self.assertEqual(history[1]["file"], "session.yaml")
        self.assertEqual(history[2]["file"], "review.md")

    def test_get_not_found(self):
        """GET /unknown — 404 を返す。"""
        resp, body = self._get("/unknown")
        self.assertEqual(resp.status, 404)

    def test_post_not_found(self):
        """POST /unknown — 404 を返す。"""
        resp, body = self._post("/unknown", {})
        self.assertEqual(resp.status, 404)

    def test_post_notify_invalid_json(self):
        """POST /notify — 不正な JSON で 400 を返す。"""
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(
            "POST", "/notify", body=b"not json",
            headers={"Content-Type": "application/json"}
        )
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 400)


class TestSSEPush(unittest.TestCase):
    """SSE Push のテスト。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = os.path.join(self.tmpdir, "review-sse-test")
        os.makedirs(os.path.join(self.session_dir, "refs"))

        with open(
            os.path.join(self.session_dir, "session.yaml"), "w", encoding="utf-8"
        ) as f:
            f.write("skill: review\nstatus: in_progress\n")

        self.port = _find_free_port()
        self.server = SkillMonitorServer(self.session_dir, port=self.port)
        self.server_thread = threading.Thread(target=self.server.start, daemon=True)
        self.server_thread.start()
        time.sleep(0.3)

    def tearDown(self):
        self.server.stop()
        self.server_thread.join(timeout=5)
        shutil.rmtree(self.tmpdir)

    def test_sse_receives_update_event(self):
        """SSE ストリームで update イベントを受信できる。"""
        import socket

        received_data = []
        connect_event = threading.Event()

        def sse_reader():
            """SSE ストリームを raw ソケットで読み取る。"""
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10)
                sock.connect(("127.0.0.1", self.port))
                sock.sendall(
                    b"GET /sse HTTP/1.1\r\n"
                    b"Host: 127.0.0.1\r\n"
                    b"Accept: text/event-stream\r\n"
                    b"\r\n"
                )
                connect_event.set()

                buffer = ""
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk.decode("utf-8")
                    # HTTP ヘッダ以降のイベントデータを解析
                    if "data: " in buffer:
                        for line in buffer.split("\n"):
                            if line.startswith("data: "):
                                data = json.loads(line[6:])
                                received_data.append(data)
                                sock.close()
                                return
            except Exception:
                pass
            finally:
                try:
                    sock.close()
                except Exception:
                    pass

        reader_thread = threading.Thread(target=sse_reader, daemon=True)
        reader_thread.start()
        connect_event.wait(timeout=3)
        time.sleep(0.3)

        # 通知を送信
        body = json.dumps({"file": "plan.yaml"}).encode("utf-8")
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(
            "POST", "/notify", body=body,
            headers={"Content-Type": "application/json"}
        )
        resp = conn.getresponse()
        resp.read()
        conn.close()

        reader_thread.join(timeout=5)

        self.assertTrue(len(received_data) > 0, "SSE イベントが受信されなかった")
        self.assertEqual(received_data[0]["type"], "update")
        self.assertEqual(received_data[0]["file"], "plan.yaml")
        self.assertIn("timestamp", received_data[0])


class TestHeartbeat(unittest.TestCase):
    """ハートビートによる自動停止のテスト。"""

    def test_heartbeat_detects_session_dir_removal(self):
        """heartbeat_interval を短周期にして _heartbeat_loop の実経路をテストする。

        session_dir を削除すると、ハートビートがそれを検知して
        サーバーが自動停止することを確認する。
        """
        tmpdir = tempfile.mkdtemp()
        session_dir = os.path.join(tmpdir, "review-hb-real-test")
        os.makedirs(os.path.join(session_dir, "refs"))

        with open(
            os.path.join(session_dir, "session.yaml"), "w", encoding="utf-8"
        ) as f:
            f.write("skill: review\nstatus: in_progress\n")

        port = _find_free_port()
        server = SkillMonitorServer(
            session_dir, port=port, heartbeat_interval=0.5
        )
        server_thread = threading.Thread(target=server.start, daemon=True)
        server_thread.start()
        time.sleep(0.3)

        try:
            # session_dir を削除
            shutil.rmtree(session_dir)

            # ハートビート（0.5秒周期）が検知して自動停止するのを待つ
            server_thread.join(timeout=5)
            self.assertFalse(
                server_thread.is_alive(),
                "ハートビートが session_dir 消失を検知してサーバーを停止すべき",
            )
        finally:
            server.stop()
            if os.path.exists(tmpdir):
                shutil.rmtree(tmpdir)

    def test_session_dir_removal_triggers_shutdown(self):
        """session_dir が消失するとサーバーが自動停止する。

        session_dir 消失時の /notify の挙動をテストする。
        """
        tmpdir = tempfile.mkdtemp()
        session_dir = os.path.join(tmpdir, "review-hb-test")
        os.makedirs(os.path.join(session_dir, "refs"))

        with open(
            os.path.join(session_dir, "session.yaml"), "w", encoding="utf-8"
        ) as f:
            f.write("skill: review\nstatus: in_progress\n")

        port = _find_free_port()
        server = SkillMonitorServer(session_dir, port=port)
        server_thread = threading.Thread(target=server.start, daemon=True)
        server_thread.start()
        time.sleep(0.3)

        try:
            # session_dir を削除
            shutil.rmtree(session_dir)

            # /notify を送信 → session_end を検知
            body = json.dumps({"file": "plan.yaml"}).encode("utf-8")
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request(
                "POST", "/notify", body=body,
                headers={"Content-Type": "application/json"}
            )
            resp = conn.getresponse()
            resp_body = resp.read()
            conn.close()

            data = json.loads(resp_body)
            self.assertEqual(data["status"], "session_end")

            # サーバー停止を待つ
            server_thread.join(timeout=5)
        finally:
            server.stop()
            if os.path.exists(tmpdir):
                shutil.rmtree(tmpdir)


class TestSkillMonitorServerInit(unittest.TestCase):
    """SkillMonitorServer の初期化テスト。"""

    def test_port_bind_failure(self):
        """同じポートで2つのサーバーを起動するとエラーになる。"""
        tmpdir = tempfile.mkdtemp()
        session_dir = os.path.join(tmpdir, "review-port-test")
        os.makedirs(session_dir)

        port = _find_free_port()
        server1 = SkillMonitorServer(session_dir, port=port)

        try:
            with self.assertRaises(OSError):
                SkillMonitorServer(session_dir, port=port)
        finally:
            server1.server_close()
            shutil.rmtree(tmpdir)

    def test_server_attributes(self):
        """サーバーの初期属性が正しく設定される。"""
        tmpdir = tempfile.mkdtemp()
        session_dir = os.path.join(tmpdir, "review-attr-test")
        os.makedirs(session_dir)

        port = _find_free_port()
        server = SkillMonitorServer(session_dir, port=port)

        try:
            self.assertEqual(server.session_dir, session_dir)
            self.assertEqual(server.port, port)
            self.assertEqual(server.history, [])
            self.assertEqual(server.sse_clients, [])
            self.assertFalse(server.shutdown_event.is_set())
        finally:
            server.server_close()
            shutil.rmtree(tmpdir)


class TestSkillMonitorCLI(unittest.TestCase):
    """CLI エントリーポイント（main()）のテスト。

    設計書 DES-012 5.1 節で定義された CLI エラー契約を検証する:
      - session_dir が存在しない場合: stderr に JSON エラーを出力して exit 1
      - ポートバインド失敗時: stderr に JSON エラーを出力して exit 1
    """

    # skill_monitor.py のパス
    SCRIPT_PATH = os.path.join(
        os.path.dirname(__file__), "..", "..", "..",
        "plugins", "forge", "scripts", "skill_monitor.py",
    )

    def test_session_dir_not_found(self):
        """存在しない session_dir を渡すと exit 1 で JSON エラーを返す。"""
        import subprocess

        fake_dir = os.path.join(tempfile.gettempdir(), "nonexistent_session_dir_xyz")
        # 万が一存在していたら削除
        if os.path.exists(fake_dir):
            shutil.rmtree(fake_dir)

        result = subprocess.run(
            [sys.executable, self.SCRIPT_PATH, fake_dir, "--no-open"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 1)
        # stderr に JSON エラーが出力される
        error = json.loads(result.stderr.strip())
        self.assertEqual(error["error"], "session_dir_not_found")
        self.assertEqual(error["session_dir"], fake_dir)

    def test_port_bind_failed(self):
        """ポートが既に使用中の場合 exit 1 で JSON エラーを返す。"""
        import socket
        import subprocess

        tmpdir = tempfile.mkdtemp()
        session_dir = os.path.join(tmpdir, "review-cli-port-test")
        os.makedirs(session_dir)

        try:
            # 先にポートをバインドしておく
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

            result = subprocess.run(
                [
                    sys.executable, self.SCRIPT_PATH,
                    session_dir, "--port", str(port), "--no-open",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(result.returncode, 1)
            # stderr に JSON エラーが出力される
            error = json.loads(result.stderr.strip())
            self.assertEqual(error["error"], "port_bind_failed")
            self.assertEqual(error["port"], port)
        finally:
            sock.close()
            shutil.rmtree(tmpdir)


if __name__ == "__main__":
    unittest.main()
