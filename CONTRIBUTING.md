# Contributing / Development Notes

## Run locally

```powershell
py -3 -m crestron_av_sim --config config/devices.json --scenarios config/scenarios.json
```

## Add a new fake device

1. Add a new object to `config/devices.json`.
2. Give it a unique id and port.
3. Add response rules if the generic reply is not enough.
4. Add a scenario to `config/scenarios.json` if you need failure testing.

## Capture real device commands

Use the dashboard and `logs/commands.jsonl` to see what the Crestron program sends.

For the next pass, capture commands from:

- actual NVX API calls
- Biamp Tesira Text Protocol commands
- Vaddio commands
- Shure commands
- display/projector commands

Then add exact response rules for those commands.
