@echo off
REM HIVE Extract - Batch file for Task Scheduler
REM This file can be used with Windows Task Scheduler for automated runs

cd /d "%~dp0"

REM Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Run the extract with date picker (interactive mode)
REM For scheduled runs, consider using --from-date and --to-date arguments
python src\main.py

REM Capture exit code
set EXIT_CODE=%ERRORLEVEL%

REM Deactivate virtual environment
if exist "venv\Scripts\deactivate.bat" (
    call deactivate
)

exit /b %EXIT_CODE%
