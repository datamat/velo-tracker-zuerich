@echo off
rem Downloads all sources into D:\nfa_data\4_projects\velo_map (see 02_Analysis\config.ini)
cd /d "%~dp002_Analysis"
where py >nul 2>nul
if %errorlevel%==0 (py collect_data.py) else (python collect_data.py)
if errorlevel 9009 (echo Python not found. Install it from python.org, tick "Add to PATH". & pause)
