#!/usr/bin/env python3
"""
Simple REPL Calculator
-----------------------
Supports  +  -  *  /
Space-separated expressions, e.g.:  5 + 3
Type 'q' to quit.
"""
def compute(a: float, op: str, b: float):
"""Return (result, error_message).  One of the two is always None."""
if op == '+':
return a + b, None
if op == '-':
return a - b, None
if op == '*':
return a * b, None
if op == '/':
if b == 0:
return None, "Error: Division by zero"
return a / b, None
return None, f"Error: Unknown operator '{op}'"
def fmt(value: float) -> str:
"""Print integer-looking results without the .0 suffix."""
if value.is_integer():
return str(int(value))
return str(value)
def repl():
print("Simple REPL Calculator")
print("Operators: +  -  *  /")
print("Usage: <num> <op> <num>   |   q to quit")
print("-" * 40)
while True:
try:
raw = input(">>> ").strip()
except (EOFError, KeyboardInterrupt):
print("\nGoodbye!")
break
if raw.lower() == 'q':
print("Goodbye!")
break
if not raw:
continue
parts = raw.split()
if len(parts) != 3:
print("Error: Expected format  <number> <operator> <number>")
continue
try:
a = float(parts[0])
b = float(parts[2])
except ValueError:
print("Error: Both operands must be numbers")
continue
op = parts[1]
if op not in ('+', '-', '*', '/'):
print(f"Error: Unsupported operator '{op}'.  Use + - * /")
continue
result, err = compute(a, op, b)
if err:
print(err)
else:
print(fmt(result))
if __name__ == "__main__":
repl()