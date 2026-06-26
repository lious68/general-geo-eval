# Win 守护进程注册脚本（仅注册任务计划 + 启动 + 自检，不重装依赖）
# 用法（管理员 PowerShell，一行）:
#   iex (irm "https://raw.githubusercontent.com/lious68/general-geo-eval/feat/webchat-cloud-automation/scripts/win_register.ps1")
#
# 契合 decision-a：登录自启（交互会话），headed 浏览器/验证码才开在 RDP 桌面可见。

$ErrorActionPreference = "Stop"
$InstallDir = "C:\general-geo-eval"
$Port = 8443

function Find-Python {
    # 1) PATH 上的 python / py（跳过 WindowsApps stub，验证 --version）
    $c = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($c -and $c.Source -notmatch "WindowsApps") { try { if ((& $c.Source --version 2>&1) -match "Python 3\.") { return $c.Source } } catch {} }
    $c = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($c) { try { $p = (& $c.Source -c "import sys;print(sys.executable)" 2>$null).Trim(); if ($p -and ($p -notmatch "WindowsApps") -and (Test-Path $p) -and ((& $p --version 2>&1) -match "Python 3\.")) { return $p } } catch {} }
    # 2) 常见安装路径
    $candidates = @(
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python310\python.exe",
        "C:\Program Files\Python39\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
    )
    foreach ($p in $candidates) { if (Test-Path $p) { try { if ((& $p --version 2>&1) -match "Python 3\.") { return $p } } catch {} } }
    return $null
}

Write-Host "==== 1. 定位 Python ====" -ForegroundColor Cyan
$py = Find-Python
if (-not $py) {
    Write-Host "未找到 Python！win_setup 的 Python 安装可能没成功。" -ForegroundColor Red
    Write-Host "请先跑 win_setup.ps1 装好 Python（或告诉我，我给装 Python 的命令）。" -ForegroundColor Yellow
    return
}
Write-Host "Python: $py" -ForegroundColor Green
& $py --version

Write-Host "`n==== 2. 检查代码与配置 ====" -ForegroundColor Cyan
$daemon = "$InstallDir\scripts\win_daemon.py"
if (-not (Test-Path $daemon)) { Write-Host "未找到 $daemon" -ForegroundColor Red; return }
$envFile = "$InstallDir\scripts\win_daemon.env"
if (-not (Test-Path $envFile)) { Write-Host "未找到 $envFile，请先跑 win_setup.ps1" -ForegroundColor Red; return }
Write-Host "守护进程: $daemon"
Write-Host "配置文件: $envFile"

Write-Host "`n==== 3. 先手动试跑一下（验证 import 不报错，5 秒后停）====" -ForegroundColor Cyan
$probe = Start-Process -FilePath $py -ArgumentList "`"$daemon`"" -WorkingDirectory $InstallDir -PassThru -WindowStyle Minimized
Start-Sleep -Seconds 5
$ok = $false
try { $r = Invoke-WebRequest "http://localhost:$Port/status" -UseBasicParsing -TimeoutSec 5; Write-Host "试跑 /status: HTTP $($r.StatusCode) -> $($r.Content)" -ForegroundColor Green; $ok = $true } catch { Write-Host "试跑 /status 失败: $($_.Exception.Message)" -ForegroundColor Yellow }
if ($probe -and -not $probe.HasExited) { Stop-Process -Id $probe.Id -Force -ErrorAction SilentlyContinue }
if (-not $ok) {
    Write-Host "守护进程试跑未起来。直接跑看报错：" -ForegroundColor Yellow
    & $py $daemon 2>&1 | Select-Object -First 30
    Write-Host "`n把上面报错贴给 Claude。" -ForegroundColor Yellow
    return
}

Write-Host "`n==== 4. 注册任务计划（登录自启）====" -ForegroundColor Cyan
$pyw = $py -replace "python\.exe$","pythonw.exe"
$exe = if (Test-Path $pyw) { $pyw } else { $py }
$action  = New-ScheduledTaskAction -Execute $exe -Argument "`"$daemon`"" -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "Administrator"
$settings= New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "WinDaemon" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "已注册任务计划 WinDaemon" -ForegroundColor Green

Write-Host "`n==== 5. 启动 + 自检 ====" -ForegroundColor Cyan
Start-ScheduledTask -TaskName "WinDaemon"
Start-Sleep -Seconds 5
try {
    $r = Invoke-WebRequest "http://localhost:$Port/status" -UseBasicParsing -TimeoutSec 8
    Write-Host "✅ 自检 /status: HTTP $($r.StatusCode)" -ForegroundColor Green
    Write-Host $r.Content
} catch {
    Write-Host "自检失败: $($_.Exception.Message)" -ForegroundColor Yellow
}
Write-Host "`n==== 完成 ====" -ForegroundColor Cyan
Write-Host "任务计划 WinDaemon 已登录自启。管理: Start/Stop/Get-ScheduledTask WinDaemon"
Write-Host "确认页: http://localhost:$Port （RDP 浏览器打开，跑批次时点[开始]）"
