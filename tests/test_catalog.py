import json
from pathlib import Path


def test_catalog_has_nvx_models():
    catalog = json.loads(Path('catalog/device_catalog.json').read_text(encoding='utf-8'))
    keys = {m['key'] for m in catalog['models']}
    assert 'crestron_dm_nvx_360' in keys
    assert 'crestron_dm_nvx_e30' in keys
    assert 'crestron_dm_nvx_d30' in keys


def test_labs_reference_catalog_models():
    catalog = json.loads(Path('catalog/device_catalog.json').read_text(encoding='utf-8'))
    keys = {m['key'] for m in catalog['models']}
    for lab_path in Path('config/labs').glob('*.json'):
        lab = json.loads(lab_path.read_text(encoding='utf-8'))
        for device in lab['devices']:
            assert device['model_key'] in keys, f"{lab_path} references missing model {device['model_key']}"
