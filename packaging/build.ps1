<#
.SYNOPSIS
    Build TruyenFull Processor desktop app (.exe) end-to-end.

.DESCRIPTION
    Chạy tuần tự: build frontend -> đóng gói PyInstaller -> self-test -> tạo Setup.exe.
    Dùng cho cả vòng lặp dev (nhanh) lẫn đóng gói bản phát hành.

.PARAMETER Fast
    Bỏ qua bước tạo Setup.exe (iscc). Dùng khi chỉ cần test app trong dist/.

.PARAMETER DevInstaller
    Khi tạo Setup.exe, dùng installer-dev.iss (nén nhanh) thay cho installer.iss.
    Bỏ qua nếu đã bật -Fast.

.PARAMETER SkipFrontend
    Bỏ qua "npm run build" (khi frontend/dist đã mới, chỉ đổi code Python).

.PARAMETER SkipSelftest
    Bỏ qua bước --selftest.

.EXAMPLE
    # Vòng lặp dev nhanh nhất: chỉ đổi code Python, không cần Setup.exe
    .\packaging\build.ps1 -Fast -SkipFrontend

.EXAMPLE
    # Đóng gói bản phát hành đầy đủ
    .\packaging\build.ps1
#>
[CmdletBinding()]
param(
    [switch]$Fast,
    [switch]$DevInstaller,
    [switch]$SkipFrontend,
    [switch]$SkipSelftest
)

$ErrorActionPreference = "Stop"

# Repo root = thư mục cha của packaging/ (nơi chứa script này).
$Repo    = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Repo "backend"
$Venv    = Join-Path $Backend "venv\Scripts"
$ExePath = Join-Path $Repo "dist\TruyenFullProcessor\TruyenFullProcessor.exe"

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

$sw = [System.Diagnostics.Stopwatch]::StartNew()

# --- 1. Frontend --------------------------------------------------------
if (-not $SkipFrontend) {
    Step "1/4 Build frontend (vite)"
    Push-Location (Join-Path $Repo "frontend")
    try {
        if (-not (Test-Path "node_modules")) { & npm install; if ($LASTEXITCODE) { throw "npm install failed" } }
        & npm run build
        if ($LASTEXITCODE) { throw "npm run build failed" }
    } finally { Pop-Location }
} else {
    Step "1/4 Frontend — BỎ QUA (-SkipFrontend)"
}

# --- 2. PyInstaller -----------------------------------------------------
# Bản dist cũ có thể đang bị khoá bởi app đang chạy -> tắt trước khi ghi đè,
# nếu không PyInstaller sẽ chết với PermissionError [WinError 5].
$running = Get-Process TruyenFullProcessor -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "  App đang chạy (PID $($running.Id)) — tắt để ghi đè dist/..." -ForegroundColor Yellow
    $running | Stop-Process -Force
    Start-Sleep -Milliseconds 800
}

Step "2/4 Đóng gói PyInstaller (bản FULL: VBEE + OmniVoice)"
& (Join-Path $Venv "pyinstaller.exe") (Join-Path $PSScriptRoot "truyenfull.spec") `
    --noconfirm --distpath (Join-Path $Repo "dist") --workpath (Join-Path $Repo "build")
if ($LASTEXITCODE) { throw "PyInstaller failed" }

# --- 3. Self-test -------------------------------------------------------
if (-not $SkipSelftest) {
    Step "3/4 Self-test bản đóng gói"
    & $ExePath --selftest
    if ($LASTEXITCODE) { throw "SELFTEST FAILED (exit $LASTEXITCODE) — xem %LOCALAPPDATA%\TruyenFullProcessor\selftest_result.txt" }
    Write-Host "SELFTEST OK" -ForegroundColor Green
} else {
    Step "3/4 Self-test — BỎ QUA (-SkipSelftest)"
}

# --- 4. Installer -------------------------------------------------------
if ($Fast) {
    Step "4/4 Installer — BỎ QUA (-Fast). Chạy thử app tại:"
    Write-Host "  $ExePath" -ForegroundColor Yellow
} else {
    $iss = if ($DevInstaller) { "installer-dev.iss" } else { "installer.iss" }
    Step "4/4 Tạo Setup.exe ($iss)"
    $iscc = Get-Command iscc -ErrorAction SilentlyContinue
    if (-not $iscc) { throw "Không tìm thấy 'iscc'. Cài Inno Setup 6 hoặc thêm vào PATH." }
    & iscc (Join-Path $PSScriptRoot $iss)
    if ($LASTEXITCODE) { throw "iscc failed" }
}

$sw.Stop()
Write-Host ("`nHOÀN TẤT trong {0:mm\:ss}" -f $sw.Elapsed) -ForegroundColor Green
