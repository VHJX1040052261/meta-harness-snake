#!/usr/bin/env python3
"""
analyze_slope.py — 10°C/min 自动调参 slope 分析脚本
解析 vhj_telemetry.jsonl，提取 slope 字段，计算 60-180°C 区间的 slope 峰峰值。

判定逻辑:
  slope_peak_to_peak = max(slope_60_180) - min(slope_60_180)
  若 slope_peak_to_peak ≤ 0.2 → PASS
  否则 → FAIL

用法:
  python3 analyze_slope.py <vhj_telemetry.jsonl> [--range 60 180] [--threshold 0.2]
"""

import json
import sys
import os


def load_jsonl(filepath: str) -> list[dict]:
    """逐行读取 JSONL 文件，返回字典列表。"""
    records = []
    if not os.path.isfile(filepath):
        print(f"[ERROR] 文件不存在: {filepath}", file=sys.stderr)
        sys.exit(1)
    with open(filepath, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] 第{lineno}行 JSON 解析失败: {e}", file=sys.stderr)
    return records


def filter_by_temp(records: list[dict], temp_lo: float, temp_hi: float) -> list[dict]:
    """筛选 temperature 在 [temp_lo, temp_hi] 范围内的记录。"""
    filtered = []
    for r in records:
        t = r.get("temperature") if "temperature" in r else r.get("temp")
        if t is None:
            continue
        try:
            t = float(t)
        except (TypeError, ValueError):
            continue
        if temp_lo <= t <= temp_hi:
            filtered.append(r)
    return filtered


def extract_slopes(records: list[dict]) -> list[float]:
    """从记录列表中提取 slope 字段（数值）。"""
    slopes = []
    for r in records:
        s = r.get("slope")
        if s is None:
            continue
        try:
            slopes.append(float(s))
        except (TypeError, ValueError):
            continue
    return slopes


def analyze(filepath: str, temp_lo: float = 60.0, temp_hi: float = 180.0,
            threshold: float = 0.2) -> dict:
    """主分析流程。

    Returns:
        dict with keys:
          - filepath, total_records, filtered_count, slope_count
          - temp_lo, temp_hi, threshold
          - slope_min, slope_max, slope_peak_to_peak
          - passed (bool), verdict (str)
    """
    result = {
        "filepath": filepath,
        "temp_lo": temp_lo,
        "temp_hi": temp_hi,
        "threshold": threshold,
    }

    records = load_jsonl(filepath)
    result["total_records"] = len(records)

    if not records:
        print("[ERROR] JSONL 文件无有效记录", file=sys.stderr)
        result["passed"] = False
        result["verdict"] = "NO_DATA"
        return result

    # 筛选温度区间
    filtered = filter_by_temp(records, temp_lo, temp_hi)
    result["filtered_count"] = len(filtered)

    if not filtered:
        print(f"[WARN] 在 {temp_lo}-{temp_hi}°C 区间内无数据点", file=sys.stderr)
        result["passed"] = False
        result["verdict"] = "NO_DATA_IN_RANGE"
        return result

    # 提取 slope 值
    slopes = extract_slopes(filtered)
    result["slope_count"] = len(slopes)

    if len(slopes) < 2:
        print(f"[WARN] slope 数据点不足 (需要≥2, 实际{len(slopes)})", file=sys.stderr)
        result["passed"] = False
        result["verdict"] = "INSUFFICIENT_DATA"
        return result

    # 计算峰峰值
    slope_min = min(slopes)
    slope_max = max(slopes)
    slope_pp = slope_max - slope_min

    result["slope_min"] = slope_min
    result["slope_max"] = slope_max
    result["slope_peak_to_peak"] = slope_pp

    # 判定
    passed = slope_pp <= threshold
    result["passed"] = passed
    result["verdict"] = "PASS" if passed else "FAIL"

    return result


def print_report(result: dict):
    """输出分析报告到 stdout。"""
    print("=" * 60)
    print("  VHJ Telemetry Slope 分析报告")
    print("=" * 60)
    print(f"  文件:            {result['filepath']}")
    print(f"  总记录数:        {result.get('total_records', 'N/A')}")
    print(f"  温度区间:        {result['temp_lo']} – {result['temp_hi']} °C")
    print(f"  区间内记录数:    {result.get('filtered_count', 'N/A')}")
    print(f"  slope 数据点数:  {result.get('slope_count', 'N/A')}")
    print("-" * 60)

    if "slope_min" in result:
        print(f"  slope_min:           {result['slope_min']:.6f}")
        print(f"  slope_max:           {result['slope_max']:.6f}")
        print(f"  slope_peak_to_peak:  {result['slope_peak_to_peak']:.6f}")
        print(f"  判定阈值:            ≤ {result['threshold']}")
    print("-" * 60)
    print(f"  判定:            {result['verdict']}")
    print("=" * 60)

    # 输出机器可读的单行 JSON 结果（便于下游解析）
    print("\n[JSON_RESULT]", json.dumps(result, ensure_ascii=False))


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="VHJ Telemetry Slope 分析 — 计算 60-180°C slope 峰峰值并判定"
    )
    parser.add_argument("filepath", help="vhj_telemetry.jsonl 文件路径")
    parser.add_argument("--range", nargs=2, type=float, default=[60.0, 180.0],
                        metavar=("LO", "HI"), help="温度分析区间 (默认: 60 180)")
    parser.add_argument("--threshold", type=float, default=0.2,
                        help="slope 峰峰值判定阈值 (默认: 0.2)")
    parser.add_argument("--json", action="store_true",
                        help="仅输出 JSON 结果行（不输出可读报告）")

    args = parser.parse_args()
    result = analyze(args.filepath, args.range[0], args.range[1], args.threshold)

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print_report(result)

    sys.exit(0 if result.get("passed") else 1)


if __name__ == "__main__":
    main()
