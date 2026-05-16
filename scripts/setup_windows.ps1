$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/Sofa-king-retarted/Mock_Server_Crestron_Devices.git"
$InstallRoot = if ($args.Count -gt 0) { $args[0] } else { "$env:USERPROFILE\CrestronLabTools" }
$RepoDir = Join-Path $InstallRoot "Mock_Server_Crestron_Devices"

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

if (Test-Path $RepoDir) {
    Write-Host "Updating existing repo at $RepoDir"
    git -C $RepoDir pull
} else {
    Write-Host "Cloning repo to $RepoDir"
    git clone $RepoUrl $RepoDir
}

Set-Location $RepoDir

py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

$Desktop = [Environment]::GetFolderPath("Desktop")
$DefaultShortcut = Join-Path $Desktop "Crestron AV Lab Simulator - Default.bat"
$AbcShortcut = Join-Path $Desktop "Crestron AV Lab Simulator - ABC Rooms.bat"
$NvxShortcut = Join-Path $Desktop "Crestron AV Lab Simulator - NVX Bench.bat"
$UpdateShortcut = Join-Path $Desktop "Update Crestron AV Lab Simulator.bat"

Set-Content -Path $DefaultShortcut -Value "@echo off`r`ncd /d `"$RepoDir`"`r`n.venv\Scripts\python.exe -m crestron_av_sim --lab config/labs/default_lab.json --catalog catalog/device_catalog.json --scenarios config/scenarios.json --open-browser`r`npause`r`n"
Set-Content -Path $AbcShortcut -Value "@echo off`r`ncd /d `"$RepoDir`"`r`n.venv\Scripts\python.exe -m crestron_av_sim --lab config/labs/abc_rooms_lab.json --catalog catalog/device_catalog.json --scenarios config/scenarios.json --open-browser`r`npause`r`n"
Set-Content -Path $NvxShortcut -Value "@echo off`r`ncd /d `"$RepoDir`"`r`n.venv\Scripts\python.exe -m crestron_av_sim --lab config/labs/nvx_bench_lab.json --catalog catalog/device_catalog.json --scenarios config/scenarios.json --open-browser`r`npause`r`n"
Set-Content -Path $UpdateShortcut -Value "@echo off`r`ncd /d `"$RepoDir`"`r`ngit pull`r`n.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`r`n.venv\Scripts\python.exe -m compileall crestron_av_sim`r`n.venv\Scripts\python.exe -m pytest -q`r`npause`r`n"

Write-Host ""
Write-Host "Installed to: $RepoDir"
Write-Host "Desktop launchers created:"
Write-Host "  $DefaultShortcut"
Write-Host "  $AbcShortcut"
Write-Host "  $NvxShortcut"
Write-Host "  $UpdateShortcut"
Write-Host ""
Write-Host "Starting default lab now..."
& .\.venv\Scripts\python.exe -m crestron_av_sim --lab config/labs/default_lab.json --catalog catalog/device_catalog.json --scenarios config/scenarios.json --open-browser
