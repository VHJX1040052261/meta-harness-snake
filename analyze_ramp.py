#!/usr/bin/env python3
# ==============================================================================
# analyze_ramp.py — FCM Ramp 5°C/min 升温数据分析脚本
# ==============================================================================
# 解析 serial_raw.txt 中的 VHJCTRL 行和纯数字 CSV 行，计算：
#   - 实际升温速率 vs 目标速率 (mean/max/RMSE error)
#   - PWM 饱和比例 (PWM >= 95% 的时间占比)
#   - 温度曲线数据 (JSON 格式，供 Dashboard 渲染)
#   - 基本统计量 (mean, std, min, max, etc.)
#
# 依赖：仅 Python 标准库 (csv, json, math, re, argparse, os, sys, statistics)
# 复用决策：自写但仅含标准库，无 matplotlib/numpy/pandas 等外部依赖
#           Dashboard 负责渲染，本脚本只输出 JSON 数据
#
# 支持格式：
#   1. VHJCTRL: 前缀行 (VHJCTRL:<timestamp>,<csv-data>)
#   2. 纯数字 CSV 行 (11 列或 24 列)
#   3. 带 headers 的 CSV
#
# 安全边界：
#   - 纯离线分析，无网络/硬件访问
#   - 只读输入文件，不修改原始数据
#   - 输出仅写入指定路径，不操作其他文件
# ==============================================================================

import argparse
import csv
import json
import math
import os
import re
import statistics
import sys
from io import StringIO

# ---- Column detection heuristics ----
# Known column patterns from FCM telemetry:
# 11-column: state, ntc1, cj_temp, v_mv, i_ma, ntc2, dsc_temp, rtd_temp, pwm_actual, pwm_set, target
# 11-column alt: state, ntc1, cj_temp, v_mv, i_ma, dsc_temp, rtd_temp, pwm_actual, pwm_set, target (10 col)
# 24-column: extended telemetry with additional ADC channels

# Column name candidates for temperature (DSC temperature is primary)
TEMP_COLUMN_NAMES = [
    "dsc_temp", "temp_dsc", "temperature", "temp", "temprature",
    "current_temp", "board_temp", "temp_c", "temp_degc"
]

# Column name candidates for PWM (actual PWM duty cycle)
PWM_COLUMN_NAMES = [
    "pwm_actual", "pwm", "duty", "duty_cycle", "power", "heater_pwm",
    "pwm_out", "pwm_duty"
]

# Column name candidates for target temperature
TARGET_COLUMN_NAMES = [
    "target", "target_temp", "setpoint", "set_temp", "temp_target"
]


def parse_vhjctrl_line(line):
    """
    Parse a line that may contain a VHJCTRL prefix.
    Returns (timestamp_str, csv_content_str) or (None, line) if no prefix.
    """
    # Pattern: VHJCTRL:<ISO8601-or-epoch>,<csv data>
    m = re.match(r'^VHJCTRL[:\s]\s*([^,]*),(.*)', line.strip())
    if m:
        return m.group(1), m.group(2)
    # Pattern: VHJCTRL:<ISO8601>|<csv data>
    m = re.match(r'^VHJCTRL[:\s]\s*([^|]*)\|(.*)', line.strip())
    if m:
        return m.group(1), m.group(2)
    return None, line.strip()


def try_parse_csv_row(row_str):
    """
    Try to parse a string as a CSV row of numbers.
    Returns list of floats or None.
    """
    try:
        reader = csv.reader([row_str])
        fields = next(reader)
        values = []
        for f in fields:
            f = f.strip()
            if f == "":
                continue
            try:
                values.append(float(f))
            except ValueError:
                return None  # Non-numeric field suggests this is a header or metadata line
        return values if len(values) >= 3 else None  # Need at least 3 columns to be useful
    except Exception:
        return None


def detect_columns(headers, sample_rows):
    """
    Detect which columns contain temperature and PWM data.
    Uses column names from headers if available, otherwise heuristics.
    Returns (temp_idx, pwm_idx, target_idx, col_count, headers_out).
    """
    col_count = 0
    headers_out = headers

    # Try to determine column count from data
    if sample_rows:
        col_count = max(len(r) for r in sample_rows)

    # Build header names (either explicit or generated)
    if not headers:
        # Generate default headers based on column count
        if col_count == 11:
            headers_out = [
                "state", "ntc1_temp", "cj_temp", "voltage_mv", "current_ma",
                "ntc2_temp", "dsc_temp", "rtd_temp", "pwm_actual", "pwm_set", "target"
            ]
        elif col_count == 10:
            headers_out = [
                "state", "ntc1_temp", "cj_temp", "voltage_mv", "current_ma",
                "dsc_temp", "rtd_temp", "pwm_actual", "pwm_set", "target"
            ]
        elif col_count >= 24:
            headers_out = [f"col_{i}" for i in range(col_count)]
            # Best guess for 24+ column format
            headers_out[6] = "dsc_temp"
            headers_out[7] = "rtd_temp"
            headers_out[8] = "pwm_actual"
        else:
            headers_out = [f"col_{i}" for i in range(col_count)]
    else:
        col_count = len(headers)

    # Find temperature column
    temp_idx = None
    for i, h in enumerate(headers_out):
        h_lower = h.lower().replace(" ", "_").replace("-", "_")
        if h_lower in TEMP_COLUMN_NAMES:
            temp_idx = i
            break
    if temp_idx is None:
        # Heuristic: temperature values are typically 10-300 (not mV-level)
        # Column with values in range [0, 500] that's not PWM
        if sample_rows:
            best_col = None
            best_score = 0
            for col_idx in range(min(col_count, len(sample_rows[0]))):
                vals = [r[col_idx] for r in sample_rows if col_idx < len(r)]
                if not vals:
                    continue
                # All values should be in reasonable temp range
                in_range = sum(1 for v in vals if -50 <= v <= 500)
                in_range_ratio = in_range / len(vals)
                # Prefer columns NOT at position 0 (state), 3 (voltage mV ~700-800)
                pos_score = 1.0 if col_idx > 2 else 0.5
                score = in_range_ratio * pos_score
                if score > best_score and score > 0.6:
                    best_score = score
                    best_col = col_idx
            temp_idx = best_col

    # Find PWM column
    pwm_idx = None
    for i, h in enumerate(headers_out):
        h_lower = h.lower().replace(" ", "_").replace("-", "_")
        if h_lower in PWM_COLUMN_NAMES:
            pwm_idx = i
            break
    if pwm_idx is None:
        # Heuristic: PWM values typically 0-100
        if sample_rows:
            best_col = None
            best_score = 0
            for col_idx in range(min(col_count, len(sample_rows[0]))):
                if col_idx == temp_idx:
                    continue
                vals = [r[col_idx] for r in sample_rows if col_idx < len(r)]
                if not vals:
                    continue
                in_range = sum(1 for v in vals if 0 <= v <= 100)
                in_range_ratio = in_range / len(vals)
                # PWM should have some variability
                if len(set(vals)) > 1:
                    in_range_ratio *= 1.2
                if in_range_ratio > best_score and in_range_ratio > 0.5:
                    best_score = in_range_ratio
                    best_col = col_idx
            pwm_idx = best_col

    # Find target temperature column
    target_idx = None
    for i, h in enumerate(headers_out):
        h_lower = h.lower().replace(" ", "_").replace("-", "_")
        if h_lower in TARGET_COLUMN_NAMES:
            target_idx = i
            break
    if target_idx is None:
        # Heuristic: last column often has target setpoint (constant or step-changing)
        if col_count > 0:
            target_idx = col_count - 1

    return temp_idx, pwm_idx, target_idx, col_count, headers_out


def compute_ramp_rate(timestamps, temperatures, sample_window=10):
    """
    Compute instantaneous ramp rate (°C/min) using linear regression
    over a sliding window of data points.
    Returns list of (timestamp, rate) pairs.
    """
    rates = []
    for i in range(sample_window, len(temperatures)):
        # Simple linear regression over the window
        x_vals = timestamps[i - sample_window:i]
        y_vals = temperatures[i - sample_window:i]

        n = len(x_vals)
        if n < 2:
            continue

        sum_x = sum(x_vals)
        sum_y = sum(y_vals)
        sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))
        sum_xx = sum(x * x for x in x_vals)

        denominator = n * sum_xx - sum_x * sum_x
        if abs(denominator) < 1e-10:
            continue

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        rate_c_per_min = slope * 60.0  # Convert from °C/second to °C/min

        rates.append(rate_c_per_min)

    return rates


def compute_rmse(actual, target):
    """Compute Root Mean Square Error."""
    if not actual:
        return 0.0
    squared_errors = [(a - target) ** 2 for a in actual]
    return math.sqrt(sum(squared_errors) / len(squared_errors))


def parse_and_analyze(input_path, output_path=None, target_rate=5.0, target_temp=200.0):
    """
    Main analysis function. Reads input file, parses rows, computes metrics.
    """
    rows = []
    timestamps_raw = []
    line_numbers = []

    # ---- Phase 1: Parse input file ----
    with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
        for line_no, line in enumerate(f, 1):
            line = line.rstrip('\n\r')
            if not line:
                continue

            # Try VHJCTRL prefix parsing
            ts_str, csv_body = parse_vhjctrl_line(line)

            # Try parse as CSV numbers
            values = try_parse_csv_row(csv_body)
            if values is not None:
                rows.append(values)
                if ts_str:
                    # Try to parse timestamp
                    try:
                        # Could be ISO8601 or Unix epoch seconds
                        if 'T' in ts_str or '-' in ts_str:
                            # ISO8601 — store as string, we'll compute relative time
                            timestamps_raw.append(ts_str)
                        else:
                            timestamps_raw.append(float(ts_str))
                    except (ValueError, TypeError):
                        timestamps_raw.append(None)
                else:
                    timestamps_raw.append(None)
                line_numbers.append(line_no)

    if not rows:
        result = {
            "status": "error",
            "error": "No valid data rows found in input file",
            "input_path": input_path,
            "lines_scanned": line_no if 'line_no' in dir() else 0
        }
        _write_result(result, output_path)
        return result

    # ---- Phase 2: Detect columns ----
    temp_idx, pwm_idx, target_idx, col_count, headers = detect_columns([], rows)

    if temp_idx is None and pwm_idx is None:
        result = {
            "status": "error",
            "error": "Could not identify temperature or PWM columns",
            "input_path": input_path,
            "total_rows": len(rows),
            "column_count": col_count,
            "sample_row": rows[0] if rows else None
        }
        _write_result(result, output_path)
        return result

    # ---- Phase 3: Extract data series ----
    temperatures = []
    pwm_values = []
    target_temps = []
    timestamps = []  # Relative time in seconds from start

    # Determine if we have real timestamps
    has_real_ts = any(ts is not None for ts in timestamps_raw)

    if has_real_ts:
        # Use provided timestamps (convert to relative seconds)
        base_ts = None
        for i, ts in enumerate(timestamps_raw):
            if ts is not None:
                if isinstance(ts, (int, float)):
                    if base_ts is None:
                        base_ts = ts
                    timestamps.append(ts - base_ts)
                else:
                    # String timestamp — just use index
                    timestamps.append(float(i))
            else:
                timestamps.append(float(i))
        # Fall back to index-based timing if all are None
    else:
        # Estimate timestamps: assume ~200ms between samples (5Hz typical FCM telemetry)
        for i in range(len(rows)):
            timestamps.append(float(i) * 0.2)

    # Extract temperature, PWM, and target series
    for i, row in enumerate(rows):
        if temp_idx is not None and temp_idx < len(row):
            temperatures.append(row[temp_idx])
        else:
            # Try fallback: use first column > 3 that looks like temperature
            found = False
            for j, val in enumerate(row):
                if j == pwm_idx:
                    continue
                if 5 <= val <= 500 and j > 1:
                    temperatures.append(val)
                    found = True
                    break
            if not found:
                temperatures.append(None)

        if pwm_idx is not None and pwm_idx < len(row):
            pwm_values.append(row[pwm_idx])
        else:
            pwm_values.append(None)

        if target_idx is not None and target_idx < len(row):
            target_temps.append(row[target_idx])
        else:
            target_temps.append(None)

    # Remove None entries for clean analysis
    clean_temps = [t for t in temperatures if t is not None]
    clean_pwms = [p for p in pwm_values if p is not None]
    clean_targets = [t for t in target_temps if t is not None]

    # ---- Phase 4: Compute ramp rates ----
    # Create clean (timestamp, temperature) pairs
    ts_temp_pairs = [(ts, t) for ts, t in zip(timestamps, temperatures) if t is not None]
    if len(ts_temp_pairs) > 10:
        clean_ts = [p[0] for p in ts_temp_pairs]
        clean_t = [p[1] for p in ts_temp_pairs]
        ramp_rates = compute_ramp_rate(clean_ts, clean_t, sample_window=10)
    else:
        ramp_rates = []

    # ---- Phase 5: Identify heating phase (where temperature is actively rising) ----
    # Heating phase: from when temp starts increasing to when it reaches target area
    heating_start_idx = 0
    heating_end_idx = len(clean_temps) - 1

    if len(clean_temps) > 10:
        # Find where temperature starts consistently rising
        for i in range(5, len(clean_temps) - 5):
            window_before = clean_temps[i - 5:i]
            window_after = clean_temps[i:i + 5]
            if statistics.mean(window_after) > statistics.mean(window_before) + 2.0:
                heating_start_idx = max(0, i - 5)
                break

        # Find where temperature approaches target (within 5°C)
        for i in range(len(clean_temps) - 1, heating_start_idx, -1):
            if clean_temps[i] >= target_temp - 5:
                heating_end_idx = i
                break

    heating_temps = clean_temps[heating_start_idx:heating_end_idx + 1]
    heating_pwms = clean_pwms[heating_start_idx:heating_end_idx + 1] if len(clean_pwms) > heating_end_idx else []

    # ---- Phase 6: Compute metrics ----
    # Ramp rate metrics
    ramp_rate_mean = statistics.mean(ramp_rates) if ramp_rates else 0.0
    ramp_rate_median = statistics.median(ramp_rates) if ramp_rates else 0.0
    ramp_rate_std = statistics.stdev(ramp_rates) if len(ramp_rates) > 1 else 0.0
    ramp_rate_max = max(ramp_rates) if ramp_rates else 0.0
    ramp_rate_min = min(ramp_rates) if ramp_rates else 0.0
    ramp_rate_rmse = compute_rmse(ramp_rates, target_rate)

    # Temperature metrics
    temp_start = clean_temps[0] if clean_temps else 0.0
    temp_final = clean_temps[-1] if clean_temps else 0.0
    temp_max = max(clean_temps) if clean_temps else 0.0
    temp_mean = statistics.mean(clean_temps) if clean_temps else 0.0
    temp_std = statistics.stdev(clean_temps) if len(clean_temps) > 1 else 0.0

    # Heating phase metrics
    if len(heating_temps) >= 2 and len(heating_pwms) >= 2:
        heating_duration = len(heating_temps) * 0.2  # rough estimate in seconds
        temp_delta = heating_temps[-1] - heating_temps[0]
        avg_heating_rate = (temp_delta / heating_duration) * 60.0 if heating_duration > 0 else 0.0

        # PWM saturation
        pwm_saturated = sum(1 for p in heating_pwms if p >= 95.0)
        pwm_saturation_ratio = pwm_saturated / len(heating_pwms) if heating_pwms else 0.0
        pwm_mean_heating = statistics.mean(heating_pwms)
        pwm_max_heating = max(heating_pwms)
    else:
        avg_heating_rate = 0.0
        pwm_saturated = 0
        pwm_saturation_ratio = 0.0
        pwm_mean_heating = 0.0
        pwm_max_heating = 0.0

    # Overall PWM metrics
    pwm_mean = statistics.mean(clean_pwms) if clean_pwms else 0.0
    pwm_max = max(clean_pwms) if clean_pwms else 0.0
    pwm_over_90 = sum(1 for p in clean_pwms if p >= 90.0) if clean_pwms else 0
    pwm_over_90_ratio = pwm_over_90 / len(clean_pwms) if clean_pwms else 0.0

    # Timing
    total_duration_s = timestamps[-1] - timestamps[0] if len(timestamps) >= 2 else 0.0
    sample_count = len(clean_temps)

    # ---- Phase 7: Build output ----
    # Temperature curve data (downsampled for JSON efficiency)
    curve_points = []
    downsample_step = max(1, len(clean_temps) // 500)  # Max ~500 points for the curve
    for i in range(0, len(ts_temp_pairs), downsample_step):
        ts, t = ts_temp_pairs[i]
        curve_points.append({
            "t_s": round(ts, 2),
            "temp_c": round(t, 3)
        })

    # PWM over time (downsampled similarly)
    pwm_curve = []
    pwm_step = max(1, len(clean_pwms) // 500)
    for i in range(0, len(clean_pwms), pwm_step):
        if i < len(timestamps) and clean_pwms[i] is not None:
            pwm_curve.append({
                "t_s": round(timestamps[i], 2),
                "pwm": round(clean_pwms[i], 3)
            })

    result = {
        "status": "ok",
        "analysis": {
            "experiment": {
                "target_rate_c_per_min": target_rate,
                "target_temp_c": target_temp,
                "sample_count": sample_count,
                "total_duration_s": round(total_duration_s, 1),
                "total_duration_min": round(total_duration_s / 60.0, 2),
                "column_count": col_count,
                "column_headers": headers,
                "temp_column_index": temp_idx,
                "pwm_column_index": pwm_idx,
                "target_column_index": target_idx
            },
            "temperature": {
                "start_c": round(temp_start, 3),
                "final_c": round(temp_final, 3),
                "max_c": round(temp_max, 3),
                "mean_c": round(temp_mean, 3),
                "std_c": round(temp_std, 3),
                "delta_c": round(temp_final - temp_start, 3)
            },
            "ramp_rate": {
                "target_c_per_min": target_rate,
                "mean_c_per_min": round(ramp_rate_mean, 3),
                "median_c_per_min": round(ramp_rate_median, 3),
                "std_c_per_min": round(ramp_rate_std, 3),
                "max_c_per_min": round(ramp_rate_max, 3),
                "min_c_per_min": round(ramp_rate_min, 3),
                "rmse_vs_target": round(ramp_rate_rmse, 3),
                "deviation_pct": round((ramp_rate_mean - target_rate) / target_rate * 100.0, 2) if target_rate > 0 else 0.0,
                "samples_used": len(ramp_rates)
            },
            "pwm": {
                "mean": round(pwm_mean, 3),
                "max": round(pwm_max, 3),
                "saturation_ratio_95pct": round(pwm_saturation_ratio, 4),
                "over_90pct_ratio": round(pwm_over_90_ratio, 4),
                "heating_phase_mean": round(pwm_mean_heating, 3),
                "heating_phase_max": round(pwm_max_heating, 3),
                "pwm_max_limit": 95
            },
            "heating_phase": {
                "start_index": heating_start_idx,
                "end_index": heating_end_idx,
                "duration_estimate_s": round(len(heating_temps) * 0.2, 1) if len(heating_temps) >= 2 else 0,
                "temp_delta_c": round(heating_temps[-1] - heating_temps[0], 3) if len(heating_temps) >= 2 else 0,
                "avg_rate_c_per_min": round(avg_heating_rate, 3)
            }
        },
        "curves": {
            "temperature": curve_points,
            "pwm": pwm_curve
        },
        "input": {
            "path": input_path,
            "total_rows_parsed": len(rows),
            "total_lines_processed": len(line_numbers),
            "has_vhjctrl_prefix": any(
                parse_vhjctrl_line(line)[0] is not None
                for line in open(input_path, 'r', encoding='utf-8', errors='replace')
            ) if os.path.exists(input_path) else False
        }
    }

    _write_result(result, output_path)
    return result


def _write_result(result, output_path):
    """Write result to JSON file or stdout."""
    json_str = json.dumps(result, indent=2, ensure_ascii=False, default=str)

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(json_str)
        print(f"RESULT: {output_path}")
        print(f"STATUS: {result.get('status', 'unknown')}")
    else:
        print(json_str)


def main():
    parser = argparse.ArgumentParser(
        description="FCM Ramp Analysis — parse serial data and compute ramp metrics"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="serial_raw.txt",
        help="Path to serial_raw.txt input file (default: serial_raw.txt)"
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Path to output JSON file (default: <input>_analysis.json)"
    )
    parser.add_argument(
        "-r", "--rate",
        type=float,
        default=5.0,
        help="Target ramp rate in °C/min (default: 5.0)"
    )
    parser.add_argument(
        "-t", "--target",
        type=float,
        default=200.0,
        help="Target temperature in °C (default: 200.0)"
    )

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # Auto-generate output path if not specified
    output_path = args.output
    if not output_path:
        base = os.path.splitext(os.path.basename(args.input))[0]
        out_dir = os.path.dirname(os.path.abspath(args.input))
        output_path = os.path.join(out_dir, f"{base}_analysis.json")

    result = parse_and_analyze(
        args.input,
        output_path=output_path,
        target_rate=args.rate,
        target_temp=args.target
    )

    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
