#!/usr/bin/env python3
import csv
import os

csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sales.csv")

total = 0
with open(csv_path, newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        total += int(row["amount"])

output = f"CSV_SUM_OK={total}"
print(output)

result_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "result.txt")
with open(result_path, "w") as f:
    f.write(output)
