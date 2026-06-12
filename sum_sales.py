import csv

total = 0
with open("sales.csv", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        total += int(row["amount"])

print(f"CSV_SUM_OK={total}")
