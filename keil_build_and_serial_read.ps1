<#
.SYNOPSIS
    Keil MDK build + COM port serial read-only acquisition script.
.DESCRIPTION
    1) Locates UV4.exe (Keil MDK) and builds the specified project with -b (build only, no flash).
    2) Opens the target COM port at the given baud rate, DtrEnable/RtsEnable both OFF,
       reads incoming bytes for the specified duration, and writes them to a raw text file.
    3) Does NOT flash firmware, write to serial, kill processes, or install dependencies.
.NOTES
    Designed for FOMS_V1.0 firmware validation pipeline.
    Boss constraints: no flashing, no firmware modification, no PID tuning, no VOFA dependency.
#>

param(
    [Parameter(Mandatory=$false, HelpMessage="Full path to .uvprojx or .uvproj Keil project file")]
    [string]$ProjectPath = "",

    [Parameter(Mandatory=$false, HelpMessage="COM port name (e.g. COM13)")]
    [string]$COMPort = "COM13",

    [Parameter(Mandatory=$false, HelpMessage="Baud rate (default 576000)")]
    [int]$BaudRate = 576000,

    [Parameter(Mandatory=$false, HelpMessage="Duration in seconds to read from serial port")]
    [int]$ReadDurationSeconds = 10,

    [Parameter(Mandatory=$false, HelpMessage="Path to write build log")]
    [string]$BuildLogPath = "build_log.txt",

    [Parameter(Mandatory=$false, HelpMessage="Path to write raw serial data")]
    [string]$SerialRawPath = "serial_raw.txt"
)

# ============================================================================
# Configuration defaults
# ============================================================================
$ErrorActionPreference = "Continue"
$script:BuildSuccess = $false
$script:SerialSuccess = $false
$script:SerialBytesRead = 0
$script:SerialError = ""

# Common Keil UV4 installation paths (ordered by likelihood)
$UV4SearchPaths = @(
    "C:\Keil_v5\UV4\UV4.exe",
    "C:\Keil\UV4\UV4.exe",
    "C:\Keil_v5\UV4\UV4.com",
    "${env:ProgramFiles}\Keil\UV4\UV4.exe",
    "${env:ProgramFiles(x86)}\Keil\UV4\UV4.exe"
)

# ============================================================================
# Helper functions
# ============================================================================

function Write-Log {
    param([string]$Message, [string]$Color = "White")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    $line = "[$timestamp] $Message"
    Write-Host $line -ForegroundColor $Color
    Add-Content -Path $BuildLogPath -Value $line -ErrorAction SilentlyContinue
}

function Find-UV4 {
    <#
    .SYNOPSIS
        Locates UV4.exe by checking known install paths and PATH.
    #>
    # Check known paths first
    foreach ($p in $UV4SearchPaths) {
        $expanded = [Environment]::ExpandEnvironmentVariables($p)
        if (Test-Path $expanded -PathType Leaf) {
            Write-Log "Found UV4 at: $expanded" "Green"
            return $expanded
        }
    }

    # Fallback: search PATH
    $fromPath = (Get-Command "UV4.exe" -ErrorAction SilentlyContinue)
    if ($fromPath) {
        Write-Log "Found UV4 via PATH: $($fromPath.Source)" "Green"
        return $fromPath.Source
    }

    # Fallback: search for uv4.com (console version)
    foreach ($p in $UV4SearchPaths -replace "UV4.exe","UV4.com") {
        $expanded = [Environment]::ExpandEnvironmentVariables($p)
        if (Test-Path $expanded -PathType Leaf) {
            Write-Log "Found UV4.com at: $expanded" "Green"
            return $expanded
        }
    }

    $fromPathCom = (Get-Command "UV4.com" -ErrorAction SilentlyContinue)
    if ($fromPathCom) {
        Write-Log "Found UV4.com via PATH: $($fromPathCom.Source)" "Green"
        return $fromPathCom.Source
    }

    return $null
}

function Find-ProjectFile {
    <#
    .SYNOPSIS
        If no explicit ProjectPath is given, searches the current directory
        and one level up for .uvprojx / .uvproj files.
    #>
    param([string]$HintPath)

    if ($HintPath -and (Test-Path $HintPath -PathType Leaf)) {
        return (Resolve-Path $HintPath).Path
    }

    # Search current directory
    $candidates = @(Get-ChildItem -Path "." -Filter "*.uvprojx" -ErrorAction SilentlyContinue) +
                  @(Get-ChildItem -Path "." -Filter "*.uvproj"  -ErrorAction SilentlyContinue) +
                  @(Get-ChildItem -Path ".." -Filter "*.uvprojx" -ErrorAction SilentlyContinue) +
                  @(Get-ChildItem -Path ".." -Filter "*.uvproj"  -ErrorAction SilentlyContinue)

    if ($candidates.Count -gt 0) {
        $chosen = $candidates[0].FullName
        Write-Log "Auto-detected project file: $chosen" "Cyan"
        return $chosen
    }

    return $null
}

# ============================================================================
# Phase 1: Keil Build
# ============================================================================

Write-Log "========== Phase 1: Keil Build ==========" "Yellow"

# 1a. Locate UV4
$UV4Path = Find-UV4
if (-not $UV4Path) {
    Write-Log "ERROR: Cannot locate UV4.exe. Checked paths: $($UV4SearchPaths -join ', ')" "Red"
    Write-Log "BUILD_RESULT: UV4_NOT_FOUND" "Red"
    # Continue execution — serial read may still be possible with existing firmware
}

# 1b. Locate project file
$ProjectFile = Find-ProjectFile -HintPath $ProjectPath
if (-not $ProjectFile) {
    Write-Log "ERROR: No Keil project file found (.uvprojx or .uvproj). Searched current dir and parent dir." "Red"
    Write-Log "BUILD_RESULT: PROJECT_NOT_FOUND" "Red"
}

# 1c. Execute build (if both UV4 and project are found)
$BuildErrorCount = -1
$BuildWarningCount = -1

if ($UV4Path -and $ProjectFile) {
    $ProjectDir = Split-Path $ProjectFile -Parent
    $ProjectName = [System.IO.Path]::GetFileNameWithoutExtension($ProjectFile)

    Write-Log "UV4 executable : $UV4Path" "Cyan"
    Write-Log "Project file   : $ProjectFile" "Cyan"
    Write-Log "Project dir    : $ProjectDir" "Cyan"
    Write-Log "Starting build with: `"$UV4Path`" -b `"$ProjectFile`" -o `"$BuildLogPath`"" "Cyan"

    # Build: -b = build only (NO -f = flash), -o = output file
    # The build log from UV4 goes to the -o file; stdout/stderr are minimal
    $buildArgs = @(
        "-b",                                           # Build only, no flash
        "`"$ProjectFile`"",
        "-o", "`"$BuildLogPath`""
    )

    try {
        $buildProc = Start-Process -FilePath $UV4Path `
            -ArgumentList $buildArgs `
            -Wait -NoNewWindow `
            -RedirectStandardOutput "build_stdout.tmp" `
            -RedirectStandardError "build_stderr.tmp" `
            -PassThru

        $BuildExitCode = $buildProc.ExitCode
        Write-Log "UV4 exit code: $BuildExitCode" "Cyan"

        # Parse build log for error/warning counts
        # Keil UV4 build log format:
        #   "... 0 Error(s), 0 Warning(s)."
        #   "... N Error(s), M Warning(s)."
        if (Test-Path $BuildLogPath) {
            $buildContent = Get-Content $BuildLogPath -Raw -ErrorAction SilentlyContinue

            # Extract error count
            if ($buildContent -match '(\d+)\s+Error\(s\)') {
                $BuildErrorCount = [int]$Matches[1]
            }
            # Extract warning count
            if ($buildContent -match '(\d+)\s+Warning\(s\)') {
                $BuildWarningCount = [int]$Matches[1]
            }

            if ($BuildErrorCount -eq 0 -and $BuildWarningCount -eq 0) {
                $script:BuildSuccess = $true
                Write-Log "BUILD_RESULT: SUCCESS (0 Error(s), 0 Warning(s))" "Green"
            } elseif ($BuildErrorCount -eq 0) {
                Write-Log "BUILD_RESULT: WARNINGS_PRESENT ($BuildErrorCount Error(s), $BuildWarningCount Warning(s))" "Yellow"
            } else {
                Write-Log "BUILD_RESULT: FAILED ($BuildErrorCount Error(s), $BuildWarningCount Warning(s))" "Red"
            }
        } else {
            Write-Log "WARNING: Build log file not found at $BuildLogPath" "Yellow"
            Write-Log "BUILD_RESULT: UNKNOWN (log missing)" "Yellow"
        }
    } catch {
        Write-Log "ERROR during build: $_" "Red"
        Write-Log "BUILD_RESULT: EXCEPTION" "Red"
    }

    # Append stdout/stderr to build log
    if (Test-Path "build_stdout.tmp") {
        $stdout = Get-Content "build_stdout.tmp" -Raw
        Add-Content -Path $BuildLogPath -Value "`n=== UV4 stdout ==="
        Add-Content -Path $BuildLogPath -Value $stdout
        Remove-Item "build_stdout.tmp" -ErrorAction SilentlyContinue
    }
    if (Test-Path "build_stderr.tmp") {
        $stderr = Get-Content "build_stderr.tmp" -Raw
        Add-Content -Path $BuildLogPath -Value "`n=== UV4 stderr ==="
        Add-Content -Path $BuildLogPath -Value $stderr
        Remove-Item "build_stderr.tmp" -ErrorAction SilentlyContinue
    }
} else {
    Write-Log "BUILD_RESULT: SKIPPED (UV4 or project not found)" "Yellow"
}

# Persist build metadata to build log for downstream parsing
Add-Content -Path $BuildLogPath -Value ""
Add-Content -Path $BuildLogPath -Value "=== BUILD SUMMARY ==="
Add-Content -Path $BuildLogPath -Value "build_success: $($script:BuildSuccess)"
Add-Content -Path $BuildLogPath -Value "error_count: $BuildErrorCount"
Add-Content -Path $BuildLogPath -Value "warning_count: $BuildWarningCount"

# ============================================================================
# Phase 2: COM Port Serial Read
# ============================================================================

Write-Log "========== Phase 2: COM Port Serial Read ($COMPort @ $BaudRate baud) ==========" "Yellow"

# Clean the target serial raw file
if (Test-Path $SerialRawPath) {
    Remove-Item $SerialRawPath -Force -ErrorAction SilentlyContinue
}
New-Item -Path $SerialRawPath -ItemType File -Force | Out-Null

$serialPort = $null
$serialStream = $null
$serialReader = $null

try {
    # Check if the port name looks valid
    if ($COMPort -notmatch '^COM\d+$') {
        throw "Invalid COM port name: '$COMPort'. Expected format: COM<n>"
    }

    Write-Log "Creating SerialPort object: PortName=$COMPort, BaudRate=$BaudRate" "Cyan"

    # Create SerialPort with DtrEnable and RtsEnable BOTH set to $false
    # This ensures we are a passive listener — no hardware flow control assertion
    $serialPort = New-Object System.IO.Ports.SerialPort
    $serialPort.PortName     = $COMPort
    $serialPort.BaudRate     = $BaudRate
    $serialPort.Parity       = [System.IO.Ports.Parity]::None
    $serialPort.DataBits     = 8
    $serialPort.StopBits     = [System.IO.Ports.StopBits]::One
    $serialPort.ReadTimeout  = 1000       # 1 second read timeout
    $serialPort.WriteTimeout = 1000
    $serialPort.DtrEnable    = $false     # Line 271: DtrEnable OFF
    $serialPort.RtsEnable    = $false     # Line 272: RtsEnable OFF
    $serialPort.NewLine      = "`n"
    $serialPort.Encoding     = [System.Text.Encoding]::ASCII

    Write-Log "SerialPort configured: DtrEnable=$($serialPort.DtrEnable), RtsEnable=$($serialPort.RtsEnable)" "Cyan"

    # Open the port
    Write-Log "Opening $COMPort ..." "Cyan"
    $serialPort.Open()
    Write-Log "$COMPort opened successfully." "Green"

    # Discard any stale data in the input buffer before starting timed read
    $serialPort.DiscardInBuffer()
    Write-Log "Input buffer discarded. Starting $ReadDurationSeconds second read window..." "Cyan"

    # Create a FileStream for efficient bulk writing
    $serialRawWriter = [System.IO.StreamWriter]::new($SerialRawPath, $false, [System.Text.Encoding]::ASCII)

    $startTime = Get-Date
    $endTime = $startTime.AddSeconds($ReadDurationSeconds)
    $totalBytes = 0
    $lastReportTime = $startTime
    $timeoutCount = 0

    # Read loop: read all available bytes every ~50ms until the duration elapses
    while ((Get-Date) -lt $endTime) {
        try {
            $bytesToRead = $serialPort.BytesToRead
            if ($bytesToRead -gt 0) {
                $buffer = New-Object byte[] $bytesToRead
                $bytesRead = $serialPort.Read($buffer, 0, $bytesToRead)

                if ($bytesRead -gt 0) {
                    # Write raw bytes to file (as ASCII text with line endings preserved)
                    $text = [System.Text.Encoding]::ASCII.GetString($buffer, 0, $bytesRead)
                    $serialRawWriter.Write($text)
                    $totalBytes += $bytesRead
                    $timeoutCount = 0
                }
            } else {
                $timeoutCount++
                Start-Sleep -Milliseconds 50
            }
        } catch [System.TimeoutException] {
            # Read timeout on empty buffer — normal, just continue
            $timeoutCount++
            Start-Sleep -Milliseconds 10
        }

        # Periodic status report every 2 seconds
        $now = Get-Date
        if (($now - $lastReportTime).TotalSeconds -ge 2) {
            $elapsed = ($now - $startTime).TotalSeconds
            Write-Log "  ... ${elapsed:F1}s elapsed, $totalBytes bytes read so far" "DarkGray"
            $lastReportTime = $now
        }
    }

    $serialRawWriter.Flush()
    $serialRawWriter.Close()
    $serialRawWriter.Dispose()

    $elapsed = ((Get-Date) - $startTime).TotalSeconds
    $script:SerialBytesRead = $totalBytes
    $script:SerialSuccess = $true

    Write-Log "Serial read complete: $totalBytes bytes in ${elapsed:F1} seconds." "Green"
    Write-Log "SERIAL_RESULT: SUCCESS ($totalBytes bytes read)" "Green"

} catch [System.UnauthorizedAccessException] {
    # CRITICAL: Do NOT kill any process. Log and exit gracefully.
    $script:SerialError = "UnauthorizedAccessException: $($_.Exception.Message)"
    Write-Log "SERIAL_RESULT: ACCESS_DENIED — $script:SerialError" "Red"
    Write-Log "Port $COMPort is in use by another process. Per E003 constraint, not killing any process." "Yellow"
    # exit 0 per spec — do NOT throw, do NOT kill
    $script:SerialSuccess = $false

} catch [System.IO.IOException] {
    $script:SerialError = "IOException: $($_.Exception.Message)"
    Write-Log "SERIAL_RESULT: IO_ERROR — $script:SerialError" "Red"
    $script:SerialSuccess = $false

} catch {
    $script:SerialError = "$($_.Exception.GetType().Name): $($_.Exception.Message)"
    Write-Log "SERIAL_RESULT: ERROR — $script:SerialError" "Red"
    $script:SerialSuccess = $false

} finally {
    # Cleanup: close reader, stream, and port unconditionally
    if ($serialRawWriter) {
        try { $serialRawWriter.Dispose() } catch {}
    }
    if ($serialReader) {
        try { $serialReader.Close(); $serialReader.Dispose() } catch {}
    }
    if ($serialStream) {
        try { $serialStream.Close(); $serialStream.Dispose() } catch {}
    }
    if ($serialPort -and $serialPort.IsOpen) {
        try {
            $serialPort.DiscardInBuffer()
            $serialPort.Close()
            Write-Log "$COMPort closed." "Cyan"
        } catch {
            Write-Log "Warning: Error closing $COMPort : $_" "DarkYellow"
        }
    }
    if ($serialPort) {
        try { $serialPort.Dispose() } catch {}
    }
}

# ============================================================================
# Persist metadata to serial_raw.txt header
# ============================================================================
if (Test-Path $SerialRawPath) {
    $existingContent = Get-Content $SerialRawPath -Raw -ErrorAction SilentlyContinue
    $header = @"
=== SERIAL ACQUISITION METADATA ===
com_port: $COMPort
baud_rate: $BaudRate
success: $($script:SerialSuccess)
bytes_read: $($script:SerialBytesRead)
error: $($script:SerialError)
dtr_enabled: false
rts_enabled: false
timestamp_utc: $(Get-Date -Format "yyyy-MM-ddTHH:mm:ss.fffZ")
=== RAW DATA BELOW ===

"@
    Set-Content -Path $SerialRawPath -Value ($header + $existingContent)
}

# ============================================================================
# Final summary
# ============================================================================
Write-Log "" "White"
Write-Log "========== FINAL SUMMARY ==========" "Yellow"
Write-Log "Build Success  : $($script:BuildSuccess) (errors=$BuildErrorCount, warnings=$BuildWarningCount)" "White"
Write-Log "Serial Success : $($script:SerialSuccess) (bytes=$($script:SerialBytesRead))" "White"
Write-Log "Output Files   : $BuildLogPath, $SerialRawPath" "White"

# Exit 0 to not break the pipeline — downstream scripts decide based on output files
exit 0
