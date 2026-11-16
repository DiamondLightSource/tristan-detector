import json

import pytest
from odin.adapters.parameter_tree import ParameterTreeError

from tristan_detector.control import tristan_detector
from tristan_detector.control.tristan_channel import TristanChannel
from tristan_detector.control.tristan_detector import (
    DetectorTimeoutError,
    TristanDetector,
    _lookup,
)
from tristan_detector.control.tristan_message import ResponseMessage

# Nothing listens here; the detector must still construct
UNUSED_ENDPOINT = "tcp://127.0.0.1:59999"


@pytest.fixture
def sent(monkeypatch):
    """Record everything sent to the detector instead of sending it"""
    messages = []

    def fake_send(self, data):
        messages.append(data)
        return -1  # as if the detector were unavailable

    monkeypatch.setattr(TristanChannel, "send", fake_send)
    return messages


@pytest.fixture
def detector(monkeypatch, sent):
    # Stop the background thread polling, so tests see only construction behaviour
    monkeypatch.setattr(TristanDetector, "update_loop", lambda self: None)
    detector = TristanDetector(UNUSED_ENDPOINT, "1.0.0", "./udp.json", 0.5)
    yield detector
    detector.shutdown()


def test_construction_does_not_contact_detector(detector, sent):
    assert sent == []


def test_schema_paths_exist_before_detector_replies(detector):
    assert detector.get("status/state") == {"value": None}
    assert detector.get("status/detector/x_pixels_in_detector") == {"value": None}
    assert detector.get("status/detector/module_dimensions/x_max") == {"value": None}
    assert detector.get("config/exposure") == {"value": None}
    assert detector.get("config/trigger/timestamp/fem") == {"value": None}


@pytest.mark.parametrize("meta", [False, True])
def test_every_schema_path_is_in_tree(detector, meta):
    for path in TristanDetector.STATUS_REQUEST_FIELDS:
        detector.get(f"status/{path}", meta=meta)
    for path in TristanDetector.DETECTOR_CONFIG:
        detector.get(f"config/{path}", meta=meta)


def test_description_is_readable_despite_reserved_name(detector):
    # "description" is a ParameterTree metadata field name
    detector._status = {"detector": {"description": "Tristan 10M"}}
    assert detector.get("status/detector/description") == {"value": "Tristan 10M"}
    response = detector.get("status/detector/description", meta=True)
    assert response["description"]["value"] == "Tristan 10M"


def test_enum_metadata_is_applied(detector):
    response = detector.get("config/trigger/start", meta=True)
    assert (
        response["start"]["allowed_values"]
        == TristanDetector.DETECTOR_ENUMS["trigger/start"]
    )
    assert detector.get("config/mode", meta=True)["mode"]["allowed_values"] == [
        "time_energy",
        "time_only",
        "count",
    ]


def test_leaves_read_latest_store_contents(detector):
    detector._status = {
        "state": "idle",
        "detector": {"x_pixels_in_detector": 4096, "module_dimensions": {"x_max": [7]}},
    }
    detector._config = {"exposure": 1.5, "trigger": {"start": "external_re"}}

    assert detector.get("status/state") == {"value": "idle"}
    assert detector.get("status/detector/x_pixels_in_detector") == {"value": 4096}
    assert detector.get("status/detector/module_dimensions/x_max") == {"value": [7]}
    assert detector.get("config/exposure") == {"value": 1.5}
    assert detector.get("config/trigger/start") == {"value": "external_re"}
    # Paths absent from the reply still read as None rather than erroring
    assert detector.get("config/frames") == {"value": None}


def test_local_fields(detector):
    assert detector.get("firmware") == {"firmware": "1.0.0"}
    assert detector.get("udp_file") == {"udp_file": "./udp.json"}
    assert detector.get("status/manufacturer") == {"value": "DLS/STFC"}


def test_shutdown_stops_thread_and_closes_channel(monkeypatch, sent):
    closed = []
    real_close = TristanChannel.close

    def recording_close(self):
        closed.append(True)
        real_close(self)

    monkeypatch.setattr(TristanChannel, "close", recording_close)
    detector = TristanDetector(UNUSED_ENDPOINT, "1.0.0", "./udp.json", 0.5)

    detector.shutdown()

    assert not detector._status_thread.is_alive()
    assert closed == [True]


STATUS_REPLY = {
    "state": "idle",
    "detector": {
        "software_version": "1.0.0",
        "x_pixels_in_detector": 2048,
        "y_pixels_in_detector": 512,
        "udp_packets_sent": [10, 20, 30],
    },
    "clock": {"dpll_lol": [True], "dpll_hold": [False], "clock_freq": 65.7},
    "sensor": {
        "temp_asics": [[50.0 + i for i in range(16)], [60.0 + i for i in range(16)]],
        "temp_pcb": [[1.0, 2.0], [3.0, 4.0]],
        "humidity": [[5.0, 6.0], [7.0, 8.0]],
    },
    "housekeeping": {"psu_temp": [28.6, 28.7]},
}
CONFIG_REPLY = {"exposure": 1.5, "trigger": {"start": "internal"}}


@pytest.fixture
def link(monkeypatch):
    """Replace detector comms with canned replies, recording the messages sent

    Set ``link.online = False`` to simulate the detector not replying.
    """

    class Link:
        def __init__(self):
            self.online = True
            self.sent = []
            self.last_msg_id = None
            self.on_send = None

        def reply(self, msg):
            self.sent.append((msg.msg_type, msg.params))
            if self.on_send is not None:
                self.on_send(msg)
            self.last_msg_id = msg.msg_id
            if not self.online:
                return None
            data = {}
            if msg.msg_type == "get" and "status" in msg.params:
                data = {"status": STATUS_REPLY}
            elif msg.msg_type == "get" and "config" in msg.params:
                data = {"config": CONFIG_REPLY}
            return ResponseMessage(msg.msg_id, data)

        def puts(self):
            return [params for msg_type, params in self.sent if msg_type == "put"]

    fake = Link()
    monkeypatch.setattr(TristanDetector, "send_recv", lambda _, msg: fake.reply(msg))
    return fake


@pytest.fixture
def polled(detector, link, tmp_path):
    udp_file = tmp_path / "udp.json"
    udp_file.write_text(json.dumps({"udp": {"dest": "10.0.0.1"}}))
    detector._udp_config_file = str(udp_file)
    return detector


def test_requests_match_main(polled, link):
    polled._poll_detector()
    gets = [params for msg_type, params in link.sent if msg_type == "get"]
    assert gets[0] == {"status": TristanDetector.STATUS_REQUEST}
    # The config request holds a None leaf for every schema path
    config_request = gets[1]["config"]
    assert config_request["exposure"] is None
    assert config_request["trigger"]["timestamp"]["fem"] is None
    for path in TristanDetector.DETECTOR_CONFIG:
        assert _lookup(config_request, path) is None
        assert path.split("/")[0] in config_request


def test_poll_stores_replies(polled):
    assert polled.get("status/connected") == {"value": False}
    polled._poll_detector()
    assert polled.get("status/connected") == {"value": True}
    assert polled.get("status/state") == {"value": "idle"}
    assert polled.get("status/housekeeping/psu_temp") == {"value": [28.6, 28.7]}
    assert polled.get("config/exposure") == {"value": 1.5}
    assert polled.get("config/trigger/start") == {"value": "internal"}


def test_derived_status_values(polled):
    polled._poll_detector()
    detector_status = polled.get("status/detector")["value"]
    assert detector_status["bytes"] == 2048 * 512 * 2
    assert detector_status["version_check"] is True
    assert detector_status["udp_packets_sent"] == 60
    assert polled.get("status/clock") == {
        "value": {"dpll_lol": True, "dpll_hold": False, "clock_freq": 65.7}
    }
    sensor = polled.get("status/sensor")["value"]
    assert sensor["temp_asics_0"] == [50.0, 60.0]
    assert sensor["temp_asics_15"] == [65.0, 75.0]
    assert sensor["temp_pcb_1"] == [2.0, 4.0]
    assert sensor["humidity_0"] == [5.0, 7.0]


def test_derived_values_are_none_before_detector_replies(detector):
    detector_status = detector.get("status/detector")["value"]
    assert detector_status["bytes"] is None
    assert detector_status["version_check"] is False
    assert detector_status["udp_packets_sent"] is None
    assert detector.get("status/sensor/temp_asics_3") == {"value": None}
    assert detector.get("status/clock/dpll_lol") == {"value": None}


def test_version_check_fails_on_firmware_mismatch(polled):
    polled._firmware = "2.0.0"
    polled._poll_detector()
    assert polled.get("status/detector/version_check") == {"value": False}


def test_time_and_udp_config_sent_once_per_connection(polled, link):
    polled._poll_detector()
    polled._poll_detector()
    puts = link.puts()
    assert len(puts) == 2
    assert "time" in puts[0]["config"]
    assert puts[1] == {"config": {"udp": {"dest": "10.0.0.1"}}}

    # Lose the detector: disconnected, nothing resent
    link.online = False
    polled._poll_detector()
    assert polled.get("status/connected") == {"value": False}
    assert polled.get("status/detector/version_check") == {"value": False}
    assert len(link.puts()) == 2

    # Reconnect: config is sent again
    link.online = True
    polled._poll_detector()
    assert polled.get("status/connected") == {"value": True}
    assert len(link.puts()) == 4


def test_acquisition_complete_when_idle(polled):
    polled._acquisition_complete = False
    polled._poll_detector()
    assert polled.get("status/acquisition_complete") == {"value": True}


def test_every_status_path_is_in_tree(detector):
    for path in TristanDetector.OTHER_STATUS_FIELDS:
        detector.get(f"status/{path}")


@pytest.mark.parametrize(
    "path, value, expected",
    [
        ("config/exposure", 1.5, {"exposure": 1.5}),
        (
            "config/trigger/timestamp/fem",
            "re",
            {"trigger": {"timestamp": {"fem": "re"}}},
        ),
        ("config", {"frames": 10, "mode": "count"}, {"frames": 10, "mode": "count"}),
        ("config/trigger", {"start": "internal"}, {"trigger": {"start": "internal"}}),
        # Paths outside the schema are passed through for the detector to judge
        ("config/bias/voltage", 50.0, {"bias": {"voltage": 50.0}}),
        # ADOdin names
        ("config/exposure_time", 2.0, {"exposure": 2.0}),
        ("config/num_images", 5, {"frames": 5}),
    ],
)
def test_config_put_message(detector, link, path, value, expected):
    detector.put(path, value)
    assert link.puts() == [{"config": expected}]


@pytest.mark.parametrize(
    "path, expected",
    [
        ("config/exposure/1", {"exposure": 1.0}),
        ("config/repeat_interval/0.5", {"repeat_interval": 0.5}),
        # Not polled or in the tree, but still passed through
        ("config/readout_time/0.25", {"readout_time": 0.25}),
        ("config/frames/10", {"frames": 10}),
        ("config/ntrigger/3.0", {"ntrigger": 3}),
        ("config/mode/count", {"mode": "count"}),
        ("config/threshold/5.2", {"threshold": "5.2"}),
        # As on main, numeric text for string parameters goes through float
        ("config/threshold/5", {"threshold": "5.0"}),
        ("config/frames/abc", {"frames": "abc"}),
        ("config/trigger/start/internal", {"trigger": {"start": "internal"}}),
        ("config/exposure_time/2", {"exposure": 2.0}),
    ],
)
def test_config_put_value_in_url(detector, link, path, expected):
    # The web UI sends config/<name>/<value> with an empty body
    detector.put(path, None)
    assert link.puts() == [{"config": expected}]
    for value in expected.values():
        if isinstance(value, float):
            assert type(value) is float


@pytest.mark.parametrize(
    "path, value, match",
    [
        ("config/mode", "bogus", "Invalid value 'bogus' for config/mode"),
        ("config/mode/bogus", None, "allowed values: time_energy, time_only, count"),
        ("config", {"trigger": {"timestamp": {"ttl": "up"}}}, "trigger/timestamp/ttl"),
        ("config", None, "No value given"),
        ("config/exposure", None, "No value given"),
        ("config", 1.5, "requires an object"),
    ],
)
def test_invalid_config_put_is_rejected(detector, link, path, value, match):
    with pytest.raises(ValueError, match=match):
        detector.put(path, value)
    assert link.sent == []


def test_put_returns_detector_reply(detector, link):
    response = detector.put("config/exposure", 1.5)
    reply = json.loads(response["reply"])
    assert reply["msg_type"] == "response"
    assert reply["msg_id"] == link.last_msg_id


def test_put_reply_is_none_without_detector(detector, link):
    link.online = False
    assert detector.put("command/stop", None) == {"reply": None}


@pytest.mark.parametrize(
    "path, msg_type",
    [("engineering_put", "put"), ("engineering_get", "get"), ("engineering", "get")],
)
def test_engineering_sends_body_as_config(detector, link, path, msg_type):
    body = {"exposure": None, "trigger": {"start": None}}
    response = detector.put(path, body)
    assert link.sent == [(msg_type, {"config": body})]
    assert response["reply"] is not None


@pytest.mark.parametrize(
    "path, value, match",
    [
        ("engineering_put", "not json", "requires a JSON object"),
        ("engineering_get", None, "requires a JSON object"),
        ("engineering_put/x", {}, "Unknown path"),
    ],
)
def test_invalid_engineering_put_is_rejected(detector, link, path, value, match):
    with pytest.raises(ValueError, match=match):
        detector.put(path, value)
    assert link.sent == []


def test_error_is_set_and_cleared_by_next_put(detector, link):
    assert detector.get("status/error") == {"value": ""}
    detector.set_error("Something went wrong")
    assert detector.get("status/error") == {"value": "Something went wrong"}
    detector.put("config/exposure", 1.0)
    assert detector.get("status/error") == {"value": ""}


def test_missing_udp_file_sets_error(detector, link, tmp_path):
    detector._udp_config_file = str(tmp_path / "missing.json")
    detector._poll_detector()
    assert (
        "Failed to open UDP configuration file" in detector.get("status/error")["value"]
    )


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(tristan_detector.time, "sleep", lambda _: None)


def test_start_acquisition_times_out_waiting_for_armed(detector, link, no_sleep):
    with pytest.raises(DetectorTimeoutError, match="armed state"):
        detector.put("command/start_acquisition", None)
    assert detector.get("status/error") == {
        "value": "Time out waiting for detector armed state"
    }
    # Nothing after the arm command is sent
    assert link.sent == [("post", {"command": "arm"})]


def test_start_acquisition_times_out_waiting_for_running(detector, link, no_sleep):
    detector._status = {"state": "armed"}
    with pytest.raises(DetectorTimeoutError, match="running state"):
        detector.put("command/start_acquisition", None)
    assert "running state" in detector.get("status/error")["value"]


def test_start_acquisition_arms_then_runs(detector, link, no_sleep):
    def follow_commands(msg):
        # Act like the detector, changing state in response to commands
        states = {"arm": "armed", "run": "running"}
        detector._status = {"state": states[msg.params["command"]]}

    link.on_send = follow_commands
    response = detector.put("command/start_acquisition", None)
    assert link.sent == [("post", {"command": "arm"}), ("post", {"command": "run"})]
    assert json.loads(response["reply"])["msg_type"] == "response"
    assert detector.get("status/acquisition_complete") == {"value": False}
    assert detector.get("status/error") == {"value": ""}


def test_get_response_shapes_match_main(detector):
    # The web UI reads response['value'] for status and config paths ...
    detector._status = {"state": "idle", "detector": {"description": "Tristan"}}
    assert detector.get("status/state") == {"value": "idle"}
    assert detector.get("status/detector/description") == {"value": "Tristan"}
    assert detector.get("status/connected") == {"value": False}
    assert detector.get("status/detector")["value"]["bytes"] is None
    # ... and response.<name> for top-level fields
    assert detector.get("endpoint") == {"endpoint": UNUSED_ENDPOINT}
    assert detector.get("username") == {"username": detector._username}


def test_metadata_get_keeps_tree_shape(detector):
    response = detector.get("status/state", meta=True)
    assert set(response) == {"state"}
    assert response["state"]["value"] is None


def test_module_defaults_to_class_name(detector):
    assert detector.get("module") == {"module": "TristanDetector"}


def test_status_paths_outside_schema_read_from_reply(detector):
    detector._status = {"detector": {"detector_variant": "1M"}, "extra": {"a": 1}}
    assert detector.get("status/detector/detector_variant") == {"value": "1M"}
    assert detector.get("status/extra") == {"value": {"a": 1}}
    # Fields the detector did not send read as None, as on main
    assert detector.get("status/not/sent") == {"value": None}


def test_unknown_paths_outside_status_are_errors(detector):
    with pytest.raises(ParameterTreeError):
        detector.get("config/not_in_schema")
    with pytest.raises(ParameterTreeError):
        detector.get("status/not/sent", meta=True)


def test_other_paths_outside_config_read_as_none(detector):
    # As on main, e.g. GETs of command paths
    assert detector.get("command/arm") == {"value": None}
    assert detector.get("command/start_acquisition") == {"value": None}


def test_process_status_adds_mains_calculated_values(detector):
    reply = json.loads(json.dumps(STATUS_REPLY))
    status = detector._process_status(reply)

    assert status["detector"]["bytes"] == 2048 * 512 * 2
    assert status["detector"]["udp_packets_sent"] == 60
    assert status["detector"]["version_check"] is True
    assert status["clock"]["dpll_lol"] is True
    assert status["clock"]["dpll_hold"] is False
    assert status["sensor"]["temp_asics_0"] == [50.0, 60.0]
    assert status["sensor"]["humidity_1"] == [6.0, 8.0]
    # Raw fields are kept, and the reply itself is not modified
    assert status["sensor"]["temp_asics"] == STATUS_REPLY["sensor"]["temp_asics"]
    assert reply == STATUS_REPLY


def test_process_status_tolerates_missing_and_malformed_fields(detector):
    status = detector._process_status({"state": "idle", "sensor": {"temp_pcb": [[1]]}})
    assert status["detector"]["version_check"] is False
    assert "bytes" not in status["detector"]
    # Too few channels in the reading: the split is skipped rather than failing
    assert "temp_pcb_1" not in status["sensor"]


def test_calculated_values_are_read_from_stored_status(polled):
    polled._poll_detector()
    assert polled.get("status/detector/bytes") == {"value": 2048 * 512 * 2}


def test_status_tree_fields_come_from_the_status_request():
    fields = TristanDetector.STATUS_REQUEST_FIELDS
    assert fields[0] == "state"
    assert "detector/acquisition_busy" in fields
    assert "detector/module_dimensions/x_max" in fields
    assert len(fields) == len(set(fields))
