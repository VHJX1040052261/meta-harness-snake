#!/usr/bin/env python3
"""
analyze_serial.py — FOMS_V1.0 Serial Data Analyzer

Parses build_log.txt and serial_raw.txt produced by keil_build_and_serial_read.ps1,
detects VOFA/RATECTRL protocol headers, extracts numeric data rows,
and generates serial_analysis.json, report.md, and report.html.

Uses Python standard library ONLY (no third-party packages).
"""

import sys
import os
import re
import csv
import json
import math
import time
import hashlib
import webbrowser
import argparse
import statistics
import traceback
from datetime import datetime, timezone
from collections import OrderedDict, defaultdict
from pathlib import Path


# ============================================================================
# Protocol signature constants
# ============================================================================

# 6 known VOFA+ / FireWater data frame header patterns
# VOFA uses a 4-byte frame header for binary streaming
VOFA_SIGNATURES = [
    b'\x00\x00\x80\x7f',   # VOFA standard float frame header
    b'\x00\x00\x7f\x80',   # VOFA alternate float frame (endian-flipped)
    b'\xaf\xfe\x00\x00',   # VOFA tail marker variant A
    b'\x00\x00\xfe\xaf',   # VOFA tail marker variant B
    b'VOFA',               # ASCII "VOFA" marker
    b'vofa',               # ASCII "vofa" marker (lowercase)
]

# 5 known RATECTRL protocol header patterns
# RATECTRL is a custom angular-rate control telemetry protocol
RATECTRL_SIGNATURES = [
    b'RATECTRL',           # ASCII header: primary rate-control telemetry
    b'ratectrl',           # lowercase variant
    b'RATE_CTRL',          # alternate naming
    b'\x52\x41\x54\x45',   # Binary header: 'R', 'A', 'T', 'E' as 4 bytes
    b'\x01\x02\x03\x04',   # RATECTRL binary preamble (fixed sync pattern)
]


# ============================================================================
# Utility functions
# ============================================================================

def read_file_bytes(filepath: str) -> bytes:
    """Read file as raw bytes."""
    with open(filepath, 'rb') as f:
        return f.read()


def read_file_text(filepath: str, encoding: str = 'utf-8') -> str:
    """Read file as text with fallback encodings."""
    for enc in [encoding, 'latin-1', 'cp1252', 'ascii']:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    # Last resort: read as bytes and decode with replace
    with open(filepath, 'rb') as f:
        return f.read().decode('utf-8', errors='replace')


def detect_signatures(data: bytes, signatures: list) -> bool:
    """Check if any of the given byte signatures appear in the data."""
    if not data:
        return False
    for sig in signatures:
        if sig in data:
            return True
    return False


def parse_build_log(filepath: str) -> dict:
    """
    Parse the Keil build log to extract build status, error/warning counts.
    Returns a dict with build metadata.
    """
    result = {
        "build_passed": False,
        "error_count": -1,
        "warning_count": -1,
        "build_summary": "",
        "uv4_path": "",
        "project_file": "",
        "exit_code": -1,
        "raw_log_exists": False,
    }

    if not os.path.exists(filepath):
        result["build_summary"] = "Build log file not found"
        return result

    result["raw_log_exists"] = True

    try:
        content = read_file_text(filepath)
    except Exception as e:
        result["build_summary"] = f"Failed to read build log: {e}"
        return result

    # Parse "build_success: True/False" line from our PS1 metadata footer
    m = re.search(r'build_success:\s*(True|False)', content, re.IGNORECASE)
    if m:
        result["build_passed"] = m.group(1).lower() == "true"

    # Parse explicit error/warning counts from metadata
    m = re.search(r'error_count:\s*(\d+)', content, re.IGNORECASE)
    if m:
        result["error_count"] = int(m.group(1))

    m = re.search(r'warning_count:\s*(\d+)', content, re.IGNORECASE)
    if m:
        result["warning_count"] = int(m.group(1))

    # Fallback: parse Keil's native format "N Error(s), M Warning(s)"
    if result["error_count"] < 0:
        m = re.search(r'(\d+)\s+Error\(s\)', content)
        if m:
            result["error_count"] = int(m.group(1))

    if result["warning_count"] < 0:
        m = re.search(r'(\d+)\s+Warning\(s\)', content)
        if m:
            result["warning_count"] = int(m.group(1))

    # Extract UV4 path
    m = re.search(r'UV4 executable\s*:\s*(.+)', content, re.IGNORECASE)
    if m:
        result["uv4_path"] = m.group(1).strip()

    # Extract project file
    m = re.search(r'Project file\s*:\s*(.+)', content, re.IGNORECASE)
    if m:
        result["project_file"] = m.group(1).strip()

    # Extract UV4 exit code
    m = re.search(r'UV4 exit code:\s*(\d+)', content, re.IGNORECASE)
    if m:
        result["exit_code"] = int(m.group(1))

    # Derive build summary
    if result["build_passed"]:
        result["build_summary"] = "BUILD SUCCESS"
    elif result["error_count"] >= 0:
        result["build_summary"] = f"BUILD FAILED ({result['error_count']} error(s), {result['warning_count']} warning(s))"
    elif "UV4_NOT_FOUND" in content:
        result["build_summary"] = "UV4 not found — build skipped"
    elif "PROJECT_NOT_FOUND" in content:
        result["build_summary"] = "Project file not found — build skipped"
    else:
        result["build_summary"] = "Build status unknown"

    return result


def parse_serial_raw(filepath: str) -> dict:
    """
    Parse the serial_raw.txt file.
    Extracts metadata header, raw payload, and computes statistics.
    """
    result = {
        "file_exists": False,
        "bytes_read": 0,
        "com_port": "",
        "baud_rate": 0,
        "acquisition_success": False,
        "acquisition_error": "",
        "raw_payload": b"",
        "raw_text": "",
        "text_lines": [],
        "numeric_rows": 0,
        "numeric_columns": 0,
        "numeric_data": [],
        "column_names": [],
        "has_vofa_header": False,
        "has_ratectrl_header": False,
        "data_start_offset": 0,
        "checksum_md5": "",
    }

    if not os.path.exists(filepath):
        return result

    result["file_exists"] = True

    # Read as bytes for signature detection and raw payload
    try:
        raw_bytes = read_file_bytes(filepath)
    except Exception as e:
        result["acquisition_error"] = f"Failed to read file: {e}"
        return result

    result["checksum_md5"] = hashlib.md5(raw_bytes).hexdigest()

    # Read as text for line-by-line parsing
    raw_text = read_file_text(filepath)
    result["raw_text"] = raw_text

    # Parse the metadata header block injected by PS1 script
    header_end = raw_text.find("=== RAW DATA BELOW ===")
    if header_end >= 0:
        header_block = raw_text[:header_end]
        result["data_start_offset"] = header_end + len("=== RAW DATA BELOW ===")

        m = re.search(r'com_port:\s*(\S+)', header_block)
        if m:
            result["com_port"] = m.group(1)

        m = re.search(r'baud_rate:\s*(\d+)', header_block)
        if m:
            result["baud_rate"] = int(m.group(1))

        m = re.search(r'success:\s*(True|False)', header_block, re.IGNORECASE)
        if m:
            result["acquisition_success"] = m.group(1).lower() == "true"

        m = re.search(r'bytes_read:\s*(\d+)', header_block)
        if m:
            result["bytes_read"] = int(m.group(1))

        m = re.search(r'error:\s*(.+?)$', header_block, re.MULTILINE)
        if m and m.group(1).strip():
            result["acquisition_error"] = m.group(1).strip()

        # Extract raw payload (everything after header)
        raw_payload_bytes = raw_bytes[result["data_start_offset"]:]
    else:
        # No header block found — entire file is raw payload
        raw_payload_bytes = raw_bytes
        # Estimate bytes_read from file size
        result["bytes_read"] = len(raw_bytes)

    result["raw_payload"] = raw_payload_bytes

    # --- Protocol signature detection ---
    if raw_payload_bytes:
        result["has_vofa_header"] = detect_signatures(raw_payload_bytes, VOFA_SIGNATURES)
        result["has_ratectrl_header"] = detect_signatures(raw_payload_bytes, RATECTRL_SIGNATURES)

    # --- Text line parsing ---
    payload_text = raw_text[result["data_start_offset"]:] if header_end >= 0 else raw_text
    lines = payload_text.splitlines()
    result["text_lines"] = [l for l in lines if l.strip()]  # non-empty lines

    # --- Numeric data extraction ---
    # Support multiple CSV-like formats:
    #   - Comma-separated floats: "1.23,4.56,7.89"
    #   - Tab-separated:        "1.23\t4.56\t7.89"
    #   - Space-separated:      "1.23 4.56 7.89"
    #   - VOFA tail format with trailing comma: "1.23,4.56,7.89,"
    numeric_rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip header/metadata lines
        if stripped.startswith("===") or stripped.startswith("---"):
            continue
        # Skip lines that look like timestamps or non-numeric text
        if re.match(r'^[\d\-:\sTZ.]+$', stripped):
            continue

        # Try comma separator first (VOFA typical format)
        parts = stripped.rstrip(',').split(',')
        if len(parts) < 2:
            # Try tab
            parts = stripped.split('\t')
        if len(parts) < 2:
            # Try whitespace
            parts = stripped.split()

        # Try to parse all fields as numbers
        nums = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            try:
                nums.append(float(p))
            except ValueError:
                # Not a number — skip the whole row as non-data
                nums = []
                break

        if len(nums) >= 2:
            numeric_rows.append(nums)

    result["numeric_data"] = numeric_rows
    result["numeric_rows"] = len(numeric_rows)

    if numeric_rows:
        result["numeric_columns"] = max(len(r) for r in numeric_rows)
        # Generate default column names
        result["column_names"] = [f"ch{i}" for i in range(result["numeric_columns"])]
    else:
        result["numeric_columns"] = 0

    return result


def compute_statistics(numeric_data: list) -> dict:
    """
    Compute per-channel statistics from the numeric data rows.
    Each row is a list of float values (one per channel).
    Returns column-wise statistics.
    """
    if not numeric_data:
        return {}

    n_cols = max(len(r) for r in numeric_data)
    stats = {}

    for col_idx in range(n_cols):
        col_values = [row[col_idx] for row in numeric_data if col_idx < len(row)]
        if not col_values:
            continue

        col_name = f"ch{col_idx}"
        col_stats = {
            "count": len(col_values),
            "min": min(col_values),
            "max": max(col_values),
            "sum": sum(col_values),
            "mean": statistics.mean(col_values),
        }

        # Standard deviation (requires at least 2 values)
        if len(col_values) >= 2:
            col_stats["stdev"] = statistics.stdev(col_values)
            col_stats["variance"] = statistics.variance(col_values)
        else:
            col_stats["stdev"] = 0.0
            col_stats["variance"] = 0.0

        # Median
        col_stats["median"] = statistics.median(col_values)

        # Quartiles (sorted values)
        sorted_vals = sorted(col_values)
        n = len(sorted_vals)
        col_stats["q1"] = sorted_vals[n // 4] if n >= 4 else sorted_vals[0]
        col_stats["q3"] = sorted_vals[(3 * n) // 4] if n >= 4 else sorted_vals[-1]

        # Range
        col_stats["range"] = col_stats["max"] - col_stats["min"]

        stats[col_name] = col_stats

    return stats


def compute_cross_channel_stats(numeric_data: list, stats: dict) -> dict:
    """Compute aggregate statistics across all channels."""
    result = {
        "total_data_points": sum(s["count"] for s in stats.values()),
        "channel_count": len(stats),
        "row_count": len(numeric_data),
        "overall_min": min(s["min"] for s in stats.values()) if stats else 0,
        "overall_max": max(s["max"] for s in stats.values()) if stats else 0,
        "overall_mean": 0.0,
    }
    if stats:
        total_count = sum(s["count"] for s in stats.values())
        if total_count > 0:
            result["overall_mean"] = sum(s["sum"] for s in stats.values()) / total_count
    return result


def build_analysis_json(build_info: dict, serial_info: dict) -> OrderedDict:
    """
    Assemble the final serial_analysis.json structure.
    Uses OrderedDict for deterministic field ordering.
    """
    stats_per_channel = compute_statistics(serial_info["numeric_data"])
    cross_stats = compute_cross_channel_stats(serial_info["numeric_data"], stats_per_channel)

    analysis = OrderedDict()

    # === Meta ===
    analysis["meta"] = OrderedDict([
        ("analysis_tool", "analyze_serial.py"),
        ("analysis_version", "1.0.0"),
        ("generated_utc", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"),
        ("source_build_log", "build_log.txt"),
        ("source_serial_raw", "serial_raw.txt"),
    ])

    # === Build ===
    analysis["build"] = OrderedDict([
        ("build_passed", build_info["build_passed"]),
        ("error_count", build_info["error_count"]),
        ("warning_count", build_info["warning_count"]),
        ("build_summary", build_info["build_summary"]),
        ("uv4_path", build_info["uv4_path"]),
        ("project_file", build_info["project_file"]),
        ("exit_code", build_info["exit_code"]),
    ])

    # === Serial Acquisition ===
    analysis["serial_acquisition"] = OrderedDict([
        ("file_exists", serial_info["file_exists"]),
        ("com_port", serial_info["com_port"]),
        ("baud_rate", serial_info["baud_rate"]),
        ("acquisition_success", serial_info["acquisition_success"]),
        ("acquisition_error", serial_info["acquisition_error"]),
        ("bytes_read", serial_info["bytes_read"]),
        ("text_lines", len(serial_info["text_lines"])),
        ("checksum_md5", serial_info["checksum_md5"]),
    ])

    # === Protocol Detection ===
    analysis["protocol_detection"] = OrderedDict([
        ("has_vofa_header", serial_info["has_vofa_header"]),
        ("has_ratectrl_header", serial_info["has_ratectrl_header"]),
        ("vofa_signatures_checked", len(VOFA_SIGNATURES)),
        ("ratectrl_signatures_checked", len(RATECTRL_SIGNATURES)),
        ("note", (
            "No RATECTRL header detected — firmware may not be the new "
            "observation-framework build."
        ) if not serial_info["has_ratectrl_header"] else "RATECTRL header detected."
    )])

    # === Numeric Data ===
    analysis["numeric_data"] = OrderedDict([
        ("numeric_rows", serial_info["numeric_rows"]),
        ("numeric_columns", serial_info["numeric_columns"]),
        ("column_names", serial_info["column_names"]),
        ("total_data_points", cross_stats["total_data_points"]),
    ])

    # === Per-Channel Statistics ===
    analysis["channel_statistics"] = stats_per_channel

    # === Cross-Channel Aggregates ===
    analysis["cross_channel"] = cross_stats

    # === Sample Data (first 10 rows) ===
    sample_rows = serial_info["numeric_data"][:10] if serial_info["numeric_data"] else []
    analysis["sample_rows"] = sample_rows

    # === Status Codes ===
    status_ok = (
        build_info["build_passed"]
        and serial_info["acquisition_success"]
        and serial_info["numeric_rows"] > 0
    )
    analysis["status"] = OrderedDict([
        ("overall_ok", status_ok),
        ("build_ok", build_info["build_passed"]),
        ("serial_ok", serial_info["acquisition_success"]),
        ("data_ok", serial_info["numeric_rows"] > 0),
    ])

    return analysis


def generate_markdown_report(analysis: dict) -> str:
    """
    Generate a human-readable Markdown report from the analysis dict.
    """
    meta = analysis["meta"]
    build = analysis["build"]
    serial = analysis["serial_acquisition"]
    proto = analysis["protocol_detection"]
    ndata = analysis["numeric_data"]
    ch_stats = analysis["channel_statistics"]
    cc = analysis["cross_channel"]
    status = analysis["status"]
    samples = analysis["sample_rows"]

    lines = []
    lines.append(f"# FOMS_V1.0 Serial Analysis Report")
    lines.append("")
    lines.append(f"**Generated:** {meta['generated_utc']}")
    lines.append(f"**Analysis Tool:** {meta['analysis_tool']} v{meta['analysis_version']}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # --- Build Section ---
    lines.append("## 1. Build Results")
    lines.append("")
    lines.append(f"| Field | Value |")
    lines.append(f"|-------|-------|")
    lines.append(f"| Build Passed | {build['build_passed']} |")
    lines.append(f"| Error Count | {build['error_count']} |")
    lines.append(f"| Warning Count | {build['warning_count']} |")
    lines.append(f"| Build Summary | {build['build_summary']} |")
    lines.append(f"| UV4 Path | `{build['uv4_path']}` |")
    lines.append(f"| Project File | `{build['project_file']}` |")
    lines.append(f"| Exit Code | {build['exit_code']} |")
    lines.append("")

    if build["build_passed"]:
        lines.append("✅ **Build: PASSED (0 Error, 0 Warning)**")
    else:
        lines.append(f"❌ **Build: FAILED** ({build['error_count']} error(s), {build['warning_count']} warning(s))")
    lines.append("")

    # --- Serial Acquisition Section ---
    lines.append("## 2. Serial Acquisition")
    lines.append("")
    lines.append(f"| Field | Value |")
    lines.append(f"|-------|-------|")
    lines.append(f"| COM Port | {serial['com_port']} |")
    lines.append(f"| Baud Rate | {serial['baud_rate']} |")
    lines.append(f"| Acquisition Success | {serial['acquisition_success']} |")
    lines.append(f"| Bytes Read | {serial['bytes_read']} |")
    lines.append(f"| Text Lines | {serial['text_lines']} |")
    lines.append(f"| MD5 Checksum | `{serial['checksum_md5']}` |")
    if serial["acquisition_error"]:
        lines.append(f"| Error | {serial['acquisition_error']} |")
    lines.append("")

    if serial["acquisition_success"]:
        lines.append(f"✅ **Serial: {serial['bytes_read']} bytes read from {serial['com_port']} @ {serial['baud_rate']} baud**")
    else:
        lines.append(f"⚠️ **Serial: Issue encountered — {serial['acquisition_error'] or 'Check raw file'}**")
    lines.append("")

    # --- Protocol Detection Section ---
    lines.append("## 3. Protocol Detection")
    lines.append("")
    lines.append(f"| Signature | Detected |")
    lines.append(f"|-----------|----------|")
    lines.append(f"| VOFA Header | {proto['has_vofa_header']} |")
    lines.append(f"| RATECTRL Header | {proto['has_ratectrl_header']} |")
    lines.append("")
    lines.append(f"> {proto['note']}")
    lines.append("")

    # --- Data Section ---
    lines.append("## 4. Numeric Data")
    lines.append("")
    lines.append(f"- **Numeric Rows:** {ndata['numeric_rows']}")
    lines.append(f"- **Columns (Channels):** {ndata['numeric_columns']}")
    lines.append(f"- **Column Names:** {', '.join(ndata['column_names'])}")
    lines.append(f"- **Total Data Points:** {ndata['total_data_points']}")
    lines.append("")

    # --- Channel Statistics ---
    if ch_stats:
        lines.append("## 5. Per-Channel Statistics")
        lines.append("")
        for ch_name, ch_s in ch_stats.items():
            lines.append(f"### {ch_name}")
            lines.append("")
            lines.append(f"| Metric | Value |")
            lines.append(f"|--------|-------|")
            lines.append(f"| Count | {ch_s['count']} |")
            lines.append(f"| Min | {ch_s['min']:.6f} |")
            lines.append(f"| Max | {ch_s['max']:.6f} |")
            lines.append(f"| Mean | {ch_s['mean']:.6f} |")
            lines.append(f"| Median | {ch_s['median']:.6f} |")
            lines.append(f"| Std Dev | {ch_s['stdev']:.6f} |")
            lines.append(f"| Variance | {ch_s['variance']:.6f} |")
            lines.append(f"| Range | {ch_s['range']:.6f} |")
            lines.append(f"| Q1 | {ch_s['q1']:.6f} |")
            lines.append(f"| Q3 | {ch_s['q3']:.6f} |")
            lines.append("")
    else:
        lines.append("## 5. Per-Channel Statistics")
        lines.append("")
        lines.append("*No numeric data available for per-channel statistics.*")
        lines.append("")

    # --- Cross-Channel ---
    lines.append("## 6. Cross-Channel Aggregate")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Channel Count | {cc['channel_count']} |")
    lines.append(f"| Total Data Points | {cc['total_data_points']} |")
    lines.append(f"| Overall Min | {cc['overall_min']:.6f} |")
    lines.append(f"| Overall Max | {cc['overall_max']:.6f} |")
    lines.append(f"| Overall Mean | {cc['overall_mean']:.6f} |")
    lines.append("")

    # --- Sample Data ---
    if samples:
        lines.append("## 7. Sample Data (first 10 rows)")
        lines.append("")
        header_cols = ndata["column_names"]
        lines.append("| " + " | ".join(header_cols) + " |")
        lines.append("|" + "|".join(["-------"] * len(header_cols)) + "|")
        for row in samples:
            padded = list(row) + [0.0] * (ndata["numeric_columns"] - len(row))
            lines.append("| " + " | ".join(f"{v:.6f}" for v in padded) + " |")
        lines.append("")

    # --- Status ---
    lines.append("## 8. Overall Status")
    lines.append("")
    if status["overall_ok"]:
        lines.append("✅ **OVERALL: PASS**")
    else:
        lines.append("❌ **OVERALL: FAIL**")
    lines.append("")
    lines.append(f"| Check | Status |")
    lines.append(f"|-------|--------|")
    lines.append(f"| Build (0 Error) | {'✅ PASS' if status['build_ok'] else '❌ FAIL'} |")
    lines.append(f"| Serial (COM open) | {'✅ PASS' if status['serial_ok'] else '❌ FAIL'} |")
    lines.append(f"| Data (rows > 0) | {'✅ PASS' if status['data_ok'] else '❌ FAIL'} |")
    lines.append("")

    # --- Footer ---
    lines.append("---")
    lines.append("")
    lines.append(f"*Report generated by analyze_serial.py v{meta['analysis_version']} — FOMS_V1.0 Validation Pipeline*")

    return "\n".join(lines)


def generate_html_report(analysis: dict, md_report: str) -> str:
    """
    Generate a styled HTML report from the analysis dict.
    Embeds the markdown-equivalent content with CSS styling.
    """
    meta = analysis["meta"]
    build = analysis["build"]
    serial = analysis["serial_acquisition"]
    proto = analysis["protocol_detection"]
    ndata = analysis["numeric_data"]
    ch_stats = analysis["channel_statistics"]
    cc = analysis["cross_channel"]
    status = analysis["status"]
    samples = analysis["sample_rows"]

    # Status badge helpers
    def badge(ok):
        if ok:
            return '<span class="badge badge-pass">PASS</span>'
        return '<span class="badge badge-fail">FAIL</span>'

    def check_icon(ok):
        return "&#x2705;" if ok else "&#x274C;"

    # Build per-channel stats table rows
    ch_rows = ""
    for ch_name, ch_s in ch_stats.items():
        ch_rows += f"""
                <tr>
                    <td><strong>{ch_name}</strong></td>
                    <td>{ch_s['count']}</td>
                    <td>{ch_s['min']:.6f}</td>
                    <td>{ch_s['max']:.6f}</td>
                    <td>{ch_s['mean']:.6f}</td>
                    <td>{ch_s['median']:.6f}</td>
                    <td>{ch_s['stdev']:.6f}</td>
                    <td>{ch_s['range']:.6f}</td>
                </tr>"""

    # Build sample data table rows
    sample_rows = ""
    if samples:
        header_cells = "".join(f"<th>{n}</th>" for n in ndata["column_names"])
        for row in samples:
            padded = list(row) + [0.0] * (ndata["numeric_columns"] - len(row))
            cells = "".join(f"<td>{v:.6f}</td>" for v in padded)
            sample_rows += f"<tr>{cells}</tr>"
    else:
        header_cells = "<th>N/A</th>"
        sample_rows = "<tr><td colspan='1'>No data</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FOMS_V1.0 Serial Analysis Report</title>
<style>
    :root {{
        --bg: #0d1117;
        --fg: #c9d1d9;
        --border: #30363d;
        --accent: #58a6ff;
        --pass: #3fb950;
        --fail: #f85149;
        --warn: #d29922;
        --card-bg: #161b22;
        --header-bg: #1c2129;
        --muted: #8b949e;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
        background: var(--bg);
        color: var(--fg);
        line-height: 1.6;
        max-width: 1100px;
        margin: 0 auto;
        padding: 20px;
    }}
    h1 {{
        font-size: 2em;
        color: var(--accent);
        border-bottom: 2px solid var(--border);
        padding-bottom: 10px;
        margin-bottom: 20px;
    }}
    h2 {{
        font-size: 1.5em;
        color: var(--accent);
        margin-top: 30px;
        margin-bottom: 12px;
        padding-bottom: 6px;
        border-bottom: 1px solid var(--border);
    }}
    h3 {{
        font-size: 1.2em;
        color: var(--fg);
        margin-top: 20px;
        margin-bottom: 8px;
    }}
    .meta-line {{
        color: var(--muted);
        font-size: 0.9em;
        margin-bottom: 4px;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 12px 0 20px 0;
        background: var(--card-bg);
        border: 1px solid var(--border);
        border-radius: 6px;
        overflow: hidden;
    }}
    th, td {{
        padding: 8px 14px;
        text-align: left;
        border-bottom: 1px solid var(--border);
    }}
    th {{
        background: var(--header-bg);
        color: var(--accent);
        font-weight: 600;
        font-size: 0.9em;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover {{ background: rgba(88, 166, 255, 0.05); }}
    .badge {{
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.8em;
        font-weight: 700;
        letter-spacing: 0.5px;
    }}
    .badge-pass {{ background: rgba(63, 185, 80, 0.15); color: var(--pass); border: 1px solid rgba(63, 185, 80, 0.3); }}
    .badge-fail {{ background: rgba(248, 81, 73, 0.15); color: var(--fail); border: 1px solid rgba(248, 81, 73, 0.3); }}
    .badge-warn {{ background: rgba(210, 153, 34, 0.15); color: var(--warn); border: 1px solid rgba(210, 153, 34, 0.3); }}
    .status-card {{
        background: var(--card-bg);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 20px;
        margin: 16px 0;
    }}
    .status-card.pass {{ border-color: var(--pass); }}
    .status-card.fail {{ border-color: var(--fail); }}
    .note {{
        background: rgba(88, 166, 255, 0.08);
        border-left: 3px solid var(--accent);
        padding: 12px 16px;
        margin: 16px 0;
        color: var(--muted);
        border-radius: 0 6px 6px 0;
    }}
    .note.warn {{
        background: rgba(210, 153, 34, 0.08);
        border-left-color: var(--warn);
    }}
    code {{
        background: rgba(110, 118, 129, 0.15);
        padding: 2px 6px;
        border-radius: 4px;
        font-family: 'SF Mono', 'Fira Code', 'Fira Mono', Menlo, Consolas, monospace;
        font-size: 0.9em;
    }}
    .footer {{
        margin-top: 40px;
        padding-top: 16px;
        border-top: 1px solid var(--border);
        color: var(--muted);
        font-size: 0.85em;
        text-align: center;
    }}
    .grid-2 {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 20px;
    }}
    @media (max-width: 768px) {{
        .grid-2 {{ grid-template-columns: 1fr; }}
        body {{ padding: 12px; }}
    }}
</style>
</head>
<body>

<h1>&#128202; FOMS_V1.0 Serial Analysis Report</h1>
<p class="meta-line">Generated: {meta["generated_utc"]}</p>
<p class="meta-line">Tool: {meta["analysis_tool"]} v{meta["analysis_version"]}</p>

<!-- OVERALL STATUS -->
<div class="status-card {"pass" if status["overall_ok"] else "fail"}">
    <h2 style="margin-top:0;border:none;">Overall Status {badge(status["overall_ok"])}</h2>
    <table style="margin-bottom:0;">
        <tr><td>Build (0 Error)</td><td>{check_icon(status["build_ok"])} {badge(status["build_ok"])}</td></tr>
        <tr><td>Serial (COM open)</td><td>{check_icon(status["serial_ok"])} {badge(status["serial_ok"])}</td></tr>
        <tr><td>Data (rows &gt; 0)</td><td>{check_icon(status["data_ok"])} {badge(status["data_ok"])}</td></tr>
    </table>
</div>

<div class="grid-2">

<!-- BUILD SECTION -->
<div>
<h2>1. Build Results</h2>
<table>
    <tr><th>Field</th><th>Value</th></tr>
    <tr><td>Build Passed</td><td>{badge(build["build_passed"])}</td></tr>
    <tr><td>Errors</td><td>{build["error_count"]}</td></tr>
    <tr><td>Warnings</td><td>{build["warning_count"]}</td></tr>
    <tr><td>Summary</td><td>{build["build_summary"]}</td></tr>
    <tr><td>UV4 Path</td><td><code>{build["uv4_path"] or 'N/A'}</code></td></tr>
    <tr><td>Project File</td><td><code>{build["project_file"] or 'N/A'}</code></td></tr>
</table>
</div>

<!-- SERIAL ACQUISITION SECTION -->
<div>
<h2>2. Serial Acquisition</h2>
<table>
    <tr><th>Field</th><th>Value</th></tr>
    <tr><td>COM Port</td><td>{serial["com_port"]}</td></tr>
    <tr><td>Baud Rate</td><td>{serial["baud_rate"]}</td></tr>
    <tr><td>Success</td><td>{badge(serial["acquisition_success"])}</td></tr>
    <tr><td>Bytes Read</td><td>{serial["bytes_read"]:,}</td></tr>
    <tr><td>Text Lines</td><td>{serial["text_lines"]:,}</td></tr>
    <tr><td>MD5</td><td><code style="font-size:0.75em;">{serial["checksum_md5"][:16]}...</code></td></tr>
</table>
</div>

</div>

<!-- PROTOCOL DETECTION -->
<h2>3. Protocol Detection</h2>
<table>
    <tr><th>Signature</th><th>Detected</th></tr>
    <tr><td>VOFA Header</td><td>{badge(proto["has_vofa_header"])}</td></tr>
    <tr><td>RATECTRL Header</td><td>{badge(proto["has_ratectrl_header"])}</td></tr>
</table>
<div class="note{" warn" if not proto["has_ratectrl_header"] else ""}">
    {proto["note"]}
</div>

<!-- NUMERIC DATA -->
<h2>4. Numeric Data Summary</h2>
<table>
    <tr><th>Metric</th><th>Value</th></tr>
    <tr><td>Numeric Rows</td><td>{ndata["numeric_rows"]:,}</td></tr>
    <tr><td>Columns (Channels)</td><td>{ndata["numeric_columns"]}</td></tr>
    <tr><td>Column Names</td><td>{", ".join(ndata["column_names"])}</td></tr>
    <tr><td>Total Data Points</td><td>{ndata["total_data_points"]:,}</td></tr>
</table>

<!-- PER-CHANNEL STATISTICS -->
<h2>5. Per-Channel Statistics</h2>
{"<table><tr><th>Channel</th><th>Count</th><th>Min</th><th>Max</th><th>Mean</th><th>Median</th><th>Std Dev</th><th>Range</th></tr>" + ch_rows + "</table>" if ch_stats else "<p><em>No numeric data available for per-channel statistics.</em></p>"}

<!-- CROSS-CHANNEL -->
<h2>6. Cross-Channel Aggregate</h2>
<table>
    <tr><th>Metric</th><th>Value</th></tr>
    <tr><td>Channel Count</td><td>{cc["channel_count"]}</td></tr>
    <tr><td>Total Data Points</td><td>{cc["total_data_points"]:,}</td></tr>
    <tr><td>Overall Min</td><td>{cc["overall_min"]:.6f}</td></tr>
    <tr><td>Overall Max</td><td>{cc["overall_max"]:.6f}</td></tr>
    <tr><td>Overall Mean</td><td>{cc["overall_mean"]:.6f}</td></tr>
</table>

<!-- SAMPLE DATA -->
<h2>7. Sample Data (first 10 rows)</h2>
<table>
    <tr>{header_cells}</tr>
    {sample_rows}
</table>

<div class="footer">
    Report generated by analyze_serial.py v{meta["analysis_version"]} &mdash; FOMS_V1.0 Validation Pipeline
</div>

</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser(
        description="FOMS_V1.0 Serial Data Analyzer — parse build log and serial raw data, generate reports"
    )
    parser.add_argument(
        "--build-log", default="build_log.txt",
        help="Path to Keil build log (default: build_log.txt)"
    )
    parser.add_argument(
        "--serial-raw", default="serial_raw.txt",
        help="Path to serial raw data file (default: serial_raw.txt)"
    )
    parser.add_argument(
        "--output-json", default="serial_analysis.json",
        help="Path for analysis JSON output (default: serial_analysis.json)"
    )
    parser.add_argument(
        "--output-md", default="report.md",
        help="Path for Markdown report (default: report.md)"
    )
    parser.add_argument(
        "--output-html", default="report.html",
        help="Path for HTML report (default: report.html)"
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Do not auto-open the HTML report in a browser"
    )
    args = parser.parse_args()

    print("=" * 72)
    print("  FOMS_V1.0 Serial Data Analyzer")
    print("=" * 72)
    print()

    # Phase 1: Parse build log
    print(f"[1/5] Parsing build log: {args.build_log}")
    build_info = parse_build_log(args.build_log)
    build_icon = "+" if build_info["build_passed"] else "!"
    print(f"      [{build_icon}] build_passed={build_info['build_passed']}, "
          f"errors={build_info['error_count']}, warnings={build_info['warning_count']}")
    print(f"      Summary: {build_info['build_summary']}")

    # Phase 2: Parse serial raw
    print(f"[2/5] Parsing serial raw: {args.serial_raw}")
    serial_info = parse_serial_raw(args.serial_raw)
    ser_icon = "+" if serial_info["acquisition_success"] else "!"
    print(f"      [{ser_icon}] file_exists={serial_info['file_exists']}, "
          f"bytes_read={serial_info['bytes_read']}, numeric_rows={serial_info['numeric_rows']}")
    print(f"      VOFA header: {serial_info['has_vofa_header']}")
    print(f"      RATECTRL header: {serial_info['has_ratectrl_header']}")

    # Phase 3: Build analysis JSON
    print(f"[3/5] Computing statistics & assembling JSON")
    analysis = build_analysis_json(build_info, serial_info)

    # Write JSON
    with open(args.output_json, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False, default=str)
    json_size = os.path.getsize(args.output_json)
    print(f"      -> {args.output_json} ({json_size:,} bytes)")

    # Phase 4: Generate Markdown report
    print(f"[4/5] Generating reports")
    md_content = generate_markdown_report(analysis)
    with open(args.output_md, 'w', encoding='utf-8') as f:
        f.write(md_content)
    md_size = os.path.getsize(args.output_md)
    print(f"      -> {args.output_md} ({md_size:,} bytes)")

    # Generate HTML report
    html_content = generate_html_report(analysis, md_content)
    with open(args.output_html, 'w', encoding='utf-8') as f:
        f.write(html_content)
    html_size = os.path.getsize(args.output_html)
    print(f"      -> {args.output_html} ({html_size:,} bytes)")

    # Phase 5: Auto-open HTML report
    print(f"[5/5] Opening report in browser...")
    if not args.no_browser:
        file_url = Path(args.output_html).resolve().as_uri()
        try:
            webbrowser.open(file_url)
            print(f"      Opened: {file_url}")
        except Exception as e:
            print(f"      [WARNING] Could not open browser: {e}")
            print(f"      File is at: {Path(args.output_html).resolve()}")
    else:
        print(f"      Skipped (--no-browser flag set)")

    print()
    print("=" * 72)
    overall = "PASS" if analysis["status"]["overall_ok"] else "ISSUES DETECTED"
    print(f"  Analysis complete. Overall: {overall}")
    print(f"  Output files: {args.output_json}, {args.output_md}, {args.output_html}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
