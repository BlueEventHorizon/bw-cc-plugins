"""review markdown から findings を抽出する純粋 parser。"""

import re
import sys

# セクションマーカーと severity のマッピング
SECTION_MARKERS = {
    "🔴": "critical",
    "🟡": "major",
    "🟢": "minor",
}

# 指摘事項の番号付きパターン
FINDING_PATTERN = re.compile(
    r"^\d+\.\s+"
    r"(\[(critical|major|minor)\]|(🔴|🟡|🟢))?\s*"
    r"\*\*(?:\[)?(.+?)(?:\])?\*\*\s*[:：]\s*(.*)"
)

# 箇所行のパターン（例: "   - 箇所: path/to/file.py:42"）
LOCATION_PATTERN = re.compile(r"^\s+-\s+箇所\s*[:：]\s*(.*)")


def extract_findings(content):
    """review.md から指摘事項を抽出する。"""
    findings = []
    current_severity = None
    finding_id = 0
    body_lines = []

    def flush_body():
        if not findings or findings[-1].get("_body_closed"):
            return
        trimmed = list(body_lines)
        while trimmed and trimmed[-1].strip() == "":
            trimmed.pop()
        if trimmed:
            findings[-1]["body"] = "\n".join(trimmed)
        findings[-1]["_body_closed"] = True

    def resolve_severity(label, marker):
        if label:
            return label
        if marker:
            return SECTION_MARKERS[marker]
        if current_severity:
            return current_severity
        return None

    def start_finding(title, line, label=None, marker=None):
        nonlocal finding_id, body_lines
        flush_body()
        severity = resolve_severity(label, marker)
        if severity is None:
            print(
                f"Warning: finding '{title}' has no severity label "
                f"([critical]/[major]/[minor]), no emoji marker, and no "
                f"section heading; defaulting to 'major'",
                file=sys.stderr,
            )
            severity = "major"
        finding_id += 1
        findings.append({
            "id": finding_id,
            "severity": severity,
            "title": title,
            "location": "",
            "status": "pending",
            "fixed_at": "",
            "files_modified": [],
            "skip_reason": "",
            "body": "",
        })
        body_lines = [line]

    for line in content.split("\n"):
        stripped = line.strip()

        if stripped.startswith("#"):
            severity_switched = False
            for marker, severity in SECTION_MARKERS.items():
                if marker in stripped:
                    flush_body()
                    body_lines = []
                    current_severity = severity
                    severity_switched = True
                    break
            if not severity_switched:
                if "### " in stripped and current_severity:
                    lower = stripped.lower()
                    if "サマリー" in lower or "summary" in lower:
                        flush_body()
                        body_lines = []
                        current_severity = None

            heading_text = stripped.lstrip("#").strip()
            match = FINDING_PATTERN.match(heading_text)
            if match:
                label = _normalize_label(match.group(1), match.group(2))
                marker = match.group(3)
                title = match.group(4).strip()
                if label or marker or current_severity:
                    start_finding(title, line, label=label, marker=marker)
            continue

        loc_match = LOCATION_PATTERN.match(line)
        if loc_match and findings:
            findings[-1]["location"] = loc_match.group(1).strip()
            body_lines.append(line)
            continue

        match = FINDING_PATTERN.match(stripped)
        if match:
            label = _normalize_label(match.group(1), match.group(2))
            marker = match.group(3)
            title = match.group(4).strip()
            start_finding(title, line, label=label, marker=marker)
            continue

        if findings and not findings[-1].get("_body_closed"):
            body_lines.append(line)

    flush_body()
    for f in findings:
        f.pop("_body_closed", None)
    return findings


def _normalize_label(raw, captured_label):
    if raw and raw.startswith("[") and raw.endswith("]"):
        return captured_label
    return None


def extract_perspective_from_filename(filename):
    """ファイル名 review_{name}.md から perspective 名を抽出する。"""
    match = re.match(r"^review_(.+)\.md$", filename)
    if match:
        return match.group(1)
    return ""
