# WebChat 云上自动化 - Windows 守护进程一键安装（在 Win 主机 RDP 内以管理员 PowerShell 运行）
#
# 用法（管理员 PowerShell）：
#   $params = '-BackendUrl "http://10.60.84.46" -WebhookSecret "WHK_xxx" -ServicePassword "GeoEval2026"'
#   & ([scriptblock]::Create((irm "https://raw.githubusercontent.com/lious68/general-geo-eval/feat/webchat-cloud-automation/scripts/win_setup.ps1"))) -BackendUrl "http://10.60.84.46" -WebhookSecret "WHK_xxx" -ServicePassword "GeoEval2026"
#
# 幂等：可重复运行。无 git/无 winget 依赖，全部直接下载。
#  - 下载 feat 分支 zip 到 C:\general-geo-eval
#  - 装 Python 3.11（若无）+ 项目依赖 + playwright chromium
#  - 写 scripts\win_daemon.env
#  - 装 NSSM，注册并启动 WinDaemon 服务
#  - 自检 http://localhost:8443/status

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BackendUrl,
    [Parameter(Mandatory=$true)][string]$WebhookSecret,
    [Parameter(Mandatory=$true)][string]$ServicePassword,
    [string]$ServiceUser = "admin",
    [string]$InstallDir  = "C:\general-geo-eval",
    [string]$Branch      = "feat/webchat-cloud-automation",
    [int]   $Port        = 8443
)

$ErrorActionPreference = "Stop"
function Step($m){ Write-Host "`n==== $m ====" -ForegroundColor Cyan }
function Log($m){ Write-Host $m }

Step "0. 管理员检查"
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "请用【管理员】身份运行 PowerShell（开始菜单右键 PowerShell -> 以管理员身份运行）" }
Log "管理员 OK"

Step "1. 下载/更新代码（feat 分支 zip）"
if (Test-Path "$InstallDir\.git") {
    Log "已有 git 目录，跳过下载（如需更新请自行 git pull）"
} else {
    $tmpZip = "$env:TEMP\geo-eval.zip"
    $url = "https://github.com/lious68/general-geo-eval/archive/refs/heads/$Branch.zip"
    Log "下载 $url"
    Invoke-WebRequest -Uri $url -OutFile $tmpZip -UseBasicParsing
    $extractTo = "$env:TEMP\geo-eval-extract"
    if (Test-Path $extractTo) { Remove-Item $extractTo -Recurse -Force }
    Expand-Archive -Path $tmpZip -DestinationPath $extractTo -Force
    $inner = Get-ChildItem $extractTo -Directory | Select-Object -First 1
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
    Move-Item $inner.FullName $InstallDir
    Remove-Item $tmpZip -Force; Remove-Item $extractTo -Recurse -Force
}
Log "代码目录: $InstallDir"
if (-not (Test-Path "$InstallDir\scripts\win_daemon.py")) { throw "未找到 scripts\win_daemon.py，代码下载可能不完整" }

Step "2. Python 3.11"
function Get-Py {
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $c = Get-Command py -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}
$py = Get-Py
if (-not $py) {
    Log "未检测到 Python，下载安装 3.11 ..."
    $installer = "$env:TEMP\python311.exe"
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $installer -UseBasicParsing
    Start-Process -FilePath $installer -ArgumentList '/quiet','InstallAllUsers=1','PrependPath=1','Include_pip=1' -Wait
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    $py = Get-Py
}
if (-not $py) { throw "Python 安装后仍不可用，请检查" }
Log "Python: $py"
# 确保 pip
& $py -m ensurepip --upgrade 2>$null | Out-Null
& $py -m pip install --upgrade pip -q

Step "3. 安装项目依赖"
$reqWin = "$InstallDir\scripts\win_requirements.txt"
if (Test-Path $reqWin) { & $py -m pip install -r $reqWin -q }
# 守护进程 + runner + 分析器需要的完整依赖（与 Linux 后端对齐）
& $py -m pip install -q fastapi uvicorn aiosqlite python-dotenv openai snownlp pandas openpyxl numpy playwright httpx aiohttp python-multipart 2>&1 | Select-Object -Last 3
Log "依赖安装完成"

Step "4. Playwright Chromium"
& $py -m playwright install chromium 2>&1 | Select-Object -Last 3
Log "chromium OK"

Step "5. 写 win_daemon.env"
$envFile = "$InstallDir\scripts\win_daemon.env"
$envContent = @"
BACKEND_URL=$BackendUrl
SERVICE_USER=$ServiceUser
SERVICE_PASSWORD=$ServicePassword
WEBHOOK_SECRET=$WebhookSecret
"@
Set-Content -Path $envFile -Value $envContent -Encoding UTF8
Log "已写 $envFile"

Step "6. 创建数据/输出目录"
New-Item -ItemType Directory -Force -Path "$InstallDir\data\webchat_auth" | Out-Null
New-Item -ItemType Directory -Force -Path "$InstallDir\output" | Out-Null

Step "7. NSSM"
$nssmDir = "C:\nssm"
$nssmExe = "$nssmDir\nssm.exe"
if (-not (Test-Path $nssmExe)) {
    New-Item -ItemType Directory -Force -Path $nssmDir | Out-Null
    $nssmZip = "$env:TEMP\nssm.zip"
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $nssmZip -UseBasicParsing
    $nssmExtract = "$env:TEMP\nssm-extract"
    if (Test-Path $nssmExtract) { Remove-Item $nssmExtract -Recurse -Force }
    Expand-Archive -Path $nssmZip -DestinationPath $nssmExtract -Force
    $exe = Get-ChildItem $nssmExtract -Recurse -Filter "nssm.exe" | Where-Object { $_.FullName -match "win64" } | Select-Object -First 1
    if (-not $exe) { $exe = Get-ChildItem $nssmExtract -Recurse -Filter "nssm.exe" | Select-Object -First 1 }
    Copy-Item $exe.FullName $nssmExe -Force
    Remove-Item $nssmZip -Force; Remove-Item $nssmExtract -Recurse -Force
}
$env:Path = "$nssmDir;$env:Path"
Log "nssm: $nssmExe"

Step "8. 注册并启动 WinDaemon 服务"
$svc = "WinDaemon"
$daemon = "$InstallDir\scripts\win_daemon.py"
# 如已存在先移除
& $nssmExe stop $svc 2>$null | Out-Null
& $nssmExe remove $svc confirm 2>$null | Out-Null
& $nssmExe install $svc $py $daemon
& $nssmExe set $svc AppDirectory "$InstallDir"
& $nssmExe set $svc AppEnvironmentExtra "PYTHONUNBUFFERED=1"
& $nssmExe set $svc Start SERVICE_AUTO_START
& $nssmExe set $svc AppStdout "$InstallDir\output\win_daemon.log"
& $nssmExe set $svc AppStderr "$InstallDir\output\win_daemon.log"
& $nssmExe start $svc
Start-Sleep -Seconds 3
$st = & $nssmExe status $svc
Log "服务状态: $st"

Step "9. 自检"
Start-Sleep -Seconds 2
try {
    $r = Invoke-WebRequest -Uri "http://localhost:$Port/status" -UseBasicParsing -TimeoutSec 8
    Log "自检 /status: HTTP $($r.StatusCode) -> $($r.Content)"
} catch {
    Log "自检失败（服务可能仍在启动）: $($_.Exception.Message)"
    Log "查看日志: $InstallDir\output\win_daemon.log"
}

Step "完成"
Write-Host "`n✅ Win 守护进程安装完成。" -ForegroundColor Green
Write-Host "   代码目录 : $InstallDir"
Write-Host "   服务名   : $svc （开机自启）"
Write-Host "   确认页    : http://localhost:$Port （RDP 内浏览器打开，跑批次时点[开始]）"
Write-Host "   日志      : $InstallDir\output\win_daemon.log"
Write-Host "   后续      : 还需完成 5 个模型首次登录（见 runbook）"
