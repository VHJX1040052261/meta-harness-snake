#!/usr/bin/env python3
"""
REPL 计算器
支持 + - * / 四则运算，除零检测，输入 q 退出。
"""
def main() -> None:
print("简易计算器 (输入 q 退出)")
print("支持运算: +  -  *  /")
print("-" * 30)
while True:
try:
expr = input(">>> ").strip()
except (EOFError, KeyboardInterrupt):
print()
break
if expr.lower() == "q":
print("再见！")
break
if not expr:
continue
# 解析运算符
op = None
for candidate in ("+", "-", "*", "/"):
if candidate in expr:
op = candidate
break
if op is None:
print("错误: 请输入包含 + - * / 的表达式，例如 3 + 5")
continue
parts = expr.split(op)
if len(parts) != 2:
print("错误: 表达式格式不正确，请使用 `数字 运算符 数字` 格式")
continue
try:
a = float(parts[0].strip())
b = float(parts[1].strip())
except ValueError:
print("错误: 无法解析数字，请检查输入")
continue
# 根据运算符计算
if op == "+":
result = a + b
elif op == "-":
result = a - b
elif op == "*":
result = a * b
elif op == "/":
if b == 0:
print("错误: 除数不能为零")
continue
result = a / b
else:
print(f"错误: 不支持的运算符 '{op}'")
continue
# 输出结果（整数则显示整数形式）
if result == int(result):
print(f"= {int(result)}")
else:
print(f"= {result}")
if __name__ == "__main__":
main()