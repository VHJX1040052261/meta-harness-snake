import os
import sys

OUTPUT_STRING = "E2E_ALPHA_OK"
OUTPUT_FILE = "result_1.txt"

def main():
    # 写入目标文件：路径为当前工作目录下的 result_1.txt
    target_path = os.path.join(os.getcwd(), OUTPUT_FILE)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(OUTPUT_STRING)

    # 终端输出
    print(OUTPUT_STRING)

    return 0

if __name__ == "__main__":
    sys.exit(main())
