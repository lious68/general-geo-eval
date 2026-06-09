@echo off
REM ============================================================
REM  UCloud GEO — WebChat 本地评测一键启动 (Windows)
REM ============================================================
REM  用法:
REM    run_webchat.bat            → 交互式引导
REM    run_webchat.bat kimi       → 指定模型，默认后台运行
REM    run_webchat.bat kimi headed → 指定模型，显示浏览器窗口
REM    run_webchat.bat config task_config.json → 从配置文件运行
REM ============================================================

cd /d "%~dp0.."

REM 切换到有 Python 虚拟环境的路径（如有）
if exist "backend\venv\Scripts\python.exe" (
    set PYTHON=backend\venv\Scripts\python.exe
) else (
    set PYTHON=python
)

REM 解析参数
if "%1"=="" goto interactive
if /i "%1"=="config" (
    if "%2"=="" (
        echo 用法: run_webchat.bat config ^<配置文件路径^>
        exit /b 1
    )
    %PYTHON% scripts\local_webchat_runner.py --config %2 --headed
    goto end
)
if /i "%2"=="headed" (
    %PYTHON% scripts\local_webchat_runner.py --models %1 --headed
    goto end
)
%PYTHON% scripts\local_webchat_runner.py --models %1

goto end

:interactive
echo.
echo  ========================================
echo   UCloud GEO WebChat 本地评测
echo  ========================================
echo.
%PYTHON% scripts\webchat_run.py --interactive

:end
