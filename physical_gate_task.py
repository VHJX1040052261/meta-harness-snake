import os
import sys

OUTPUT = "PHYSICAL_GATE_OK"
OUTPUT_FILE = "result_physical_gate.txt"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def write_result() -> None:
    target_path = os.path.join(SCRIPT_DIR, OUTPUT_FILE)
    with open(target_path, "w", encoding="utf-8") as fh:
        fh.write(OUTPUT)


def main() -> None:
    sys.stdout.write(OUTPUT)
    sys.stdout.write("\n")
    write_result()


if __name__ == "__main__":
    main()
