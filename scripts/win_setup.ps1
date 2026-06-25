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
function Test-RealPy($p) {
    if (-not $p) { return $false }
    if ($p -match "WindowsApps") { return $false }   # 跳过 Windows 商店 stub
    if (-not (Test-Path $p)) { return $false }
    try { $v = & $p --version 2>&1 } catch { return $false }
    if ($v -notmatch "Python 3\.") { return $false }
    return $true
}
function Get-Py {
    $c = Get-Command python.exe -ErrorAction SilentlyContinue
    if (Test-RealPy $c.Source) { return $c.Source }
    $c = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($c) { try { $p = (& $c.Source -c "import sys;print(sys.executable)" 2>$null).Trim(); if (Test-RealPy $p) { return $p } } catch {} }
    foreach ($p in @("C:\Program Files\Python311\python.exe","C:\Program Files\Python312\python.exe","C:\Program Files\Python310\python.exe")) { if (Test-RealPy $p) { return $p } }
    return $null
}
$py = Get-Py
if (-not $py) {
    Log "未检测到真实 Python（WindowsApps stub 不算），下载安装 3.11 ..."
    $installer = "$env:TEMP\python311.exe"
    # 国内镜像优先（npmmirror），python.org 兜底
    $pyUrls = @(
        "https://registry.npmmirror.com/-/binary/python/3.11.9/python-3.11.9-amd64.exe",
        "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    )
    $dl = $false
    foreach ($u in $pyUrls) { try { Invoke-WebRequest -Uri $u -OutFile $installer -UseBasicParsing; $dl = $true; break } catch { Log "下载失败 $u : $($_.Exception.Message)" } }
    if (-not $dl) { throw "Python 安装包下载失败" }
    Start-Process -FilePath $installer -ArgumentList '/quiet','InstallAllUsers=1','PrependPath=1','Include_pip=1' -Wait
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    $py = "C:\Program Files\Python311\python.exe"
    if (-not (Test-RealPy $py)) { throw "Python 3.11 安装后仍不可用: $py" }
}
Log "Python: $py"
& $py --version
if (-not $py) { throw "Python 安装后仍不可用，请检查" }
Log "Python: $py"
# 国内 pip 镜像（乌兰察布到 pypi 官方源 SSL 不稳）
$PipIndex = "https://pypi.tuna.tsinghua.edu.cn/simple"
& $py -m pip config set global.index-url $PipIndex 2>$null | Out-Null
& $py -m pip install --upgrade pip -q -i $PipIndex

Step "3. 安装项目依赖"
$reqWin = "$InstallDir\scripts\win_requirements.txt"
if (Test-Path $reqWin) { & $py -m pip install -r $reqWin -q -i $PipIndex }
# 守护进程 + runner + 分析器需要的完整依赖（与 Linux 后端对齐）
& $py -m pip install -q -i $PipIndex fastapi uvicorn aiosqlite python-dotenv openai snownlp pandas openpyxl numpy playwright httpx aiohttp python-multipart 2>&1 | Select-Object -Last 5
Log "依赖安装完成"

Step "4. Playwright Chromium"
# chromium 走 npmmirror 镜像（官方 CDN 在墙内不稳）
$env:PLAYWRIGHT_DOWNLOAD_HOST = "https://cdn.npmmirror.com/binaries/playwright"
& $py -m playwright install chromium 2>&1 | Select-Object -Last 5
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

Step "7. 注册守护进程（任务计划-登录自启，交互会话）"
# ⚠️ 不用 NSSM 服务：Windows 服务跑在 session 0 无桌面，headed 浏览器/验证码看不见。
# 用任务计划「登录时触发」在 Administrator 交互会话里跑，浏览器才开在 RDP 桌面。
# 契合 decision-a「人在才跑」：RDP 进去它才起；不在时批次留 config_downloaded，下次登录 _bootstrap_pending 自动拉回。
$daemon = "$InstallDir\scripts\win_daemon.py"
$pyw = $py -replace "python\.exe$","pythonw.exe"
$exe  = if (Test-Path $pyw) { $pyw } else { $py }   # pythonw 无控制台窗口；没有则用 python
$action  = New-ScheduledTaskAction -Execute $exe -Argument "`"$daemon`"" -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "Administrator"
$settings= New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "WinDaemon" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Log "已注册任务计划 WinDaemon（登录自启，崩溃 1 分钟后自动重启）"

Step "8. 启动守护进程 + 自检"
Start-ScheduledTask -TaskName "WinDaemon"
Start-Sleep -Seconds 5
try {
    $r = Invoke-WebRequest -Uri "http://localhost:$Port/status" -UseBasicParsing -TimeoutSec 8
    Log "自检 /status: HTTP $($r.StatusCode) -> $($r.Content)"
} catch {
    Log "自检失败（进程可能仍在启动）: $($_.Exception.Message)"
    Log "查看日志: $InstallDir\output\win_daemon.log"
}

Step "完成"
Write-Host "`n✅ Win 守护进程安装完成。" -ForegroundColor Green
Write-Host "   代码目录 : $InstallDir"
Write-Host "   运行方式 : 任务计划 WinDaemon（Administrator 登录自启，非开机后台服务）"
Write-Host "   确认页    : http://localhost:$Port （RDP 内浏览器打开，跑批次时点[开始]）"
Write-Host "   日志      : 控制台窗口实时输出；异常看 $InstallDir\output\win_daemon.log"
Write-Host "   后续      : 还需完成 5 个模型首次登录（见 runbook）"
Write-Host "   手动管理 : Start-ScheduledTask WinDaemon / Stop-ScheduledTask WinDaemon / Get-ScheduledTask WinDaemon"
