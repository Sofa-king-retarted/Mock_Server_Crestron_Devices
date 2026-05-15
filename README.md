# Crestron AV Lab Simulator

Mock-device framework for testing Crestron control logic in a lab without every physical AV device.

This is not a real hardware emulator for NVX, DM, HDMI, USB, AVB, HDCP, EDID, or touchpanel firmware. It provides fake TCP, UDP, and HTTP endpoints so you can test command formatting, feedback parsing, online/offline logic, route logic, polling, timeout handling, and failure scenarios.

## Included mock device types

- PJLink-style projector
- Vaddio-style camera TCP control
- Basic VISCA-over-IP UDP camera replies
- Biamp Tesira-style TCP replies
- Shure-style TCP replies
- Generic display TCP replies
- Basic mock NVX HTTP status and route endpoint

## Run on Windows

```powershell
py -3 -m crestron_av_sim --config config/devices.json --scenarios config/scenarios.json
```

Then open:

```text
http://127.0.0.1:8080
```

## Docker

```bash
docker compose up --build
```

For real processor testing, point your Crestron modules at the lab PC IP and configured ports in `config/devices.json`.

Use real hardware later for final NVX video, HDMI, USB, audio, and firmware validation.
