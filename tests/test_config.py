import json
from pathlib import Path

from crestron_av_sim.server_app import LabApp, load_json, self_test_targets


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
    scenarios = json.loads(Path('config/scenarios.json').read_text(encoding='utf-8'))
    labs = {
        'legacy': json.loads(Path('config/devices.json').read_text(encoding='utf-8')),
    }
    for path in Path('config/labs').glob('*.json'):
        lab = json.loads(path.read_text(encoding='utf-8'))
        labs[lab['lab_id']] = lab

    for scenario in scenarios['scenarios']:
        scenario_labs = scenario.get('labs') or list(labs)
        for dotted_key in scenario.get('set', {}):
            device_id, _ = dotted_key.split('.', 1)
            assert any(
                device_id in {d['id'] for d in labs[lab_id]['devices']}
                for lab_id in scenario_labs
            ), f'{scenario["id"]} references missing device {device_id}'


def test_doe_multiroom_lab_only_loads_doe_scenarios():
    app = LabApp(
        'config/labs/doe_multiroom_lab.json',
        load_json('config/labs/doe_multiroom_lab.json'),
        load_json('catalog/device_catalog.json'),
        load_json('config/scenarios.json'),
    )

    scenario_ids = {scenario['id'] for scenario in app.snapshot()['scenarios']}

    assert 'doe_projector_a_offline' in scenario_ids
    assert 'doe_tesira_slow' in scenario_ids
    assert 'projector_offline' not in scenario_ids


def test_doe_multiroom_fault_scenario_changes_expected_device_state():
    app = LabApp(
        'config/labs/doe_multiroom_lab.json',
        load_json('config/labs/doe_multiroom_lab.json'),
        load_json('catalog/device_catalog.json'),
        load_json('config/scenarios.json'),
    )

    app.apply_scenario('doe_tesira_slow')
    devices = {device['id']: device for device in app.snapshot()['devices']}

    assert devices['BIAMP-TESIRA']['state']['online'] is True
    assert devices['BIAMP-TESIRA']['state']['response_delay_ms'] == 2500

    app.apply_scenario('doe_all_online')
    devices = {device['id']: device for device in app.snapshot()['devices']}

    assert devices['BIAMP-TESIRA']['state']['online'] is True
    assert devices['BIAMP-TESIRA']['state']['response_delay_ms'] == 0
    assert all(device['state']['online'] is True for device in devices.values())


def test_doe_multiroom_lab_matches_backend_mock_ports():
    lab = json.loads(Path('config/labs/doe_multiroom_lab.json').read_text(encoding='utf-8'))
    devices = {d['id']: d for d in lab['devices']}
    expected_ports = {
        'projector_a': 3629,
        'projector_b': 3630,
        'projector_c': 3631,
        'sharp_tv_a': 10002,
        'sharp_tv_b': 10003,
        'sharp_tv_c': 10004,
        'BIAMP-TESIRA': 9001,
        'VADDIO-A-FRONT': 5678,
        'VADDIO-A-REAR': 5679,
        'VADDIO-B-FRONT': 5680,
        'VADDIO-B-REAR': 5681,
        'VADDIO-C-FRONT': 5682,
        'VADDIO-C-REAR': 5683,
        'DM-NVX-36x-A-PC': 8209,
        'DM-NVX-36x-B-PC': 8210,
        'DM-NVX-36x-C-PC': 8211,
        'DM-NVX-36x-A-Laptop': 8212,
        'DM-NVX-36x-B-Laptop': 8213,
        'DM-NVX-36x-C-Laptop': 8214,
        'DM-NVX-36xC-A-Barco': 8218,
        'DM-NVX-36xC-B-Barco': 8219,
        'DM-NVX-36xC-C-Barco': 8226,
        'DM-NVX-E30C-505-Rear-Camera': 8251,
        'DM-NVX-E30C-505-Front-Camera': 8252,
        'DM-NVX-E30C-506-Rear-Camera': 8253,
        'DM-NVX-E30C-506-Front-Camera': 8254,
        'DM-NVX-E30C-507-Rear-Camera': 8255,
        'DM-NVX-E30C-507-Front-Camera': 8256,
        'DM-NVX-D30-A-TV': 8306,
        'DM-NVX-D30-B-TV': 8307,
        'DM-NVX-D30-C-TV': 8308,
        'DM-NVX-D30C-505-AVBridge': 8348,
        'DM-NVX-D30C-506-AVBridge': 8349,
        'DM-NVX-D30C-507-AVBridge': 8350,
    }

    assert lab.get('nvx_control') == 'tcp'
    for device_id, port in expected_ports.items():
        assert devices[device_id]['port'] == port


def test_doe_multiroom_self_test_targets_cover_cp4n_lab_paths():
    lab_path = 'config/labs/doe_multiroom_lab.json'
    app = LabApp(
        lab_path,
        load_json(lab_path),
        load_json('catalog/device_catalog.json'),
        load_json('config/scenarios.json'),
    )

    target_ids = {target['device_id'] for target in self_test_targets(app)}

    assert {'projector_a', 'projector_b', 'projector_c'}.issubset(target_ids)
    assert {'sharp_tv_a', 'sharp_tv_b', 'sharp_tv_c'}.issubset(target_ids)
    assert 'BIAMP-TESIRA' in target_ids
    assert {'VADDIO-A-FRONT', 'VADDIO-A-REAR', 'VADDIO-B-FRONT', 'VADDIO-B-REAR', 'VADDIO-C-FRONT', 'VADDIO-C-REAR'}.issubset(target_ids)
    assert {'DM-NVX-D30-A-TV', 'DM-NVX-D30C-505-AVBridge'}.issubset(target_ids)
    assert len(target_ids) == 15
