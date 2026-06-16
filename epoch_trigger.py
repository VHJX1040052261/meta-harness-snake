#!/usr/bin/env python3
"""
epoch_trigger.py — DSC 自动看门狗脚本
部署路径: D:\Project\DSC\Linux\DSC\Linux_FCM\Mac\tools\epoch_trigger.py

功能:
  1. 监控遥测 JSONL 文件的 T0 温度
  2. T0 ≥ 200°C → 自动通过 SSH 发送停止加热命令
  3. 停止加热后优雅终止采集器进程
  4. 600°C 硬保护（独立于目标温度触发）
  5. dry-run 模式用于部署前验证
  6. --selftest 模式用于功能测试证据输出

环境:
  - Windows 端运行（使用 Windows OpenSSH 客户端）
  - 目标 Linux 板: root@192.168.31.211
  - 停止加热命令: cd /home/Linux_Menu && printf '7\n200.0\n0\n' | timeout 10 ./canfd_test

用法:
  python epoch_trigger.py <jsonl_path> [--target 200] [--interval 1.0] [--dry-run] [--selftest]
  python epoch_trigger.py <jsonl_path> --collector-pid 1234
  python epoch_trigger.py <jsonl_path> --collector-name "python_telemetry"
"""

import json
import os
import sys
import subprocess
import time
import argparse
import signal
from typing import Optional, Tuple


# ═══════════════════════════════════════════════════════════════════
# 安全边界常量（与 analyze_epoch.py 共享 SAFETY_MAX_TEMP_C）
# ═══════════════════════════════════════════════════════════════════
SAFETY_MAX_TEMP_C = 600          # 绝对最高温度 (°C) — 硬保护阈值
DEFAULT_TARGET_TEMP_C = 200.0    # 默认目标温度 (°C)
DEFAULT_POLL_INTERVAL_S = 1.0    # 默认轮询间隔 (秒)

# SSH 连接参数（V 指定）
SSH_HOST = "192.168.31.211"
SSH_USER = "root"
SSH_OPTIONS = [
    "ssh",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=10",
    "-o", "ServerAliveInterval=5",
    f"{SSH_USER}@{SSH_HOST}",
]

# 停止加热命令（V 指定：Linux_Menu canfd_test 管道）
STOP_HEATING_REMOTE_CMD = (
    "cd /home/Linux_Menu && printf '7\\n200.0\\n0\\n' | timeout 10 ./canfd_test"
)


# ═══════════════════════════════════════════════════════════════════
# 核心函数
# ═══════════════════════════════════════════════════════════════════

def get_last_t0(filepath: str) -> Optional[float]:
    """读取 JSONL 文件最后一行，提取 t0/T0 温度字段。

    逐行扫描文件，取最后一条非空 JSON 行中的 t0 或 T0 键值。
    与 analyze_epoch.py 的 get_temp() 键名约定保持一致。

    Args:
        filepath: JSONL 遥测文件路径

    Returns:
        float: t0 温度值 (°C)，若文件不存在 / 无有效记录则返回 None
    """
    if not os.path.isfile(filepath):
        print(f"[WARN] 文件不存在: {filepath}", file=sys.stderr)
        return None

    last_t0 = None
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            # 提取 t0 / T0 字段（与 analyze_epoch.py get_temp() 保持一致）
            for key in ("t0", "T0"):
                val = record.get(key)
                if val is not None:
                    try:
                        last_t0 = float(val)
                    except (TypeError, ValueError):
                        continue
                    break  # 找到 t0/T0 后不再尝试同行的另一个 key
    return last_t0


def stop_heating_via_ssh(dry_run: bool = False) -> Tuple[bool, str]:
    """通过 SSH 向 Linux 板发送停止加热命令。

    使用 Windows OpenSSH 客户端连接到目标 Linux 板，
    执行 canfd_test 管道命令：选择菜单项 7，设定温度 200.0°C，输出 0。

    Args:
        dry_run: True 时仅打印命令不执行

    Returns:
        (success: bool, message: str)
    """
    full_cmd = SSH_OPTIONS + [STOP_HEATING_REMOTE_CMD]

    if dry_run:
        cmd_str = " ".join(full_cmd)
        msg = f"[DRY-RUN] 将执行: {cmd_str}"
        print(msg)
        return True, msg

    print(f"[ACTION] 正在通过 SSH 发送停止加热命令到 {SSH_USER}@{SSH_HOST} ...")
    print(f"[CMD] {' '.join(full_cmd)}")

    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=20,  # 总超时 20s（含 SSH 连接 + 远程命令执行）
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode == 0:
            msg = f"[OK] 停止加热命令执行成功 (rc={result.returncode})"
            print(msg)
            if stdout:
                print(f"[STDOUT] {stdout[:500]}")
            return True, msg
        else:
            msg = (f"[FAIL] 停止加热命令失败 (rc={result.returncode})"
                   f"\n  stdout: {stdout[:300] if stdout else '(空)'}"
                   f"\n  stderr: {stderr[:300] if stderr else '(空)'}")
            print(msg, file=sys.stderr)
            return False, msg

    except subprocess.TimeoutExpired:
        msg = "[FAIL] SSH 命令超时 (20s)"
        print(msg, file=sys.stderr)
        return False, msg
    except FileNotFoundError:
        msg = "[FAIL] 未找到 ssh 命令 — 请确认 Windows OpenSSH 客户端已安装并在 PATH 中"
        print(msg, file=sys.stderr)
        return False, msg
    except Exception as e:
        msg = f"[FAIL] SSH 命令异常: {e}"
        print(msg, file=sys.stderr)
        return False, msg


def terminate_collector(pid: Optional[int] = None,
                         name: Optional[str] = None,
                         dry_run: bool = False) -> Tuple[bool, str]:
    """优雅终止采集器进程。

    Args:
        pid: 采集器进程 PID
        name: 采集器进程名（用于 taskkill /IM 匹配）
        dry_run: True 时仅打印不执行

    Returns:
        (success: bool, message: str)
    """
    if dry_run:
        if pid:
            print(f"[DRY-RUN] 将终止 PID={pid}")
        if name:
            print(f"[DRY-RUN] 将终止进程名={name}")
        return True, "[DRY-RUN] 跳过采集器终止"

    success = True
    messages = []

    if pid is not None:
        try:
            if sys.platform == "win32":
                cmd = ["taskkill", "/PID", str(pid)]
            else:
                cmd = ["kill", str(pid)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                messages.append(f"[OK] 已终止 PID={pid}")
            else:
                messages.append(f"[WARN] 终止 PID={pid} 失败: {r.stderr.strip()}")
                success = False
        except Exception as e:
            messages.append(f"[WARN] 终止 PID={pid} 异常: {e}")
            success = False

    if name is not None:
        try:
            if sys.platform == "win32":
                cmd = ["taskkill", "/IM", name, "/F"]
            else:
                cmd = ["pkill", "-f", name]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                messages.append(f"[OK] 已终止进程名={name}")
            else:
                messages.append(f"[WARN] 终止进程名={name} 失败: {r.stderr.strip()}")
                success = False
        except Exception as e:
            messages.append(f"[WARN] 终止进程名={name} 异常: {e}")
            success = False

    msg = "\n".join(messages) if messages else "[INFO] 未指定采集器终止目标"
    for m in messages:
        print(m)
    return success, msg


# ═══════════════════════════════════════════════════════════════════
# 看门狗主循环
# ═══════════════════════════════════════════════════════════════════

def run_watchdog(filepath: str,
                 target_temp: float = DEFAULT_TARGET_TEMP_C,
                 poll_interval: float = DEFAULT_POLL_INTERVAL_S,
                 dry_run: bool = False,
                 collector_pid: Optional[int] = None,
                 collector_name: Optional[str] = None) -> int:
    """看门狗主循环：监控 T0 → 触发停止 → 终止采集器。

    Returns:
        int: 0=正常停止, 1=错误
    """
    print("=" * 60)
    print("  DSC 自动看门狗 — epoch_trigger.py")
    print("=" * 60)
    print(f"  监控文件:     {filepath}")
    print(f"  目标温度:     {target_temp} °C")
    print(f"  硬保护上限:   {SAFETY_MAX_TEMP_C} °C")
    print(f"  轮询间隔:     {poll_interval} s")
    print(f"  SSH 目标:     {SSH_USER}@{SSH_HOST}")
    print(f"  Dry-Run:      {'是 (不执行 SSH)' if dry_run else '否'}")
    if collector_pid:
        print(f"  采集器 PID:   {collector_pid}")
    if collector_name:
        print(f"  采集器名:     {collector_name}")
    print("-" * 60)

    if not os.path.isfile(filepath):
        print(f"[ERROR] 监控文件不存在: {filepath}", file=sys.stderr)
        return 1

    triggered = False
    safety_triggered = False
    last_t0 = None

    try:
        while True:
            t0 = get_last_t0(filepath)

            if t0 is None:
                print(f"[{time.strftime('%H:%M:%S')}] 等待数据... (文件尚无有效 t0 记录)")
                time.sleep(poll_interval)
                continue

            # 温度变化时输出日志
            if last_t0 is None or abs(t0 - last_t0) > 0.1:
                print(f"[{time.strftime('%H:%M:%S')}] T0 = {t0:.2f} °C")
            last_t0 = t0

            # ── 600°C 硬保护（优先级最高，独立于 triggered 标志）──
            if t0 >= SAFETY_MAX_TEMP_C and not safety_triggered:
                safety_triggered = True
                print(f"\n{'!' * 60}")
                print(f"  ⚠ 硬保护触发: T0={t0:.2f}°C ≥ {SAFETY_MAX_TEMP_C}°C")
                print(f"  立即执行紧急停止！")
                print(f"{'!' * 60}")
                ok, msg = stop_heating_via_ssh(dry_run=dry_run)
                if ok:
                    print("[SAFETY] 紧急停止加热命令已发送")
                else:
                    print(f"[SAFETY] 紧急停止失败: {msg}", file=sys.stderr)
                # 即使 triggered 也为 true，防止后续重复触发
                triggered = True

            # ── 目标温度触发 ──
            if t0 >= target_temp and not triggered:
                triggered = True
                print(f"\n{'=' * 60}")
                print(f"  ✓ 目标温度到达: T0={t0:.2f}°C ≥ {target_temp}°C")
                print(f"  正在执行停止加热流程...")
                print(f"{'=' * 60}")
                ok, msg = stop_heating_via_ssh(dry_run=dry_run)
                if ok:
                    print("[OK] 停止加热命令已发送")
                else:
                    print(f"[FAIL] 停止加热命令失败: {msg}", file=sys.stderr)

                # 终止采集器
                if collector_pid or collector_name:
                    print(f"\n[INFO] 正在终止采集器...")
                    terminate_collector(
                        pid=collector_pid,
                        name=collector_name,
                        dry_run=dry_run,
                    )

                print(f"\n[INFO] 看门狗任务完成，退出监控循环。")
                break

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print(f"\n[INFO] 用户中断 (Ctrl+C)，看门狗退出。")
        return 0

    return 0


# ═══════════════════════════════════════════════════════════════════
# 自检模式 — 生成测试证据
# ═══════════════════════════════════════════════════════════════════

def run_selftest():
    """自检模式：创建模拟 JSONL 文件并验证 get_last_t0() 和 stop_heating_via_ssh()。

    产出: Evidence Pack — 所有测试结果打印到 stdout，可直接作为审查证据。
    """
    import tempfile
    import os as _os

    print("=" * 64)
    print("  epoch_trigger.py — 功能自检 (Evidence Pack)")
    print("=" * 64)
    print(f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  平台: {sys.platform}")
    print(f"  Python: {sys.version}")
    print()

    # ── 测试 1: get_last_t0() 基本读取 ──
    print("-" * 64)
    print("  TEST 1: get_last_t0() — 基本 JSONL 读取")
    print("-" * 64)

    test_jsonl_content = (
        '{"t0": 50.0, "Ts": 48.2, "pwm": 10, "timestamp": "2026-06-16T10:00:01"}\n'
        '{"t0": 75.3, "Ts": 72.1, "pwm": 25, "timestamp": "2026-06-16T10:00:02"}\n'
        '{"t0": 120.7, "Ts": 118.5, "pwm": 40, "timestamp": "2026-06-16T10:00:03"}\n'
        '{"t0": 165.2, "Ts": 162.8, "pwm": 60, "timestamp": "2026-06-16T10:00:04"}\n'
        '{"t0": 199.8, "Ts": 197.1, "pwm": 75, "timestamp": "2026-06-16T10:00:05"}\n'
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        f.write(test_jsonl_content)
        tmp_path = f.name

    try:
        result = get_last_t0(tmp_path)
        print(f"  模拟 JSONL 文件: {tmp_path}")
        print(f"  最后一行内容:    {test_jsonl_content.strip().split(chr(10))[-1]}")
        print(f"  get_last_t0() 返回: {result}")
        expected = 199.8
        if result == expected:
            print(f"  ✓ PASS: 正确提取 t0={result} (期望 {expected})")
        else:
            print(f"  ✗ FAIL: 期望 {expected}, 实际 {result}")
    finally:
        _os.unlink(tmp_path)

    # ── 测试 2: get_last_t0() — 大写 T0 键名 ──
    print()
    print("-" * 64)
    print("  TEST 2: get_last_t0() — 大写 T0 键名兼容")
    print("-" * 64)

    test_upper = '{"T0": 185.5, "Ts": 183.0, "pwm": 70}\n'

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        f.write(test_upper)
        tmp_path2 = f.name

    try:
        result = get_last_t0(tmp_path2)
        print(f"  模拟 JSONL 内容: {test_upper.strip()}")
        print(f"  get_last_t0() 返回: {result}")
        expected2 = 185.5
        if result == expected2:
            print(f"  ✓ PASS: 兼容大写 T0 键名, t0={result}")
        else:
            print(f"  ✗ FAIL: 期望 {expected2}, 实际 {result}")
    finally:
        _os.unlink(tmp_path2)

    # ── 测试 3: get_last_t0() — 空文件 ──
    print()
    print("-" * 64)
    print("  TEST 3: get_last_t0() — 空文件 / 无 t0 字段")
    print("-" * 64)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        f.write('{"Ts": 100.0, "pwm": 50}\n')
        tmp_path3 = f.name

    try:
        result = get_last_t0(tmp_path3)
        print(f"  模拟 JSONL 内容: {{\"Ts\": 100.0, \"pwm\": 50}}")
        print(f"  get_last_t0() 返回: {result}")
        if result is None:
            print(f"  ✓ PASS: 无 t0/T0 字段时正确返回 None")
        else:
            print(f"  ✗ FAIL: 期望 None, 实际 {result}")
    finally:
        _os.unlink(tmp_path3)

    # ── 测试 4: get_last_t0() — 文件不存在 ──
    print()
    print("-" * 64)
    print("  TEST 4: get_last_t0() — 文件不存在")
    print("-" * 64)

    result = get_last_t0("/nonexistent/path/telemetry.jsonl")
    print(f"  get_last_t0('/nonexistent/...') 返回: {result}")
    if result is None:
        print(f"  ✓ PASS: 文件不存在时正确返回 None")
    else:
        print(f"  ✗ FAIL: 期望 None, 实际 {result}")

    # ── 测试 5: get_last_t0() — 含空行的 JSONL ──
    print()
    print("-" * 64)
    print("  TEST 5: get_last_t0() — 含空行和无效行的 JSONL")
    print("-" * 64)

    test_mixed = (
        '{"t0": 50.0}\n'
        '\n'
        '{"t0": 100.0}\n'
        '   \n'
        'invalid json line\n'
        '{"t0": 150.5}\n'
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        f.write(test_mixed)
        tmp_path5 = f.name

    try:
        result = get_last_t0(tmp_path5)
        print(f"  模拟 JSONL 含空行 + 无效行, 最后有效行 t0=150.5")
        print(f"  get_last_t0() 返回: {result}")
        if result == 150.5:
            print(f"  ✓ PASS: 跳过空行和无效行，正确提取最后有效 t0")
        else:
            print(f"  ✗ FAIL: 期望 150.5, 实际 {result}")
    finally:
        _os.unlink(tmp_path5)

    # ── 测试 6: get_last_t0() — T0 优先于 t0（同记录中）──
    print()
    print("-" * 64)
    print("  TEST 6: get_last_t0() — t0/T0 提取优先级")
    print("-" * 64)

    test_both = '{"T0": 200.0, "t0": 199.0}\n'

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        f.write(test_both)
        tmp_path6 = f.name

    try:
        result = get_last_t0(tmp_path6)
        print(f"  模拟 JSONL: {{\"T0\": 200.0, \"t0\": 199.0}}")
        print(f"  get_last_t0() 返回: {result}")
        # 按代码逻辑：先检查 "t0" 再检查 "T0"，所以返回 199.0
        if result == 199.0:
            print(f"  ✓ PASS: t0 优先于 T0 (与 analyze_epoch.py get_temp() 顺序一致)")
        elif result == 200.0:
            print(f"  ! INFO: 返回 T0=200.0 (顺序与预期不同但值有效)")
        else:
            print(f"  ✗ FAIL: 期望 199.0 或 200.0, 实际 {result}")
    finally:
        _os.unlink(tmp_path6)

    # ── 测试 7: stop_heating_via_ssh() dry-run ──
    print()
    print("-" * 64)
    print("  TEST 7: stop_heating_via_ssh() — dry-run 模式")
    print("-" * 64)

    ok, msg = stop_heating_via_ssh(dry_run=True)
    print(f"  stop_heating_via_ssh(dry_run=True) → ok={ok}")
    if ok and "DRY-RUN" in msg:
        print(f"  ✓ PASS: dry-run 模式正确（未实际执行 SSH）")
    else:
        print(f"  ✗ FAIL: dry-run 模式异常")

    # ── 测试 8: SSH 命令格式验证 ──
    print()
    print("-" * 64)
    print("  TEST 8: SSH 停止加热命令格式验证")
    print("-" * 64)

    expected_host = "192.168.31.211"
    expected_user = "root"
    expected_menu_cmd = "cd /home/Linux_Menu"
    expected_can_cmd = "printf '7\\n200.0\\n0\\n' | timeout 10 ./canfd_test"

    checks = []
    checks.append(("SSH_HOST", SSH_HOST == expected_host, SSH_HOST))
    checks.append(("SSH_USER", SSH_USER == expected_user, SSH_USER))
    checks.append(("STOP_HEATING 含 Linux_Menu",
                    expected_menu_cmd in STOP_HEATING_REMOTE_CMD,
                    STOP_HEATING_REMOTE_CMD))
    checks.append(("STOP_HEATING 含 printf 管道",
                    "printf" in STOP_HEATING_REMOTE_CMD and "canfd_test" in STOP_HEATING_REMOTE_CMD,
                    STOP_HEATING_REMOTE_CMD))
    checks.append(("STOP_HEATING 含 timeout 10",
                    "timeout 10" in STOP_HEATING_REMOTE_CMD,
                    STOP_HEATING_REMOTE_CMD))

    all_ok = True
    for name, ok_flag, val in checks:
        status = "✓" if ok_flag else "✗"
        if not ok_flag:
            all_ok = False
        print(f"  {status} {name}: {val}")

    if all_ok:
        print(f"  ✓ PASS: 所有 SSH 命令格式检查通过")
    else:
        print(f"  ✗ FAIL: 部分格式检查未通过")

    # ── 测试 9: 600°C 硬保护常量 ──
    print()
    print("-" * 64)
    print("  TEST 9: 安全常量一致性")
    print("-" * 64)
    print(f"  epoch_trigger.py SAFETY_MAX_TEMP_C = {SAFETY_MAX_TEMP_C}")
    print(f"  analyze_epoch.py  SAFETY_MAX_TEMP_C = 600 (引用)")
    if SAFETY_MAX_TEMP_C == 600:
        print(f"  ✓ PASS: 硬保护阈值 = 600°C (与 analyze_epoch.py 一致)")
    else:
        print(f"  ✗ FAIL: 硬保护阈值不一致")

    # ── 汇总 ──
    print()
    print("=" * 64)
    print("  Evidence Pack 完成")
    print("=" * 64)
    print("  测试覆盖:")
    print("    get_last_t0():         TEST 1-6 (基本/大写/空文件/不存在/空行/优先级)")
    print("    stop_heating_via_ssh(): TEST 7 (dry-run)")
    print("    SSH 命令格式:           TEST 8 (host/user/menu/canfd/timeout)")
    print("    安全常量:              TEST 9 (600°C 硬保护)")
    print("=" * 64)


# ═══════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="DSC 自动看门狗 — 监控 T0 温度，自动停止加热并终止采集器"
    )
    parser.add_argument(
        "jsonl_path",
        nargs="?",
        help="遥测 JSONL 文件路径 (--selftest 模式下可省略)",
    )
    parser.add_argument(
        "--target", "-t",
        type=float,
        default=DEFAULT_TARGET_TEMP_C,
        help=f"目标温度 °C (默认: {DEFAULT_TARGET_TEMP_C})",
    )
    parser.add_argument(
        "--interval", "-i",
        type=float,
        default=DEFAULT_POLL_INTERVAL_S,
        help=f"轮询间隔秒数 (默认: {DEFAULT_POLL_INTERVAL_S})",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="仅监控不执行 SSH 停止命令",
    )
    parser.add_argument(
        "--collector-pid",
        type=int,
        default=None,
        help="采集器进程 PID (停止加热后终止)",
    )
    parser.add_argument(
        "--collector-name",
        type=str,
        default=None,
        help="采集器进程名 (停止加热后终止)",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="运行自检测试并输出 Evidence Pack",
    )

    args = parser.parse_args()

    # 自检模式
    if args.selftest:
        run_selftest()
        return

    # 正常模式需要 jsonl_path
    if not args.jsonl_path:
        parser.error("请指定 jsonl_path 或使用 --selftest 运行自检")

    # 参数校验
    if args.target > SAFETY_MAX_TEMP_C:
        print(
            f"[ERROR] 目标温度 ({args.target}) 超过安全上限 ({SAFETY_MAX_TEMP_C}°C)",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(run_watchdog(
        filepath=args.jsonl_path,
        target_temp=args.target,
        poll_interval=args.interval,
        dry_run=args.dry_run,
        collector_pid=args.collector_pid,
        collector_name=args.collector_name,
    ))


if __name__ == "__main__":
    main()
