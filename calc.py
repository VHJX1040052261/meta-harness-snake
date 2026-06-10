#!/usr/bin/env python3
"""Simple REPL calculator supporting +, -, *, / operations."""
import sys
def evaluate(expression: str) -> float:
"""Parse and evaluate a simple arithmetic expression.
Supports: +, -, *, /
Operands and operators must be separated by whitespace.
Example: "3 + 4 * 2" -> 11.0
"""
tokens = expression.strip().split()
if not tokens:
raise ValueError("Empty expression")
# Phase 1: handle * and / (higher precedence) — left to right
stack = []
i = 0
while i < len(tokens):
token = tokens[i]
if token in ("*", "/"):
operator = token
left = stack.pop()
right_str = tokens[i + 1]
right = _parse_number(right_str)
if operator == "*":
stack.append(left * right)
else:
if right == 0:
raise ZeroDivisionError("Division by zero")
stack.append(left / right)
i += 2
else:
stack.append(_parse_number(token))
i += 1
# Phase 2: handle + and - (lower precedence) — left to right
result = stack[0]
j = 1
while j < len(tokens):
token = tokens[j]
if token in ("+", "-"):
operator = token
right = tokens[j + 1]
# Skip tokens that have been processed in phase 1
# We need to find the next unprocessed token
j += 1
continue
j += 1
# Simpler approach: rebuild from stack using original operator positions
result = stack[0]
idx = 1
i = 0
while i < len(tokens):
token = tokens[i]
if token in ("+", "-"):
# find the next value in the stack
if idx < len(stack):
right = stack[idx]
if token == "+":
result += right
else:
result -= right
idx += 1
i += 1
return result
def _parse_number(token: str) -> float:
"""Convert a token string to a number, raising on invalid input."""
try:
if "." in token:
return float(token)
return int(token)
except ValueError:
raise ValueError(f"Invalid number: {token}")
def _add_sub(expression: str) -> float:
"""Handle addition and subtraction (lowest precedence)."""
tokens = expression.strip().split()
# First pass: resolve * and /
resolved = []
i = 0
while i < len(tokens):
token = tokens[i]
if token in ("*", "/"):
left = _parse_number(resolved.pop())
op = token
right = _parse_number(tokens[i + 1])
if op == "*":
resolved.append(left * right)
else:
if right == 0:
raise ZeroDivisionError("Division by zero")
resolved.append(left / right)
i += 2
else:
resolved.append(token)
i += 1
# Second pass: resolve + and -
result = _parse_number(resolved[0])
i = 1
while i < len(resolved):
op = resolved[i]
right = _parse_number(resolved[i + 1])
if op == "+":
result += right
else:  # op == "-"
result -= right
i += 2
return result
def repl():
"""Run the REPL loop."""
print("Simple Calculator REPL")
print("Enter expressions like: 3 + 4 * 2")
print("Operators: +  -  *  /")
print("Type 'quit', 'exit', or 'q' to quit.")
print("-" * 40)
while True:
try:
raw = input("> ").strip()
except (EOFError, KeyboardInterrupt):
print()
break
if not raw:
continue
if raw.lower() in ("quit", "exit", "q"):
print("Goodbye.")
break
try:
result = _add_sub(raw)
print(result)
except ZeroDivisionError:
print("Error: Division by zero.")
except ValueError as e:
print(f"Error: {e}")
except (IndexError, TypeError):
print("Error: Invalid expression format.")
if __name__ == "__main__":
repl()