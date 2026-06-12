import csv

def analyze_inventory(csv_path):
    low_stock_skus = []
    total_value = 0.0
    category_stock = {}

    with open(csv_path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = row['sku']
            category = row['category']
            stock = int(row['stock'])
            min_stock = int(row['min_stock'])
            price = float(row['price'])

            if stock < min_stock:
                low_stock_skus.append(sku)

            total_value += stock * price

            category_stock[category] = category_stock.get(category, 0) + stock

    lines = []
    lines.append(f"LOW_STOCK={','.join(low_stock_skus)}")
    lines.append(f"TOTAL_VALUE={total_value:.2f}")
    for cat in sorted(category_stock.keys()):
        lines.append(f"CATEGORY_{cat}={category_stock[cat]}")

    output = '\n'.join(lines) + '\n'
    return output

if __name__ == '__main__':
    output = analyze_inventory('inventory.csv')
    print(output, end='')
    with open('result.txt', 'w') as f:
        f.write(output)
