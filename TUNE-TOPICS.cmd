@echo off
call "%~dp0START-HERE-DATAVERSE.cmd" --tune-topics %*
exit /b %errorlevel%