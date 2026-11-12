@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 goto use_python
for %%V in (3.14 3.13 3.12 3.11 3.10) do (
    py -%%V -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY_VERSION=%%V"
    if not errorlevel 1 goto run_py_launcher
)
goto use_python

:run_py_launcher
py -%PY_VERSION% "tools\guided_dataverse_setup.py" --mode desktop-validation %*
set "EXIT_CODE=%errorlevel%"
goto finish

:use_python
where python >nul 2>&1
if errorlevel 1 goto python_missing
python -c "import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 15) else 1)" >nul 2>&1
if errorlevel 1 goto python_unsupported
python "tools\guided_dataverse_setup.py" --mode desktop-validation %*
set "EXIT_CODE=%errorlevel%"
goto finish

:python_missing
echo.
echo Python 3.10 through 3.14 is required, but Windows could not find it.
echo Download Python from https://www.python.org/downloads/windows/
echo During installation, select "Add python.exe to PATH", then run this file again.
set "EXIT_CODE=1"
goto finish

:python_unsupported
echo.
echo This package requires Python 3.10 through 3.14.
echo Python 3.15 is not yet supported by the required NumPy and ONNX Runtime libraries.
echo Install Python 3.14 from https://www.python.org/downloads/windows/
echo Python 3.15 may remain installed; this launcher will prefer Python 3.14.
set "EXIT_CODE=1"

:finish
echo.
if not "%ESS_SETUP_NO_PAUSE%"=="1" pause
exit /b %EXIT_CODE%
