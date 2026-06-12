"""e2e_task_2_sum.py — 纯离线计算 1+2+3+4+5，输出 SUM_BETA_OK=15 并写入 result_2.txt"""

import os

RESULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "result_2.txt")
OUTPUT = "SUM_BETA_OK=15"


def compute_sum() -> int:
    """计算 1 到 5 的累加和"""
    return sum(range(1, 6))  # 1+2+3+4+5 = 15


def main() -> None:
    total = compute_sum()
    assert total == 15, f"Expected 15, got {total}"
    line = f"SUM_BETA_OK={total}"
    print(line)

    # 写入结果文件
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    main()
