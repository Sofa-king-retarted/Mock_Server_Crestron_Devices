# Standalone Server App

The app runs on a lab PC and provides two things:

1. Mock AV device endpoints for a Crestron processor.
2. A browser dashboard for technician control.

## Core files

- `crestron_av_sim/server_app.py` - server app, mock protocol handlers, and dashboard
- `crestron_av_sim/__main__.py` - Python entrypoint
- `catalog/device_catalog.json` - available mock model types
- `config/labs/*.json` - lab profiles
- `config/scenarios.json` - failure and recovery scenarios
- `logs/commands.jsonl` - Crestron command log

## Lab profiles

A lab profile is a list of device instances. Each instance references a `model_key` from the catalog and can override name, port, and starting state.

Current profiles:

- `config/labs/default_lab.json`
- `config/labs/abc_rooms_lab.json`

## Dashboard controls

The dashboard lets you toggle devices online or offline, edit common state keys, apply scenarios, view the model catalog, and view recent Crestron commands.

## Next improvements

- Add a page to create lab profiles from the catalog.
- Add import and export for lab profiles.
- Add model-specific protocol handlers based on real command captures.
- Add multiple IP binding support for one-IP-per-device lab layouts.
