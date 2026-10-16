@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 "tools\guided_dataverse_setup.py" --mode service-refresh %*
set "EXIT_CODE=%errorlevel%"
goto finish

:use_python
where python >nul 2>&1
if errorlevel 1 goto python_missing
python "tools\guided_dataverse_setup.py" --mode service-refresh %*
set "EXIT_CODE=%errorlevel%"
goto finish

:python_missing
echo.
echo Python 3.10 or later is required, but Windows could not find it.
echo Download Python from https://www.python.org/downloads/windows/
echo During installation, select "Add python.exe to PATH", then run this file again.
set "EXIT_CODE=1"

:finish
echo.
if not "%ESS_SETUP_NO_PAUSE%"=="1" pause
exit /b %EXIT_CODE%
