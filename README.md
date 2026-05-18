# Crestron AV Lab Simulator

Standalone server app for testing Crestron control logic in a lab without every physical AV device.

This is not a real hardware emulator for NVX, DM, HDMI, USB, AVB, HDCP, EDID, or touchpanel firmware. It provides fake TCP, UDP, and HTTP endpoints plus a browser GUI so you can test command formatting, feedback parsing, online/offline logic, route logic, polling, timeout handling, and failure scenarios.

## What it includes

- Browser GUI dashboard
- Per-device online/offline toggles
- Editable state fields such as power, input, stream location, mute, video sync, and response delay
- Scenario buttons for failure testing
- Built-in mock self-test for the DOE lab TCP paths
- CP4N traffic card showing whether `192.168.1.2` has reached each expected direct-control mock device
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

## Run the built-in self-test

On the dashboard, press **Run Self Test**. For the DOE multiroom lab this probes the local mock TCP paths for projectors, Sharp TVs, Tesira, Vaddio cameras, and NVX route commands. It does not prove the CP4N can reach the lab PC; use the CP4N Traffic card and command log for that.

The same check is available as JSON:

```text
http://127.0.0.1:8080/api/self-test
```

## Check CP4N traffic

The DOE dashboard Devices page marks each row as one of:

- `CP4N seen`: the CP4N opened a socket and sent a command to that mock device.
- `CP4N not hit`: this device is expected to receive a direct CP4N startup command, but none has been logged recently.
- `Inventory only`: this device is part of the lab health/config inventory, but the startup check is not expected to directly command it.

Rows marked `CP4N seen` also show the recent payload history from `192.168.1.2`, newest first, so you can verify the exact commands the processor sent to that device.

The dashboard includes an optional `Live Refresh` card. Leave it off while scrolling logs, or turn it on when watching the CP4N send fresh traffic; live mode reloads every 5 seconds and shows the last-seen age on the CP4N Traffic card.

For the DOE multiroom lab, a healthy CP4N startup currently reports:

```text
16/16 expected direct-control devices
```

The same check is available as JSON:

```text
http://127.0.0.1:8080/api/cp4n-activity
```

The `Audit` section checks the CP4N payload text against expected DOE startup commands. This catches content problems, such as an NVX route using a source ID with the wrong multicast stream. The same audit is available as JSON:

```text
http://127.0.0.1:8080/api/cp4n-audit
```

The DOE lab scenarios include quick fault drills:

- `DOE All Online`
- `DOE Room A Projector Offline`
- `DOE Tesira Slow Replies`
- `DOE Tesira Offline`
- `DOE Room B Rear Camera Offline`
- `DOE Room A TV NVX No Video`
- `DOE Room B Projector Path Degraded`
- `DOE Room C Control Network Down`
- `DOE All TV NVX Decoders No Video`
- `DOE All Vaddio Cameras Offline`

Use these from the `Scenarios` section, then run/reload the CP4N backend and watch `CP4N Traffic`, `Audit`, and the touchpanel health page.

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
