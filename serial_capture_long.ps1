<#
.SYNOPSIS
    serial_capture_long.ps1 — FCM Ramp 5°C/min 长时间串口采集
.DESCRIPTION
    独立 PowerShell 脚本，只读 COM13/576000，采集 45 分钟。
    输出 raw text 和结构化 JSON 到指定目录。

    复用资产：
      1. System.IO.Ports.SerialPort — V 指定的复用模式
      2. serial_capture.ps1 — 串口参数和错误处理模式
      3. fcm_full_validation.ps1 — 结构化 JSON 输出格式

    安全边界（强制保证）：
      - DtrEnable=$false, RtsEnable=$false — 不控制 DTR/RTS 硬件线
      - 代码中零次 $sp.Write() / $sp.WriteLine() 调用
      - 唯一写操作目标为文件 StreamWriter
      - finally 块保证端口关闭
      - 时间边界保护：到达持续时间后自动关闭端口
.PARAMETER Port
    串口名称，默认 COM13
.PARAMETER BaudRate
    波特率，默认 576000
.PARAMETER DurationSeconds
    采集时长（秒），默认 2700（45 分钟）
.PARAMETER OutDir
    输出目录，留空则自动生成时间戳目录
.PARAMETER DataBits
    数据位，默认 8
.PARAMETER Parity
    校验位，默认 None
.PARAMETER StopBits
    停止位，默认 One
.PARAMETER ReadTimeoutMs
    读超时（毫秒），默认 500
#>

param(
    [string]$Port = "COM13",
    [int]$BaudRate = 576000,
    [int]$DurationSeconds = 2700,
    [string]$OutDir = "",
    [int]$DataBits = 8,
    [string]$Parity = "None",
    [string]$StopBits = "One",
    [bool]$DtrEnable = $false,
    [bool]$RtsEnable = $false,
    [int]$ReadTimeoutMs = 500
)

$ErrorActionPreference = "Continue"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# ---- Timestamp & Output Path ----
$timestamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
if ($OutDir -eq "") {
    $OutDir = "C:\MetaBridge\outbox\serial_ramp_5cpm_$timestamp"
}
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$rawTextPath    = Join-Path $OutDir "serial_raw.txt"
$resultJsonPath = Join-Path $OutDir "serial_capture.json"

# ---- Parity / StopBits Maps ----
$parityMap = @{
    "None"  = [System.IO.Ports.Parity]::None
    "Odd"   = [System.IO.Ports.Parity]::Odd
    "Even"  = [System.IO.Ports.Parity]::Even
    "Mark"  = [System.IO.Ports.Parity]::Mark
    "Space" = [System.IO.Ports.Parity]::Space
}
$stopBitsMap = @{
    "None"         = [System.IO.Ports.StopBits]::None
    "One"          = [System.IO.Ports.StopBits]::One
    "Two"          = [System.IO.Ports.StopBits]::Two
    "OnePointFive" = [System.IO.Ports.StopBits]::OnePointFive
}
$parityEnum   = $parityMap[$Parity]
$stopBitsEnum = $stopBitsMap[$StopBits]

# ---- Result Scaffold ----
$result = [ordered]@{
    job_id             = "serial_ramp_5cpm_001"
    status             = "started"
    port               = $Port
    baud_rate          = $BaudRate
    data_bits          = $DataBits
    parity             = $Parity
    stop_bits          = $StopBits
    dtr_enable         = $DtrEnable
    rts_enable         = $RtsEnable
    duration_seconds   = $DurationSeconds
    duration_requested = "$([Math]::Round($DurationSeconds / 60.0, 1)) min"
    windows_host       = $env:COMPUTERNAME
    timestamp_utc      = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    bytes              = 0
    total_lines        = 0
    text_preview       = ""
    error              = ""
    out_dir            = $OutDir
    raw_text_path      = $rawTextPath
}

$sp = $null
$writer = $null

try {
    # ---- Check port availability ----
    $availablePorts = [System.IO.Ports.SerialPort]::getportnames()
    if ($Port -notin $availablePorts) {
        $result.status = "port_not_found"
        $result.error = "COM13 not found in available ports: $($availablePorts -join ', ')"
        $json = $result | ConvertTo-Json -Depth 6
        [System.IO.File]::WriteAllText($resultJsonPath, $json, $utf8NoBom)
        Write-Host "RESULT: $resultJsonPath"
        Write-Host "STATUS: port_not_found"
        exit 0
    }

    # ---- Open serial port (READ-ONLY configuration) ----
    $sp = New-Object System.IO.Ports.SerialPort(
        $Port,
        $BaudRate,
        $parityEnum,
        $DataBits,
        $stopBitsEnum
    )
    $sp.ReadTimeout  = $ReadTimeoutMs
    $sp.WriteTimeout = $ReadTimeoutMs
    $sp.DtrEnable    = $DtrEnable    # $false — do NOT control DTR
    $sp.RtsEnable    = $RtsEnable    # $false — do NOT control RTS

    try {
        $sp.Open()
    } catch {
        $errMsg = $_.Exception.Message
        if ($errMsg -match "Access.*denied|denied|being used|in use|unavailable|does not exist") {
            $result.status = "port_busy_or_denied"
            $result.error  = $errMsg
        } else {
            $result.status = "error"
            $result.error  = $errMsg
        }
        $json = $result | ConvertTo-Json -Depth 6
        [System.IO.File]::WriteAllText($resultJsonPath, $json, $utf8NoBom)
        Write-Host "RESULT: $resultJsonPath"
        Write-Host "STATUS: $($result.status)"
        exit 0
    }

    Write-Host "SERIAL: Port $Port opened at $BaudRate baud"
    Write-Host "SERIAL: Duration = $DurationSeconds seconds ($([Math]::Round($DurationSeconds / 60.0, 1)) min)"
    Write-Host "SERIAL: Read-only mode confirmed (DtrEnable=$DtrEnable, RtsEnable=$RtsEnable)"
    Write-Host "SERIAL: Output -> $rawTextPath"

    # ---- Open file writer (the ONLY write target in this script) ----
    $writer = New-Object System.IO.StreamWriter($rawTextPath, $false, $utf8NoBom)

    # ---- Read-only capture loop ----
    # SECURITY: This loop contains ZERO calls to $sp.Write() or $sp.WriteLine()
    # The only write operations target $writer (file StreamWriter)
    $deadline    = (Get-Date).AddSeconds($DurationSeconds)
    $totalBytes  = 0
    $lineCount   = 0
    $lastReport  = Get-Date
    $reportInterval = 300  # Report progress every 5 minutes

    Write-Host "SERIAL: Capture started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

    while ((Get-Date) -lt $deadline) {
        try {
            # ReadExisting() is READ-ONLY — does not transmit any data
            $chunk = $sp.ReadExisting()
            if ($chunk.Length -gt 0) {
                $writer.Write($chunk)
                $totalBytes += [System.Text.Encoding]::UTF8.GetByteCount($chunk)

                # Count newlines for approximate line count
                $lineCount += ($chunk -split "`n").Count - 1
            }
        } catch {
            # Read timeout is expected when no data; other errors are logged
            if ($_.Exception.Message -notmatch "timeout|timed out") {
                Write-Host "SERIAL: Read error (non-fatal): $($_.Exception.Message)"
            }
        }

        # Progress report every reportInterval seconds
        if (([DateTime]::Now - $lastReport).TotalSeconds -ge $reportInterval) {
            $elapsed  = [Math]::Round(([DateTime]::Now - $deadline.AddSeconds(-$DurationSeconds)).TotalSeconds, 0)
            $remaining = $DurationSeconds - $elapsed
            $elapsedMin = [Math]::Round($elapsed / 60.0, 1)
            $remainingMin = [Math]::Round($remaining / 60.0, 1)
            Write-Host "SERIAL: Progress — ${elapsedMin}min elapsed, ${remainingMin}min remaining, ${totalBytes} bytes captured"
            $lastReport = [DateTime]::Now
        }

        # Small sleep to prevent CPU spinning
        Start-Sleep -Milliseconds 100
    }

    # ---- Flush and close writer ----
    $writer.Flush()
    $writer.Close()
    $writer = $null

    $actualDuration = [Math]::Round((Get-Date).AddSeconds($DurationSeconds) - $deadline.AddSeconds(-$DurationSeconds).AddSeconds($DurationSeconds) + $DurationSeconds, 1)

    # ---- Read back first 500 chars for preview ----
    if (Test-Path $rawTextPath) {
        $rawBytes = (Get-Item $rawTextPath).Length
        $previewText = Get-Content -Path $rawTextPath -TotalCount 10 -Raw

        $result.status = if ($rawBytes -gt 0) { "ok" } else { "ok_no_data" }
        $result.bytes = $rawBytes
        $result.total_lines = $lineCount

        if ($previewText -and $previewText.Length -gt 0) {
            if ($previewText.Length -gt 500) {
                $result.text_preview = $previewText.Substring(0, 500)
            } else {
                $result.text_preview = $previewText
            }
        }
    } else {
        $result.status = "ok_no_data"
        $result.bytes = 0
        $result.total_lines = 0
    }

    $result.duration_actual = $actualDuration

    Write-Host "SERIAL: Capture complete — status=$($result.status) bytes=$($result.bytes) lines=$($result.total_lines)"
    Write-Host "SERIAL: Actual duration: ${actualDuration}s"

} catch {
    $result.status = "error"
    $result.error  = $_.Exception.Message
    Write-Host "SERIAL: FATAL ERROR — $($_.Exception.Message)"
} finally {
    # ---- Guaranteed cleanup ----
    # Close file writer if still open
    if ($writer) {
        try { $writer.Flush(); $writer.Close() } catch {}
        $writer = $null
    }

    # Close serial port — IMPORTANT: release hardware resource
    if ($sp -and $sp.IsOpen) {
        try { $sp.Close() } catch {}
        $sp = $null
    }

    # ---- Write result JSON ----
    $json = $result | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText($resultJsonPath, $json, $utf8NoBom)

    Write-Host "RESULT: $resultJsonPath"
    Write-Host "STATUS: $($result.status)"
    Write-Host "OUTDIR: $OutDir"
    Write-Host "RAWTXT: $rawTextPath"
}
