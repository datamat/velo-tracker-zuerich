@echo off
rem Checks the downloaded data, writes 03_Outputs\data_check.txt
cd /d "%~dp002_Analysis"
where py >nul 2>nul
if %errorlevel%==0 (py check_data.py) else (python check_data.py)
if errorlevel 9009 (echo Python not found. Install it from python.org, tick "Add to PATH". & pause)
