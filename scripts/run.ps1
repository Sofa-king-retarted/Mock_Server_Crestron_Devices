$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path -Parent $PSScriptRoot)
py -3 -m crestron_av_sim --config config/devices.json --scenarios config/scenarios.json
