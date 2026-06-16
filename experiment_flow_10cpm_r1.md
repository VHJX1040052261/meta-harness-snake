# 10°C/min 自动调参第1轮 — 实验执行流程

## 实验参数

| 参数 | 值 |
|------|-----|
| 升温速率 | 10.0 °C/min |
| 目标温度 | 200.0 °C |
| 串口 | COM13 |
| 波特率 | 576000 |
| 分析区间 | 60 – 180 °C |

---

## 执行流程

### Step 1: 清空旧数据
```
# 在 Windows 侧执行
Remove-Item -Path tools\vhj_telemetry*.jsonl -Force -ErrorAction SilentlyContinue
```
**目的**: 遵守 data_isolation 规则，每轮实验前清除旧采集数据。

---

### Step 2: Preflight 检查
```
# 在 Windows 侧执行
powershell -ExecutionPolicy Bypass -File preflight_com13.ps1
```
**复用**: `preflight_com13.ps1`
**检查项**: COM13 可用性、波特率 576000、VHJ 设备响应、通讯链路完整性。

---

### Step 3: 启动 VHJ Telemetry 采集
```
# 在 Windows 侧执行（后台运行）
python vhj_collector.py --port COM13 --baud 576000 --output vhj_telemetry_r1.jsonl
```
**复用**: `vhj_collector.py`（VHJ telemetry 10字段 JSONL）
**输出**: `vhj_telemetry_r1.jsonl`（每行一个 JSON 对象，包含 temperature、slope 等 10 个字段）

---

### Step 4: 执行 Ramp
```
# 在 Linux 侧通过 Linux_Menu canfd_test 管道模式发送 ramp 指令
echo "RAMP 10.0 200.0" | canfd_test --pipe
```
**复用**: `Linux_Menu canfd_test` 管道模式
**行为**: 以 10.0 °C/min 速率升温至 200.0 °C，期间 VHJ 持续采集。

---

### Step 5: 停止采集 & 停止加热
```
# 停止 Python 采集进程 (Ctrl+C 或 kill)
# 发送停止加热指令
echo "STOP" | canfd_test --pipe
```

---

### Step 6: 拉取数据到独立目录
```
# 在分析侧执行（scp 或文件同步）
# 将 Windows 侧的 vhj_telemetry_r1.jsonl 拉到独立实验目录
mkdir -p experiments/r1_10cpm
scp user@windows_host:tools/vhj_telemetry_r1.jsonl experiments/r1_10cpm/
```
**数据隔离**: 每轮实验结果存放在独立目录（如 `experiments/r1_10cpm/`），不合并。

---

### Step 7: Slope 分析
```
python3 analyze_slope.py experiments/r1_10cpm/vhj_telemetry_r1.jsonl --range 60 180 --threshold 0.2
```
**复用**: `analyze_slope.py`（本轮创建）
**判定逻辑**:
```
slope_peak_to_peak = max(slope) - min(slope)   # 60-180°C 区间
若 slope_peak_to_peak ≤ 0.2 → PASS
否则 → FAIL
```

---

## 判定标准

| 指标 | 公式 | 阈值 | 含义 |
|------|------|------|------|
| slope 峰峰值 | max(slope) − min(slope) | ≤ 0.2 | 60-180°C 区间内 slope 波动在允许范围内 |

## 预期产物

| 产物 | 路径 | 说明 |
|------|------|------|
| 采集数据 | `experiments/r1_10cpm/vhj_telemetry_r1.jsonl` | VHJ 10字段 JSONL |
| 分析报告 | stdout + JSON_RESULT 行 | slope 峰峰值及 PASS/FAIL 判定 |

## 回滚 / 重试

若本轮 FAIL，调整 PID/控制参数后从 Step 1 重新执行下一轮（r2, r3...）。
