@echo off
cd /d "%~dp0"
git pull
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  .venv\Scripts\python.exe -m pip install --upgrade pip
)
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m compileall crestron_av_sim
.venv\Scripts\python.exe -m pytest -q
pause
