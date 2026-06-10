"""
timer.py — 终端倒计时器
用法: python timer.py
输入秒数，程序逐秒显示剩余时间，到零时打印 "时间到！"
"""
import time
def main() -> None:
try:
total = int(input("请输入倒计时秒数: "))
except ValueError:
print("错误：请输入一个有效的整数。")
return
if total <= 0:
print("错误：秒数必须大于 0。")
return
remaining = total
while remaining > 0:
print(f"剩余 {remaining} 秒...")
time.sleep(1)
remaining -= 1
print("时间到！")
if __name__ == "__main__":
main()