@echo off
REM setup_task_scheduler.bat
REM Registers a Windows Scheduled Task that runs keep_warm.py once every 6 hours,
REM regardless of whether the user is logged in.
REM Right-click this file and choose "Run as administrator".

setlocal

REM Resolve absolute path to keep_warm.py (this script's directory)
set "SCRIPT_DIR=%~dp0"
set "PY_SCRIPT=%SCRIPT_DIR%keep_warm.py"

REM Find the system Python (try py launcher first, then python.exe on PATH).
where py >nul 2>nul
if %errorlevel% equ 0 (
    set "PYTHON=py"
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON=python"
    ) else (
        echo ERROR: Cannot find Python on PATH.  Install Python from python.org or microsoft store first.
        pause
        exit /b 1
    )
)

echo Using Python launcher: %PYTHON%
echo Using script path:     %PY_SCRIPT%
echo.

REM Build the schtasks command:
REM   /Create  -- create new task
REM   /TN      -- task name (visible in Task Scheduler)
REM   /TR      -- task action (what to run)
REM   /SC HOURLY  -- schedule type
REM   /MO 6    -- modifier: every 6 hours
REM   /RL HIGHEST -- run with highest privileges (allows running when not logged in)
REM   /F       -- force overwrite if task already exists

schtasks /Create ^
    /TN "bindsight Keep-warm" ^
    /TR "\"%PYTHON%\" \"%PY_SCRIPT%\"" ^
    /SC HOURLY ^
    /MO 6 ^
    /RL HIGHEST ^
    /F

if %errorlevel% equ 0 (
    echo.
    echo SUCCESS: Task "bindsight Keep-warm" registered to run %PYTHON% %PY_SCRIPT% every 6 hours.
    echo You can verify in Task Scheduler ^> Task Scheduler Library ^> bindsight Keep-warm
    echo To trigger manually right now, run:
    echo     schtasks /Run /TN "bindsight Keep-warm"
) else (
    echo.
    echo FAIL: schtasks returned errorlevel %errorlevel%.  Run this .bat as Administrator.
)

echo.
pause
endlocal
