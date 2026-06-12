import csv


def main():
    total = 0
    with open('sales.csv', 'r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += int(row['amount'])

    output = f'CSV_SUM_OK={total}'
    print(output)

    with open('result.txt', 'w', newline='') as f:
        f.write(output)


if __name__ == '__main__':
    main()
