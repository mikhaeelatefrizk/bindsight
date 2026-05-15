@echo off
REM unregister_task_scheduler.bat
REM Removes the "bindsight Keep-warm" scheduled task created by setup_task_scheduler.bat.
REM Right-click this file and choose "Run as administrator".

schtasks /Delete /TN "bindsight Keep-warm" /F

if %errorlevel% equ 0 (
    echo SUCCESS: Task "bindsight Keep-warm" removed.
) else (
    echo FAIL: schtasks returned errorlevel %errorlevel%.  Either the task doesn't exist, or run this .bat as Administrator.
)

pause
