# Phase 1 Epoch 1: 50–200°C 10°C/min PID 基线测试 — 实验执行流程

**协议**: DSC自动化PID调参作战纲领 v1.0
**实验参数**: 50–200°C, 10.0°C/min, 冷却阈值 50.0°C
**PID策略**: 基线测试, 不改PID参数

---

## 安全保护

| 约束 | 值 | 说明 |
|------|-----|------|
| 最高温度 | 600°C | 超限立即断电 |
| PWM 上限 | 95% | 防止加热器过载 |
| COM13 预检 | 强制 | 实验前必须通过 |
| 无数据不加热 | 强制 | 采集未就绪禁止升温 |

---

## 执行流程

### Step 1: COM13 预检 (Preflight)

```powershell
# 在 Windows Bridge 端执行
powershell -ExecutionPolicy Bypass -File preflight_com13.ps1
```

**预期输出**: `COM13_OK`
**失败处理**: 若输出 `COM13_FAIL`，检查串口连接和驱动，修复后重新执行。

---

### Step 2: 清空旧数据 & 启动采集

```bash
# 清空上一轮遥测数据
rm -f vhj_telemetry.jsonl

# 启动 vhj_collector.py 后台采集
python3 vhj_collector.py --output vhj_telemetry.jsonl &
COLLECTOR_PID=$!
echo "Collector PID: $COLLECTOR_PID"
```

**验证**: 确认 `vhj_telemetry.jsonl` 文件已创建并开始写入数据。

---

### Step 3: 发送 Ramp 指令 (Linux_Menu canfd_test 管道模式)

```bash
# 通过 Linux_Menu canfd_test 管道模式发送升温指令
# 协议: 目标温度 200°C, 升温速率 10.0°C/min
# 管道模式: 发送指令后立即退出，不阻塞

echo "ramp 200.0 10.0" | Linux_Menu canfd_test --pipe
```

**预期**: FCM 开始按 10°C/min 从当前温度升温至 200°C。

---

### Step 4: 监控升温过程

```bash
# 监控遥测数据，实时查看温度和 slope
tail -f vhj_telemetry.jsonl | while read line; do
  temp=$(echo "$line" | jq -r '.t0 // .T0 // .temperature // empty')
  slope=$(echo "$line" | jq -r '.slope // .rate_fast // empty')
  pwm=$(echo "$line" | jq -r '.pwm // .pwm_out // empty')
  echo "[$(date +%H:%M:%S)] T0=${temp}°C  slope=${slope}  PWM=${pwm}%"
done
```

**关键检查项**:
- 温度是否在上升（`slope > 0`）
- PWM 是否在安全范围内（`≤ 95%`）
- 温度是否接近目标 200°C

---

### Step 5: 到达 200°C 后停止加热

```bash
# 方案A: 设置目标温度到冷却阈值（模式保持，自然降温）
echo "ramp 50.0 10.0" | Linux_Menu canfd_test --pipe

# 方案B: 切换到空闲模式 (mode=0)
echo "idle" | Linux_Menu canfd_test --pipe
```

**等待**: 温度降至冷却阈值 50.0°C 以下，或自然冷却至安全温度。

---

### Step 6: 停止采集 & 拉取数据

```bash
# 停止采集进程
kill $COLLECTOR_PID 2>/dev/null

# 确认数据文件完整性
wc -l vhj_telemetry.jsonl
ls -lh vhj_telemetry.jsonl
```

---

### Step 7: 运行 Epoch 分析

```bash
# 按纲领切片逻辑分析遥测数据
python3 analyze_epoch.py vhj_telemetry.jsonl \
  --start-temp 50 \
  --target-temp 200 \
  --threshold 0.2
```

**分析输出**:
- 爬升期 (50–70°C): slope 范围报告，不计入稳态考核
- 稳态期 (70–200°C): Steady_P2P 计算
- 判定: PASS (Steady_P2P ≤ 0.2) 或 FAIL

---

### Step 8: 保存结果到归档

```bash
# 创建结果目录
RESULT_DIR="epoch1_10cpm_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RESULT_DIR"

# 保存遥测数据和分析结果
cp vhj_telemetry.jsonl "$RESULT_DIR/"
python3 analyze_epoch.py vhj_telemetry.jsonl --json > "$RESULT_DIR/epoch_analysis.json"

echo "结果已保存到: $RESULT_DIR"
```

---

## 数据切片逻辑 (纲领 v1.0)

```
温度轴:  50°C ─────── 70°C ──────────────────────── 200°C
         │  爬升期     │       稳态期                  │
         │ (Climb)     │      (Steady)                │
         │             │                               │
判定:    不计入考核     Steady_P2P = max(slope) - min(slope)
                       PASS if Steady_P2P ≤ 0.2
```

---

## 后续 Epoch 调参方向

| 现象 | 策略 |
|------|------|
| 升温过慢 | 增加 P 和 I |
| 稳态噪声大 | 增加 D 或引入软件滤波 |
| 低频振荡 | 减小 I，增加积分分离/抗积分饱和 |

---

## 紧急停止

若实验中出现以下任一情况，立即执行紧急停止：

```bash
# 紧急: 切换到空闲模式
echo "idle" | Linux_Menu canfd_test --pipe

# 或: 物理断开加热器电源
```

**触发条件**:
- 温度 ≥ 600°C
- PWM ≥ 95% 持续超过 3 秒
- 遥测数据中断超过 5 秒
- 烟雾/异味/异常噪音
