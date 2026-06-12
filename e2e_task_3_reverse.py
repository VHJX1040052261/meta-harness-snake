#!/usr/bin/env python3
"""E2E Task 3: Reverse the string 'gamma' and output the result."""

def main():
    input_str = "gamma"
    reversed_str = input_str[::-1]

    output = f"REVERSE_GAMMA_OK={reversed_str}"

    # Print to stdout
    print(output)

    # Write to result file
    with open("result_3.txt", "w") as f:
        f.write(output)


if __name__ == "__main__":
    main()
