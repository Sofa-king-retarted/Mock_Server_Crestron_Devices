@echo off
setlocal
cd /d "%~dp0"
py -3 -m crestron_av_sim --lab config/labs/doe_multiroom_lab.json --open-browser
