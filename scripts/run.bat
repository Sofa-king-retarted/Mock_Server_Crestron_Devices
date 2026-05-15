@echo off
cd /d "%~dp0.."
py -3 -m crestron_av_sim --config config/devices.json --scenarios config/scenarios.json
