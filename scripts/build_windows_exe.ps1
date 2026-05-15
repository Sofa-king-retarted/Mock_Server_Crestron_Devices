$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path -Parent $PSScriptRoot)

py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --onefile --name CrestronAvLabSimulator --add-data "config;config" --add-data "catalog;catalog" --add-data "docs;docs" crestron_av_sim\__main__.py

Write-Host "Built: dist\CrestronAvLabSimulator.exe"
