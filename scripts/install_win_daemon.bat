@echo off
REM 用 NSSM 把 win_daemon 注册为开机自启服务。需先装 NSSM 并放 PATH。
REM 用法（管理员 PowerShell/ CMD）： scripts\install_win_daemon.bat
setlocal
set ROOT=%~dp0..
set PY=python
set SCRIPT=%ROOT%\scripts\win_daemon.py
set ENVFILE=%ROOT%\scripts\win_daemon.env

if not exist "%ENVFILE%" (
  echo [ERR] 未找到 %ENVFILE%
  echo        请复制 win_daemon.env.example 为 win_daemon.env 并填写
  exit /b 1
)

echo [1/3] 安装服务 WinDaemon ...
nssm install WinDaemon "%PY%" "%SCRIPT%"
nssm set WinDaemon AppDirectory "%ROOT%"
nssm set WinDaemon AppEnvironmentExtra "PYTHONUNBUFFERED=1"
nssm set WinDaemon Start SERVICE_AUTO_START

echo [2/3] 启动服务 ...
nssm start WinDaemon

echo [3/3] 完成。
echo        查看状态: nssm status WinDaemon
echo        查看日志: nssm logs WinDaemon
echo        本地确认页: http://localhost:8443
endlocal
