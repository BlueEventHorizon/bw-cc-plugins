#!/usr/bin/env python3
"""review: 常駐 Codex セッションの cmux pane を発見する read-only CLI。

`project_root` の cwd と一致する cmux workspace を探し、その中で実際に Codex プロセスが
稼働している surface を探す。副作用は一切無い（ファイルへの書き込み・cmux send 等は行わない）。
発見結果はキャッシュしない——毎回この場で呼び出すことを前提とする（cmux が同じ pane を
維持したまま workspace ID だけを再発行することがあり、キャッシュされた ID が stale 化
して機能しなくなる実事故が起きたため。発見処理自体は数回の cmux subprocess 呼び出しで
軽量であり、依頼往復ごとに高々1回しか呼ばれない）。

**検出方式は実プロセスの直接確認のみ（実インシデントで発見・単純化）**: 旧実装は
`resume_binding.kind == "codex"` や `initial_command` の正規表現一致という、cmux 自身の
「codex として再開した」という構造化記録（＝間接的な推測）に依存していた。ユーザーが
普通のターミナル surface で `codex` コマンドをそのまま起動した構成（cmux の resume 経由
ではない）では、この記録が一切残らず、Codex が実際に稼働していてもこの判定は必ず
`not_found` を返す実バグがあった。`cmux top --processes --json --id-format uuids` は
surface にアタッチされた実プロセス名を直接返す一次情報であり、cmux の resume 由来か
素のシェル起動かに関わらず、Codex プロセスが存在すれば必ず捕捉できる。したがって
メタデータ判定を「まず試し、ダメならプロセスツリーへフォールバック」という二段構えに
せず、実プロセス確認 1 本に統合した（二重の検出方式は保守対象が増えるだけで、
後者が前者を包含するため前者を残す理由がない）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess

# 実プロセスツリー走査で Codex 実行バイナリと判定するプロセス名パターン。
# 実測値: "codex-aarch64-a"（/opt/homebrew/Caskroom/codex/<version>/codex-aarch64-apple-darwin）。
_CODEX_PROCESS_NAME_PATTERN = re.compile(r"^codex(-|$)", re.IGNORECASE)


def _run_json(args: list[str]) -> tuple[dict | None, str | None]:
    """cmux サブコマンドを実行し、パース済み JSON か、失敗理由の文字列を返す。"""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"{' '.join(args)} の実行に失敗しました: {exc}"
    if proc.returncode != 0:
        detail = proc.stderr.strip()
        reason = f"{' '.join(args)} が非ゼロ終了しました"
        return None, f"{reason}: {detail}" if detail else reason
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, f"{' '.join(args)} の出力が JSON として解析できません"
    return data, None


def _codex_surfaces_with_running_process(workspace_id: str) -> tuple[list[str], str | None]:
    """workspace 内で実際に Codex プロセスがアタッチされている surface の UUID 一覧を返す
    （read-only、副作用無し）。戻り値は (surface_ids, error)。"""
    data, error = _run_json(
        ["cmux", "top", "--workspace", workspace_id, "--processes", "--json", "--id-format", "uuids"]
    )
    if error:
        return [], error
    if not isinstance(data, dict) or not isinstance(data.get("windows"), list):
        return [], f"workspace {workspace_id} の top --processes 出力スキーマが不正です"

    # `cmux top --workspace <id>` は cmux 自身が既に該当 workspace のみへ絞り込んで
    # 返す。返却 JSON 内で workspace id を再照合するのは cmux の絞り込みを信用しない
    # 冗長な二重チェックであり、行わない。
    surface_ids: set[str] = set()
    for window in data["windows"]:
        if not isinstance(window, dict):
            continue
        for ws in window.get("workspaces", []) or []:
            if not isinstance(ws, dict):
                continue
            for pane in ws.get("panes", []) or []:
                if not isinstance(pane, dict):
                    continue
                for s in pane.get("surfaces", []) or []:
                    if not isinstance(s, dict):
                        continue
                    surface_id = s.get("id")
                    if not surface_id:
                        continue
                    for p in s.get("processes", []) or []:
                        if not isinstance(p, dict):
                            continue
                        # surface 直下の top-level プロセスのみ判定する（cmux_surface_id は
                        # 直接アタッチされたプロセスにのみ設定され、その子プロセス（node 等）
                        # は null を継承するため誤って別 surface のプロセスを拾わない）。
                        if p.get("cmux_surface_id") != surface_id:
                            continue
                        name = p.get("name") or ""
                        if _CODEX_PROCESS_NAME_PATTERN.search(name):
                            surface_ids.add(surface_id)
    return list(surface_ids), None


def find_codex_pane(project_root: str) -> dict:
    canonical_root = os.path.realpath(project_root)

    ws_data, error = _run_json(["cmux", "workspace", "list", "--json", "--id-format", "uuids"])
    if error:
        return {"status": "error", "reason": error}
    if not isinstance(ws_data, dict) or not isinstance(ws_data.get("workspaces"), list):
        return {"status": "error", "reason": "workspace list の出力スキーマが不正です"}

    candidates = []
    inspection_errors = []
    for w in ws_data["workspaces"]:
        if not isinstance(w, dict):
            return {"status": "error", "reason": "workspace list に不正な workspace 要素があります"}
        cwd = w.get("current_directory")
        if not isinstance(cwd, str):
            return {"status": "error", "reason": "workspace の current_directory が不正です"}
        if os.path.realpath(cwd) != canonical_root:
            continue
        workspace_id = w.get("id")
        if not isinstance(workspace_id, str) or not workspace_id:
            inspection_errors.append("project_root に一致する workspace の id が不正です")
            continue

        panel_data, panel_error = _run_json(
            ["cmux", "list-panels", "--workspace", workspace_id, "--json", "--id-format", "uuids"]
        )
        if panel_error:
            inspection_errors.append(panel_error)
            continue
        if not isinstance(panel_data, dict) or not isinstance(panel_data.get("surfaces"), list):
            inspection_errors.append(f"workspace {workspace_id} の list-panels 出力スキーマが不正です")
            continue

        cwd_matched_surface_ids = set()
        for s in panel_data["surfaces"]:
            if not isinstance(s, dict):
                inspection_errors.append(
                    f"workspace {workspace_id} の list-panels に不正な surface 要素があります"
                )
                continue
            surface_id = s.get("id")
            if not surface_id:
                continue
            resume_binding = s.get("resume_binding") or {}
            if not isinstance(resume_binding, dict):
                inspection_errors.append(
                    f"workspace {workspace_id} の surface の resume_binding が不正です"
                )
                continue
            surface_cwd = resume_binding.get("cwd") or s.get("requested_working_directory")
            if surface_cwd and os.path.realpath(surface_cwd) == canonical_root:
                cwd_matched_surface_ids.add(surface_id)

        # project_root と cwd が一致する surface が1件も無ければ、この workspace に
        # プロセスツリー確認を行う意味が無い（無関係な surface の codex プロセスを
        # 誤って拾わないため、および無駄な subprocess 呼び出しを避けるため）。
        if not cwd_matched_surface_ids:
            continue

        codex_surface_ids, proc_error = _codex_surfaces_with_running_process(workspace_id)
        if proc_error:
            inspection_errors.append(proc_error)
            continue
        for surface_id in codex_surface_ids:
            if surface_id in cwd_matched_surface_ids:
                candidates.append((workspace_id, surface_id))

    # project_root に一致する workspace の調査に失敗している場合、その workspace に
    # Codex pane が存在しないとは断定できない。候補を勝手に選んで別 pane へ注入したり、
    # 「対象なし」という意図的な見送りとして失敗を隠したりしないため、機械的エラーとして
    # 呼び出し元へ返す。
    if inspection_errors:
        return {"status": "error", "reason": "; ".join(inspection_errors)}

    if not candidates:
        return {
            "status": "not_found",
            "reason": f"{canonical_root} で稼働中の Codex セッション（cmux pane）が見つかりません",
        }

    if len(candidates) > 1:
        return {
            "status": "ambiguous",
            "reason": f"{len(candidates)} 件の候補が見つかり、自動選択を見送りました",
        }

    workspace_id, surface_id = candidates[0]
    return {"status": "found", "workspace": workspace_id, "surface": surface_id}


def main() -> int:
    parser = argparse.ArgumentParser(description="常駐 Codex セッションの cmux pane を発見する（read-only）")
    parser.add_argument("project_root")
    args = parser.parse_args()

    result = find_codex_pane(args.project_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "found" else 1


if __name__ == "__main__":
    raise SystemExit(main())
