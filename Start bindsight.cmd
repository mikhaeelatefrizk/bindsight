@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto use_python
for %%V in (3.13 3.12 3.11) do (
    py -%%V -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        py -%%V launch.py
        goto finished
    )
)
:use_python
python launch.py
:finished
if errorlevel 1 pause
