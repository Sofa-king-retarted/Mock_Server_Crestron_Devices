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
- Mock endpoints for NVX, PJLink, Vaddio, VISCA-over-IP, Biamp Tesira, Shure, generic displays, scalers, and amplifiers

## Run on Windows

```powershell
py -3 -m crestron_av_sim --lab config/labs/default_lab.json
```

Then open:

```text
http://127.0.0.1:8080
```

## Run the A/B/C room lab

```powershell
py -3 -m crestron_av_sim --lab config/labs/abc_rooms_lab.json
```

## Run with helper scripts

```powershell
.\scripts\run.ps1
.\scripts\run.ps1 config/labs/abc_rooms_lab.json
```

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
