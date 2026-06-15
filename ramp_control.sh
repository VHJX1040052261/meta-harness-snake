#!/usr/bin/env bash
# ==============================================================================
# ramp_control.sh — FCM Ramp 5°C/min 升温控制脚本
# ==============================================================================
# 通过 FIFO 管道向 canfd_test 发送菜单命令，实现：
#   系统复位(1) → FEP启动(3) → 温度安全检查 → 启动ramp(6,200.0,5.0)
#   → 每120秒查询温度(9) → 200°C附近发送停止加热(7)
#
# 复用资产：
#   1. canfd_test 管道模式 — 基于 linux_menu_log.txt 验证过的菜单序号和交互时序
#   2. SSH/SCP 桥接 — 本脚本由 V 通过 SSH 在 Linux 板上远程执行
#
# 安全边界：
#   - 管道模式只通过 stdin 发送菜单序号，无硬件直接访问
#   - 启动温度阈值检查 (< 40.0°C)
#   - 防超时保护 (60分钟)
#   - trap EXIT 保证中断时发送退出命令
#   - PWM 上限由固件保证 (pwm_max=95)
# ==============================================================================

set -euo pipefail

# ---- Configuration ----
TARGET_TEMP="200.0"
RAMP_RATE="5.0"
START_TEMP_THRESHOLD="40.0"
POLL_INTERVAL=120
STOP_THRESHOLD="195.0"
PWM_MAX=95
CANFD_BIN="${CANFD_BIN:-./canfd_test}"
LOG_DIR="/tmp/ramp_control_$$"
CMD_FIFO="$LOG_DIR/cmd_fifo"
OUT_LOG="$LOG_DIR/canfd_output.log"
RUN_LOG="$LOG_DIR/ramp_run.log"

mkdir -p "$LOG_DIR"

# ---- Logging helpers ----
log() {
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$ts] $*" | tee -a "$RUN_LOG"
}

# ---- Cleanup trap ----
cleanup() {
    log "CLEANUP: Shutting down..."
    # Try to send exit command (0) to canfd_test
    echo "0" > "$CMD_FIFO" 2>/dev/null || true
    sleep 2
    # Kill canfd_test if it's still running
    if [ -n "${CANFD_PID:-}" ]; then
        kill "$CANFD_PID" 2>/dev/null || true
        wait "$CANFD_PID" 2>/dev/null || true
    fi
    # Kill the FIFO keeper (holds write end open so canfd_test doesn't see EOF)
    if [ -n "${FIFO_KEEPER:-}" ]; then
        kill "$FIFO_KEEPER" 2>/dev/null || true
    fi
    log "CLEANUP: Log preserved at $OUT_LOG"
    log "CLEANUP: Run log at $RUN_LOG"
}
trap cleanup EXIT INT TERM

log "=============================================="
log "RAMP CONTROL STARTED"
log "=============================================="
log "Target:        $TARGET_TEMP °C"
log "Rate:          $RAMP_RATE °C/min"
log "Start thr:     $START_TEMP_THRESHOLD °C"
log "Stop thr:      $STOP_THRESHOLD °C"
log "Poll interval: ${POLL_INTERVAL}s"
log "PWM max:       $PWM_MAX"
log "CANFD binary:  $CANFD_BIN"
log "Log dir:       $LOG_DIR"
log "=============================================="

# ---- Create FIFO ----
if [ -p "$CMD_FIFO" ]; then
    rm -f "$CMD_FIFO"
fi
mkfifo "$CMD_FIFO"
log "Created FIFO: $CMD_FIFO"

# ---- FIFO keeper: holds write end open to prevent canfd_test from seeing EOF ----
# sleep 999999 with stdout redirect to FIFO keeps the write end open but writes nothing
sleep 999999 > "$CMD_FIFO" &
FIFO_KEEPER=$!
log "FIFO keeper PID=$FIFO_KEEPER"

# ---- Start canfd_test ----
# stdin reads from FIFO, stdout+stderr go to log file
"$CANFD_BIN" < "$CMD_FIFO" > "$OUT_LOG" 2>&1 &
CANFD_PID=$!
log "canfd_test PID=$CANFD_PID"
sleep 2  # Wait for CAN bus initialization

# ---- Helpers ----

# send_cmd: write a command string to the FIFO
send_cmd() {
    local cmd="$1"
    echo "$cmd" > "$CMD_FIFO"
    sleep 0.5
}

# get_temp: extract the most recent temperature reading from canfd_test output
# Expected format: "当前温度: XX.XX °C"
get_temp() {
    grep "当前温度:" "$OUT_LOG" 2>/dev/null | tail -1 | grep -oE '[0-9]+\.[0-9]+' | head -1
}

# get_state: extract control state for diagnostics
get_state() {
    grep "当前状态:" "$OUT_LOG" 2>/dev/null | tail -1 | grep -oP '当前状态:\s*\K.*' | head -1
}

# safe_compare: floating point comparison using bc, returns 0 if true, 1 if false
safe_gt() {
    local a="$1" b="$2"
    local result
    result=$(echo "$a > $b" | bc -l 2>/dev/null) || return 1
    [ "$result" = "1" ]
}

safe_ge() {
    local a="$1" b="$2"
    local result
    result=$(echo "$a >= $b" | bc -l 2>/dev/null) || return 1
    [ "$result" = "1" ]
}

# ==============================================================================
# MAIN CONTROL SEQUENCE
# ==============================================================================

# ---- Step 1: System Reset (CMD 1) ----
log "[1/8] System reset (CMD 1)..."
send_cmd "1"
sleep 3
log "[1/8] System reset sent."

# ---- Step 2: Start FEP (CMD 3) ----
log "[2/8] Start FEP (CMD 3)..."
send_cmd "3"
sleep 3
log "[2/8] FEP start sent."

# ---- Step 3: Check current temperature (CMD 9) ----
log "[3/8] Check current temperature (CMD 9)..."
send_cmd "9"
sleep 2
T=$(get_temp)
if [ -n "$T" ]; then
    log "[3/8] Current temperature: $T °C"
else
    log "[3/8] WARNING: Could not read initial temperature. Will retry..."
    sleep 2
    send_cmd "9"
    sleep 2
    T=$(get_temp)
    log "[3/8] Retry temperature: ${T:-STILL_UNKNOWN} °C"
fi

# ---- Step 4: Safety check — start temperature must be below threshold ----
log "[4/8] Safety check: start temp must be < $START_TEMP_THRESHOLD °C"
if [ -n "$T" ]; then
    if safe_ge "$T" "$START_TEMP_THRESHOLD"; then
        log "[ABORT] Start temperature $T °C >= $START_TEMP_THRESHOLD °C threshold!"
        log "[ABORT] Unsafe to start ramp — board may be too hot. Let it cool down."
        exit 1
    fi
    log "[4/8] Start temperature $T °C is SAFE (< $START_TEMP_THRESHOLD °C)"
else
    log "[4/8] WARNING: Cannot read temperature. Proceeding with caution."
    log "[4/8] Will check temperature again in monitoring loop."
fi

# ---- Step 5: Start Ramp (CMD 6) — target=200.0°C, rate=5.0°C/min ----
log "[5/8] Start ramp: target=$TARGET_TEMP °C, rate=$RAMP_RATE °C/min (CMD 6)..."
send_cmd "6"
sleep 1
# Send target temperature as sub-parameter
send_cmd "$TARGET_TEMP"
sleep 1
# Send ramp rate as sub-parameter
send_cmd "$RAMP_RATE"
sleep 3
log "[5/8] Ramp command sequence sent (6 → $TARGET_TEMP → $RAMP_RATE)."

# ---- Step 6: Monitor temperature every POLL_INTERVAL seconds ----
log "[6/8] Entering monitoring loop..."
log "[6/8] Poll interval: ${POLL_INTERVAL}s"
log "[6/8] Stop threshold: $STOP_THRESHOLD °C"
log "[6/8] Safety timeout: 3600s (60 min)"

START_TS=$(date +%s)
MONITOR_COUNT=0

while true; do
    # Wait for poll interval
    sleep "$POLL_INTERVAL"

    MONITOR_COUNT=$((MONITOR_COUNT + 1))

    # Query current temperature (CMD 9)
    send_cmd "9"
    sleep 2
    T=$(get_temp)

    # Also query control state for diagnostics (CMD 8)
    send_cmd "8"
    sleep 1
    STATE=$(get_state)
    [ -n "$STATE" ] && STATE=" | State: $STATE" || STATE=""

    ELAPSED=$(($(date +%s) - START_TS))
    ELAPSED_MIN=$(echo "scale=1; $ELAPSED / 60" | bc 2>/dev/null || echo "?")

    if [ -n "$T" ]; then
        log "[MONITOR #$MONITOR_COUNT] T+${ELAPSED}s (${ELAPSED_MIN}min) | Temp: ${T}°C | Target: ${TARGET_TEMP}°C$STATE"

        # Check if we've reached the stop threshold
        if safe_ge "$T" "$STOP_THRESHOLD"; then
            log "[TRIGGER] Temperature $T °C >= $STOP_THRESHOLD °C threshold!"
            log "[TRIGGER] Sending STOP HEATING command."
            break
        fi
    else
        log "[MONITOR #$MONITOR_COUNT] T+${ELAPSED}s (${ELAPSED_MIN}min) | Temp: READ_ERROR$STATE"
    fi

    # Safety timeout: 60 minutes maximum
    if [ "$ELAPSED" -ge 3600 ]; then
        log "[SAFETY_TIMEOUT] 60 minutes elapsed. Forcing stop for safety."
        break
    fi
done

# ---- Step 7: Stop Heating (CMD 7) ----
log "[7/8] Stop heating (CMD 7)..."
send_cmd "7"
sleep 3
log "[7/8] Stop heating command sent."

# ---- Step 8: Final status check ----
log "[8/8] Final status check..."
send_cmd "9"
sleep 2
T=$(get_temp)

send_cmd "8"
sleep 1
STATE=$(get_state)

TOTAL_ELAPSED=$(($(date +%s) - START_TS))
TOTAL_MIN=$(echo "scale=1; $TOTAL_ELAPSED / 60" | bc 2>/dev/null || echo "?")

log ""
log "=============================================="
log "  RAMP 5°C/min EXPERIMENT COMPLETE"
log "=============================================="
log "  Target:         $TARGET_TEMP °C"
log "  Rate:           $RAMP_RATE °C/min"
log "  Final temp:     ${T:-N/A} °C"
log "  Control state:  ${STATE:-N/A}"
log "  Total elapsed:  ${TOTAL_ELAPSED}s (${TOTAL_MIN}min)"
log "  Output log:     $OUT_LOG"
log "  Run log:        $RUN_LOG"
log "=============================================="

# Send exit command (0) to canfd_test
log "Sending exit command (0) to canfd_test..."
send_cmd "0"
sleep 2

log "RAMP CONTROL FINISHED SUCCESSFULLY."
