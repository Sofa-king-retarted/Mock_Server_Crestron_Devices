@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
)
.venv\Scripts\python.exe -m crestron_av_sim --lab config/labs/abc_rooms_lab.json --catalog catalog/device_catalog.json --scenarios config/scenarios.json --open-browser
pause
