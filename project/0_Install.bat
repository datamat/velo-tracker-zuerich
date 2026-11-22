@echo off
rem Installs the Python packages, checks Git
cd /d "%~dp002_Analysis"
where py >nul 2>nul
if %errorlevel%==0 (py install.py) else (python install.py)
if errorlevel 9009 (echo Python not found. Install it from python.org, tick "Add to PATH". & pause)
