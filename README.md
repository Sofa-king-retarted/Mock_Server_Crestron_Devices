# Crestron AV Lab Simulator

Standalone server app for testing Crestron control logic in a lab without every physical AV device.

This is not a real hardware emulator for NVX, DM, HDMI, USB, AVB, HDCP, EDID, or touchpanel firmware. It provides fake TCP, UDP, and HTTP endpoints plus a browser GUI so you can test command formatting, feedback parsing, online/offline logic, route logic, polling, timeout handling, and failure scenarios.

## What it includes

- Browser GUI dashboard
- Per-device online/offline toggles
- Editable state fields such as power, input, stream location, mute, video sync, and response delay
- Scenario buttons for failure testing
- Command logging to `logs/commands.jsonl`
- Device catalog for multiple lab templates
- Lab profiles for different rooms or test benches
- GUI lab builder for adding/removing devices from the catalog
- Saveable lab profiles from the browser
- Mock endpoints for NVX, PJLink, Vaddio, VISCA-over-IP, Biamp Tesira, Shure, generic displays, scalers, USB mocks, and amplifiers

## Put it on a Windows lab PC

Open PowerShell and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
irm https://raw.githubusercontent.com/Sofa-king-retarted/Mock_Server_Crestron_Devices/main/scripts/setup_windows.ps1 -OutFile $env:TEMP\setup_crestron_lab.ps1
powershell -ExecutionPolicy Bypass -File $env:TEMP\setup_crestron_lab.ps1
```

The setup script clones or updates the repo under:

```text
%USERPROFILE%\CrestronLabTools\Mock_Server_Crestron_Devices
```

It also creates two desktop launchers:

```text
Crestron AV Lab Simulator - Default.bat
Crestron AV Lab Simulator - ABC Rooms.bat
```

## Run on Windows manually

```powershell
py -3 -m crestron_av_sim --lab config/labs/default_lab.json --open-browser
```

Then open:

```text
http://127.0.0.1:8080
```

## Run the A/B/C room lab

```powershell
py -3 -m crestron_av_sim --lab config/labs/abc_rooms_lab.json --open-browser
```

## Run with helper scripts

```powershell
.\scripts\run.ps1
.\scripts\run.ps1 config/labs/abc_rooms_lab.json
```

## GUI Lab Builder

The dashboard has a Builder section where you can:

- add a device from the catalog
- set device ID, name, host, and port
- start newly added fake devices
- remove devices from the active profile
- save the lab profile JSON

If a device is removed after the server already bound its port, restart the app to free that old listener.

## Docker

```bash
docker compose up --build
```

## Device catalog

Device models live in:

```text
catalog/device_catalog.json
```

Lab profiles instantiate those models with unique IDs and ports.

## Build Windows EXE

```powershell
.\scripts\build_windows_exe.ps1
```

The generated app will be placed under `dist/`.

## Important limits

Use real hardware later for final NVX video, HDMI, USB, audio, EDID, HDCP, AVB, and firmware validation.
