@echo off
cd /d "%~dp0.."
set LAB=%1
if "%LAB%"=="" set LAB=config/labs/default_lab.json
py -3 -m crestron_av_sim --lab %LAB% --catalog catalog/device_catalog.json --scenarios config/scenarios.json
