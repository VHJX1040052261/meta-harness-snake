#!/usr/bin/env python3
"""
analyze_epoch.py — DSC PID 调参 Epoch 分析脚本 (Phase 1 纲领切片逻辑)

按 DSC自动化PID调参作战纲领 v1.0 的数据切片逻辑分析遥测数据：

  爬升期 (Climb Zone):  起始温度 ～ 起始温度+20°C
                        该区间 slope 峰值不计入稳态考核，单独报告。

  稳态期 (Steady Zone): 爬升期结束 ～ 目标温度
                        计算 Steady_P2P = max(slope_steady) - min(slope_steady)
                        判定: Steady_P2P ≤ 0.2 → PASS, 否则 → FAIL

用法:
  python3 analyze_epoch.py <vhj_telemetry.jsonl> [--start-temp 50] [--target-temp 200] [--threshold 0.2]
  python3 analyze_epoch.py <vhj_telemetry.jsonl> --json   # 仅输出 JSON
"""

import json
import sys
import os
from typing import Optional


# ── 安全边界常量 ──
SAFETY_MAX_TEMP_C = 600      # 绝对最高温度 (°C)
SAFETY_PWM_MAX = 95          # PWM 占空比上限 (%)


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


def get_temp(record: dict) -> Optional[float]:
    """从遥测记录中提取温度值。

    支持多种 JSON 键名约定:
      - "t0" / "T0": 控制输入温度 (VHJCTRL 协议)
      - "temperature" / "temp": 通用遥测格式
      - "Ts": 传感器温度 (fallback)
    """
    for key in ("t0", "T0", "temperature", "temp", "Ts"):
        val = record.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def get_slope(record: dict) -> Optional[float]:
    """从遥测记录中提取 slope 字段。

    支持多种键名: "slope", "rate_fast", "rate_slow"
    """
    for key in ("slope", "rate_fast", "rate_slow"):
        val = record.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def get_pwm(record: dict) -> Optional[float]:
    """从遥测记录中提取 PWM 输出值。"""
    for key in ("pwm", "pwm_out", "pwm_pid"):
        val = record.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def filter_by_temp_range(records: list[dict], temp_lo: float, temp_hi: float) -> list[dict]:
    """筛选温度在 [temp_lo, temp_hi] 范围内的记录。"""
    filtered = []
    for r in records:
        t = get_temp(r)
        if t is not None and temp_lo <= t <= temp_hi:
            filtered.append(r)
    return filtered


def extract_values(records: list[dict], extractor) -> list[float]:
    """从记录列表中提取数值字段。"""
    values = []
    for r in records:
        v = extractor(r)
        if v is not None:
            values.append(v)
    return values


def zone_stats(slopes: list[float], label: str) -> dict:
    """计算单个 zone 的 slope 统计信息。"""
    n = len(slopes)
    if n == 0:
        return {
            "label": label,
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "p2p": None,
            "has_data": False,
        }
    s_min = min(slopes)
    s_max = max(slopes)
    s_mean = sum(slopes) / n
    s_p2p = s_max - s_min
    return {
        "label": label,
        "count": n,
        "min": round(s_min, 6),
        "max": round(s_max, 6),
        "mean": round(s_mean, 6),
        "p2p": round(s_p2p, 6),
        "has_data": True,
    }


def safety_check(records: list[dict]) -> dict:
    """检查安全边界: 温度 ≤ 600°C, PWM ≤ 95%。"""
    max_temp = None
    max_pwm = None
    violations = []

    for r in records:
        t = get_temp(r)
        if t is not None:
            if max_temp is None or t > max_temp:
                max_temp = t
        p = get_pwm(r)
        if p is not None:
            if max_pwm is None or p > max_pwm:
                max_pwm = p

    if max_temp is not None and max_temp > SAFETY_MAX_TEMP_C:
        violations.append(f"温度超限: max={max_temp:.1f}°C > {SAFETY_MAX_TEMP_C}°C")
    if max_pwm is not None and max_pwm > SAFETY_PWM_MAX:
        violations.append(f"PWM超限: max={max_pwm:.1f}% > {SAFETY_PWM_MAX}%")

    return {
        "max_temp_observed": round(max_temp, 3) if max_temp is not None else None,
        "max_pwm_observed": round(max_pwm, 3) if max_pwm is not None else None,
        "temp_limit": SAFETY_MAX_TEMP_C,
        "pwm_limit": SAFETY_PWM_MAX,
        "violations": violations,
        "safe": len(violations) == 0,
    }


def analyze_epoch(filepath: str,
                  start_temp: float = 50.0,
                  target_temp: float = 200.0,
                  threshold: float = 0.2) -> dict:
    """主分析流程 — 按纲领切片逻辑分析遥测数据。

    Args:
        filepath: vhj_telemetry.jsonl 文件路径
        start_temp: 起始温度 (°C), 默认 50
        target_temp: 目标温度 (°C), 默认 200
        threshold: Steady_P2P 判定阈值, 默认 0.2

    Returns:
        dict with keys:
          - filepath, start_temp, target_temp, threshold
          - climb_zone: {temp_lo, temp_hi, stats}
          - steady_zone: {temp_lo, temp_hi, stats}
          - safety: safety check result
          - passed, verdict
          - total_records
    """
    climb_end_temp = start_temp + 20.0  # 爬升期结束温度

    result = {
        "filepath": filepath,
        "start_temp": start_temp,
        "target_temp": target_temp,
        "climb_end_temp": climb_end_temp,
        "threshold": threshold,
        "climb_zone": {
            "temp_lo": start_temp,
            "temp_hi": climb_end_temp,
            "description": f"爬升期 ({start_temp}–{climb_end_temp}°C), slope峰值不计入稳态考核",
            "stats": {},
        },
        "steady_zone": {
            "temp_lo": climb_end_temp,
            "temp_hi": target_temp,
            "description": f"稳态期 ({climb_end_temp}–{target_temp}°C), Steady_P2P = max-min slope",
            "stats": {},
        },
    }

    # 加载数据
    records = load_jsonl(filepath)
    result["total_records"] = len(records)

    if not records:
        print("[ERROR] JSONL 文件无有效记录", file=sys.stderr)
        result["passed"] = False
        result["verdict"] = "NO_DATA"
        return result

    # 安全边界检查
    result["safety"] = safety_check(records)
    if not result["safety"]["safe"]:
        result["passed"] = False
        result["verdict"] = "SAFETY_VIOLATION"
        return result

    # ── 爬升期分析 ──
    climb_records = filter_by_temp_range(records, start_temp, climb_end_temp)
    climb_slopes = extract_values(climb_records, get_slope)
    result["climb_zone"]["stats"] = zone_stats(climb_slopes, "爬升期")

    # ── 稳态期分析 ──
    steady_records = filter_by_temp_range(records, climb_end_temp, target_temp)
    steady_slopes = extract_values(steady_records, get_slope)
    result["steady_zone"]["stats"] = zone_stats(steady_slopes, "稳态期")

    steady_stats = result["steady_zone"]["stats"]

    # 数据不足判定
    if not steady_stats.get("has_data"):
        print(f"[WARN] 稳态期 ({climb_end_temp}–{target_temp}°C) 无数据点", file=sys.stderr)
        result["passed"] = False
        result["verdict"] = "NO_STEADY_DATA"
        return result

    if steady_stats["count"] < 2:
        print(f"[WARN] 稳态期 slope 数据点不足 (需要≥2, 实际{steady_stats['count']})", file=sys.stderr)
        result["passed"] = False
        result["verdict"] = "INSUFFICIENT_STEADY_DATA"
        return result

    # ── Steady_P2P 判定 ──
    steady_p2p = steady_stats["p2p"]
    passed = steady_p2p <= threshold

    result["passed"] = passed
    result["verdict"] = "PASS" if passed else "FAIL"
    result["steady_p2p"] = steady_p2p

    return result


def print_report(result: dict):
    """输出 epoch 分析报告到 stdout。"""
    print("=" * 64)
    print("  DSC PID Epoch 分析报告 — Phase 1 纲领切片逻辑")
    print("=" * 64)
    print(f"  文件:              {result['filepath']}")
    print(f"  总记录数:          {result.get('total_records', 'N/A')}")
    print(f"  起始温度:          {result['start_temp']} °C")
    print(f"  目标温度:          {result['target_temp']} °C")
    print(f"  爬升期结束温度:    {result['climb_end_temp']} °C")
    print("-" * 64)

    # 安全
    safety = result.get("safety", {})
    if safety:
        status_icon = "✓" if safety.get("safe") else "✗"
        print(f"  安全检查:          {status_icon} {'通过' if safety.get('safe') else '违规!'}")
        if safety.get("violations"):
            for v in safety["violations"]:
                print(f"    ⚠ {v}")
        print(f"  观测最高温度:      {safety.get('max_temp_observed', 'N/A')} °C")
        print(f"  观测最高PWM:       {safety.get('max_pwm_observed', 'N/A')} %")
    print("-" * 64)

    # 爬升期
    climb = result.get("climb_zone", {}).get("stats", {})
    print(f"  [爬升期] {result['climb_zone']['temp_lo']}–{result['climb_zone']['temp_hi']}°C")
    print(f"    (slope峰值不计入稳态考核)")
    if climb.get("has_data"):
        print(f"    数据点: {climb['count']} | "
              f"slope min={climb['min']:.4f} max={climb['max']:.4f} "
              f"P2P={climb['p2p']:.4f} °C/min")
    else:
        print(f"    无数据")
    print("-" * 64)

    # 稳态期
    steady = result.get("steady_zone", {}).get("stats", {})
    print(f"  [稳态期] {result['steady_zone']['temp_lo']}–{result['steady_zone']['temp_hi']}°C")
    if steady.get("has_data"):
        print(f"    数据点: {steady['count']} | "
              f"slope min={steady['min']:.4f} max={steady['max']:.4f} "
              f"mean={steady['mean']:.4f}")
        print(f"    Steady_P2P = {steady['p2p']:.4f} °C/min  "
              f"(阈值: ≤ {result['threshold']})")
    else:
        print(f"    无数据")
    print("=" * 64)

    # 判定
    verdict = result.get("verdict", "UNKNOWN")
    verdict_icon = "✓ PASS" if verdict == "PASS" else "✗ FAIL"
    print(f"  判定:              {verdict_icon}")
    if verdict == "PASS":
        print(f"  结论: 稳态期 slope 峰峰值 {result.get('steady_p2p', 'N/A')} ≤ {result['threshold']}，基线测试通过。")
    elif verdict == "FAIL":
        print(f"  结论: 稳态期 slope 峰峰值 {result.get('steady_p2p', 'N/A')} > {result['threshold']}，需后续 epoch 调参。")
    elif "SAFETY" in str(verdict):
        print(f"  结论: 安全边界违规，实验应立即终止并检查硬件。")
    print("=" * 64)

    # 机器可读 JSON
    print("\n[JSON_RESULT]", json.dumps(result, ensure_ascii=False))


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="DSC PID Epoch 分析 — 按纲领切片逻辑分析遥测数据"
    )
    parser.add_argument("filepath", help="vhj_telemetry.jsonl 文件路径")
    parser.add_argument("--start-temp", type=float, default=50.0,
                        help="起始温度 °C (默认: 50)")
    parser.add_argument("--target-temp", type=float, default=200.0,
                        help="目标温度 °C (默认: 200)")
    parser.add_argument("--threshold", type=float, default=0.2,
                        help="Steady_P2P 判定阈值 (默认: 0.2)")
    parser.add_argument("--json", action="store_true",
                        help="仅输出 JSON 结果行（不输出可读报告）")

    args = parser.parse_args()

    # 参数合法性校验
    if args.start_temp >= args.target_temp:
        print(f"[ERROR] 起始温度 ({args.start_temp}) 必须小于目标温度 ({args.target_temp})",
              file=sys.stderr)
        sys.exit(2)
    if args.target_temp > SAFETY_MAX_TEMP_C:
        print(f"[ERROR] 目标温度 ({args.target_temp}) 超过安全上限 ({SAFETY_MAX_TEMP_C}°C)",
              file=sys.stderr)
        sys.exit(2)

    result = analyze_epoch(
        args.filepath,
        args.start_temp,
        args.target_temp,
        args.threshold,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print_report(result)

    sys.exit(0 if result.get("passed") else 1)


if __name__ == "__main__":
    main()
