import json
from pathlib import Path


def test_default_config_loads():
    data = json.loads(Path('config/devices.json').read_text(encoding='utf-8'))
    assert 'devices' in data
    assert len(data['devices']) >= 1
    ids = {d['id'] for d in data['devices']}
    assert 'projector_a' in ids
    assert 'tesira_server' in ids
    assert 'nvx_a_tx' in ids
    assert 'nvx_a_rx' in ids


def test_scenarios_reference_existing_devices():
    devices = json.loads(Path('config/devices.json').read_text(encoding='utf-8'))
    scenarios = json.loads(Path('config/scenarios.json').read_text(encoding='utf-8'))
    ids = {d['id'] for d in devices['devices']}
    for scenario in scenarios['scenarios']:
        for dotted_key in scenario.get('set', {}):
            device_id, _ = dotted_key.split('.', 1)
            assert device_id in ids, f'{scenario["id"]} references missing device {device_id}'
