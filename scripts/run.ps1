$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path -Parent $PSScriptRoot)

$Lab = if ($args.Count -gt 0) { $args[0] } else { "config/labs/default_lab.json" }
py -3 -m crestron_av_sim --lab $Lab --catalog catalog/device_catalog.json --scenarios config/scenarios.json --open-browser
