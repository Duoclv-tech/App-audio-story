<#
.SYNOPSIS
    Build AudioStory desktop app (.exe) end-to-end.

.DESCRIPTION
    Chạy tuần tự: build frontend -> đóng gói PyInstaller -> self-test -> tạo Setup.exe.
    Dùng cho cả vòng lặp dev (nhanh) lẫn đóng gói bản phát hành.

.PARAMETER Mode
    product (mặc định): bản phát hành — DB ship kèm CHỈ có reference data
        (từ kiểm duyệt + prompt), KHÔNG có truyện test.
    fulldev: ship TOÀN BỘ data test (app.db đầy đủ + thư mục storage audio/video)
        để bản cài mới lên là có sẵn mọi truyện bạn đã tạo.

.PARAMETER SeedSource
    DB nguồn để tạo seed (mặc định: %LOCALAPPDATA%\AudioStory\app.db —
    chính là DB của bản .exe đang dùng).

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
    # Đóng gói bản phát hành (product): không kèm truyện test
    .\packaging\build.ps1

.EXAMPLE
    # Bản full dev: kèm toàn bộ truyện + audio/video đã test
    .\packaging\build.ps1 -Mode fulldev
#>
[CmdletBinding()]
param(
    # product  = release build: shipped DB has ONLY reference data (banned words
    #            + prompts), no stories. (default)
    # fulldev  = ship your full test DB + storage (audio/video) so a fresh
    #            install comes up with all your test data.
    [ValidateSet("product", "fulldev")]
    [string]$Mode = "product",
    # Source DB to build the seed from. Default = the packaged app's live DB.
    [string]$SeedSource = "$env:LOCALAPPDATA\AudioStory\app.db",
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
$ExePath = Join-Path $Repo "dist\AudioStory\AudioStory.exe"

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

# --- 1b. Chuẩn bị seed data (theo -Mode) --------------------------------
# product : default_seed.db chỉ giữ reference (từ kiểm duyệt + prompt), no story.
# fulldev : default_seed.db giữ TẤT CẢ + bundle storage/ để media dùng được.
Step "Chuẩn bị seed data (mode: $Mode)"
$env:SEED_STORAGE_DIR = ""   # mặc định KHÔNG kèm media (product)
$Python = Join-Path $Venv "python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }   # fallback: PATH
if ($Mode -eq "fulldev") {
    if (-not (Test-Path $SeedSource)) {
        throw "fulldev cần DB nguồn nhưng không thấy: $SeedSource (mở app tạo data trước, hoặc truyền -SeedSource)."
    }
    & $Python (Join-Path $PSScriptRoot "make_seed_db.py") --full $SeedSource
    if ($LASTEXITCODE) { throw "make_seed_db.py --full failed" }
    $storageDir = Join-Path (Split-Path -Parent $SeedSource) "storage"
    if (Test-Path $storageDir) {
        $env:SEED_STORAGE_DIR = $storageDir
        Write-Host "  Kèm storage: $storageDir" -ForegroundColor Yellow
    } else {
        Write-Host "  (Không thấy storage tại $storageDir — chỉ bundle DB)" -ForegroundColor Yellow
    }
} else {
    if (Test-Path $SeedSource) {
        & $Python (Join-Path $PSScriptRoot "make_seed_db.py") $SeedSource
        if ($LASTEXITCODE) { throw "make_seed_db.py failed" }
    } else {
        Write-Host "  (Không thấy DB nguồn $SeedSource — giữ nguyên default_seed.db hiện có)" -ForegroundColor Yellow
    }
}

# --- 2. PyInstaller -----------------------------------------------------
# Bản dist cũ có thể đang bị khoá bởi app đang chạy -> tắt trước khi ghi đè,
# nếu không PyInstaller sẽ chết với PermissionError [WinError 5].
$running = Get-Process AudioStory -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "  App đang chạy (PID $($running.Id)) — tắt để ghi đè dist/..." -ForegroundColor Yellow
    $running | Stop-Process -Force
    Start-Sleep -Milliseconds 800
}

Step "2/4 Đóng gói PyInstaller (bản FULL: VBEE + AI Voice local)"
& (Join-Path $Venv "pyinstaller.exe") (Join-Path $PSScriptRoot "audiostory.spec") `
    --noconfirm --distpath (Join-Path $Repo "dist") --workpath (Join-Path $Repo "build")
if ($LASTEXITCODE) { throw "PyInstaller failed" }

# --- 3. Self-test -------------------------------------------------------
if (-not $SkipSelftest) {
    Step "3/4 Self-test bản đóng gói"
    & $ExePath --selftest
    if ($LASTEXITCODE) { throw "SELFTEST FAILED (exit $LASTEXITCODE) — xem %LOCALAPPDATA%\AudioStory\selftest_result.txt" }
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
    # Tìm iscc: PATH trước, rồi các vị trí cài phổ biến (kể cả bản per-user trong
    # %LOCALAPPDATA%\Programs — winget hay cài vào đó nên không nằm trên PATH).
    $isccCmd = (Get-Command iscc -ErrorAction SilentlyContinue).Source
    if (-not $isccCmd) {
        $candidates = @(
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        )
        $isccCmd = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if (-not $isccCmd) { throw "Không tìm thấy 'iscc'. Cài Inno Setup 6 hoặc thêm vào PATH." }
    Write-Host "  iscc: $isccCmd" -ForegroundColor DarkGray
    & $isccCmd (Join-Path $PSScriptRoot $iss)
    if ($LASTEXITCODE) { throw "iscc failed" }
}

$sw.Stop()
Write-Host ("`nHOÀN TẤT trong {0:mm\:ss}" -f $sw.Elapsed) -ForegroundColor Green
