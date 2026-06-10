import random
def main():
"""终端猜数字游戏：在 1~100 之间猜一个随机数。"""
target = random.randint(1, 100)
attempts = 0
print("🎯 猜数字游戏 (1~100)")
print("输入数字后按回车，看看你几次能猜中！\n")
while True:
raw = input("请输入你的猜测: ").strip()
# 处理空输入
if not raw:
print("⚠️  请输入一个数字。")
continue
# 直接尝试转换为整数，由 Python 原生校验
try:
guess = int(raw)
except ValueError:
print("⚠️  请输入有效的整数。")
continue
attempts += 1
# 范围校验
if guess < 1 or guess > 100:
print("⚠️  请输入 1~100 之间的数字。")
continue
# 比较分支
if guess < target:
print("📉 小了，再试试！")
elif guess > target:
print("📈 大了，再试试！")
else:
print(f"🎉 恭喜你猜中了！答案是 {target}，你一共猜了 {attempts} 次。")
break
if __name__ == "__main__":
main()