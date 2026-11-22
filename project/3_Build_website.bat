@echo off
rem Builds the website in 03_Outputs\website
cd /d "%~dp002_Analysis"
where py >nul 2>nul
if %errorlevel%==0 (py build_site.py) else (python build_site.py)
if errorlevel 9009 (echo Python not found. Install it from python.org, tick "Add to PATH". & pause)
