from crestron_av_sim.server_app import CommandLog, Device, LabApp, TcpMock, Web


CATALOG = {
    "vaddio_ptz_camera": {
        "vendor": "Vaddio",
        "model": "Vaddio Camera TCP Mock",
        "type": "vaddio_camera",
        "protocol": "tcp",
        "default_state": {"power": "on", "preset": 1, "pan": 0, "tilt": 0, "zoom": 0},
    },
    "biamp_tesira_server": {
        "vendor": "Biamp",
        "model": "Tesira Server Mock",
        "type": "tesira",
        "protocol": "tcp",
        "default_state": {},
    },
    "epson_projector_tcp": {
        "vendor": "Epson",
        "model": "Epson TCP Mock",
        "type": "pjlink_projector",
        "protocol": "tcp",
        "default_state": {"power": "off", "input": "HDMI1", "mute": False},
    },
    "crestron_dm_nvx_d30": {
        "vendor": "Crestron",
        "model": "DM-NVX-D30",
        "type": "nvx_tcp",
        "protocol": "tcp",
        "default_state": {"role": "receiver", "stream_location": "239.8.0.111", "video_sync": True},
    },
}


def tcp_mock(model_key: str, tmp_path) -> TcpMock:
    device = Device({"id": "dev", "model_key": model_key, "port": 1}, {}, CATALOG)
    return TcpMock(device, CommandLog(str(tmp_path / "commands.jsonl")))


def test_vaddio_ptz_commands_update_state(tmp_path):
    mock = tcp_mock("vaddio_ptz_camera", tmp_path)

    assert mock.reply("camera pan right").decode() == "OK\r\n"
    assert mock.reply("camera tilt up").decode() == "OK\r\n"
    assert mock.reply("camera zoom in").decode() == "OK\r\n"
    assert mock.reply("camera preset store 3").decode() == "OK\r\n"

    assert mock.d.get("pan") == 1
    assert mock.d.get("tilt") == 1
    assert mock.d.get("zoom") == 1
    assert mock.d.get("stored_preset") == 3


def test_tesira_doe_commands_update_object_tag_state(tmp_path):
    mock = tcp_mock("biamp_tesira_server", tmp_path)

    assert mock.reply("505-Vol set level 1 47185").decode() == "+OK\r\n"
    assert mock.reply("505-Mics set mute 1 true").decode() == "+OK\r\n"
    assert mock.reply("DEVICE recallPreset 1007").decode() == "+OK\r\n"

    assert mock.d.get("tesira_505_vol_level_1") == 47185
    assert mock.d.get("tesira_505_mics_mute_1") is True
    assert mock.d.get("last_preset") == 1007
    assert mock.reply("505-Vol get level 1").decode() == "+OK 47185\r\n"
    assert mock.reply("505-Mics get mute 1").decode() == "+OK true\r\n"


def test_epson_esc_vp21_commands_update_state(tmp_path):
    mock = tcp_mock("epson_projector_tcp", tmp_path)

    assert mock.reply("PWR ON").decode() == ":\r\n"
    assert mock.reply("MUTE ON").decode() == ":\r\n"
    assert mock.reply("SOURCE 30").decode() == ":\r\n"

    assert mock.d.get("power") == "on"
    assert mock.d.get("mute") is True
    assert mock.d.get("input") == "30"


def test_nvx_route_commands_update_decoder_state(tmp_path):
    mock = tcp_mock("crestron_dm_nvx_d30", tmp_path)

    assert mock.reply("ROUTE DM-NVX-36x-A-Laptop 239.10.50.12:5004").decode() == "OK\r\n"

    assert mock.d.get("route") == "DM-NVX-36x-A-Laptop"
    assert mock.d.get("stream_location") == "239.10.50.12"
    assert mock.d.get("stream_port") == 5004
    assert mock.d.get("video_sync") is True

    assert mock.reply("BLANK DM-NVX-D30-A-TV").decode() == "OK\r\n"
    assert mock.d.get("video_sync") is False


def test_command_log_tracks_device_activity_by_controller_peer(tmp_path):
    log = CommandLog(str(tmp_path / "commands.jsonl"))

    log.add("projector_a", "rx", "PWR ON", "('192.168.1.2', 12345)")
    log.add("projector_a", "rx", "MUTE OFF", "('192.168.1.2', 12346)")
    log.add("projector_a", "tx", ":\r\n", "('192.168.1.2', 12345)")
    log.add("sharp_tv_a", "rx", "RM-A-TV-ON", "('127.0.0.1', 55555)")

    activity = log.device_activity("192.168.1.2", "rx")
    history = log.device_activity_history("192.168.1.2", "rx")

    assert set(activity) == {"projector_a"}
    assert activity["projector_a"]["payload"] == "MUTE OFF"
    assert [entry["payload"] for entry in history["projector_a"]] == ["MUTE OFF", "PWR ON"]


def test_web_cp4n_activity_reports_touched_mock_devices(tmp_path):
    lab = {
        "lab_id": "test",
        "name": "Test Lab",
        "defaults": {"host": "0.0.0.0", "online": True},
        "devices": [
            {"id": "projector_a", "model_key": "epson_projector_tcp", "port": 3629},
            {"id": "sharp_tv_a", "model_key": "epson_projector_tcp", "port": 10002},
        ],
    }
    catalog_doc = {"models": [{"key": key, **value} for key, value in CATALOG.items()]}
    app = LabApp(str(tmp_path / "lab.json"), lab, catalog_doc, {"scenarios": []})
    log = CommandLog(str(tmp_path / "commands.jsonl"))
    log.add("projector_a", "rx", "PWR ON", "('192.168.1.2', 12345)")
    log.add("projector_a", "rx", "MUTE OFF", "('192.168.1.2', 12346)")
    dashboard = Web(app, log, None, "127.0.0.1", 8080)

    activity = dashboard.cp4n_activity()

    assert activity["seen"] is True
    assert activity["touched"] == 1
    assert activity["total"] == 2
    assert activity["expected_touched"] == 1
    assert activity["expected_total"] == 2
    assert activity["devices"]["projector_a"]["payload"] == "MUTE OFF"
    assert [entry["payload"] for entry in activity["history"]["projector_a"]] == ["MUTE OFF", "PWR ON"]
    assert activity["last_seen"] is not None
    assert activity["last_seen_age_seconds"] >= 0
    assert activity["last_seen_age_text"].endswith("ago")


def test_web_marks_source_encoders_as_inventory_only():
    row = Web.device_row(
        {
            "id": "DM-NVX-36x-A-Laptop",
            "name": "Room A Laptop NVX Encoder",
            "vendor": "Crestron",
            "model": "DM-NVX-36x",
            "type": "nvx_tcp",
            "protocol": "tcp",
            "host": "0.0.0.0",
            "port": 8212,
            "state": {"online": True, "role": "encoder", "stream_location": "239.10.50.12"},
        },
        None,
        [],
        False,
    )

    assert "Inventory only" in row
    assert "CP4N not hit" not in row


def test_web_device_row_shows_cp4n_command_history():
    row = Web.device_row(
        {
            "id": "projector_a",
            "name": "Room A Projector",
            "vendor": "Epson",
            "model": "Epson TCP Mock",
            "type": "pjlink_projector",
            "protocol": "tcp",
            "host": "0.0.0.0",
            "port": 3629,
            "state": {"online": True, "power": "on"},
        },
        {"ts": "2026-05-17T00:00:00+00:00", "payload": "MUTE OFF"},
        [
            {"ts": "2026-05-17T00:00:00+00:00", "payload": "MUTE OFF"},
            {"ts": "2026-05-16T23:59:59+00:00", "payload": "PWR ON"},
        ],
        True,
    )

    assert "2 command(s)" in row
    assert "MUTE OFF" in row
    assert "PWR ON" in row


def test_dashboard_live_refresh_is_opt_in(tmp_path):
    lab = {
        "lab_id": "test",
        "name": "Test Lab",
        "defaults": {"host": "0.0.0.0", "online": True},
        "devices": [],
    }
    app = LabApp(str(tmp_path / "lab.json"), lab, {"models": []}, {"scenarios": []})
    dashboard = Web(app, CommandLog(str(tmp_path / "commands.jsonl")), None, "127.0.0.1", 8080)

    paused = dashboard.dashboard("/")
    live = dashboard.dashboard("/?live=1")

    assert "http-equiv='refresh'" not in paused
    assert "Live Refresh</b><span>Off" in paused
    assert "http-equiv='refresh' content='5'" in live
    assert "Live Refresh</b><span>On" in live


def test_dashboard_shows_processor_readiness_section(tmp_path, monkeypatch):
    lab = {
        "lab_id": "test",
        "name": "Test Lab",
        "defaults": {"host": "0.0.0.0", "online": True},
        "devices": [
            {"id": "projector_a", "model_key": "epson_projector_tcp", "port": 3629},
        ],
    }
    catalog_doc = {"models": [{"key": key, **value} for key, value in CATALOG.items()]}
    app = LabApp(str(tmp_path / "lab.json"), lab, catalog_doc, {"scenarios": []})
    log = CommandLog(str(tmp_path / "commands.jsonl"))
    dashboard = Web(app, log, None, "127.0.0.1", 8080)
    monkeypatch.setattr(Web, "tcp_port_open", staticmethod(lambda host, port, timeout=0.25: port == 22))

    readiness = dashboard.processor_readiness()
    html = dashboard.dashboard("/")

    assert readiness["ready"] is False
    assert readiness["status"] == "blocked"
    assert "CP4N Smart Graphics service" in readiness["summary"]
    assert "Processor Readiness" in html
    assert "Mock URL for CP4N lab profile" in html
    assert "blocked" in html


def test_cp4n_command_audit_checks_nvx_route_against_source_stream(tmp_path):
    lab = {
        "lab_id": "test",
        "name": "Test Lab",
        "defaults": {"host": "0.0.0.0", "online": True},
        "devices": [
            {
                "id": "DM-NVX-36x-A-Laptop",
                "model_key": "crestron_dm_nvx_d30",
                "port": 8212,
                "state": {"role": "encoder", "stream_location": "239.10.50.18", "stream_port": 5004},
            },
            {"id": "DM-NVX-D30-A-TV", "model_key": "crestron_dm_nvx_d30", "port": 8306},
        ],
    }
    catalog_doc = {"models": [{"key": key, **value} for key, value in CATALOG.items()]}
    app = LabApp(str(tmp_path / "lab.json"), lab, catalog_doc, {"scenarios": []})
    log = CommandLog(str(tmp_path / "commands.jsonl"))
    log.add(
        "DM-NVX-D30-A-TV",
        "rx",
        "ROUTE DM-NVX-36x-A-Laptop 239.10.50.18:5004",
        "('192.168.1.2', 12345)",
    )
    dashboard = Web(app, log, None, "127.0.0.1", 8080)

    audit = dashboard.cp4n_command_audit()
    route_check = next(check for check in audit["checks"] if check["label"] == "Room A TV NVX route")

    assert route_check["ok"] is True
    assert route_check["expected"] == "ROUTE DM-NVX-36x-A-Laptop 239.10.50.18:5004"
